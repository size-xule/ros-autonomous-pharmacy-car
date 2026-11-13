"""Host-side state machine tests for ``eprobot_base.client``.

Everything is driven by a mutable fake clock and
:class:`eprobot_base.transport.LoopbackTransport`; the suite never sleeps and
never touches a real UART.  The chassis is played by the test: it injects ACK
and telemetry frames and inspects the frames the client wrote.
"""

import struct

from eprobot_base import protocol as P
from eprobot_base.client import ChassisClient, ClientConfig, State
from eprobot_base.transport import LoopbackTransport


# ---------------------------------------------------------------------------
# test rig
# ---------------------------------------------------------------------------


class FakeClock:
    """Mutable ``time.monotonic`` replacement."""

    def __init__(self, start=0.0):
        self.now = float(start)

    def __call__(self):
        return self.now

    def advance(self, dt):
        self.now += float(dt)


def make_frame(type_, seq, payload=b""):
    """Build a frame straight from the PROTOCOL.md §2.1 layout."""
    total = len(payload) + 6
    assert 6 <= total <= 72
    body = bytes((P.FRAME_HEADER, total, type_, seq)) + payload
    crc = P.crc16(body)
    return body + bytes((crc >> 8, crc & 0xFF))


class OSErrorTransport(LoopbackTransport):
    """Loopback whose ``write`` raises a raw ``OSError`` once armed.

    pyserial's ``SerialException`` is an ``OSError`` subclass; raising the
    built-in here pins the client's ``_write`` conversion without pyserial.
    """

    def __init__(self):
        super().__init__()
        self.fail_writes = False
        self.write_calls = 0

    def write(self, data):
        self.write_calls += 1
        if self.fail_writes:
            raise OSError(5, "Input/output error")
        super().write(data)


class Rig:
    """A client + loopback transport + fake clock, with chassis-side helpers."""

    def __init__(self, transport=None, **overrides):
        options = dict(
            drain_time=0.0,
            cmd_period=0.05,
            handshake_timeout=0.5,
            ack_timeout=0.05,
            cmd_timeout=0.5,
        )
        options.update(overrides)
        self.config = ClientConfig(**options)
        self.clock = FakeClock()
        self.transport = transport if transport is not None else LoopbackTransport()
        self.client = ChassisClient(self.transport, self.config, clock=self.clock)
        self._telemetry_seq = 0

    # -- plumbing ---------------------------------------------------------
    def poll(self):
        self.client.poll()
        return self

    def advance(self, dt):
        self.clock.advance(dt)
        return self

    def feed(self, data):
        self.transport.feed(data)
        return self

    def take(self):
        """Parse and clear everything the client has written so far."""
        return P.parse_one(self.transport.take_written())

    # -- chassis side -----------------------------------------------------
    def telemetry(self, flags, vx_mm_s=0, yaw_cdeg=0, gyro_cdps=0, age_ms=0):
        payload = struct.pack(
            ">hhhhhHHBB",
            vx_mm_s,
            yaw_cdeg,
            gyro_cdps,
            0,
            0,
            1500,
            11800,
            flags,
            age_ms,
        )
        frame = P.build_frame(P.TYPE_TELEMETRY, self._telemetry_seq, payload)
        self._telemetry_seq = (self._telemetry_seq + 1) & 0xFF
        return frame

    def ack(self, type_, seq, status):
        return P.build_frame(type_, seq, bytes((status,)))

    # -- scenarios --------------------------------------------------------
    def open_and_poll(self):
        """Open the port and return the STOP written by the first poll."""
        self.client.open()
        self.poll()
        frames = self.take()
        assert len(frames) == 1, "first poll wrote %r" % (frames,)
        stop = frames[0]
        assert stop.type == P.TYPE_STOP, "first frame must be STOP, got 0x%02X" % (
            stop.type,
        )
        return stop

    def become_ready(self):
        stop = self.open_and_poll()
        self.feed(self.ack(P.TYPE_ACK_STOP, stop.seq, P.ST_OK))
        self.feed(self.telemetry(P.FLAG_ARMED | P.FLAG_IMU_OK))
        self.poll()
        assert self.client.state is State.READY, self.client.state
        self.take()
        return self


