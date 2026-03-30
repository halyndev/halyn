# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Serial meta-driver — UART, RS-485, Modbus RTU/TCP.

Covers legacy industrial hardware, embedded controllers,
PLCs, energy meters, and any RS-232/485 device.
"""

from __future__ import annotations

import logging
import struct
from typing import Any

from halyn._nrp import NRPDriver, NRPManifest, NRPId, ChannelSpec, ActionSpec, ShieldSpec, ShieldRule, ShieldType

log = logging.getLogger("halyn.drivers.serial")

try:
    import serial
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

try:
    from pymodbus.client import ModbusTcpClient, ModbusSerialClient
    HAS_MODBUS = True
except ImportError:
    HAS_MODBUS = False


class SerialDriver(NRPDriver):
    """
    Serial port driver with Modbus support.

    Modes:
      - raw: direct UART read/write
      - modbus_rtu: Modbus over RS-485 serial
      - modbus_tcp: Modbus over TCP/IP
    """

    def __init__(
        self,
        port: str = "/dev/ttyUSB0",
        baudrate: int = 9600,
        mode: str = "raw",
        modbus_host: str = "",
        modbus_port: int = 502,
        unit_id: int = 1,
        registers: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.mode = mode
        self.modbus_host = modbus_host
        self.modbus_port = modbus_port
        self.unit_id = unit_id
        self.registers = registers or {}
        self._serial = None
        self._modbus = None

    def manifest(self) -> NRPManifest:
        channels = []
        actions = []

        if self.mode == "raw":
            channels.append(ChannelSpec("buffer", "string", description="Raw serial buffer"))
            actions.append(ActionSpec("write", {"data": "string — bytes to send"}, "Write to serial port"))
            actions.append(ActionSpec("query", {"data": "string", "timeout": "float"}, "Write then read response"))
        else:
            for name, reg in self.registers.items():
                rtype = reg.get("type", "int")
                unit = reg.get("unit", "")
                channels.append(ChannelSpec(name, rtype, unit=unit, description=reg.get("desc", "")))
                if reg.get("writable"):
                    actions.append(ActionSpec(
                        f"write_{name}",
                        {"value": f"{rtype} — target value"},
                        f"Write {name} register",
                        dangerous=reg.get("dangerous", False),
                    ))

        actions.append(ActionSpec("reconnect", {}, "Reset connection"))

        return NRPManifest(
            nrp_id=self._nrp_id or NRPId.create("local", "serial", self.port.split("/")[-1]),
            manufacturer="Serial",
            model=f"{self.mode} @ {self.port if self.mode == 'raw' else self.modbus_host}",
            firmware=f"baud={self.baudrate}" if self.mode == "raw" else f"unit={self.unit_id}",
            observe=channels,
            act=actions,
            shield=[ShieldSpec("rate", "limit", 10, "req/s", "Max poll rate")],
        )

    async def connect(self) -> bool:
        if self.mode == "raw":
            if not HAS_SERIAL:
                log.warning("serial: pyserial not installed")
                return False
            try:
                self._serial = serial.Serial(self.port, self.baudrate, timeout=1)
                return self._serial.is_open
            except Exception as e:
                log.error("serial.connect_failed port=%s error=%s", self.port, e)
                return False

        elif self.mode in ("modbus_rtu", "modbus_tcp"):
            if not HAS_MODBUS:
                log.warning("serial: pymodbus not installed")
                return False
            try:
                if self.mode == "modbus_tcp":
                    self._modbus = ModbusTcpClient(self.modbus_host, port=self.modbus_port)
                else:
                    self._modbus = ModbusSerialClient(self.port, baudrate=self.baudrate)
                return self._modbus.connect()
            except Exception as e:
                log.error("modbus.connect_failed error=%s", e)
                return False
        return False

    async def observe(self, channels: list[str] | None = None) -> dict[str, Any]:
        if self.mode == "raw":
            return self._observe_raw()
        return self._observe_modbus(channels)

    async def act(self, command: str, args: dict[str, Any]) -> Any:
        if command == "reconnect":
            await self.disconnect()
            return {"reconnected": await self.connect()}

        if self.mode == "raw":
            return self._act_raw(command, args)
        return self._act_modbus(command, args)

    def shield_rules(self) -> list[ShieldRule]:
        return [ShieldRule("rate", ShieldType.LIMIT, 10)]

    async def disconnect(self) -> None:
        if self._serial and self._serial.is_open:
            self._serial.close()
        if self._modbus:
            self._modbus.close()

    def _observe_raw(self) -> dict[str, Any]:
        if not self._serial or not self._serial.is_open:
            return {"buffer": "", "error": "not connected"}
        waiting = self._serial.in_waiting
        data = self._serial.read(min(waiting, 4096)) if waiting else b""
        return {"buffer": data.hex() if data else "", "bytes_waiting": waiting}

    def _observe_modbus(self, channels: list[str] | None) -> dict[str, Any]:
        if not self._modbus:
            return {"error": "not connected"}
        state: dict[str, Any] = {}
        targets = channels or list(self.registers.keys())
        for name in targets:
            reg = self.registers.get(name)
            if not reg:
                continue
            try:
                addr = reg["address"]
                count = reg.get("count", 1)
                fc = reg.get("function", "holding")
                if fc == "holding":
                    result = self._modbus.read_holding_registers(addr, count, slave=self.unit_id)
                elif fc == "input":
                    result = self._modbus.read_input_registers(addr, count, slave=self.unit_id)
                elif fc == "coil":
                    result = self._modbus.read_coils(addr, count, slave=self.unit_id)
                else:
                    continue

                if hasattr(result, "registers"):
                    raw = result.registers
                    scale = reg.get("scale", 1.0)
                    if count == 1:
                        state[name] = raw[0] * scale
                    elif reg.get("type") == "float" and count == 2:
                        state[name] = struct.unpack(">f", struct.pack(">HH", *raw))[0]
                    else:
                        state[name] = [v * scale for v in raw]
                elif hasattr(result, "bits"):
                    state[name] = result.bits[:count]
            except Exception as e:
                state[name] = f"error: {e}"
        return state

    def _act_raw(self, command: str, args: dict[str, Any]) -> Any:
        if not self._serial or not self._serial.is_open:
            return {"error": "not connected"}
        if command == "write":
            data = bytes.fromhex(args.get("data", ""))
            self._serial.write(data)
            return {"written": len(data)}
        if command == "query":
            data = bytes.fromhex(args.get("data", ""))
            self._serial.write(data)
            timeout = float(args.get("timeout", 1.0))
            self._serial.timeout = timeout
            response = self._serial.read(4096)
            return {"response": response.hex(), "length": len(response)}
        return {"error": f"unknown command: {command}"}

    def _act_modbus(self, command: str, args: dict[str, Any]) -> Any:
        if not self._modbus:
            return {"error": "not connected"}
        for name, reg in self.registers.items():
            if command == f"write_{name}" and reg.get("writable"):
                value = args.get("value")
                addr = reg["address"]
                try:
                    if reg.get("type") == "float":
                        packed = struct.pack(">f", float(value))
                        regs = struct.unpack(">HH", packed)
                        self._modbus.write_registers(addr, list(regs), slave=self.unit_id)
                    elif reg.get("function") == "coil":
                        self._modbus.write_coil(addr, bool(value), slave=self.unit_id)
                    else:
                        self._modbus.write_register(addr, int(float(value)), slave=self.unit_id)
                    return {"written": name, "value": value}
                except Exception as e:
                    return {"error": str(e)}
        return {"error": f"unknown command: {command}"}
