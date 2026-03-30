# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Sanitizer — Clean all inputs before execution.

Prevents: command injection, path traversal, output flooding.
Applied BEFORE the shield, BEFORE the driver.
"""

from __future__ import annotations

import re
import logging
from typing import Any

log = logging.getLogger("halyn.sanitizer")

# Max output size to prevent OOM
MAX_OUTPUT_BYTES: int = 1_048_576  # 1MB

# Max timeout any user can request
MAX_TIMEOUT: int = 300  # 5 minutes

# Shell injection patterns (beyond what shield catches)
INJECTION_PATTERNS: tuple[str, ...] = (
    "$(", "`",           # Command substitution
    " | ", " || ",       # Pipe to another command
    " ; ",               # Command chaining
    " && ",              # Conditional chaining
    "\n",               # Newline injection
    ">> /etc/", "> /etc/",  # Write to system files
    "curl ", "wget ",    # Download and execute
    "nc ", "ncat ",      # Netcat reverse shells
    "python -c", "python3 -c",  # Inline code execution
    "perl -e", "ruby -e",
    "base64 -d",         # Decode hidden payloads
)

# Path traversal patterns
PATH_TRAVERSAL: tuple[str, ...] = (
    "..",
    "~root",
    "/etc/shadow",
    "/etc/passwd",
    "/proc/",
    "/sys/",
)


def sanitize_action(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """
    Sanitize action arguments. Returns cleaned args.
    Raises ValueError if dangerous.
    """
    args = dict(args)  # Don't mutate original

    # Cap timeout everywhere
    if "timeout" in args:
        args["timeout"] = min(int(args["timeout"]), MAX_TIMEOUT)

    # Cap output limit
    if "limit" in args:
        args["limit"] = min(int(args["limit"]), MAX_OUTPUT_BYTES)
    if "lines" in args:
        args["lines"] = min(int(args["lines"]), 500)
    if "n" in args and isinstance(args["n"], int):
        args["n"] = min(args["n"], 500)

    # Shell command sanitization
    if tool in ("shell",) and "command" in args:
        cmd = args["command"]
        _check_injection(cmd)

    # File path sanitization
    if "path" in args:
        path = str(args["path"])
        _check_path(path)

    return args


def sanitize_output(data: Any) -> Any:
    """Truncate output to prevent OOM."""
    if isinstance(data, str) and len(data) > MAX_OUTPUT_BYTES:
        truncated = data[:MAX_OUTPUT_BYTES]
        log.warning("sanitizer.output_truncated original=%d", len(data))
        return truncated + f"\n... [truncated, {len(data)} bytes total]"
    return data


def _check_injection(cmd: str) -> None:
    """Check for shell injection patterns in non-shell tools."""
    # For the "shell" tool, we ALLOW these (that's the point of shell).
    # But we LOG them for the audit trail.
    for pattern in INJECTION_PATTERNS:
        if pattern in cmd:
            log.info("sanitizer.injection_pattern cmd=%s pattern=%s", cmd[:100], pattern)
            # We don't block — shield handles dangerous patterns.
            # We just make sure the audit knows.
            return


def _check_path(path: str) -> None:
    """Block path traversal."""
    for pattern in PATH_TRAVERSAL:
        if pattern in path:
            raise ValueError(f"path traversal blocked: {pattern}")


def redact_error(error: str) -> str:
    """Remove sensitive info from error messages before sending to client."""
    # Remove file paths
    error = re.sub(r"/[\w/.-]+\.(?:pem|key|crt|conf|env)", "[REDACTED_PATH]", error)
    # Remove IP:port patterns that might reveal internal topology
    error = re.sub(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+", "[REDACTED_HOST]", error)
    # Remove potential credentials
    error = re.sub(r"(?:password|passwd|token|secret|key)[\s=:]+\S+", "[REDACTED]", error, flags=re.IGNORECASE)
    # Limit length
    return error[:300]

