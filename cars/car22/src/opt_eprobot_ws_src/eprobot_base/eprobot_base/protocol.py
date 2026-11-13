"""Wire protocol v2.1 for the ISCC_CAR STM32 chassis.

Single source of truth: ``固件代码/PROTOCOL.md``.  This module is deliberately
pure Python (no ROS, no pyserial) so it can be unit-tested on any machine and
reused by the ROS 2 node, the backtest simulator and the Pi 4 deployment.

Frame::

    0x5A | len | type | seq | payload ... | CRC16 hi | CRC16 lo

* ``len`` is the *whole* frame length (6..72), not the payload length.
* type bit7=0 host->chassis, bit7=1 chassis->host.
* CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflection, xorout 0),
  covering ``[0, len-2)`` and stored big-endian.
* Every multi-byte field is big-endian.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .imu_trust import IMU_AGE_INVALID, telemetry_imu_trusted

# ---------------------------------------------------------------------------
# Constants (PROTOCOL.md sections 1.2, 3.1, 4.1, 5.1)
# ---------------------------------------------------------------------------

FRAME_HEADER = 0x5A
FRAME_MIN = 6
FRAME_MAX = 72
PARTIAL_TIMEOUT_S = 0.050

# Downlink (host -> chassis)
TYPE_SET_VELOCITY = 0x01
TYPE_STOP = 0x02
TYPE_SET_LASER = 0x03
TYPE_GET_IMU = 0x11
TYPE_GET_DIAG = 0x12

# Uplink (chassis -> host)
TYPE_TELEMETRY = 0xC0
TYPE_ACK_SET_VELOCITY = 0x81
TYPE_ACK_STOP = 0x82
TYPE_ACK_SET_LASER = 0x83
TYPE_IMU_RAW = 0x91
TYPE_DIAG = 0x92

#: type -> total frame length.  Indexed by the *full* type byte (bit7
#: included), exactly like the firmware's 256-entry table.  A type not in this
#: table has no fixed length and is only bounded by FRAME_MIN..FRAME_MAX.
TYPE_LEN: Dict[int, int] = {
    TYPE_SET_VELOCITY: 16,
    TYPE_STOP: 6,
    TYPE_SET_LASER: 7,
    TYPE_GET_IMU: 6,
    TYPE_GET_DIAG: 6,
    TYPE_TELEMETRY: 22,
    TYPE_ACK_SET_VELOCITY: 7,
    TYPE_ACK_STOP: 7,
    TYPE_ACK_SET_LASER: 7,
    TYPE_IMU_RAW: 39,
    TYPE_DIAG: 70,
}

# Status codes (PROTOCOL.md 5.1)
ST_OK = 0
ST_UNKNOWN_CMD = 1
ST_INTERLOCK = 2
ST_FAULT_LATCHED = 3
ST_BUSY = 4
ST_RANGE = 5
ST_STALE = 6

STATUS_NAMES = {
    ST_OK: "OK",
    ST_UNKNOWN_CMD: "UNKNOWN_CMD",
    ST_INTERLOCK: "INTERLOCK",
    ST_FAULT_LATCHED: "FAULT_LATCHED",
    ST_BUSY: "BUSY",
    ST_RANGE: "RANGE",
    ST_STALE: "STALE",
}

# flags bits (PROTOCOL.md 4.3)
FLAG_ARMED = 1 << 0
FLAG_FAULT = 1 << 1
FLAG_CAL_FAILED = 1 << 2
FLAG_IMU_OK = 1 << 3
FLAG_GYRO_FS_OK = 1 << 4
FLAG_BRAKING = 1 << 5
FLAG_STALLED = 1 << 6
FLAG_LASER_ON = 1 << 7

# Protocol limits (PROTOCOL.md 3.2)
VX_MAX_MM_S = 1500
STEER_MAX_MRAD = 524
GAIN_HOLD = -1
GAIN_MIN = 0
GAIN_MAX = 32767

#: DLPF group delay of the MPU6050 CONFIG=2 setting used by the firmware.
DLPF_DELAY_MS = 3.0

#: Telemetry `age` saturation value: no usable snapshot.
AGE_INVALID = IMU_AGE_INVALID


class ProtocolError(ValueError):
    """Raised when a frame cannot be built or decoded."""


# ---------------------------------------------------------------------------
# CRC / byte helpers
# ---------------------------------------------------------------------------


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE.  ``crc16(b"123456789") == 0x29B1``."""
    crc = 0xFFFF
    for value in data:
        crc ^= value << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def _i16(payload: bytes, offset: int) -> int:
    return struct.unpack_from(">h", payload, offset)[0]


def _u16(payload: bytes, offset: int) -> int:
    return struct.unpack_from(">H", payload, offset)[0]


