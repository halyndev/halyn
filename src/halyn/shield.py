# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Halyn Shield Engine — Enforceable safety rules.

Shield rules are constraints that AI agents physically cannot bypass.
They are enforced by the protocol, not by the AI.

Hardened against:
  - Case variations (DELETE, Delete, dElEtE)
  - Unicode tricks (fullwidth characters ＤＥＬ)
  - Obfuscation (d.e.l.e.t.e, d-e-l-e-t-e)
  - Synonyms (delete=rm=remove=unlink=shred=erase=destroy=wipe=purge=truncate)
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional


# Semantic groups: words that mean the same dangerous action
SYNONYMS: dict[str, set[str]] = {
    "delete": {"delete", "rm", "remove", "unlink", "shred", "erase", "destroy",
               "wipe", "purge", "truncate", "del", "rmdir", "rmtree"},
    "drop": {"drop", "truncate", "destroy"},
    "kill": {"kill", "terminate", "abort", "sigkill", "sigterm"},
    "reboot": {"reboot", "restart", "shutdown", "poweroff", "halt", "init 0",
               "init 6", "systemctl reboot", "systemctl poweroff"},
    "format": {"format", "mkfs", "fdisk", "dd if=/dev/zero"},
    "chmod": {"chmod 777", "chmod 666", "chmod a+rwx"},
}

# Build reverse lookup: word → canonical group
_WORD_TO_GROUP: dict[str, str] = {}
for group, words in SYNONYMS.items():
    for w in words:
        _WORD_TO_GROUP[w] = group


def normalize_command(command: str) -> str:
    """Normalize a command for shield matching.
    
    1. Unicode NFKD normalization (fullwidth → ASCII)
    2. Strip non-alphanumeric separators used for obfuscation
    3. Lowercase
    """
    # NFKD: fullwidth ＤＥＬ → DEL, accented → base
    norm = unicodedata.normalize("NFKD", command)
    # Keep only ASCII
    norm = norm.encode("ascii", "ignore").decode("ascii")
    # Lowercase
    norm = norm.lower()
    # Remove common obfuscation: brackets, dots between letters
    # But keep spaces and slashes (meaningful in commands)
    norm = re.sub(r'[\[\]\(\)\{\}]', '', norm)
    return norm


def expand_synonyms(action_word: str) -> set[str]:
    """Get all synonyms for a given action word."""
    action_lower = action_word.lower()
    group = _WORD_TO_GROUP.get(action_lower)
    if group:
        return SYNONYMS[group]
    return {action_lower}


def check_shields(shields: list[str], node: str, command: str) -> Optional[str]:
    """Check if a command is blocked by any shield rule.
    
    Returns the blocking rule string, or None if allowed.
    
    Rule format: "deny <scope> <action> [condition]"
      scope: "*" or specific node name
      action: "*" or word (with synonym expansion)
      condition: optional additional match
    """
    cmd_normalized = normalize_command(command)
    
    for rule in shields:
        parts = rule.lower().split()
        if len(parts) < 3 or parts[0] != "deny":
            continue
        
        scope = parts[1]
        action = parts[2]
        condition = " ".join(parts[3:]) if len(parts) > 3 else ""
        
        # Check scope
        if scope != "*" and scope != node.lower():
            continue
        
        # Check action with synonym expansion
        if action == "*":
            # Wildcard action: check condition
            if not condition or condition == "*":
                return rule  # deny everything
            cond_words = expand_synonyms(condition)
            if any(w in cmd_normalized for w in cond_words):
                return rule
        else:
            # Specific action: expand synonyms
            action_words = expand_synonyms(action)
            if any(w in cmd_normalized for w in action_words):
                # Check condition if present
                if not condition or condition == "*":
                    return rule
                cond_words = expand_synonyms(condition)
                if any(w in cmd_normalized for w in cond_words):
                    return rule
    
    return None