def velocity_frames(frames):
    return [f for f in frames if f.type == P.TYPE_SET_VELOCITY]


def vx_of(frame):
    return struct.unpack(">h", frame.payload[:2])[0]


def delta_of(frame):
    return struct.unpack(">h", frame.payload[2:4])[0]


# ---------------------------------------------------------------------------
# handshake
# ---------------------------------------------------------------------------


def test_first_poll_sends_stop():
    rig = Rig()
    stop = rig.open_and_poll()
    assert stop.seq == 0
    assert len(stop.raw) == 6
    assert rig.client.state is State.HANDSHAKE


def test_handshake_needs_stop_ack_and_armed_telemetry():
    rig = Rig()
    stop = rig.open_and_poll()

    # ACK alone is not enough: ARMED must be observed in telemetry.
    rig.feed(rig.ack(P.TYPE_ACK_STOP, stop.seq, P.ST_OK))
    rig.poll()
    assert rig.client.state is State.HANDSHAKE
    assert rig.client.ready is False
    rig.take()

    # ARMED telemetry alone is not enough either (the STOP was not acked).
    rig2 = Rig()
    rig2.open_and_poll()
    rig2.feed(rig2.telemetry(P.FLAG_ARMED | P.FLAG_IMU_OK))
    rig2.poll()
    assert rig2.client.state is State.HANDSHAKE

    # Both together complete the handshake.
    rig.feed(rig.telemetry(P.FLAG_ARMED | P.FLAG_IMU_OK))
    rig.poll()
    assert rig.client.state is State.READY
    assert rig.client.ready is True


# ---------------------------------------------------------------------------
# SET_VELOCITY streaming
# ---------------------------------------------------------------------------


def test_ready_streams_set_velocity_with_configured_gains():
    rig = Rig()
    rig.become_ready()
    rig.client.set_setpoint(500, 0)
    rig.advance(rig.config.cmd_period)
    rig.poll()

    velocities = velocity_frames(rig.take())
    assert len(velocities) == 1
    frame = velocities[0]
    assert len(frame.raw) == 16
    vx, delta, kp, ki, kd = struct.unpack(">hhhhh", frame.payload)
    assert vx == 500
    assert delta == 0
    assert (kp, ki, kd) == (350, 500, 0)


def test_idle_after_cmd_timeout_sends_zero_keepalive():
    rig = Rig()
    rig.become_ready()
    rig.client.set_setpoint(500, 0)
    rig.advance(rig.config.cmd_period)
    rig.poll()
    assert [vx_of(f) for f in velocity_frames(rig.take())] == [500]

    # No new setpoint for longer than cmd_timeout: the keepalive must be vx=0.
    rig.advance(rig.config.cmd_timeout + 0.1)
    rig.feed(rig.telemetry(P.FLAG_ARMED | P.FLAG_IMU_OK))
    rig.poll()
    assert [vx_of(f) for f in velocity_frames(rig.take())] == [0]


def test_disarmed_telemetry_never_sends_nonzero_vx():
    rig = Rig()
    rig.become_ready()
    rig.client.set_setpoint(500, 0)

    rig.feed(rig.telemetry(P.FLAG_IMU_OK))  # ARMED clear
    rig.advance(rig.config.cmd_period)
    rig.poll()
    for frame in rig.take():
        if frame.type == P.TYPE_SET_VELOCITY:
            assert vx_of(frame) == 0, "non-zero vx while disarmed"

    # Keep polling for several command periods; still no non-zero command.
    for _ in range(6):
        rig.feed(rig.telemetry(P.FLAG_IMU_OK))
        rig.advance(rig.config.cmd_period)
        rig.poll()
        for frame in rig.take():
            if frame.type == P.TYPE_SET_VELOCITY:
                assert vx_of(frame) == 0, "non-zero vx while disarmed"


def test_set_setpoint_is_clamped_to_config_limits():
    rig = Rig()
    rig.become_ready()
    rig.client.set_setpoint(5000, 4000)
    rig.advance(rig.config.cmd_period)
    rig.poll()
    velocities = velocity_frames(rig.take())
    assert len(velocities) == 1
    assert vx_of(velocities[0]) == rig.config.max_vx_mm_s
    assert delta_of(velocities[0]) == rig.config.max_steer_mrad


