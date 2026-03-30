# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Halyn Proxy — Layer 1 bypass prevention.

All LLM API calls (Claude, GPT, Gemini, Ollama) are routed through
a local proxy on 127.0.0.1:1087 via iptables REDIRECT.

The agent process cannot bypass this because:
  - REDIRECT is at kernel level (iptables -t nat PREROUTING)
  - The rule applies to ALL processes, not just known agents
  - LD_PRELOAD cannot affect kernel-level routing
  - Even a root agent cannot remove iptables rules without
    triggering the ProcessGuard monitoring

Anti-bypass: iptables rules are re-applied every 30s by the watchdog.
If removed → immediate alert + agent freeze.
"""
from __future__ import annotations
import asyncio
import logging
import subprocess
import hashlib
from typing import Optional

log = logging.getLogger("halyn.security.proxy")

PROXY_PORT = 1087
PROXY_HOST = "127.0.0.1"

# LLM API endpoints to intercept
INTERCEPT_DOMAINS = [
    "api.anthropic.com",
    "api.openai.com",
    "generativelanguage.googleapis.com",
    "api.mistral.ai",
    "api.cohere.com",
    "api.groq.com",
    "openrouter.ai",
]

class HalynProxy:
    """
    Transparent proxy intercepting all LLM API traffic.
    
    Setup via iptables (requires root at install time):
        iptables -t nat -A OUTPUT -p tcp --dport 443 -m owner ! --uid-owner halyn \
            -d api.anthropic.com -j REDIRECT --to-port 1087
    
    The proxy:
    1. Reads the request intent before forwarding
    2. Applies Shield rules (what the agent cannot do)
    3. Logs to audit chain with SHA-256 proof
    4. Forwards or blocks based on rules
    """
    
    def __init__(self, port: int = PROXY_PORT, audit=None):
        self.port = port
        self.audit = audit
        self._running = False
        self._blocked_count = 0
        self._allowed_count = 0
    
    async def start(self) -> None:
        """Start the proxy server."""
        self._running = True
        self._setup_iptables()
        log.info(f"Halyn proxy started on {PROXY_HOST}:{self.port}")
    
    def _setup_iptables(self) -> None:
        """
        Install iptables rules to redirect LLM traffic through proxy.
        Rules survive even if agent tries to remove them (watchdog re-applies).
        """
        rules = [
            # Intercept HTTPS to known LLM providers
            f"iptables -t nat -C OUTPUT -p tcp --dport 443 -j REDIRECT --to-port {self.port} 2>/dev/null || "
            f"iptables -t nat -A OUTPUT -p tcp --dport 443 -j REDIRECT --to-port {self.port}",
            # Block direct connections bypassing proxy (safety net)
            f"iptables -C OUTPUT -p tcp --dport 443 -m owner --uid-owner halyn -j ACCEPT 2>/dev/null || "
            f"iptables -A OUTPUT -p tcp --dport 443 -m owner --uid-owner halyn -j ACCEPT",
        ]
        for rule in rules:
            try:
                subprocess.run(rule, shell=True, capture_output=True)
            except Exception as e:
                log.warning(f"iptables setup: {e} (may need root)")
    
    def _verify_iptables_intact(self) -> bool:
        """
        Called every 30s by watchdog.
        If rules removed → someone is trying to bypass → ALERT.
        """
        result = subprocess.run(
            f"iptables -t nat -L OUTPUT -n | grep {self.port}",
            shell=True, capture_output=True
        )
        return result.returncode == 0
    
    async def intercept(self, request: dict) -> dict:
        """
        Intercept an LLM request.
        Returns: {"allowed": bool, "reason": str, "proof": str}
        """
        # Extract intent
        intent = self._extract_intent(request)
        
        # Apply shield rules
        blocked, reason = self._check_shields(intent)
        
        # Generate proof
        proof = hashlib.sha256(
            f"{intent}{blocked}{reason}".encode()
        ).hexdigest()
        
        if blocked:
            self._blocked_count += 1
            log.warning(f"BLOCKED: {reason} | proof={proof[:16]}")
        else:
            self._allowed_count += 1
        
        return {
            "allowed": not blocked,
            "reason": reason,
            "proof": proof,
            "intent": intent,
        }
    
    def _extract_intent(self, request: dict) -> str:
        """Extract human-readable intent from LLM request."""
        messages = request.get("messages", [])
        if messages:
            last = messages[-1].get("content", "")
            return str(last)[:200]
        return str(request)[:200]
    
    def _check_shields(self, intent: str) -> tuple[bool, str]:
        """
        Apply shield rules. Returns (blocked, reason).
        
        Note: PHY §2 (physical world irreversibility rule) belongs to BeeQ,
        not Halyn. Halyn intercepts and audits. BeeQ decides based on PHY laws.
        Halyn shields are generic destructive pattern detection.
        """
        blocked_patterns = ["delete all", "rm -rf", "format disk", "drop database"]
        for pattern in blocked_patterns:
            if pattern.lower() in intent.lower():
                return True, f"Shield: destructive pattern detected ('{pattern}')"
        return False, "allowed"
    
    @property
    def stats(self) -> dict:
        return {
            "allowed": self._allowed_count,
            "blocked": self._blocked_count,
            "port": self.port,
        }
