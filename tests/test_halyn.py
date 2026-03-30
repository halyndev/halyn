# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Halyn Test Suite — Every README example must pass.

Run: pytest tests/ -v
"""
import pytest
import json
import subprocess
import time
import urllib.request


# ═══════════════════════════════════════
#  IMPORTS — what the user sees first
# ═══════════════════════════════════════

class TestImports:
    def test_import_controlplane(self):
        from halyn import ControlPlane
        assert ControlPlane is not None

    def test_import_sshdriver(self):
        from halyn import SSHDriver
        assert SSHDriver is not None

    def test_import_autonomy(self):
        from halyn import Autonomy
        assert Autonomy is not None

    def test_import_auditchain(self):
        from halyn import AuditChain
        assert AuditChain is not None

    def test_import_all_12_drivers(self):
        from halyn import (SSHDriver, HTTPDriver, WebSocketDriver, SerialDriver,
                           MQTTDriver, OPCUADriver, ROS2Driver, DDSDriver,
                           DockerDriver, BrowserDriver, UnitreeDriver, SocketDriver)
        drivers = [SSHDriver, HTTPDriver, WebSocketDriver, SerialDriver,
                   MQTTDriver, OPCUADriver, ROS2Driver, DDSDriver,
                   DockerDriver, BrowserDriver, UnitreeDriver, SocketDriver]
        for d in drivers:
            assert d is not None, f"{d} is None"

    def test_import_nrpid(self):
        from nrp import NRPId
        assert NRPId is not None


# ═══════════════════════════════════════
#  CONTROLPLANE — the README quickstart
# ═══════════════════════════════════════

class TestControlPlane:
    def test_create(self):
        from halyn import ControlPlane
        cp = ControlPlane()
        assert cp is not None

    def test_shield(self):
        from halyn import ControlPlane
        cp = ControlPlane()
        cp.shield("deny * delete *")
        assert len(cp.shields) == 1

    def test_shield_multiple(self):
        from halyn import ControlPlane
        cp = ControlPlane()
        cp.shield("deny * delete *")
        cp.shield("deny * rm *")
        cp.shield("deny * DROP *")
        assert len(cp.shields) == 3

    def test_shield_empty_rejected(self):
        from halyn import ControlPlane
        cp = ControlPlane()
        with pytest.raises(ValueError):
            cp.shield("")

    def test_shield_invalid_rejected(self):
        from halyn import ControlPlane
        cp = ControlPlane()
        with pytest.raises(ValueError):
            cp.shield("blah blah")

    def test_connect(self):
        from halyn import ControlPlane, SSHDriver
        cp = ControlPlane()
        drv = SSHDriver("192.168.1.10", "admin")
        cp.connect(drv)

    def test_act_allowed(self):
        from halyn import ControlPlane
        cp = ControlPlane()
        cp.shield("deny * delete *")
        result = cp.act("restart nginx")
        assert result.get("ok") is True

    def test_act_blocked(self):
        from halyn import ControlPlane
        cp = ControlPlane()
        cp.shield("deny * delete *")
        result = cp.act("delete files")
        assert result.get("blocked") is True

    def test_observe(self):
        from halyn import ControlPlane
        cp = ControlPlane()
        state = cp.observe()
        assert isinstance(state, dict)


# ═══════════════════════════════════════
#  NRP SDK
# ═══════════════════════════════════════

class TestNRP:
    def test_parse(self):
        from nrp import NRPId
        nid = NRPId.parse("nrp://factory/robot/arm-7")
        assert nid.scope == "factory"
        assert nid.kind == "robot"
        assert nid.name == "arm-7"

    def test_aliases(self):
        from nrp import NRPId
        nid = NRPId.parse("nrp://factory/robot/arm-7")
        assert nid.domain == "factory"
        assert nid.device == "robot"
        assert nid.instance == "arm-7"

    def test_uri(self):
        from nrp import NRPId
        nid = NRPId.parse("nrp://factory/robot/arm-7")
        assert str(nid) == "nrp://factory/robot/arm-7"

    def test_invalid(self):
        from nrp import NRPId
        with pytest.raises(ValueError):
            NRPId.parse("not-a-valid-id")


# ═══════════════════════════════════════
#  SHIELD HARDENING — the security claims
# ═══════════════════════════════════════

class TestShieldHardening:
    """Test that shields are actually enforceable, not just string matching."""

    def _cp(self):
        from halyn import ControlPlane
        cp = ControlPlane()
        cp.shield("deny * delete *")
        cp.shield("deny * rm *")
        cp.shield("deny * DROP *")
        return cp

    # Basic blocking
    def test_block_delete(self):
        assert self._cp().act("delete files")["blocked"]

    def test_block_rm(self):
        assert self._cp().act("rm -rf /")["blocked"]

    def test_block_drop(self):
        assert self._cp().act("DROP TABLE users")["blocked"]

    # Case variations
    def test_block_uppercase(self):
        assert self._cp().act("DELETE files")["blocked"]

    def test_block_mixed_case(self):
        assert self._cp().act("dElEtE files")["blocked"]

    # Unicode bypass attempts
    def test_block_fullwidth_unicode(self):
        assert self._cp().act("ｄｅｌｅｔｅ files")["blocked"]

    # Synonym bypass attempts
    def test_block_remove(self):
        assert self._cp().act("remove all files")["blocked"]

    def test_block_unlink(self):
        assert self._cp().act("unlink /etc/passwd")["blocked"]

    def test_block_shred(self):
        assert self._cp().act("shred -u /etc/passwd")["blocked"]

    def test_block_erase(self):
        assert self._cp().act("erase disk")["blocked"]

    def test_block_wipe(self):
        assert self._cp().act("wipe partition")["blocked"]

    def test_block_purge(self):
        assert self._cp().act("purge all data")["blocked"]

    # Allowed actions must still work
    def test_allow_restart(self):
        assert self._cp().act("restart nginx").get("ok")

    def test_allow_status(self):
        assert self._cp().act("systemctl status").get("ok")

    def test_allow_ls(self):
        assert self._cp().act("ls -la").get("ok")

    def test_allow_uptime(self):
        assert self._cp().act("uptime").get("ok")

    # Shield persistence
    def test_shields_persist(self):
        cp = self._cp()
        assert len(cp.shields) == 3
        cp.act("delete files")  # blocked
        assert len(cp.shields) == 3  # still 3


# ═══════════════════════════════════════
#  DRIVERS — instantiation
# ═══════════════════════════════════════

class TestDrivers:
    def test_ssh_driver(self):
        from halyn import SSHDriver
        drv = SSHDriver("192.168.1.10", "admin")
        assert drv is not None

    def test_mqtt_driver(self):
        from halyn import MQTTDriver
        drv = MQTTDriver("localhost", 1883)
        assert drv is not None

    def test_docker_driver(self):
        from halyn import DockerDriver
        drv = DockerDriver()
        assert drv is not None

    def test_http_driver(self):
        from halyn import HTTPDriver
        drv = HTTPDriver("http://localhost:8080")
        assert drv is not None

    def test_browser_driver(self):
        from halyn import BrowserDriver
        drv = BrowserDriver()
        assert drv is not None