# ---------------------------------------------------------------------------
# laser
# ---------------------------------------------------------------------------


def test_set_laser_is_queued_before_ready_and_acked_after():
    rig = Rig()
    stop = rig.open_and_poll()
    assert rig.client.state is State.HANDSHAKE

    assert rig.client.set_laser(2) is False
    assert rig.transport.pending_written == 0, "laser must be queued, not sent"

    rig.feed(rig.ack(P.TYPE_ACK_STOP, stop.seq, P.ST_OK))
    rig.feed(rig.telemetry(P.FLAG_ARMED | P.FLAG_IMU_OK))
    rig.poll()
    assert rig.client.state is State.READY

    frames = rig.take()
    lasers = [f for f in frames if f.type == P.TYPE_SET_LASER]
    assert len(lasers) == 1, frames
    assert lasers[0].payload == b"\x02"
    assert len(lasers[0].raw) == 7
    assert rig.client.laser_mode == 0, "mode only changes when the ACK arrives"

    rig.feed(rig.ack(P.TYPE_ACK_SET_LASER, lasers[0].seq, P.ST_OK))
    rig.poll()
    assert rig.client.laser_mode == 2
    assert rig.client.last_status == (P.TYPE_SET_LASER, lasers[0].seq, P.ST_OK)


# ---------------------------------------------------------------------------
# safety reactions
# ---------------------------------------------------------------------------


def test_interlock_ack_sends_stop_and_leaves_ready():
    rig = Rig()
    rig.become_ready()
    rig.feed(rig.ack(P.TYPE_ACK_SET_VELOCITY, 0x00, P.ST_INTERLOCK))
    rig.poll()

    assert rig.client.state is State.HANDSHAKE
    frames = rig.take()
    assert any(f.type == P.TYPE_STOP for f in frames), frames
    assert any("INTERLOCK" in event for event in rig.client.events)


def test_fault_latched_ack_enters_fault_and_sends_stop():
    rig = Rig()
    rig.become_ready()
    rig.feed(rig.ack(P.TYPE_ACK_SET_VELOCITY, 0x01, P.ST_FAULT_LATCHED))
    rig.poll()

    assert rig.client.state is State.FAULT
    frames = rig.take()
    assert any(f.type == P.TYPE_STOP for f in frames), frames


def test_telemetry_fault_stops_and_armed_telemetry_recovers():
    rig = Rig()
    rig.become_ready()

    rig.feed(rig.telemetry(P.FLAG_ARMED | P.FLAG_FAULT))
    rig.poll()
    assert rig.client.state is State.FAULT
    assert any(f.type == P.TYPE_STOP for f in rig.take())

    rig.feed(rig.telemetry(P.FLAG_ARMED | P.FLAG_IMU_OK))
    rig.poll()
    assert rig.client.state is State.READY


def test_link_timeout_sends_stop_and_rehandshakes():
    rig = Rig()
    rig.become_ready()
    rig.advance(0.41)  # > 400 ms with no valid frame
    rig.poll()

    assert rig.client.state is State.HANDSHAKE
    frames = rig.take()
    assert any(f.type == P.TYPE_STOP for f in frames), frames
    assert any("link timeout" in event for event in rig.client.events)


def test_stop_is_retransmitted_with_the_same_seq():
    rig = Rig()
    stop = rig.open_and_poll()

    rig.advance(rig.config.ack_timeout + 0.001)
    rig.poll()
    frames = rig.take()
    assert len(frames) == 1
    assert frames[0].type == P.TYPE_STOP
    assert frames[0].seq == stop.seq
    assert frames[0].raw == stop.raw


def test_close_sends_final_stop_before_closing():
    rig = Rig()
    rig.become_ready()
    rig.client.close()

    frames = rig.take()
    assert [f.type for f in frames] == [P.TYPE_STOP]
    assert rig.client.state is State.CLOSED
    assert rig.transport.is_open is False
    assert rig.transport.close_count == 1


# ---------------------------------------------------------------------------
# sequence numbers and unknown uplinks
# ---------------------------------------------------------------------------


