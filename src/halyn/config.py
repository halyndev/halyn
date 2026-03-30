# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Configuration — YAML-based Halyn setup.

YAML/env-based configuration loader.
Merges file config, environment variables, and defaults.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("halyn.config")

_DEFAULT_CONFIG = {
    "version": "1",
    "server": {
        "host": "0.0.0.0",
        "port": 7420,
        "api_key": "",
    },
    "llm": {
        "provider": "ollama",
        "model": "",
        "api_key": "",
    },
    "domains": {
        "infrastructure": {
            "level": 2,
            "nodes": ["server/*", "cloud/*", "docker/*"],
            "confirm": ["restart", "deploy", "delete"],
        },
        "monitoring": {
            "level": 4,
            "nodes": ["sensor/*", "monitor/*"],
        },
    },
    "nodes": [],
    "logging": {
        "level": "INFO",
        "file": "",
    },
}


@dataclass(slots=True)
class HalynConfig:
    """Parsed configuration."""
    host: str = "0.0.0.0"
    port: int = 7420
    api_key: str = ""
    llm_provider: str = "ollama"
    llm_model: str = ""
    llm_api_key: str = ""
    domains: dict[str, dict[str, Any]] = field(default_factory=dict)
    nodes: list[dict[str, Any]] = field(default_factory=list)
    log_level: str = "INFO"
    log_file: str = ""
    data_dir: str = ""

    @classmethod
    def load(cls, path: str = "") -> HalynConfig:
        """Load config from YAML file, env vars, or defaults."""
        raw = dict(_DEFAULT_CONFIG)

        # Try loading YAML
        config_path = path or os.environ.get("HALYN_CONFIG", "")
        if not config_path:
            for candidate in ["halyn.yml", "halyn.yaml", ".halyn.yml",
                              str(Path.home() / ".halyn" / "config.yml")]:
                if Path(candidate).is_file():
                    config_path = candidate
                    break

        if config_path and Path(config_path).is_file():
            try:
                import yaml
                with open(config_path) as f:
                    user_config = yaml.safe_load(f) or {}
                _deep_merge(raw, user_config)
                log.info("config.loaded path=%s", config_path)
            except ImportError:
                # Fallback: try JSON
                import json as json_mod
                if config_path.endswith(".json"):
                    with open(config_path) as f:
                        user_config = json_mod.load(f)
                    _deep_merge(raw, user_config)
            except Exception as exc:
                log.warning("config.load_error path=%s error=%s", config_path, exc)

        # Environment variable overrides
        server = raw.get("server", {})
        llm = raw.get("llm", {})

        cfg = cls(
            host=os.environ.get("HALYN_HOST", str(server.get("host", "0.0.0.0"))),
            port=int(os.environ.get("HALYN_PORT", server.get("port", 7420))),
            api_key=os.environ.get("HALYN_API_KEY", server.get("api_key", "")),
            llm_provider=os.environ.get("HALYN_LLM_PROVIDER", llm.get("provider", "ollama")),
            llm_model=os.environ.get("HALYN_LLM_MODEL", llm.get("model", "")),
            llm_api_key=os.environ.get("ANTHROPIC_API_KEY",
                        os.environ.get("OPENAI_API_KEY", llm.get("api_key", ""))),
            domains=raw.get("domains", {}),
            nodes=raw.get("nodes", []),
            log_level=os.environ.get("HALYN_LOG_LEVEL",
                                     raw.get("logging", {}).get("level", "INFO")),
            log_file=raw.get("logging", {}).get("file", ""),
            data_dir=os.environ.get("HALYN_DATA_DIR",
                                    str(Path.home() / ".halyn")),
        )
        return cfg

    def to_dict(self) -> dict[str, Any]:
        return {
            "server": {"host": self.host, "port": self.port},
            "llm": {"provider": self.llm_provider, "model": self.llm_model},
            "domains": self.domains,
            "nodes": self.nodes,
            "logging": {"level": self.log_level},
        }


def _deep_merge(base: dict, override: dict) -> None:
    for key, val in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            _deep_merge(base[key], val)
        else:
            base[key] = val

