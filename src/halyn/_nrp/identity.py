# Copyright (c) 2026 Elmadani SALKA. 
# Licensed under the  See LICENSE file.
"""
NRP Identity — Universal node addressing.

Stable addressing: nrp://scope/kind/name
Survives IP changes, network moves, device replacement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# nrp://factory-3/robot/arm-7
# nrp://home/sensor/kitchen-temp
# nrp://fleet/vehicle/truck-42
# nrp://farm/drone/survey-1
_NRP_PATTERN = re.compile(
    r"^nrp://(?P<scope>[a-z0-9][a-z0-9._-]*)/"
    r"(?P<kind>[a-z0-9][a-z0-9_-]*)/"
    r"(?P<name>[a-z0-9][a-z0-9._-]*)$"
)


@dataclass(frozen=True, slots=True)
class NRPId:
    """Universal node identifier."""
    scope: str    # Location/org: "factory-3", "home", "fleet", "farm"
    kind: str     # Type: "robot", "sensor", "server", "vehicle", "drone"
    name: str     # Instance: "arm-7", "kitchen-temp", "truck-42"

    @property
    def uri(self) -> str:
        return f"nrp://{self.scope}/{self.kind}/{self.name}"

    @property
    def short(self) -> str:
        """Short form for display: kind/name."""
        return f"{self.kind}/{self.name}"

    def matches(self, pattern: str) -> bool:
        """Match against glob patterns. E.g. 'factory-*/robot/*'."""
        import fnmatch
        return fnmatch.fnmatch(self.uri, f"nrp://{pattern}")

    @classmethod
    def parse(cls, uri: str) -> NRPId:
        """Parse 'nrp://scope/kind/name' into NRPId."""
        m = _NRP_PATTERN.match(uri.lower().strip())
        if not m:
            raise ValueError(
                f"Invalid NRP ID: {uri!r}. "
                f"Format: nrp://scope/kind/name (lowercase, alphanumeric, hyphens)"
            )
        return cls(scope=m["scope"], kind=m["kind"], name=m["name"])

    @classmethod
    def create(cls, scope: str, kind: str, name: str) -> NRPId:
        """Create and validate an NRP ID."""
        nid = cls(scope=scope.lower(), kind=kind.lower(), name=name.lower())
        # Validate by roundtripping through parse
        NRPId.parse(nid.uri)
        return nid


    # Aliases for common naming conventions
    @property
    def domain(self) -> str:
        """Alias for scope."""
        return self.scope

    @property
    def device(self) -> str:
        """Alias for kind."""
        return self.kind

    @property
    def instance(self) -> str:
        """Alias for name."""
        return self.name

    def __str__(self) -> str:
        return self.uri

    def __repr__(self) -> str:
        return f"NRPId({self.uri!r})"