def _i32(payload: bytes, offset: int) -> int:
    return struct.unpack_from(">i", payload, offset)[0]


def _put_i16(value: int) -> bytes:
    if not -32768 <= value <= 32767:
        raise ProtocolError("int16 out of range: %r" % (value,))
    return struct.pack(">h", value)


def _put_u16(value: int) -> bytes:
    if not 0 <= value <= 65535:
        raise ProtocolError("uint16 out of range: %r" % (value,))
    return struct.pack(">H", value)


def _saturate_i16(value: int) -> int:
    return max(-32768, min(32767, value))


# ---------------------------------------------------------------------------
# Frame building
# ---------------------------------------------------------------------------


def build_frame(type_: int, seq: int, payload: bytes = b"") -> bytes:
    """Build a frame for a *known* type, enforcing the type length table."""
    if type_ not in TYPE_LEN:
        raise ProtocolError(
            "unknown type 0x%02X; use build_unknown_ack() for the 7-byte ACK"
            % type_
        )
    total = len(payload) + 6
    if TYPE_LEN[type_] != total:
        raise ProtocolError(
            "type 0x%02X requires %d bytes, got %d"
            % (type_, TYPE_LEN[type_], total)
        )
    return _assemble(type_, seq, payload, total)


def build_unknown_ack(type_: int, seq: int, status: int = ST_UNKNOWN_CMD) -> bytes:
    """The only legal frame outside the length table (PROTOCOL.md 3.6)."""
    if not type_ & 0x80:
        raise ProtocolError("unknown-ACK type must have bit7 set")
    return _assemble(type_, seq, bytes((status & 0xFF,)), 7)


def _assemble(type_: int, seq: int, payload: bytes, total: int) -> bytes:
    if not FRAME_MIN <= total <= FRAME_MAX:
        raise ProtocolError("frame length %d outside %d..%d" % (total, FRAME_MIN, FRAME_MAX))
    head = bytes((FRAME_HEADER, total, type_ & 0xFF, seq & 0xFF)) + payload
    crc = crc16(head)
    return head + bytes((crc >> 8, crc & 0xFF))


def encode_set_velocity(
    vx_mm_s: int,
    delta_mrad: int,
    seq: int,
    kp: int = 35,
    ki: int = 5,
    kd: int = 0,
) -> bytes:
    """0x01 SET_VELOCITY: five big-endian int16 fields (PROTOCOL.md 3.2)."""
    payload = b"".join(
        (
            _put_i16(int(vx_mm_s)),
            _put_i16(int(delta_mrad)),
            _put_i16(int(kp)),
            _put_i16(int(ki)),
            _put_i16(int(kd)),
        )
    )
    return build_frame(TYPE_SET_VELOCITY, seq, payload)


def encode_stop(seq: int) -> bytes:
    return build_frame(TYPE_STOP, seq)


def encode_set_laser(mode: int, seq: int) -> bytes:
    if not 0 <= mode <= 255:
        raise ProtocolError("laser mode must be 0..255")
    return build_frame(TYPE_SET_LASER, seq, bytes((mode,)))


def encode_get_imu(seq: int) -> bytes:
    return build_frame(TYPE_GET_IMU, seq)


def encode_get_diag(seq: int) -> bytes:
    return build_frame(TYPE_GET_DIAG, seq)


# ---------------------------------------------------------------------------
# Frame model and streaming parser
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Frame:
    type: int
    seq: int
    payload: bytes
    raw: bytes
    rx_time: float = 0.0

    @property
    def ack_for(self) -> Optional[int]:
        """For a 7-byte ACK, the downlink command it answers; else None."""
        if len(self.raw) == 7 and self.type & 0x80:
            return self.type & 0x7F
        return None

    @property
    def status(self) -> Optional[int]:
        if self.ack_for is not None:
            return self.payload[0]
        return None


