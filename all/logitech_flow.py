#!/usr/bin/env python3
"""logitech_flow.py - Standalone Logitech Flow host-switching daemon and utility.

A simplified, single-file reimplementation of logitech-flow-kvm.
Eliminates pairing requests (direct HTTP connection) and works using standard
Python 3 with zero required third-party dependencies.

Usage:
    # 1. Discover devices:
    ./logitech_flow.py list

    # 2. Run server (on machine 1):
    ./logitech_flow.py server 1 <leader_device_id> <follower_device_id...>

    # 3. Run client (on machine 2):
    ./logitech_flow.py client 2 <server_ip_or_hostname>

    # 4. Directly switch a device to host:
    ./logitech_flow.py switch <device_id_or_path> <host_number>

    # 5. Watch connection events:
    ./logitech_flow.py watch <device_id_or_path>
"""

from __future__ import annotations

import argparse
import configparser
import dataclasses
import glob
import json
import logging
import os
import queue
import random
import re
import select
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from typing import Any

# ==============================================================================
# Constants
# ==============================================================================

DEFAULT_PORT = 54875
LOGITECH_VENDOR_ID = 0x046D
HIDPP_USB_INTERFACE = 2
HIDRAW_SYSFS_GLOB = "/sys/class/hidraw/hidraw*"

KNOWN_RECEIVERS: dict[int, str] = {
    0xC548: "bolt",
    0xC52B: "unifying",
}

SHORT_MESSAGE_ID = 0x10
LONG_MESSAGE_ID = 0x11
SHORT_REPORT_SIZE = 7
LONG_REPORT_SIZE = 20
MAX_READ_SIZE = 32

RECEIVER_DEVNUMBER = 0xFF
ROOT_FEATURE_INDEX = 0x00
FEATURE_CHANGE_HOST = 0x1814
CHANGE_HOST_READ_FUNCTION = 0x00
CHANGE_HOST_WRITE_FUNCTION = 0x10

RECEIVER_INFO_REGISTER = 0x2B5
NOTIFICATIONS_REGISTER = 0x00
RECEIVER_CONNECTION_REGISTER = 0x02

SUB_RECEIVER_INFORMATION = 0x03
SUB_UNIFYING_PAIRING_INFO = 0x20
SUB_UNIFYING_EXTENDED_PAIRING_INFO = 0x30
SUB_UNIFYING_DEVICE_NAME = 0x40
SUB_BOLT_PAIRING_INFO = 0x50
SUB_BOLT_DEVICE_NAME = 0x60

DEFAULT_MAX_DEVICES = 6
CONNECTION_NOTIFICATION_FLAGS = 0x100000 | 0x000100 | 0x000800

ERROR_INVALID_SUBID = 0x05
UNREACHABLE_ERRORS = {0x01, 0x02, 0x06, 0x09}

DEVICE_KIND = {
    1: "keyboard",
    2: "mouse",
    3: "numpad",
    4: "presenter",
    8: "trackball",
    9: "touchpad",
}

RECONCILE_INTERVAL = 2.0
PROBE_INTERVAL = 30.0
KEEPALIVE_INTERVAL = 15.0
SERVER_GRACE_PERIOD = 5.0
DEFAULT_TIMEOUT = 2.0

logger = logging.getLogger("logitech_flow")

# ==============================================================================
# Exceptions
# ==============================================================================


class FlowException(Exception):
    """Base exception for logitech_flow."""


class ProtocolError(FlowException):
    def __init__(self, error_code: int):
        self.error_code = error_code
        super().__init__(f"HID++ protocol error 0x{error_code:02x}")

    @property
    def means_unreachable(self) -> bool:
        return self.error_code in UNREACHABLE_ERRORS


class DeviceNotFound(FlowException):
    def __init__(self, identifier: str):
        super().__init__(f"Logitech device not found: {identifier}")


class DeviceUnreachable(FlowException):
    def __init__(self, device_id: str):
        super().__init__(
            f"Device is unreachable (asleep or on another host): {device_id}"
        )


class CannotChangeHost(FlowException):
    def __init__(self, msg: str):
        super().__init__(msg)


# ==============================================================================
# Data Models
# ==============================================================================


@dataclasses.dataclass(frozen=True)
class ReceiverInfo:
    path: str
    product_id: int
    kind: str
    interface: int


@dataclasses.dataclass(frozen=True)
class Notification:
    report_id: int
    devnumber: int
    sub_id: int
    address: int
    data: bytes


@dataclasses.dataclass(frozen=True)
class ChangeHostInfo:
    feature_index: int
    num_hosts: int
    current_host: int


@dataclasses.dataclass(frozen=True)
class PairedDevice:
    receiver: Receiver
    number: int
    wpid: str
    kind: str
    serial: str | None
    codename: str | None

    @property
    def id(self) -> str:
        return self.serial or self.wpid

    @property
    def path(self) -> str:
        return f"{self.receiver.path}:{self.number}"

    def __repr__(self) -> str:
        name = self.codename or self.kind
        return f"<Device id={self.id} name='{name}' path={self.path}>"


# ==============================================================================
# HID++ Transport & Protocol
# ==============================================================================


class HidRawIO:
    """Raw read/write access to /dev/hidraw* node."""

    def __init__(self, path: str):
        self.path = path
        self._fd = os.open(path, os.O_RDWR)

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def __enter__(self) -> HidRawIO:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def write(self, devnumber: int, payload: bytes, long_message: bool) -> None:
        if long_message or len(payload) > SHORT_REPORT_SIZE - 2:
            body = payload.ljust(LONG_REPORT_SIZE - 2, b"\x00")
            report = bytes([LONG_MESSAGE_ID, devnumber]) + body
        else:
            body = payload.ljust(SHORT_REPORT_SIZE - 2, b"\x00")
            report = bytes([SHORT_MESSAGE_ID, devnumber]) + body

        for attempt in range(3):
            try:
                written = os.write(self._fd, report)
                if written != len(report):
                    raise OSError(f"Short write: {written}/{len(report)} bytes")
                return
            except BrokenPipeError:
                if attempt == 2:
                    raise
                time.sleep(0.1)

    def read(self, timeout: float) -> tuple[int, int, bytes] | None:
        rlist, _, _ = select.select([self._fd], [], [], max(0.0, timeout))
        if not rlist:
            return None
        data = os.read(self._fd, MAX_READ_SIZE)
        if not data or len(data) < 2:
            return None
        return data[0], data[1], data[2:]

    def drain(self) -> None:
        while self.read(0) is not None:
            pass


def make_notification(
    report_id: int, devnumber: int, data: bytes
) -> Notification | None:
    """Classify incoming report as notification or request reply."""
    if len(data) < 2:
        return None
    sub_id = data[0]
    if sub_id & 0x80 == 0x80:
        return None

    address = data[1]
    if sub_id == 0x00 and (address & 0x0F) == 0x00:
        return None

    is_notification = (
        sub_id >= 0x40
        or (sub_id in (0x07, 0x0D) and len(data) == 5 and data[4:5] == b"\x00")
        or (sub_id == 0x17 and len(data) == 5)
        or ((address & 0x0F) == 0x00)
    )
    if is_notification:
        return Notification(
            report_id=report_id,
            devnumber=devnumber,
            sub_id=sub_id,
            address=address,
            data=data[2:],
        )
    return None