def test_seq_wraps_from_ff_to_00():
    rig = Rig()
    rig.become_ready()
    rig.client._seq = 0xFF

    rig.client.send_stop(force=True)
    rig.advance(0.03)
    rig.client.send_stop(force=True)

    frames = rig.take()
    assert [f.type for f in frames] == [P.TYPE_STOP, P.TYPE_STOP]
    assert [f.seq for f in frames] == [0xFF, 0x00], "0x00 must follow 0xFF"

    # The parser/driver pair must still pair the wrapped ACK correctly.
    rig.feed(rig.ack(P.TYPE_ACK_STOP, 0x00, P.ST_OK))
    rig.poll()
    assert rig.client._stop_acked is True
    assert rig.client.stats.stop_acked >= 1


def test_unknown_uplink_is_counted_and_ignored():
    rig = Rig()
    rig.become_ready()
    rig.feed(make_frame(0x7F, 0x01, b"\xDE\xAD\xBE\xEF"))
    rig.poll()

    assert rig.client.state is State.READY
    assert rig.client.stats.unknown_frames == 1
    assert any("unknown uplink" in event for event in rig.client.events)


def test_unknown_command_ack_is_logged_not_fatal():
    rig = Rig()
    rig.become_ready()
    acks_before = rig.client.stats.ack_frames

    rig.feed(make_frame(0xFE, 0x33, b"\x01"))
    rig.poll()

    assert rig.client.state is State.READY
    assert rig.client.last_status == (0x7E, 0x33, P.ST_UNKNOWN_CMD)
    assert rig.client.stats.ack_frames == acks_before + 1
    assert any("unknown command" in event for event in rig.client.events)


def test_seven_byte_ack_for_a_mis_sent_query_type_is_accepted():
    # PROTOCOL.md §3.6: sending 0x91 as a *request* (39 bytes) is answered by
    # 0x91 with len=7 and status=1.  The client must classify that as a
    # generic ACK, not as IMU_RAW and not as an unknown frame.
    rig = Rig()
    rig.become_ready()
    acks_before = rig.client.stats.ack_frames
    imu_before = rig.client.stats.imu_frames

    rig.feed(make_frame(P.TYPE_IMU_RAW, 0x05, b"\x01"))
    rig.poll()

    assert rig.client.state is State.READY
    assert rig.client.last_status == (P.TYPE_GET_IMU, 0x05, P.ST_UNKNOWN_CMD)
    assert rig.client.stats.ack_frames == acks_before + 1
    assert rig.client.stats.imu_frames == imu_before
    assert rig.client.stats.unknown_frames == 0
    assert rig.client.imu_raw is None


# ---------------------------------------------------------------------------
# regression: transport write failures (review M5 / m2)
# ---------------------------------------------------------------------------


def test_write_oserror_enters_error_and_reconnects_after_interval():
    transport = OSErrorTransport()
    rig = Rig(transport=transport)
    rig.become_ready()
    assert transport.write_calls > 0
    opens_before = transport.open_count

    transport.fail_writes = True
    rig.client.set_setpoint(300, 0)
    rig.advance(rig.config.cmd_period)
    rig.poll()

    assert rig.client.state is State.ERROR
    assert "Input/output error" in rig.client.stats.last_error
    assert rig.client.stats.reconnects == 0
    assert rig.client.ready is False

    # ERROR is sticky until reconnect_interval has elapsed ...
    rig.advance(rig.config.reconnect_interval - 0.01)
    rig.poll()
    assert rig.client.state is State.ERROR
    assert transport.open_count == opens_before

    # ... then the transport is reopened and the drain starts again.
    rig.advance(0.02)
    rig.poll()
    assert rig.client.stats.reconnects == 1
    assert transport.open_count == opens_before + 1
    assert rig.client.state is State.DRAINING


def test_write_oserror_from_stop_enters_error():
    transport = OSErrorTransport()
    rig = Rig(transport=transport)
    stop = rig.open_and_poll()
    rig.feed(rig.ack(P.TYPE_ACK_STOP, stop.seq, P.ST_OK))
    rig.feed(rig.telemetry(P.FLAG_ARMED | P.FLAG_IMU_OK))
    rig.poll()
    assert rig.client.state is State.READY

    transport.fail_writes = True
    rig.client.stop(reason="test")
    assert rig.client.state is State.ERROR
    assert "Input/output error" in rig.client.stats.last_error