class FrameParser:
    """Byte-stream state machine with the firmware's resync rules.

    * a bad length, bad type-length pair or bad CRC drops exactly **one** byte
      (a real frame header may be hiding inside the garbage);
    * the partial-frame timeout is measured from the *last byte received*, not
      from the start of the frame (PROTOCOL.md 2.5).
    """

    def __init__(self, partial_timeout: float = PARTIAL_TIMEOUT_S) -> None:
        self.partial_timeout = float(partial_timeout)
        self._buf = bytearray()
        self._last_byte_time = 0.0
        self.crc_errors = 0
        self.length_errors = 0
        self.bytes_dropped = 0
        self.consecutive_crc_errors = 0

    def reset(self) -> None:
        self._buf.clear()
        self._last_byte_time = 0.0
        self.consecutive_crc_errors = 0

    @property
    def buffered(self) -> int:
        return len(self._buf)

    def feed(self, data: bytes, now: float) -> List[Frame]:
        frames: List[Frame] = []
        if not data:
            return frames
        self._buf.extend(data)
        self._last_byte_time = now

        while True:
            if len(self._buf) < 2:
                break

            # 1) find the header, dropping one byte at a time
            if self._buf[0] != FRAME_HEADER:
                idx = self._buf.find(bytes((FRAME_HEADER,)))
                if idx < 0:
                    self.bytes_dropped += len(self._buf)
                    del self._buf[:]
                    break
                self.bytes_dropped += idx
                del self._buf[:idx]
                if len(self._buf) < 2:
                    break

            # 2) validate len
            total = self._buf[1]
            if not FRAME_MIN <= total <= FRAME_MAX:
                self.length_errors += 1
                self._drop_one()
                continue

            # 3) validate the type/length pair (unknown types only get 6..72)
            if len(self._buf) < 4:
                break
            type_ = self._buf[2]
            # PROTOCOL.md 3.6: *any* uplink frame with len=7 is a generic ACK,
            # even when its type collides with a data type (0xC0/0x91/0x92).
            # The type-length table must not reject that 7-byte ACK.
            is_generic_ack = total == 7 and bool(type_ & 0x80)
            expected = TYPE_LEN.get(type_)
            if not is_generic_ack and expected is not None and expected != total:
                self.length_errors += 1
                self._drop_one()
                continue

            # 4) wait for the whole frame
            if len(self._buf) < total:
                break

            raw = bytes(self._buf[:total])
            want = (raw[-2] << 8) | raw[-1]
            if crc16(raw[:-2]) != want:
                self.crc_errors += 1
                self.consecutive_crc_errors += 1
                self._drop_one()
                continue

            self.consecutive_crc_errors = 0
            frames.append(
                Frame(
                    type=type_,
                    seq=raw[3],
                    payload=raw[4:-2],
                    raw=raw,
                    rx_time=now,
                )
            )
            del self._buf[:total]

        # A valid frame is at most 72 bytes.  If we are still waiting for a
        # frame that claims <=72 bytes but the buffer is far larger, the head
        # is bogus; drop one byte and let the loop resync.
        while len(self._buf) > FRAME_MAX and self._buf and self._buf[0] == FRAME_HEADER:
            if len(self._buf) >= 2 and self._buf[1] <= len(self._buf):
                break
            self._drop_one()
        return frames

    def tick(self, now: float) -> bool:
        """Drop a half frame after ``partial_timeout`` without new bytes."""
        if self._buf and (now - self._last_byte_time) >= self.partial_timeout:
            self.bytes_dropped += len(self._buf)
            self._buf.clear()
            return True
        return False

    def _drop_one(self) -> None:
        if self._buf:
            del self._buf[0]
            self.bytes_dropped += 1


# ---------------------------------------------------------------------------
# Decoded uplink messages
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Flags:
    raw: int

    @property
    def armed(self) -> bool:
        return bool(self.raw & FLAG_ARMED)

    @property
    def fault(self) -> bool:
        return bool(self.raw & FLAG_FAULT)

    @property
    def cal_failed(self) -> bool:
        return bool(self.raw & FLAG_CAL_FAILED)

    @property
    def imu_ok(self) -> bool:
        return bool(self.raw & FLAG_IMU_OK)

    @property
    def gyro_fs_ok(self) -> bool:
        return bool(self.raw & FLAG_GYRO_FS_OK)

    @property
    def braking(self) -> bool:
        return bool(self.raw & FLAG_BRAKING)

    @property
    def stalled(self) -> bool:
        return bool(self.raw & FLAG_STALLED)

    @property
    def laser_on(self) -> bool:
        return bool(self.raw & FLAG_LASER_ON)

    def names(self) -> List[str]:
        names = []
        for bit, name in (
            (FLAG_ARMED, "ARMED"),
            (FLAG_FAULT, "FAULT"),
            (FLAG_CAL_FAILED, "CAL_FAILED"),
            (FLAG_IMU_OK, "IMU_OK"),
            (FLAG_GYRO_FS_OK, "GYRO_FS_OK"),
            (FLAG_BRAKING, "BRAKING"),
            (FLAG_STALLED, "STALLED"),
            (FLAG_LASER_ON, "LASER_ON"),
        ):
            if self.raw & bit:
                names.append(name)
        return names

    def __str__(self) -> str:
        return "|".join(self.names()) or "0x00"


