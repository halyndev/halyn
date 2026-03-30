# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Halyn — The governance layer for AI agents.

Every action intercepted. Every decision auditable.
The AI cannot bypass it.
"""

__version__ = "2.2.4"
__author__ = "Elmadani SALKA"
__license__ = "BUSL-1.1"
__email__ = "contact@halyn.dev"
__url__ = "https://halyn.dev"


def _try(module, cls):
    try:
        mod = __import__(module, fromlist=[cls])
        return getattr(mod, cls)
    except (ImportError, AttributeError):
        return None


# Core exports
ControlPlane = _try("halyn.control_plane", "ControlPlane")
AuditChain = _try("halyn.audit", "AuditChain")
Shield = _try("halyn.shield", "Shield")
