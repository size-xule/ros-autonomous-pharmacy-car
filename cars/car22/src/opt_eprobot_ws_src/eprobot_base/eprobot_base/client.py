"""Chassis client: protocol state machine, handshake, keepalive and safety.

This class is ROS-agnostic on purpose.  It owns a byte transport and a
:class:`~eprobot_base.protocol.FrameParser`, and implements the host-side rules
from PROTOCOL.md sections 5 and 6:

* drain 200 ms after opening the port;
* send ``STOP`` first and wait for ``0x82 status=0`` plus ``flags.ARMED``;
* stream ``SET_VELOCITY`` at a fixed rate (also when idle, as a keepalive);
* on ``INTERLOCK``/``FAULT_LATCHED`` stop immediately and re-arm;
* declare the link lost after 400 ms without any valid frame, or telemetry
  stale after 200 ms;
* never send a non-zero speed unless the chassis is armed, fault-free and the
  telemetry is fresh.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Deque, Dict, Optional, Tuple

from . import protocol as P
from .transport import Transport, TransportError


class State(Enum):
    CLOSED = "CLOSED"
    DRAINING = "DRAINING"
    HANDSHAKE = "HANDSHAKE"
    READY = "READY"
    FAULT = "FAULT"
    ERROR = "ERROR"


@dataclass
class ClientConfig:
    cmd_period: float = 0.033  # 30 Hz SET_VELOCITY
    keepalive_period: float = 0.25  # well inside the 400 ms link timeout
    ack_timeout: float = 0.05
    handshake_timeout: float = 0.5
    handshake_retries: int = 3
    reconnect_interval: float = 2.0
    drain_time: float = 0.2
    telemetry_stale_timeout: float = 0.2
    link_timeout: float = 0.4
    cmd_timeout: float = 0.5
    max_vx_mm_s: int = 1000
    max_steer_mrad: int = P.STEER_MAX_MRAD
    # Wire units (0.1): 350/500 -> firmware PID kp=35.0, ki=50.0.  These are
    # the values that pass the Renode HIL (drive + stall fault); the old
    # 35/5 produced 0.012 m/s and never reached the stall threshold.
    kp: int = 350
    ki: int = 500
    kd: int = 0
    auto_clear_faults: bool = True
    fault_stop_interval: float = 0.25
    laser_mode: int = 0
    query_timeout: float = 0.15
    query_retries: int = 1


@dataclass
class _Pending:
    frame: bytes
    sent_at: float
    retries: int
    kind: str


@dataclass
class Stats:
    rx_frames: int = 0
    tx_frames: int = 0
    telemetry_frames: int = 0
    ack_frames: int = 0
    imu_frames: int = 0
    diag_frames: int = 0
    crc_errors: int = 0
    length_errors: int = 0
    bytes_dropped: int = 0
    unknown_frames: int = 0
    stop_sent: int = 0
    stop_acked: int = 0
    velocity_sent: int = 0
    status_counts: Dict[int, int] = field(default_factory=dict)
    state_changes: int = 0
    reconnects: int = 0
    last_error: str = ""


class ChassisClient:
    def __init__(
        self,
        transport: Transport,
        config: Optional[ClientConfig] = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        on_telemetry: Optional[Callable[[P.Telemetry, P.Frame], None]] = None,
        on_imu: Optional[Callable[[P.ImuRaw, P.Frame], None]] = None,
        on_diag: Optional[Callable[[P.Diag, P.Frame], None]] = None,
        on_status: Optional[Callable[[int, int, int], None]] = None,
        on_state: Optional[Callable[[State, State, str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.transport = transport
        self.config = config or ClientConfig()
        self.clock = clock
        self.on_telemetry = on_telemetry
        self.on_imu = on_imu
        self.on_diag = on_diag
        self.on_status = on_status
        self.on_state = on_state
        self.on_error = on_error

        self.parser = P.FrameParser()
        self.state = State.CLOSED
        self.stats = Stats()

        self._seq = 0
        self._now = 0.0
        self._drain_until = 0.0
        self._handshake_started = 0.0
        self._handshake_tries = 0
        self._error_since = 0.0
        self._last_rx_time = 0.0
        self._last_tx_time = 0.0
        self._last_velocity_tx = 0.0
        self._last_stop_tx = 0.0
        self._last_auto_stop = 0.0
        self._last_setpoint_time = 0.0
        self._stop_acked = False

        self._pending: Dict[Tuple[int, int], _Pending] = {}
        self._pending_query: Optional[_Pending] = None
        self._pending_laser_mode: Dict[int, int] = {}
        self._setpoint = (0, 0)
        self._want_velocity = False
        self._pending_laser: Optional[int] = None

        self.telemetry: Optional[P.Telemetry] = None
        self.imu_raw: Optional[P.ImuRaw] = None
        self.diag: Optional[P.Diag] = None
        self.last_telemetry_time = 0.0
        self.last_imu_time = 0.0
        self.last_diag_time = 0.0
        self.last_status: Optional[Tuple[int, int, int]] = None
        self.laser_mode = 0
        self.events: Deque[str] = deque(maxlen=64)

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def open(self, now: Optional[float] = None) -> None:
        now = self.clock() if now is None else now
        self.transport.open()
        self.parser.reset()
        self._seq = 0
        self._now = now
        self._drain_until = now + self.config.drain_time
        self._handshake_started = now
        self._handshake_tries = 0
        self._stop_acked = False
        self._pending.clear()
        self._pending_query = None
        self._pending_laser_mode.clear()
        self._last_rx_time = now
        self._last_tx_time = now
        self._last_velocity_tx = 0.0
        self._setpoint = (0, 0)
        self._want_velocity = False
        self.telemetry = None
        self.imu_raw = None
        self.diag = None
        self._change_state(State.DRAINING, "port opened, draining %.0f ms" % (self.config.drain_time * 1e3))

    def close(self, now: Optional[float] = None) -> None:
        now = self.clock() if now is None else now
        if self.state is not State.CLOSED and self.transport.is_open:
            try:
                self.send_stop(now, reason="shutdown", force=True)
            except Exception:
                pass
        try:
            self.transport.close()
        finally:
            self._change_state(State.CLOSED, "closed")

    @property
    def ready(self) -> bool:
        return self.state is State.READY

    def telemetry_age(self, now: Optional[float] = None) -> float:
        now = self.clock() if now is None else now
        if self.telemetry is None:
            return float("inf")
        return now - self.last_telemetry_time

    def telemetry_stale(self, now: Optional[float] = None) -> bool:
        return self.telemetry_age(now) > self.config.telemetry_stale_timeout

    # ------------------------------------------------------------------
    # public commands
    # ------------------------------------------------------------------
    def set_setpoint(self, vx_mm_s: int, delta_mrad: int, now: Optional[float] = None) -> None:
        now = self.clock() if now is None else now
        vx = max(-self.config.max_vx_mm_s, min(self.config.max_vx_mm_s, int(vx_mm_s)))
        delta = max(-self.config.max_steer_mrad, min(self.config.max_steer_mrad, int(delta_mrad)))
        self._setpoint = (vx, delta)
        self._last_setpoint_time = now
        self._want_velocity = True

    def clear_setpoint(self) -> None:
        self._setpoint = (0, 0)
        self._want_velocity = False

    def stop(self, now: Optional[float] = None, reason: str = "operator") -> None:
        """STOP: the only command that clears faults and re-arms the chassis."""
        now = self.clock() if now is None else now
        self.clear_setpoint()
        if not self.transport.is_open:
            return
        self.send_stop(now, reason=reason, force=True)
        self._stop_acked = False
        self._handshake_started = now
        self._handshake_tries = 1
        if self.state in (State.READY, State.FAULT):
            self._change_state(State.HANDSHAKE, "STOP requested (%s)" % reason)

    def set_laser(self, mode: int, now: Optional[float] = None) -> bool:
        if not 0 <= int(mode) <= 2:
            raise ValueError("laser mode must be 0, 1 or 2")
        now = self.clock() if now is None else now
        if self.state is not State.READY:
            self._pending_laser = int(mode)
            return False
        self._send_laser(int(mode), now)
        return True

    def query_imu(self, now: Optional[float] = None) -> bool:
        return self._send_query(P.TYPE_GET_IMU, now)

    def query_diag(self, now: Optional[float] = None) -> bool:
        return self._send_query(P.TYPE_GET_DIAG, now)

    # ------------------------------------------------------------------
    # polling
    # ------------------------------------------------------------------
    def poll(self, now: Optional[float] = None) -> None:
        now = self.clock() if now is None else now
        self._now = now
        if self.state is State.CLOSED:
            return

        if not self.transport.is_open:
            if self.state is not State.ERROR:
                self._enter_error(now, "transport is closed")
            self._tick(now)
            return

        try:
            for _ in range(64):
                data = self.transport.read(4096)
                if not data:
                    break
                for frame in self.parser.feed(data, now):
                    self._handle_frame(frame, now)
        except TransportError as exc:
            self._enter_error(now, str(exc))
            return
        except OSError as exc:
            self._enter_error(now, "transport I/O error: %s" % exc)
            return

        if self.parser.tick(now):
            self.events.append("partial frame dropped after 50 ms")
        self._sync_parser_stats()
        if self.parser.consecutive_crc_errors >= 3:
            # PROTOCOL.md 6.1: three consecutive bad-CRC frames are a link
            # exception, not just noise; force a clean reopen.
            self.parser.reset()
            self._enter_error(now, "3 consecutive CRC errors")
            return
        self._tick(now)

    # ------------------------------------------------------------------
    # frame handling
    # ------------------------------------------------------------------
    def _handle_frame(self, frame: P.Frame, now: float) -> None:
        self.stats.rx_frames += 1
        self._last_rx_time = now

        if frame.type == P.TYPE_TELEMETRY and len(frame.raw) == 22:
            telemetry = P.decode_telemetry(frame.payload)
            self.telemetry = telemetry
            self.last_telemetry_time = now
            self.stats.telemetry_frames += 1
            if self.on_telemetry is not None:
                self.on_telemetry(telemetry, frame)
            self._handle_telemetry_flags(telemetry, now)
            return

        if frame.type == P.TYPE_IMU_RAW and len(frame.raw) == 39:
            imu = P.decode_imu_raw(frame.payload)
            self.imu_raw = imu
            self.last_imu_time = now
            self.stats.imu_frames += 1
            self._clear_pending_query(P.TYPE_GET_IMU)
            if self.on_imu is not None:
                self.on_imu(imu, frame)
            return

        if frame.type == P.TYPE_DIAG and len(frame.raw) == 70:
            diag = P.decode_diag(frame.payload)
            self.diag = diag
            self.last_diag_time = now
            self.stats.diag_frames += 1
            self._clear_pending_query(P.TYPE_GET_DIAG)
            if self.on_diag is not None:
                self.on_diag(diag, frame)
            return

        if len(frame.raw) == 7 and frame.type & 0x80:
            status = frame.payload[0]
            self.stats.ack_frames += 1
            self.stats.status_counts[status] = self.stats.status_counts.get(status, 0) + 1
            self.last_status = (frame.type & 0x7F, frame.seq, status)
            self._pending.pop((frame.type, frame.seq), None)
            if frame.type == P.TYPE_ACK_STOP and status == P.ST_OK:
                self.stats.stop_acked += 1
                self._stop_acked = True
                self.laser_mode = 0
                if self.state is State.HANDSHAKE and self._telemetry_armed():
                    self._change_state(State.READY, "STOP ACK + ARMED")
            if frame.type == P.TYPE_ACK_SET_LASER:
                mode = self._pending_laser_mode_for_seq(frame.seq)
                if mode is not None and status == P.ST_OK:
                    self.laser_mode = mode
            if status == P.ST_INTERLOCK:
                self.events.append("INTERLOCK on 0x%02X" % (frame.type & 0x7F))
                self._auto_rearm(now, "INTERLOCK")
            elif status == P.ST_FAULT_LATCHED:
                self.events.append("FAULT_LATCHED on 0x%02X" % (frame.type & 0x7F))
                self._auto_stop_for_fault(now)
            elif status == P.ST_UNKNOWN_CMD:
                self.events.append("chassis rejected unknown command 0x%02X" % (frame.type & 0x7F))
            elif status == P.ST_RANGE:
                self.events.append("RANGE on 0x%02X (clamped)" % (frame.type & 0x7F))
            if self.on_status is not None:
                self.on_status(frame.type & 0x7F, frame.seq, status)
            return

        self.stats.unknown_frames += 1
        self.events.append(
            "unknown uplink type=0x%02X len=%d" % (frame.type, len(frame.raw))
        )

    def _handle_telemetry_flags(self, telemetry: P.Telemetry, now: float) -> None:
        if self.state is State.READY:
            if telemetry.flags.fault:
                self._auto_stop_for_fault(now)
            elif not telemetry.flags.armed:
                self.events.append("telemetry says disarmed; re-handshaking")
                self._auto_rearm(now, "disarmed")
        elif self.state is State.HANDSHAKE and self._stop_acked and telemetry.flags.armed:
            self._change_state(State.READY, "armed")
        elif self.state is State.FAULT:
            if telemetry.flags.armed and not telemetry.flags.fault:
                self._change_state(State.READY, "fault cleared")

    def _telemetry_armed(self) -> bool:
        return self.telemetry is not None and self.telemetry.flags.armed

    # ------------------------------------------------------------------
    # timers
    # ------------------------------------------------------------------
    def _tick(self, now: float) -> None:
        self._expire_pending(now)

        if self.state is State.DRAINING:
            if now >= self._drain_until:
                self.send_stop(now, reason="handshake", force=True)
                if self.state is State.ERROR:
                    return
                self._handshake_started = now
                self._handshake_tries = 1
                self._change_state(State.HANDSHAKE, "drain complete")
            return

        if self.state is State.HANDSHAKE:
            if self._stop_acked and self._telemetry_armed():
                self._change_state(State.READY, "handshake complete")
                return
            if now - self._handshake_started >= self.config.handshake_timeout:
                if self._handshake_tries < self.config.handshake_retries:
                    self._handshake_tries += 1
                    self.send_stop(now, reason="handshake retry", force=True)
                    self._handshake_started = now
                else:
                    self._enter_error(now, "handshake failed after %d STOP attempts" % self._handshake_tries)
            return

        if self.state is State.ERROR:
            if now - self._error_since >= self.config.reconnect_interval:
                self._try_reopen(now)
            return

        if self.state is State.READY:
            if now - self._last_rx_time > self.config.link_timeout:
                self.events.append("link timeout (no valid frame for 400 ms)")
                self.send_stop(now, reason="link timeout", force=True)
                self._handshake_started = now
                self._handshake_tries = 1
                self._change_state(State.HANDSHAKE, "link timeout")
                return

            if self._pending_laser is not None:
                self._send_laser(self._pending_laser, now)
                self._pending_laser = None

            self._send_periodic(now)
            return

        if self.state is State.FAULT:
            if now - self._last_auto_stop >= self.config.fault_stop_interval:
                if self.config.auto_clear_faults:
                    self.send_stop(now, reason="fault clear", force=True)
                else:
                    # Keep the link alive without clearing the latch: vx=0 is
                    # accepted in FAULT and does not re-arm the chassis.
                    self._send_velocity(0, 0, now)
                self._last_auto_stop = now
            return

    def _send_periodic(self, now: float) -> None:
        if now - self._last_velocity_tx < self.config.cmd_period:
            return
        if self.telemetry_stale(now) or not self._telemetry_armed():
            vx, delta = 0, 0
        elif not self._want_velocity or now - self._last_setpoint_time > self.config.cmd_timeout:
            vx, delta = 0, 0
        else:
            vx, delta = self._setpoint
        self._send_velocity(vx, delta, now)

    def _expire_pending(self, now: float) -> None:
        for key, pending in list(self._pending.items()):
            if now - pending.sent_at < self.config.ack_timeout:
                continue
            if pending.retries < 3:
                try:
                    self._write(pending.frame, now)
                except TransportError as exc:
                    self._enter_error(now, str(exc))
                    return
                pending.sent_at = now
                pending.retries += 1
            else:
                self._pending.pop(key, None)
                self.events.append("%s ACK timeout" % pending.kind)

        query = self._pending_query
        if query is not None and now - query.sent_at >= self.config.query_timeout:
            if query.retries < self.config.query_retries:
                try:
                    self._write(query.frame, now)
                except TransportError as exc:
                    self._enter_error(now, str(exc))
                    return
                query.sent_at = now
                query.retries += 1
            else:
                self._pending_query = None
                self.events.append("query 0x%02X timed out" % (query.frame[2] & 0x7F))

    def _try_reopen(self, now: float) -> None:
        self.stats.reconnects += 1
        try:
            self.transport.close()
        except Exception:
            pass
        try:
            self.transport.open()
        except Exception as exc:
            self._error_since = now
            self._error(str(exc))
            return
        self.parser.reset()
        self._pending.clear()
        self._pending_query = None
        self._stop_acked = False
        self._drain_until = now + self.config.drain_time
        self._last_rx_time = now
        self._change_state(State.DRAINING, "reopened, draining")

    def _enter_error(self, now: float, reason: str) -> None:
        if self.state is State.ERROR:
            self._error(reason)
            return
        self._error_since = now
        self.clear_setpoint()
        self._change_state(State.ERROR, reason)
        self._error(reason)

    def _auto_rearm(self, now: float, reason: str) -> None:
        if self.state not in (State.READY, State.HANDSHAKE):
            return
        self.send_stop(now, reason="auto rearm: " + reason, force=True)
        if self.state is State.ERROR:
            return
        self._stop_acked = False
        self._handshake_started = now
        self._handshake_tries = 1
        self._change_state(State.HANDSHAKE, "auto rearm: " + reason)

    def _auto_stop_for_fault(self, now: float) -> None:
        if self.state is State.FAULT:
            return
        self.clear_setpoint()
        self.send_stop(now, reason="fault", force=True)
        if self.state is State.ERROR:
            return
        self._last_auto_stop = now
        self._change_state(State.FAULT, "fault latched")

    # ------------------------------------------------------------------
    # raw send helpers
    # ------------------------------------------------------------------
    def _next_seq(self) -> int:
        seq = self._seq
        self._seq = (self._seq + 1) & 0xFF
        return seq

    def _write(self, frame: bytes, now: float) -> None:
        try:
            self.transport.write(frame)
        except TransportError:
            raise
        except OSError as exc:
            raise TransportError(str(exc)) from exc
        self._last_tx_time = now
        self.stats.tx_frames += 1

    def _sync_parser_stats(self) -> None:
        """Expose the parser's cumulative counters through Stats."""
        self.stats.crc_errors = self.parser.crc_errors
        self.stats.length_errors = self.parser.length_errors
        self.stats.bytes_dropped = self.parser.bytes_dropped

    def send_stop(self, now: Optional[float] = None, reason: str = "", force: bool = False) -> None:
        now = self.clock() if now is None else now
        if not self.transport.is_open:
            return
        if not force and now - self._last_stop_tx < 0.02:
            return
        seq = self._next_seq()
        frame = P.encode_stop(seq)
        try:
            self._write(frame, now)
        except TransportError as exc:
            self._enter_error(now, str(exc))
            return
        self._last_stop_tx = now
        self.stats.stop_sent += 1
        self._pending[(P.TYPE_ACK_STOP, seq)] = _Pending(frame, now, 0, "STOP")
        if len(self._pending) > 16:
            self._pending.pop(next(iter(self._pending)))

    def _send_velocity(self, vx_mm_s: int, delta_mrad: int, now: float) -> None:
        seq = self._next_seq()
        frame = P.encode_set_velocity(
            vx_mm_s,
            delta_mrad,
            seq,
            kp=self.config.kp,
            ki=self.config.ki,
            kd=self.config.kd,
        )
        try:
            self._write(frame, now)
        except TransportError as exc:
            self._enter_error(now, str(exc))
            return
        self._last_velocity_tx = now
        self.stats.velocity_sent += 1

    def _send_laser(self, mode: int, now: float) -> None:
        seq = self._next_seq()
        frame = P.encode_set_laser(mode, seq)
        try:
            self._write(frame, now)
        except TransportError as exc:
            self._enter_error(now, str(exc))
            return
        self._pending[(P.TYPE_ACK_SET_LASER, seq)] = _Pending(frame, now, 0, "SET_LASER")
        self._pending_laser_mode[seq] = mode

    def _pending_laser_mode_for_seq(self, seq: int) -> Optional[int]:
        mode = self._pending_laser_mode.pop(seq, None)
        if len(self._pending_laser_mode) > 16:
            self._pending_laser_mode.pop(next(iter(self._pending_laser_mode)))
        return mode

    def _send_query(self, type_: int, now: Optional[float] = None) -> bool:
        now = self.clock() if now is None else now
        if self.state is not State.READY or not self.transport.is_open:
            return False
        if self._pending_query is not None:
            return False
        seq = self._next_seq()
        frame = P.encode_get_imu(seq) if type_ == P.TYPE_GET_IMU else P.encode_get_diag(seq)
        try:
            self._write(frame, now)
        except TransportError as exc:
            self._enter_error(now, str(exc))
            return False
        self._pending_query = _Pending(frame, now, 0, "query")
        return True

    def _clear_pending_query(self, type_: int) -> None:
        if self._pending_query is not None:
            pending_type = self._pending_query.frame[2]
            if pending_type == type_:
                self._pending_query = None

    # ------------------------------------------------------------------
    # state helpers
    # ------------------------------------------------------------------
    def _change_state(self, new: State, reason: str) -> None:
        old = self.state
        if old is new:
            return
        self.state = new
        self.stats.state_changes += 1
        self.events.append("%s -> %s: %s" % (old.value, new.value, reason))
        if self.on_state is not None:
            self.on_state(old, new, reason)

    def _error(self, message: str) -> None:
        self.stats.last_error = message
        if self.on_error is not None:
            self.on_error(message)