@dataclass(frozen=True)
class Telemetry:
    """0xC0 TELEMETRY, 22 bytes, pushed at 100 Hz."""

    vx_mm_s: int
    yaw_cdeg: int
    gyro_cdps: int
    pwm_left: int
    pwm_right: int
    steer_us: int
    battery_mv: int
    flags: Flags
    age_ms: int

    @property
    def vx_mps(self) -> float:
        """Firmware-scale speed (compiled D=0.065 m).  Multiply by base_kv."""
        return self.vx_mm_s / 1000.0

    @property
    def yaw_deg(self) -> float:
        return self.yaw_cdeg / 100.0

    @property
    def gyro_dps(self) -> float:
        return self.gyro_cdps / 100.0

    @property
    def age_valid(self) -> bool:
        return self.age_ms != AGE_INVALID

    @property
    def imu_trusted(self) -> bool:
        """Whether yaw/gyro may be used (PROTOCOL.md 6.2)."""
        return telemetry_imu_trusted(
            self.flags.imu_ok, self.flags.cal_failed, self.age_ms
        )


@dataclass(frozen=True)
class ImuRaw:
    """0x91 IMU_RAW, 39 bytes, answer to GET_IMU."""

    status: int
    gyro_dps: Tuple[float, float, float]
    accel_mm_s2: Tuple[float, float, float]
    quaternion: Tuple[float, float, float, float]  # w, x, y, z


@dataclass(frozen=True)
class Diag:
    """0x92 DIAG, 70 bytes, answer to GET_DIAG."""

    status: int
    raw_accel: Tuple[int, int, int]
    raw_gyro: Tuple[int, int, int]
    accel_mm_s2: Tuple[float, float, float]
    gyro_dps: Tuple[float, float, float]
    quaternion: Tuple[float, float, float, float]
    euler_deg: Tuple[float, float, float]
    flags: Flags
    dt_ticks: int
    i2c_errors: int


def decode_telemetry(payload: bytes) -> Telemetry:
    if len(payload) != 16:
        raise ProtocolError("TELEMETRY payload must be 16 bytes, got %d" % len(payload))
    return Telemetry(
        vx_mm_s=_i16(payload, 0),
        yaw_cdeg=_i16(payload, 2),
        gyro_cdps=_i16(payload, 4),
        pwm_left=_i16(payload, 6),
        pwm_right=_i16(payload, 8),
        steer_us=_u16(payload, 10),
        battery_mv=_u16(payload, 12),
        flags=Flags(payload[14]),
        age_ms=payload[15],
    )


def decode_imu_raw(payload: bytes) -> ImuRaw:
    if len(payload) != 33:
        raise ProtocolError("IMU_RAW payload must be 33 bytes, got %d" % len(payload))
    return ImuRaw(
        status=payload[0],
        gyro_dps=tuple(_i32(payload, 1 + 4 * i) * 1e-5 for i in range(3)),
        accel_mm_s2=tuple(_i32(payload, 13 + 4 * i) * 1e-4 for i in range(3)),
        quaternion=tuple(_i16(payload, 25 + 2 * i) / 10000.0 for i in range(4)),
    )


def decode_diag(payload: bytes) -> Diag:
    if len(payload) != 64:
        raise ProtocolError("DIAG payload must be 64 bytes, got %d" % len(payload))
    return Diag(
        status=payload[0],
        raw_accel=tuple(_i16(payload, 1 + 2 * i) for i in range(3)),
        raw_gyro=tuple(_i16(payload, 7 + 2 * i) for i in range(3)),
        accel_mm_s2=tuple(_i32(payload, 13 + 4 * i) * 0.01 for i in range(3)),
        gyro_dps=tuple(_i32(payload, 25 + 4 * i) * 0.01 for i in range(3)),
        quaternion=tuple(_i32(payload, 37 + 4 * i) / 10000.0 for i in range(4)),
        euler_deg=tuple(_i16(payload, 53 + 2 * i) * 0.01 for i in range(3)),
        flags=Flags(payload[59]),
        dt_ticks=_u16(payload, 60),
        i2c_errors=_u16(payload, 62),
    )


def decode_frame(frame: Frame):
    """Decode a data frame by ``(type, len)``; returns None for ACKs/unknown."""
    if frame.type == TYPE_TELEMETRY and len(frame.raw) == 22:
        return decode_telemetry(frame.payload)
    if frame.type == TYPE_IMU_RAW and len(frame.raw) == 39:
        return decode_imu_raw(frame.payload)
    if frame.type == TYPE_DIAG and len(frame.raw) == 70:
        return decode_diag(frame.payload)
    return None


def status_name(status: int) -> str:
    return STATUS_NAMES.get(status, "0x%02X" % status)


def parse_one(data: bytes, now: float = 0.0) -> List[Frame]:
    """Convenience helper for tests/tools: parse every complete frame in bytes."""
    return FrameParser().feed(data, now)