def parse_connection_status(data: bytes) -> dict[str, Any]:
    """Parse connection status flags from 0x41 notification data."""
    if not data:
        return {"connected": False, "device_type": 0}
    b0 = data[0]
    link_status = (b0 >> 6) & 1  # 0 = Link established, 1 = Link not established
    connected = link_status == 0
    device_type = b0 & 0x0F
    return {"connected": connected, "device_type": device_type}


class HidppConnection:
    """Request/reply and ping logic for HID++1.0 and HID++2.0."""

    def __init__(self, transport: HidRawIO):
        self._transport = transport
        self._lock = threading.Lock()

    def request(
        self,
        devnumber: int,
        request_id: int,
        params: bytes = b"",
        *,
        no_reply: bool = False,
        long_message: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
        randomize_software_id: bool = True,
    ) -> bytes | None:
        if randomize_software_id and request_id < 0x8000:
            request_id = (request_id & 0xFFF0) | 0x08 | random.getrandbits(3)

        request_header = struct.pack("!H", request_id)

        with self._lock:
            self._transport.drain()
            self._transport.write(devnumber, request_header + params, long_message)
            if no_reply:
                return None

            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                reply = self._transport.read(remaining)
                if reply is None:
                    continue
                _report_id, reply_devnumber, reply_data = reply
                if reply_devnumber != devnumber:
                    continue

                if (
                    reply_data[:1] in (b"\x8f", b"\xff")
                    and reply_data[1:3] == request_header
                ):
                    raise ProtocolError(reply_data[3])
                if reply_data[:2] == request_header:
                    return reply_data[2:]

    def read_register(
        self,
        devnumber: int,
        register: int,
        params: bytes = b"",
        *,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> bytes | None:
        request_id = 0x8100 | (register & 0x2FF)
        return self.request(devnumber, request_id, params, timeout=timeout)

    def write_register(
        self,
        devnumber: int,
        register: int,
        value: bytes,
        *,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> bytes | None:
        request_id = 0x8000 | (register & 0x2FF)
        return self.request(devnumber, request_id, value, timeout=timeout)

    def ping(self, devnumber: int, *, timeout: float = DEFAULT_TIMEOUT) -> float | None:
        marker = random.getrandbits(8)
        request_id = 0x0018 | random.getrandbits(3)
        request_header = struct.pack("!H", request_id)
        params = bytes([0, 0, marker])

        with self._lock:
            self._transport.drain()
            self._transport.write(
                devnumber, request_header + params, long_message=False
            )
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                reply = self._transport.read(remaining)
                if reply is None:
                    continue
                _report_id, reply_devnumber, reply_data = reply
                if reply_devnumber != devnumber:
                    continue

                if reply_data[:2] == request_header and reply_data[4:5] == bytes(
                    [marker]
                ):
                    return reply_data[2] + reply_data[3] / 10.0

                if reply_data[:1] == b"\x8f" and reply_data[1:3] == request_header:
                    error = reply_data[3]
                    if error == ERROR_INVALID_SUBID:
                        return 1.0
                    if error in UNREACHABLE_ERRORS:
                        return None

    def get_feature_index(self, devnumber: int, feature_id: int) -> int | None:
        reply = self.request(
            devnumber, ROOT_FEATURE_INDEX << 8, struct.pack("!H", feature_id)
        )
        if not reply:
            return None
        return reply[0] or None


# ==============================================================================
# Receiver & Devices
# ==============================================================================


def _decode_codename(raw: bytes, *, length_offset: int, text_offset: int) -> str | None:
    if len(raw) <= length_offset:
        return None
    length = raw[length_offset]
    text = raw[text_offset : text_offset + length]
    try:
        return text.decode("ascii") or None
    except UnicodeDecodeError:
        return None


class Receiver:
    """Connection to a single Logitech receiver."""

    def __init__(self, info: ReceiverInfo):
        self.path = info.path
        self.kind = info.kind
        self.product_id = info.product_id
        self._io = HidRawIO(info.path)
        self._conn = HidppConnection(self._io)
        self.max_devices = self._detect_max_devices()

    def close(self) -> None:
        self._io.close()

    def __enter__(self) -> Receiver:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _detect_max_devices(self) -> int:
        if self.kind == "bolt":
            return DEFAULT_MAX_DEVICES
        try:
            info = self._conn.read_register(
                RECEIVER_DEVNUMBER,
                RECEIVER_INFO_REGISTER,
                bytes([SUB_RECEIVER_INFORMATION]),
            )
        except ProtocolError:
            return DEFAULT_MAX_DEVICES
        if info and len(info) >= 7 and 0 < info[6] <= DEFAULT_MAX_DEVICES:
            return info[6]
        return DEFAULT_MAX_DEVICES

    def _device_codename(self, number: int) -> str | None:
        try:
            if self.kind == "bolt":
                raw = self._conn.read_register(
                    RECEIVER_DEVNUMBER,
                    RECEIVER_INFO_REGISTER,
                    bytes([SUB_BOLT_DEVICE_NAME + number, 0x01]),
                )
                if not raw or len(raw) < 3:
                    return None
                return _decode_codename(raw, length_offset=2, text_offset=3)
            raw = self._conn.read_register(
                RECEIVER_DEVNUMBER,
                RECEIVER_INFO_REGISTER,
                bytes([SUB_UNIFYING_DEVICE_NAME + (number - 1)]),
            )
            if not raw or len(raw) < 2:
                return None
            return _decode_codename(raw, length_offset=1, text_offset=2)
        except ProtocolError:
            return None

    def _bolt_paired_device(self, number: int) -> PairedDevice | None:
        try:
            info = self._conn.read_register(
                RECEIVER_DEVNUMBER,
                RECEIVER_INFO_REGISTER,
                bytes([SUB_BOLT_PAIRING_INFO + number]),
            )
        except ProtocolError:
            return None
        if not info or len(info) < 8:
            return None

        wpid = f"{info[3]:02X}{info[2]:02X}"
        kind = DEVICE_KIND.get(info[1] & 0x0F, "unknown")
        serial = info[4:8].hex().upper()
        return PairedDevice(
            receiver=self,
            number=number,
            wpid=wpid,
            kind=kind,
            serial=serial,
            codename=self._device_codename(number),
        )

    def _unifying_paired_device(self, number: int) -> PairedDevice | None:
        try:
            info = self._conn.read_register(
                RECEIVER_DEVNUMBER,
                RECEIVER_INFO_REGISTER,
                bytes([SUB_UNIFYING_PAIRING_INFO + (number - 1)]),
            )
        except ProtocolError:
            return None
        if not info or len(info) < 8:
            return None

        wpid = f"{info[3]:02X}{info[4]:02X}"
        kind = DEVICE_KIND.get(info[7] & 0x0F, "unknown")

        serial = None
        try:
            ext = self._conn.read_register(
                RECEIVER_DEVNUMBER,
                RECEIVER_INFO_REGISTER,
                bytes([SUB_UNIFYING_EXTENDED_PAIRING_INFO + (number - 1)]),
            )
            if ext and len(ext) >= 5:
                serial = ext[1:5].hex().upper()
        except ProtocolError:
            pass

        return PairedDevice(
            receiver=self,
            number=number,
            wpid=wpid,
            kind=kind,
            serial=serial,
            codename=self._device_codename(number),
        )

    def get_device(self, number: int) -> PairedDevice | None:
        if self.kind == "bolt":
            return self._bolt_paired_device(number)
        return self._unifying_paired_device(number)

    def enumerate_devices(self) -> list[PairedDevice]:
        devices = []
        for number in range(1, self.max_devices + 1):
            dev = self.get_device(number)
            if dev is not None:
                devices.append(dev)
        return devices

    def ping_device(self, number: int, *, timeout: float = 1.5) -> float | None:
        return self._conn.ping(number, timeout=timeout)

    def get_change_host_info(self, number: int) -> ChangeHostInfo | None:
        feature_index = self._conn.get_feature_index(number, FEATURE_CHANGE_HOST)
        if feature_index is None:
            return None
        reply = self._conn.request(
            number, (feature_index << 8) | CHANGE_HOST_READ_FUNCTION
        )
        if not reply or len(reply) < 2:
            return None
        return ChangeHostInfo(
            feature_index=feature_index,
            num_hosts=reply[0],
            current_host=reply[1],
        )

    def set_current_host(
        self, number: int, feature_index: int, host_0_indexed: int
    ) -> None:
        self._conn.request(
            number,
            (feature_index << 8) | CHANGE_HOST_WRITE_FUNCTION,
            bytes([host_0_indexed]),
            no_reply=True,
        )

    def enable_connection_notifications(self) -> None:
        self._conn.write_register(
            RECEIVER_DEVNUMBER,
            NOTIFICATIONS_REGISTER,
            CONNECTION_NOTIFICATION_FLAGS.to_bytes(3, "big"),
        )

    def notify_devices(self) -> None:
        self._conn.write_register(
            RECEIVER_DEVNUMBER,
            RECEIVER_CONNECTION_REGISTER,
            bytes([0x02]),
        )


def change_device_host(device: PairedDevice, host_1_indexed: int) -> None:
    """Switch device to host (1-indexed)."""
    try:
        info = device.receiver.get_change_host_info(device.number)
    except ProtocolError as err:
        if err.means_unreachable:
            raise DeviceUnreachable(device.id) from err
        raise

    if info is None or not (1 <= host_1_indexed <= info.num_hosts):
        max_h = info.num_hosts if info else "unknown"
        raise CannotChangeHost(
            f"Device {device.id} does not support host {host_1_indexed} (max: {max_h})"
        )

    device.receiver.set_current_host(
        device.number, info.feature_index, host_1_indexed - 1
    )


# ==============================================================================
# Discovery
# ==============================================================================


def _read_uevent(uevent_path: str) -> dict[str, str]:
    try:
        with open(uevent_path) as f:
            return dict(line.strip().split("=", 1) for line in f if "=" in line)
    except OSError:
        return {}


def _parse_interface_number(hid_phys: str) -> int | None:
    if "/input" not in hid_phys:
        return None
    tail = hid_phys.rsplit("/input", 1)[1]
    digits = "".join(ch for ch in tail if ch.isdigit())
    return int(digits) if digits else None


def find_receivers() -> list[ReceiverInfo]:
    """Enumerate Logitech receivers attached to the system via sysfs."""
    found: list[ReceiverInfo] = []
    for node in sorted(glob.glob(HIDRAW_SYSFS_GLOB)):
        uevent = _read_uevent(os.path.join(node, "device", "uevent"))
        hid_id = uevent.get("HID_ID")
        if not hid_id:
            continue
        try:
            _bus, vendor_hex, product_hex = hid_id.split(":")
            vendor = int(vendor_hex, 16)
            product = int(product_hex, 16) & 0xFFFF
        except ValueError:
            continue

        if vendor != LOGITECH_VENDOR_ID or product not in KNOWN_RECEIVERS:
            continue

        interface = _parse_interface_number(uevent.get("HID_PHYS", ""))
        if interface != HIDPP_USB_INTERFACE:
            continue

        found.append(
            ReceiverInfo(
                path=f"/dev/{os.path.basename(node)}",
                product_id=product,
                kind=KNOWN_RECEIVERS[product],
                interface=interface,
            )
        )
    return found


def device_matches(device: PairedDevice, query: str) -> bool:
    """Check if device matches by id/serial, WPID, kind, codename, or path."""
    q = query.strip().lower()
    if not q:
        return False

    # 1. Exact ID / serial / WPID
    if device.id.lower() == q:
        return True
    if device.serial and device.serial.lower() == q:
        return True
    if device.wpid.lower() == q:
        return True

    # 2. Path or :number
    if device.path.lower() == q or device.path.lower().endswith(f":{q}"):
        return True

    # 3. Kind (e.g. keyboard, mouse, trackball, touchpad, numpad)
    if device.kind and device.kind.lower() == q:
        return True

    # 4. Codename (exact or substring)
    if device.codename:
        c_lower = device.codename.lower()
        if c_lower == q or q in c_lower:
            return True

    return False


def find_matching_device(
    devices: list[PairedDevice], query: str
) -> PairedDevice | None:
    """Find the best matching device from a list of devices."""
    q = query.strip().lower()
    if not q:
        return None

    # Priority 1: Exact ID / serial / WPID
    for dev in devices:
        if (
            dev.id.lower() == q
            or (dev.serial and dev.serial.lower() == q)
            or dev.wpid.lower() == q
        ):
            return dev

    # Priority 2: Exact path or :number
    for dev in devices:
        if dev.path.lower() == q or dev.path.lower().endswith(f":{q}"):
            return dev

    # Priority 3: Exact codename
    for dev in devices:
        if dev.codename and dev.codename.lower() == q:
            return dev

    # Priority 4: Exact kind (e.g. "keyboard", "mouse")
    for dev in devices:
        if dev.kind and dev.kind.lower() == q:
            return dev

    # Priority 5: Substring in codename
    for dev in devices:
        if dev.codename and q in dev.codename.lower():
            return dev

    return None


def resolve_devices(
    receivers: list[Receiver], queries: list[str]
) -> dict[str, PairedDevice]:
    """Resolve each query (ID, serial, kind, codename, path) to a PairedDevice."""
    all_devices: list[PairedDevice] = []
    for receiver in receivers:
        all_devices.extend(receiver.enumerate_devices())

    found: dict[str, PairedDevice] = {}
    for query in queries:
        dev = find_matching_device(all_devices, query)
        if dev is None:
            raise DeviceNotFound(query)
        found[query] = dev
        found[dev.id] = dev

    return found


# ==============================================================================
# Notification Listener & Manager
# ==============================================================================


class NotificationListener(threading.Thread):
    def __init__(
        self,
        receiver_path: str,
        callback: Callable[[Notification], None],
        on_disconnect: Callable[[], None] | None = None,
    ):
        super().__init__(daemon=True)
        self._receiver_path = receiver_path
        self._callback = callback
        self._on_disconnect = on_disconnect
        self._active = threading.Event()
        self._stop_requested = False

    def run(self) -> None:
        self._active.set()
        disconnected = False
        try:
            with HidRawIO(self._receiver_path) as io:
                while self._active.is_set():
                    try:
                        reply = io.read(1.0)
                    except OSError:
                        disconnected = True
                        break
                    if reply is None:
                        continue
                    report_id, devnumber, data = reply
                    notification = make_notification(report_id, devnumber, data)
                    if notification is not None:
                        try:
                            self._callback(notification)
                        except Exception:
                            logger.exception("Notification callback error; continuing")
        except OSError:
            disconnected = True
        finally:
            self._active.clear()
            if disconnected and not self._stop_requested:
                logger.warning("Receiver %s vanished", self._receiver_path)
                if self._on_disconnect is not None:
                    self._on_disconnect()

    def stop(self) -> None:
        self._stop_requested = True
        self._active.clear()


class ReceiverManager(threading.Thread):
    def __init__(
        self,
        receivers: list[Receiver],
        rebind: Callable[[list[Receiver]], None],
        callback: Callable[[Receiver, Notification], None],
    ):
        super().__init__(daemon=True)
        self._receivers = receivers
        self._rebind = rebind
        self._callback = callback
        self._listeners: list[NotificationListener] = []
        self._lost = threading.Event()
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()
        self._lost.set()

    def run(self) -> None:
        try:
            self._activate()
        except Exception:
            logger.exception("Could not start listening to receivers; recovering")
            self._lost.set()

        while not self._stop_event.is_set():
            self._lost.wait()
            if self._stop_event.is_set():
                break
            self._lost.clear()
            logger.warning("Lost receiver connection; waiting to reconnect...")
            self._recover()

        self._teardown()

    def _activate(self) -> None:
        for receiver in self._receivers:
            receiver.enable_connection_notifications()
            listener = NotificationListener(
                receiver.path,
                lambda notif, r=receiver: self._callback(r, notif),
                on_disconnect=self._lost.set,
            )
            self._listeners.append(listener)
            listener.start()
            receiver.notify_devices()

    def _teardown(self) -> None:
        for listener in self._listeners:
            listener.stop()
        self._listeners.clear()
        for receiver in self._receivers:
            receiver.close()
        self._receivers.clear()

    def _recover(self) -> None:
        self._teardown()
        while not self._stop_event.is_set():
            time.sleep(2.0)
            infos = find_receivers()
            if not infos:
                continue
            receivers = [Receiver(info) for info in infos]
            try:
                self._rebind(receivers)
                self._receivers = receivers
                self._activate()
                logger.info("Successfully recovered receivers and rebound devices")
                return
            except DeviceNotFound:
                for r in receivers:
                    r.close()
            except Exception:
                logger.exception("Error during receiver recovery")
                for r in receivers:
                    r.close()


# ==============================================================================
# Follower Reconciler
# ==============================================================================


class Reconciler(threading.Thread):
    """Continuously reconciles local follower devices toward the desired host."""

    def __init__(
        self,
        devices: list[PairedDevice],
        get_desired_host: Callable[[], int | None],
        host_number: int,
    ):
        super().__init__(daemon=True)
        self._devices = devices
        self._get_desired_host = get_desired_host
        self._host_number = host_number
        self._connected: dict[PairedDevice, bool] = {d: False for d in devices}
        self._last_probe = time.monotonic()
        self._wake = threading.Event()
        self._stop = threading.Event()

    def observe(self, device: PairedDevice, connected: bool) -> None:
        if device in self._connected:
            self._connected[device] = connected
            self.poke()

    def set_devices(self, devices: list[PairedDevice]) -> None:
        self._devices = devices
        self._connected = {d: False for d in devices}
        self.poke()

    def poke(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def run(self) -> None:
        while not self._stop.is_set():
            self.reconcile_once()
            self._wake.wait(RECONCILE_INTERVAL)
            self._wake.clear()

    def reconcile_once(self) -> None:
        desired_host = self._get_desired_host()
        if desired_host is None or desired_host == self._host_number:
            return

        now = time.monotonic()
        if now - self._last_probe >= PROBE_INTERVAL:
            self._last_probe = now
            for device in self._devices:
                if not self._connected.get(device, False):
                    try:
                        version = device.receiver.ping_device(
                            device.number, timeout=0.5
                        )
                        if version is not None:
                            self._connected[device] = True
                    except Exception:
                        pass

        for device in self._devices:
            if self._connected.get(device, False):
                try:
                    logger.info(
                        "Switching follower %s to host %d", device.id, desired_host
                    )
                    change_device_host(device, desired_host)
                except DeviceUnreachable:
                    logger.info("Follower %s unreachable (switched away)", device.id)
                    self._connected[device] = False
                except Exception as e:
                    logger.warning(
                        "Could not switch %s to host %d yet (%s); retrying",
                        device.id,
                        desired_host,
                        e,
                    )


# ==============================================================================
# Clipboard Helpers
# ==============================================================================


def get_clipboard() -> str:
    """Fetch clipboard contents using pyperclip, wl-paste, or xclip/xsel."""
    try:
        import pyperclip  # type: ignore

        return pyperclip.paste()
    except Exception:
        pass

    if shutil.which("wl-paste") and os.environ.get("WAYLAND_DISPLAY"):
        try:
            res = subprocess.run(
                ["wl-paste", "--no-newline"], capture_output=True, text=True, timeout=2
            )
            if res.returncode == 0:
                return res.stdout
        except Exception:
            pass

    if shutil.which("xclip") and os.environ.get("DISPLAY"):
        try:
            res = subprocess.run(
                ["xclip", "-selection", "clipboard", "-o"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0:
                return res.stdout
        except Exception:
            pass

    if shutil.which("xsel") and os.environ.get("DISPLAY"):
        try:
            res = subprocess.run(
                ["xsel", "--clipboard", "--output"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0:
                return res.stdout
        except Exception:
            pass

    return ""


def set_clipboard(text: str) -> bool:
    """Set clipboard contents using pyperclip, wl-copy, or xclip/xsel."""
    try:
        import pyperclip  # type: ignore

        pyperclip.copy(text)
        return True
    except Exception:
        pass

    if shutil.which("wl-copy") and os.environ.get("WAYLAND_DISPLAY"):
        try:
            res = subprocess.run(["wl-copy"], input=text, text=True, timeout=2)
            if res.returncode == 0:
                return True
        except Exception:
            pass

    if shutil.which("xclip") and os.environ.get("DISPLAY"):
        try:
            res = subprocess.run(
                ["xclip", "-selection", "clipboard"], input=text, text=True, timeout=2
            )
            if res.returncode == 0:
                return True
        except Exception:
            pass

    if shutil.which("xsel") and os.environ.get("DISPLAY"):
        try:
            res = subprocess.run(
                ["xsel", "--clipboard", "--input"], input=text, text=True, timeout=2
            )
            if res.returncode == 0:
                return True
        except Exception:
            pass

    return False


# ==============================================================================
# Flow HTTP Server (Zero Pairing Required)
# ==============================================================================


class EventBroadcaster:
    """Manages SSE subscribers and broadcasts state changes."""

    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers: set[queue.Queue[str]] = set()
        self.current_state: str | None = None

    def subscribe(self) -> tuple[queue.Queue[str], str | None]:
        q: queue.Queue[str] = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.add(q)
            return q, self.current_state

    def unsubscribe(self, q: queue.Queue[str]) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def broadcast(self, event: str, data: str) -> None:
        msg = f"event: {event}\ndata: {data}\n\n"
        with self._lock:
            if event == "leader-host":
                self.current_state = data
            elif event == "leader-host-unknown":
                if self.current_state == data:
                    self.current_state = None

            dead = set()
            for q in self._subscribers:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead.add(q)
            self._subscribers.difference_update(dead)


class FlowHTTPHandler(BaseHTTPRequestHandler):
    """Multi-threaded HTTP handler supporting SSE and REST endpoints."""

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress noisy default HTTP logging
        pass

    def _check_auth(self) -> bool:
        secret = getattr(self.server, "secret", None)
        if not secret:
            return True
        auth_header = self.headers.get("Authorization", "")
        if auth_header == f"Bearer {secret}":
            return True
        self.send_response(401)
        self.end_headers()
        return False

    def do_GET(self) -> None:
        if not self._check_auth():
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/configuration":
            server_app: FlowServerInstance = self.server.app  # type: ignore
            data = {
                "leader": server_app.leader_device.id,
                "followers": [d.id for d in server_app.follower_devices],
            }
            body = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/events":
            server_app = self.server.app  # type: ignore
            q, current = server_app.events.subscribe()
            client_id = f"{self.client_address[0]}:{self.client_address[1]}"
            logger.info("Client connected to SSE stream: %s", client_id)

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            try:
                if current is not None:
                    self.wfile.write(
                        f"event: leader-host\ndata: {current}\n\n".encode()
                    )
                    self.wfile.flush()

                while not server_app.stop_event.is_set():
                    try:
                        msg = q.get(timeout=KEEPALIVE_INTERVAL)
                        self.wfile.write(msg.encode("utf-8"))
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                server_app.events.unsubscribe(q)
                logger.info("Client disconnected from SSE stream: %s", client_id)
            return

        if path == "/clipboard":
            server_app = self.server.app  # type: ignore
            if not server_app.clipboard_enabled:
                self.send_response(404)
                self.end_headers()
                return

            text = get_clipboard()
            body = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def do_PUT(self) -> None:
        if not self._check_auth():
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        if path == "/leader-host":
            server_app: FlowServerInstance = self.server.app  # type: ignore
            try:
                new_host = int(body.decode("utf-8").strip())
                server_app.report_leader_host(new_host)
                self.send_response(200)
                self.end_headers()
            except ValueError:
                self.send_response(400)
                self.end_headers()
            return

        if path == "/clipboard":
            server_app = self.server.app  # type: ignore
            if not server_app.clipboard_enabled:
                self.send_response(404)
                self.end_headers()
                return

            text = body.decode("utf-8", errors="replace")
            set_clipboard(text)
            logger.info("Clipboard updated from client (%d bytes)", len(body))
            self.send_response(200)
            self.end_headers()
            return

        self.send_response(404)
        self.end_headers()


class FlowServerInstance:
    """Manages the server state, device watchers, and HTTP server."""

    def __init__(
        self,
        host_number: int,
        leader_device: PairedDevice,
        follower_devices: list[PairedDevice],
        clipboard_enabled: bool = True,
        secret: str | None = None,
    ):
        self.host_number = host_number
        self.leader_device = leader_device
        self.follower_devices = follower_devices
        self.clipboard_enabled = clipboard_enabled
        self.secret = secret

        self.events = EventBroadcaster()
        self.stop_event = threading.Event()

        self._leader_id = leader_device.id
        self._follower_ids = [d.id for d in follower_devices]

        self.reconciler = Reconciler(
            follower_devices,
            get_desired_host=self._get_desired_host,
            host_number=host_number,
        )

        seen_receivers: list[Receiver] = []
        for dev in (self.leader_device, *self.follower_devices):
            if dev.receiver not in seen_receivers:
                seen_receivers.append(dev.receiver)

        self.manager = ReceiverManager(
            seen_receivers,
            rebind=self._rebind,
            callback=self._on_notification,
        )

    def _get_desired_host(self) -> int | None:
        state = self.events.current_state
        return int(state) if state is not None else None

    def _rebind(self, receivers: list[Receiver]) -> None:
        devices = resolve_devices(receivers, [self._leader_id, *self._follower_ids])
        self.leader_device = devices[self._leader_id]
        self.follower_devices = [devices[i] for i in self._follower_ids]
        self.reconciler.set_devices(self.follower_devices)
        logger.info(
            "Rebound leader %s and %d followers",
            self._leader_id,
            len(self.follower_devices),
        )

    def _on_notification(self, receiver: Receiver, notification: Notification) -> None:
        if notification.sub_id != 0x41:
            return

        device = next(
            (
                d
                for d in (self.leader_device, *self.follower_devices)
                if d.receiver is receiver and d.number == notification.devnumber
            ),
            None,
        )
        if device is None:
            return

        status = parse_connection_status(notification.data)
        connected = status["connected"]

        if device is self.leader_device:
            if connected:
                logger.info(
                    "Leader device %s connected to host %d", device.id, self.host_number
                )
                self.report_leader_host(self.host_number)
            else:
                logger.info(
                    "Leader device %s disconnected from host %d",
                    device.id,
                    self.host_number,
                )
        else:
            self.reconciler.observe(device, connected)
            if connected:
                logger.info("Follower device %s connected", device.id)
            else:
                logger.info("Follower device %s disconnected", device.id)

    def report_leader_host(self, host: int) -> None:
        logger.info("Leader is on host %d", host)
        self.events.broadcast("leader-host", str(host))
        self.reconciler.poke()

    def start(self, host: str, port: int) -> None:
        self.manager.start()
        self.reconciler.start()

        server = ThreadingHTTPServer((host, port), FlowHTTPHandler)
        server.app = self  # type: ignore
        server.secret = self.secret  # type: ignore

        logger.info(
            "Flow server running on %s:%d (Host %d)", host, port, self.host_number
        )
        logger.info("Leader device: %s", self.leader_device.id)
        logger.info(
            "Follower devices: %s", ", ".join(d.id for d in self.follower_devices)
        )
        if self.secret:
            logger.info("Shared secret authentication enabled")
        else:
            logger.info("Direct connection enabled (no pairing request needed)")

        try:
            server.serve_forever()
        except KeyboardInterrupt:
            logger.info("Shutting down server...")
        finally:
            self.stop_event.set()
            server.shutdown()
            self.reconciler.stop()
            self.manager.stop()


# ==============================================================================
# Flow Client
# ==============================================================================


class FlowClientInstance:
    """Manages the client state, server connection, and local devices."""

    def __init__(
        self,
        host_number: int,
        server_host: str,
        port: int = DEFAULT_PORT,
        clipboard_enabled: bool = True,
        secret: str | None = None,
    ):
        self.host_number = host_number
        self.server_host = server_host
        self.port = port
        self.clipboard_enabled = clipboard_enabled
        self.secret = secret

        self.leader_id: str | None = None
        self.follower_ids: list[str] = []
        self.follower_devices: list[PairedDevice] = []
        self.local_receivers: list[Receiver] = []

        self.leader_host: int | None = None
        self._leader_here = False
        self._connected_to_server = False
        self._disconnected_since: float | None = None

        self.stop_event = threading.Event()
        self._resync_event = threading.Event()
        self.reconciler: Reconciler | None = None
        self.manager: ReceiverManager | None = None

    def _request(
        self,
        method: str,
        path: str,
        data: bytes | None = None,
        timeout: float = 10.0,
    ) -> urllib.request.Request:
        url = f"http://{self.server_host}:{self.port}{path}"
        req = urllib.request.Request(url, data=data, method=method)
        if self.secret:
            req.add_header("Authorization", f"Bearer {self.secret}")
        return req

    def fetch_configuration(self) -> None:
        req = self._request("GET", "/configuration")
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.leader_id = data["leader"]
            self.follower_ids = data["followers"]
            logger.info(
                "Fetched configuration: Leader=%s, Followers=%s",
                self.leader_id,
                self.follower_ids,
            )

    def _get_desired_host(self) -> int | None:
        if self._leader_here:
            return self.host_number

        if not self._connected_to_server:
            if (
                self._disconnected_since
                and (time.monotonic() - self._disconnected_since) > SERVER_GRACE_PERIOD
            ):
                return None  # Hold devices

        return self.leader_host

    def _rebind(self, receivers: list[Receiver]) -> None:
        self.local_receivers = receivers
        all_devices: list[PairedDevice] = []
        for r in receivers:
            all_devices.extend(r.enumerate_devices())

        self.follower_devices = [
            d
            for d in all_devices
            if any(device_matches(d, fid) for fid in self.follower_ids)
        ]
        if self.reconciler:
            self.reconciler.set_devices(self.follower_devices)
        logger.info("Found %d local follower devices", len(self.follower_devices))

    def _on_notification(self, receiver: Receiver, notification: Notification) -> None:
        if notification.sub_id != 0x41:
            return

        status = parse_connection_status(notification.data)
        connected = status["connected"]

        dev = next(
            (
                d
                for d in self.follower_devices
                if d.receiver is receiver and d.number == notification.devnumber
            ),
            None,
        )
        if dev is None:
            dev = receiver.get_device(notification.devnumber)
        if dev is None:
            return

        is_leader = (dev.id == self.leader_id) or (
            self.leader_id is not None and device_matches(dev, self.leader_id)
        )

        if connected:
            logger.info("Device %s connected", dev.id)
        else:
            logger.info("Device %s disconnected", dev.id)

        if is_leader:
            self._leader_here = connected
            if self.reconciler:
                self.reconciler.poke()

            if connected:
                # Leader connected to this machine! Notify server and pull clipboard
                threading.Thread(target=self._report_leader_here, daemon=True).start()
                if self.clipboard_enabled:
                    threading.Thread(target=self._pull_clipboard, daemon=True).start()
            else:
                # Leader disconnected from this machine! Push clipboard to server
                if self.clipboard_enabled:
                    threading.Thread(target=self._push_clipboard, daemon=True).start()
        else:
            if self.reconciler:
                self.reconciler.observe(dev, connected)

    def _report_leader_here(self) -> None:
        try:
            req = self._request(
                "PUT", "/leader-host", data=str(self.host_number).encode("utf-8")
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                if resp.status == 200:
                    logger.info(
                        "Reported leader is on host %d to server", self.host_number
                    )
        except Exception as e:
            logger.warning("Could not report leader to server: %s", e)

    def _pull_clipboard(self) -> None:
        try:
            req = self._request("GET", "/clipboard")
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                if resp.status == 200:
                    text = resp.read().decode("utf-8", errors="replace")
                    set_clipboard(text)
                    logger.info("Pulled clipboard from server (%d bytes)", len(text))
        except Exception as e:
            logger.debug("Failed pulling clipboard: %s", e)

    def _push_clipboard(self) -> None:
        try:
            text = get_clipboard()
            req = self._request("PUT", "/clipboard", data=text.encode("utf-8"))
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                if resp.status == 200:
                    logger.info("Pushed clipboard to server (%d bytes)", len(text))
        except Exception as e:
            logger.debug("Failed pushing clipboard: %s", e)

    def _consume_events(self) -> None:
        backoff = 1.0
        while not self.stop_event.is_set():
            try:
                req = self._request("GET", "/events")
                with urllib.request.urlopen(req, timeout=30.0) as resp:
                    self._connected_to_server = True
                    backoff = 1.0
                    logger.info("Connected to server SSE event stream")

                    for r in self.local_receivers:
                        try:
                            r.notify_devices()
                        except Exception:
                            pass

                    event_type = "message"
                    data_lines: list[str] = []

                    while not self.stop_event.is_set():
                        raw_line = resp.readline()
                        if not raw_line:
                            break
                        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                        if not line:
                            if data_lines:
                                self._handle_event(event_type, "\n".join(data_lines))
                            event_type = "message"
                            data_lines = []
                            continue

                        if line.startswith(":"):
                            continue

                        field, _, val = line.partition(":")
                        if val.startswith(" "):
                            val = val[1:]

                        if field == "event":
                            event_type = val
                        elif field == "data":
                            data_lines.append(val)

            except Exception as e:
                if self._connected_to_server:
                    logger.warning("Disconnected from server: %s", e)
                    self._connected_to_server = False
                    self._disconnected_since = time.monotonic()

            if self.stop_event.is_set():
                break

            self._resync_event.wait(backoff)
            self._resync_event.clear()
            backoff = min(backoff * 2, 30.0)

    def _handle_event(self, event_type: str, data: str) -> None:
        if event_type == "leader-host":
            try:
                new_host = int(data.strip())
                self.leader_host = new_host
                logger.info("Server reported leader on host %d", new_host)
                if self.reconciler:
                    self.reconciler.poke()
            except ValueError:
                pass
        elif event_type == "leader-host-unknown":
            logger.info("Server reported leader position is unknown (holding devices)")
            self.leader_host = None
            if self.reconciler:
                self.reconciler.poke()

    def start(self) -> None:
        logger.info(
            "Connecting to server at http://%s:%d...", self.server_host, self.port
        )
        while not self.stop_event.is_set():
            try:
                self.fetch_configuration()
                break
            except Exception as e:
                logger.warning("Waiting for server: %s (retrying in 2s)", e)
                time.sleep(2.0)

        # Enumerate local receivers
        infos = find_receivers()
        self.local_receivers = [Receiver(info) for info in infos]
        self._rebind(self.local_receivers)

        self.reconciler = Reconciler(
            self.follower_devices,
            get_desired_host=self._get_desired_host,
            host_number=self.host_number,
        )
        self.manager = ReceiverManager(
            self.local_receivers,
            rebind=self._rebind,
            callback=self._on_notification,
        )

        self.manager.start()
        self.reconciler.start()

        event_thread = threading.Thread(target=self._consume_events, daemon=True)
        event_thread.start()

        logger.info("Flow client running (Host %d)", self.host_number)
        try:
            while not self.stop_event.is_set():
                time.sleep(1.0)
        except KeyboardInterrupt:
            logger.info("Shutting down client...")
        finally:
            self.stop_event.set()
            self._resync_event.set()
            if self.reconciler:
                self.reconciler.stop()
            if self.manager:
                self.manager.stop()


# ==============================================================================
# Commands: List, Switch, Watch
# ==============================================================================


def cmd_list(args: argparse.Namespace) -> None:
    receivers_info = find_receivers()
    if not receivers_info:
        print("No Logitech receivers found.")
        return

    print(f"Found {len(receivers_info)} Logitech receiver(s):")
    print("-" * 75)
    print(f"{'ID / Serial':<14} {'Kind':<10} {'Name':<22} {'Path':<18}")
    print("-" * 75)

    for info in receivers_info:
        try:
            with Receiver(info) as r:
                devices = r.enumerate_devices()
                if not devices:
                    receiver_label = "(receiver)"
                    no_dev_label = "(no paired devices)"
                    print(
                        f"{receiver_label:<14} {r.kind:<10} {no_dev_label:<22} "
                        f"{r.path:<18}"
                    )
                for dev in devices:
                    name = dev.codename or dev.kind
                    print(f"{dev.id:<14} {dev.kind:<10} {name:<22} {dev.path:<18}")
        except PermissionError:
            print(
                f"Permission denied accessing {info.path}. "
                "Try running with sudo or set up udev rules."
            )
        except Exception as e:
            print(f"Error accessing {info.path}: {e}")
    print("-" * 75)


def cmd_switch(args: argparse.Namespace) -> None:
    target_host = args.host_number
    identifier = args.device

    receivers_info = find_receivers()
    for info in receivers_info:
        try:
            with Receiver(info) as r:
                dev = find_matching_device(r.enumerate_devices(), identifier)
                if dev is not None:
                    name = dev.codename or dev.kind
                    print(
                        f"Found device {name} ({dev.id}). "
                        f"Switching to host {target_host}..."
                    )
                    change_device_host(dev, target_host)
                    print("Switch command sent successfully.")
                    return
        except Exception as e:
            logger.debug("Error checking receiver %s: %s", info.path, e)

    print(f"Error: device '{identifier}' not found on any connected receiver.")
    sys.exit(1)


def cmd_watch(args: argparse.Namespace) -> None:
    target = args.device
    print(f"Watching for events on '{target}'... (Press Ctrl+C to exit)")

    receivers_info = find_receivers()
    if not receivers_info:
        print("No Logitech receivers found.")
        sys.exit(1)

    receivers = [Receiver(info) for info in receivers_info]
    listeners: list[NotificationListener] = []

    def callback(r: Receiver, notif: Notification) -> None:
        if notif.sub_id == 0x41:
            dev = r.get_device(notif.devnumber)
            if dev and device_matches(dev, target):
                st = parse_connection_status(notif.data)
                action = "CONNECTED" if st["connected"] else "DISCONNECTED"
                name = dev.codename or dev.kind
                print(f"[{time.strftime('%X')}] {name} ({dev.id}): {action}")

    for r in receivers:
        listener = NotificationListener(
            r.path, lambda notif, rec=r: callback(rec, notif)
        )
        listener.start()
        listeners.append(listener)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nExiting watch.")
        for listener in listeners:
            listener.stop()


# ==============================================================================
# Configuration File Support (configparser by Hostname)
# ==============================================================================

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.config/logitech_flow.ini")


def get_default_config_paths() -> list[str]:
    paths: list[str] = []
    real_home = os.environ.get("SNAP_REAL_HOME")
    if real_home:
        paths.append(os.path.join(real_home, ".config", "logitech_flow.ini"))
    paths.append(DEFAULT_CONFIG_PATH)
    paths.extend(
        [
            "logitech_flow.ini",
            os.path.expanduser("~/.config/logitech_flow.conf"),
            os.path.expanduser("~/.config/logitech-flow/config.ini"),
            "logitech_flow.conf",
            "flow.ini",
            "config.ini",
        ]
    )
    seen: set[str] = set()
    result: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result


def find_config_file(explicit_path: str | None = None) -> str | None:
    if explicit_path:
        if not os.path.isfile(explicit_path):
            raise FileNotFoundError(f"Config file not found: {explicit_path}")
        with open(explicit_path):
            pass
        return explicit_path

    for candidate in get_default_config_paths():
        try:
            if os.path.isfile(candidate):
                with open(candidate):
                    pass
                return candidate
        except (PermissionError, OSError):
            continue
    return None


def load_config(
    explicit_path: str | None = None,
) -> tuple[configparser.ConfigParser | None, str | None]:
    path = find_config_file(explicit_path)
    if not path:
        return None, None
    cp = configparser.ConfigParser()
    cp.read(path)
    return cp, path


def get_host_section_name(
    cp: configparser.ConfigParser,
    target_hostname: str | None = None,
) -> str | None:
    if target_hostname is None:
        target_hostname = socket.gethostname()

    candidates = [
        target_hostname,
        target_hostname.lower(),
        target_hostname.split(".")[0],
        target_hostname.split(".")[0].lower(),
    ]
    for candidate in candidates:
        if cp.has_section(candidate):
            return candidate
    return None


def get_host_config(
    explicit_path: str | None = None,
    target_hostname: str | None = None,
) -> tuple[str | None, str | None, dict[str, Any]]:
    """Extract settings for the current hostname from the INI config file."""
    cp, path = load_config(explicit_path)
    if cp is None:
        return None, None, {}

    section = get_host_section_name(cp, target_hostname)
    if not section:
        return path, None, {}

    data: dict[str, Any] = {}
    sec = cp[section]

    # Mode / role (server or client)
    mode = sec.get("mode") or sec.get("role")
    if mode:
        data["mode"] = mode.strip().lower()

    # Host number
    if "host_number" in sec:
        try:
            data["host_number"] = sec.getint("host_number")
        except ValueError:
            pass

    # Devices
    data["leader_device"] = sec.get("leader_device") or sec.get("leader")
    followers_raw = sec.get("follower_devices") or sec.get("followers") or ""
    if followers_raw:
        data["follower_devices"] = [
            f.strip() for f in re.split(r"[\s,]+", followers_raw) if f.strip()
        ]

    # Server address for client
    data["server"] = sec.get("server")

    # Network / options
    if "bind" in sec:
        data["bind"] = sec.get("bind")
    if "port" in sec:
        try:
            data["port"] = sec.getint("port")
        except ValueError:
            pass
    if "clipboard" in sec:
        data["clipboard"] = sec.getboolean("clipboard", fallback=True)
    if "secret" in sec:
        data["secret"] = sec.get("secret")

    return path, section, data


def cmd_config(args: argparse.Namespace) -> None:
    config_path, section, cfg = get_host_config(getattr(args, "config", None))
    current_host = socket.gethostname()

    print("Logitech Flow Host Configuration:")
    print("-" * 55)
    print(f"{'Detected Hostname':<20}: {current_host}")
    print(f"{'Config File Path':<20}: {config_path or '(none found)'}")
    print(f"{'Active Section':<20}: {f'[{section}]' if section else '(none matched)'}")
    print("-" * 55)

    if cfg:
        for k, v in cfg.items():
            print(f"{k:<20}: {v}")
    else:
        if config_path:
            print(
                f"To configure this machine, add a [{current_host}] "
                f"section to '{config_path}'."
            )
        else:
            print("Create a '~/.config/logitech_flow.ini' file to configure hosts.")
    print("-" * 55)


def cmd_server(args: argparse.Namespace) -> None:
    config_path, section, cfg = get_host_config(getattr(args, "config", None))

    host_number = getattr(args, "host_number", None)
    if host_number is None:
        host_number = cfg.get("host_number")

    leader_device = getattr(args, "leader_device", None)
    if leader_device is None:
        leader_device = cfg.get("leader_device")

    follower_devices = getattr(args, "follower_devices", None)
    if not follower_devices:
        follower_devices = cfg.get("follower_devices")

    bind = getattr(args, "bind", "0.0.0.0")
    if bind == "0.0.0.0":
        bind = cfg.get("bind", "0.0.0.0")

    port = getattr(args, "port", DEFAULT_PORT)
    if port == DEFAULT_PORT:
        port = cfg.get("port", DEFAULT_PORT)

    no_clipboard = getattr(args, "no_clipboard", False)
    clipboard_enabled = (
        (not no_clipboard) if no_clipboard else cfg.get("clipboard", True)
    )

    secret = getattr(args, "secret", None)
    if secret is None:
        secret = cfg.get("secret")

    if host_number is None or leader_device is None or not follower_devices:
        cur_host = socket.gethostname()
        print(
            "Error: Missing required server parameters "
            "(host_number, leader_device, follower_devices)."
        )
        if section:
            print(
                f"Loaded [{section}] from '{config_path}', "
                "but required fields are missing."
            )
        else:
            print(f"No section for hostname '{cur_host}' found in config file.")
        print(
            "Provide them on the command line or configure a [hostname] "
            "section in '~/.config/logitech_flow.ini'."
        )
        sys.exit(1)

    receiver_infos = find_receivers()
    if not receiver_infos:
        print("Error: No Logitech receivers found.")
        sys.exit(1)

    try:
        receivers = [Receiver(info) for info in receiver_infos]
    except PermissionError as e:
        print(
            f"Error accessing receiver: {e}. "
            "Try running with sudo or configure udev rules."
        )
        sys.exit(1)
    all_ids = [leader_device, *follower_devices]

    try:
        resolved = resolve_devices(receivers, all_ids)
    except DeviceNotFound as e:
        print(f"Error: {e}")
        print("Run './logitech_flow.py list' to inspect available devices.")
        sys.exit(1)

    leader = resolved[leader_device]
    followers = [resolved[fid] for fid in follower_devices]

    instance = FlowServerInstance(
        host_number=host_number,
        leader_device=leader,
        follower_devices=followers,
        clipboard_enabled=clipboard_enabled,
        secret=secret,
    )
    instance.start(host=bind, port=port)


def cmd_client(args: argparse.Namespace) -> None:
    config_path, section, cfg = get_host_config(getattr(args, "config", None))

    host_number = getattr(args, "host_number", None)
    if host_number is None:
        host_number = cfg.get("host_number")

    server = getattr(args, "server", None)
    if server is None:
        server = cfg.get("server")

    port = getattr(args, "port", DEFAULT_PORT)
    if port == DEFAULT_PORT:
        port = cfg.get("port", DEFAULT_PORT)

    no_clipboard = getattr(args, "no_clipboard", False)
    clipboard_enabled = (
        (not no_clipboard) if no_clipboard else cfg.get("clipboard", True)
    )

    secret = getattr(args, "secret", None)
    if secret is None:
        secret = cfg.get("secret")

    if host_number is None or server is None:
        cur_host = socket.gethostname()
        print("Error: Missing required client parameters (host_number, server).")
        if section:
            print(
                f"Loaded [{section}] from '{config_path}', "
                "but required fields are missing."
            )
        else:
            print(f"No section for hostname '{cur_host}' found in config file.")
        print(
            "Provide them on the command line or configure a [hostname] "
            "section in '~/.config/logitech_flow.ini'."
        )
        sys.exit(1)

    instance = FlowClientInstance(
        host_number=host_number,
        server_host=server,
        port=port,
        clipboard_enabled=clipboard_enabled,
        secret=secret,
    )
    instance.start()


def cmd_run(args: argparse.Namespace) -> None:
    config_path, section, cfg = get_host_config(getattr(args, "config", None))
    cur_host = socket.gethostname()

    if not config_path:
        print("Error: No configuration file found.")
        print(
            "Create a '~/.config/logitech_flow.ini' file or specify one with --config."
        )
        print("Run './logitech_flow.py --help' for usage.")
        sys.exit(1)

    if not section or not cfg:
        print(
            f"Error: Config file '{config_path}' has no section matching "
            f"current hostname '{cur_host}'."
        )
        print(f"Add a [{cur_host}] section to '{config_path}'.")
        sys.exit(1)

    mode = cfg.get("mode")
    if mode == "server":
        logger.info(
            "Auto-starting server for host [%s] (from %s)", section, config_path
        )
        cmd_server(args)
    elif mode == "client":
        logger.info(
            "Auto-starting client for host [%s] (from %s)", section, config_path
        )
        cmd_client(args)
    else:
        print(
            f"Error: Unknown or missing 'mode' in [{section}] "
            "(expected 'mode = server' or 'mode = client')."
        )
        sys.exit(1)


# ==============================================================================
# CLI Entrypoint
# ==============================================================================


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Logitech Flow KVM - One-key host switching for Logitech devices."
    )
    parser.add_argument(
        "-c",
        "--config",
        default=None,
        help="Path to config file (default: ~/.config/logitech_flow.ini)",
    )

    subparsers = parser.add_subparsers(dest="command")

    # run (auto based on hostname in config)
    subparsers.add_parser(
        "run",
        help="Run automatically based on hostname section in config file",
    )

    # config
    subparsers.add_parser(
        "config",
        help="Display detected hostname and active configuration settings",
    )

    # list
    subparsers.add_parser("list", help="List connected receivers and paired devices")

    # server
    p_server = subparsers.add_parser(
        "server",
        help="Run the Flow coordinator server (options fall back to config file)",
    )
    p_server.add_argument(
        "host_number",
        type=int,
        nargs="?",
        default=None,
        help="Host number for this PC (e.g. 1; optional if set in config)",
    )
    p_server.add_argument(
        "leader_device",
        nargs="?",
        default=None,
        help="ID/serial, kind ('keyboard'), or name ('MX Keys') of leader device",
    )
    p_server.add_argument(
        "follower_devices",
        nargs="*",
        default=None,
        help="ID/serial, kind ('mouse'), or name ('MX Anywhere') of follower(s)",
    )
    p_server.add_argument(
        "-b",
        "--bind",
        default="0.0.0.0",
        help="Binding interface address (default: 0.0.0.0)",
    )
    p_server.add_argument(
        "-p",
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Server port (default: {DEFAULT_PORT})",
    )
    p_server.add_argument(
        "--no-clipboard", action="store_true", help="Disable clipboard synchronization"
    )
    p_server.add_argument(
        "--secret",
        default=None,
        help="Optional preshared secret for HTTP authentication",
    )

    # client
    p_client = subparsers.add_parser(
        "client",
        help="Run the Flow client on another PC (options fall back to config file)",
    )
    p_client.add_argument(
        "host_number",
        type=int,
        nargs="?",
        default=None,
        help="Host number for this PC (e.g. 2; optional if set in config)",
    )
    p_client.add_argument(
        "server",
        nargs="?",
        default=None,
        help="IP or hostname of server (optional if set in config)",
    )
    p_client.add_argument(
        "-p",
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Server port (default: {DEFAULT_PORT})",
    )
    p_client.add_argument(
        "--no-clipboard", action="store_true", help="Disable clipboard synchronization"
    )
    p_client.add_argument(
        "--secret", default=None, help="Optional preshared secret matching the server"
    )

    # switch
    p_switch = subparsers.add_parser(
        "switch", help="Manually switch a device to a specific host"
    )
    p_switch.add_argument(
        "device",
        help="Device ID/serial, kind ('mouse'), name ('MX Anywhere'), or path",
    )
    p_switch.add_argument(
        "host_number", type=int, help="Target host number (1, 2, or 3)"
    )

    # watch
    p_watch = subparsers.add_parser("watch", help="Watch device connection events")
    p_watch.add_argument(
        "device",
        help="Device ID/serial, kind ('keyboard'), name, or path to watch",
    )

    args = parser.parse_args()

    if args.command is None or args.command == "run":
        cmd_run(args)
    elif args.command == "config":
        cmd_config(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "server":
        cmd_server(args)
    elif args.command == "client":
        cmd_client(args)
    elif args.command == "switch":
        cmd_switch(args)
    elif args.command == "watch":
        cmd_watch(args)


if __name__ == "__main__":
    main()