def test_fault_stop_write_failure_does_not_overwrite_error():
    transport = OSErrorTransport()
    rig = Rig(transport=transport)
    rig.become_ready()

    transport.fail_writes = True
    rig.feed(rig.telemetry(P.FLAG_ARMED | P.FLAG_FAULT))
    rig.poll()

    assert rig.client.state is State.ERROR
    assert rig.client.stats.last_error
    assert not any(
        "-> FAULT" in event for event in rig.client.events
    ), "a failed STOP must not claim the chassis reached FAULT"

    # Still ERROR after another poll: the reconnect timer is in charge.
    rig.poll()
    assert rig.client.state is State.ERROR


# ---------------------------------------------------------------------------
# regression: parser counters and consecutive-CRC escalation (review M6)
# ---------------------------------------------------------------------------


def test_poll_copies_parser_counters_into_stats():
    rig = Rig()
    rig.become_ready()

    # Garbage with no header at all: bytes_dropped.
    rig.feed(b"\xDE\xAD\xBE\xEF")

    # A structurally valid TELEMETRY frame with a corrupted CRC: crc_errors.
    bad = bytearray(rig.telemetry(P.FLAG_ARMED | P.FLAG_IMU_OK))
    bad[-1] ^= 0xFF
    rig.feed(bytes(bad))

    # A header whose len byte is outside 6..72: length_errors.
    rig.feed(bytes((P.FRAME_HEADER, P.FRAME_MAX + 4, P.TYPE_TELEMETRY, 0x01)))
    rig.poll()

    assert rig.client.stats.crc_errors >= 1
    assert rig.client.stats.length_errors >= 1
    assert rig.client.stats.bytes_dropped >= 1
    assert rig.client.stats.crc_errors == rig.client.parser.crc_errors
    assert rig.client.stats.length_errors == rig.client.parser.length_errors
    assert rig.client.stats.bytes_dropped == rig.client.parser.bytes_dropped
    # One bad CRC is noise, not a link exception.
    assert rig.client.state is State.READY


def test_two_bad_crc_frames_stay_ready_three_enter_error():
    rig = Rig()
    rig.become_ready()

    def bad_telemetry():
        raw = bytearray(rig.telemetry(P.FLAG_ARMED | P.FLAG_IMU_OK))
        raw[-1] ^= 0xFF
        return bytes(raw)

    rig.feed(bad_telemetry())
    rig.feed(bad_telemetry())
    rig.poll()
    assert rig.client.state is State.READY
    assert rig.client.parser.consecutive_crc_errors == 2
    assert rig.client.stats.crc_errors == 2

    # A single valid frame resets the consecutive counter ...
    rig.feed(rig.telemetry(P.FLAG_ARMED | P.FLAG_IMU_OK))
    rig.poll()
    assert rig.client.parser.consecutive_crc_errors == 0
    assert rig.client.stats.crc_errors == 2  # cumulative counter untouched
    assert rig.client.state is State.READY

    # ... but three bad frames in a row are a link exception.
    for _ in range(3):
        rig.feed(bad_telemetry())
    rig.poll()
    assert rig.client.state is State.ERROR
    assert "3 consecutive CRC errors" in rig.client.stats.last_error
    assert rig.client.parser.consecutive_crc_errors == 0


# ---------------------------------------------------------------------------
# regression: FAULT-state keepalive (review m1)
# ---------------------------------------------------------------------------


def test_fault_auto_clear_sends_stop_at_fault_stop_interval():
    rig = Rig()
    assert rig.config.fault_stop_interval == 0.25

    rig.become_ready()
    rig.feed(rig.telemetry(P.FLAG_ARMED | P.FLAG_FAULT))
    rig.poll()
    assert rig.client.state is State.FAULT

    # ACK the entry STOP so retransmissions do not pollute the gap measurement.
    entry_stops = [f for f in rig.take() if f.type == P.TYPE_STOP]
    assert entry_stops
    rig.feed(rig.ack(P.TYPE_ACK_STOP, entry_stops[-1].seq, P.ST_OK))
    rig.poll()

    stop_times = []
    elapsed = 0.0
    while elapsed < 0.62:
        rig.advance(0.01)
        elapsed += 0.01
        rig.poll()
        for frame in rig.take():
            if frame.type == P.TYPE_STOP:
                stop_times.append(elapsed)
                rig.feed(rig.ack(P.TYPE_ACK_STOP, frame.seq, P.ST_OK))
        rig.poll()

    assert len(stop_times) >= 2, "no periodic STOP in FAULT: %r" % (stop_times,)
    gaps = [later - earlier for earlier, later in zip(stop_times, stop_times[1:])]
    assert all(gap < 0.4 for gap in gaps), "FAULT STOP gap >= 400 ms: %r" % (gaps,)
    assert all(gap >= 0.2 for gap in gaps), "STOP sent too often: %r" % (gaps,)
    assert rig.client.state is State.FAULT


def test_fault_without_auto_clear_sends_zero_velocity_keepalive():
    rig = Rig(auto_clear_faults=False)
    assert rig.config.fault_stop_interval == 0.25

    rig.become_ready()
    rig.feed(rig.telemetry(P.FLAG_ARMED | P.FLAG_FAULT))
    rig.poll()
    assert rig.client.state is State.FAULT

    entry_stops = [f for f in rig.take() if f.type == P.TYPE_STOP]
    assert entry_stops
    rig.feed(rig.ack(P.TYPE_ACK_STOP, entry_stops[-1].seq, P.ST_OK))
    rig.poll()

    rig.advance(rig.config.fault_stop_interval)
    rig.poll()
    frames = rig.take()
    velocities = [f for f in frames if f.type == P.TYPE_SET_VELOCITY]
    assert velocities, "FAULT keepalive must write SET_VELOCITY(vx=0)"
    assert vx_of(velocities[-1]) == 0
    assert delta_of(velocities[-1]) == 0
    assert not any(f.type == P.TYPE_STOP for f in frames), (
        "auto_clear_faults=False must not send STOP"
    )
    assert rig.client.state is State.FAULT

    # The link stays alive: another keepalive one interval later, still no STOP.
    rig.advance(rig.config.fault_stop_interval)
    rig.poll()
    frames = rig.take()
    assert [vx_of(f) for f in frames if f.type == P.TYPE_SET_VELOCITY] == [0]
    assert not any(f.type == P.TYPE_STOP for f in frames)
    assert rig.client.state is State.FAULT


# ---------------------------------------------------------------------------
# regression: rejected SET_LASER ACK must not leak (review m5)
# ---------------------------------------------------------------------------


def test_rejected_laser_ack_drops_pending_and_ok_ack_cannot_resurrect():
    rig = Rig()
    rig.become_ready()

    assert rig.client.set_laser(2) is True
    lasers = [f for f in rig.take() if f.type == P.TYPE_SET_LASER]
    assert len(lasers) == 1
    seq = lasers[0].seq
    assert seq in rig.client._pending_laser_mode

    rig.feed(rig.ack(P.TYPE_ACK_SET_LASER, seq, P.ST_RANGE))
    rig.poll()
    assert rig.client._pending_laser_mode == {}
    assert (P.TYPE_ACK_SET_LASER, seq) not in rig.client._pending
    assert rig.client.laser_mode == 0

    # A duplicate/late OK ACK for the same sequence must not apply the mode.
    rig.feed(rig.ack(P.TYPE_ACK_SET_LASER, seq, P.ST_OK))
    rig.poll()
    assert rig.client.laser_mode == 0
    assert rig.client._pending_laser_mode == {}


def test_stop_ack_clears_laser_mode_cache():
    """STOP turns the laser off, so the client cache must follow the ACK."""
    rig = Rig()
    rig.become_ready()

    assert rig.client.set_laser(2) is True
    lasers = [f for f in rig.take() if f.type == P.TYPE_SET_LASER]
    assert len(lasers) == 1
    rig.feed(rig.ack(P.TYPE_ACK_SET_LASER, lasers[0].seq, P.ST_OK))
    rig.poll()
    assert rig.client.laser_mode == 2

    rig.client.stop()
    stops = [f for f in rig.take() if f.type == P.TYPE_STOP]
    assert stops
    rig.feed(rig.ack(P.TYPE_ACK_STOP, stops[-1].seq, P.ST_OK))
    rig.poll()
    assert rig.client.laser_mode == 0
