"""End-to-end test: EprobotBaseNode over a real TCP socket.

A fake chassis runs in a background thread on ``127.0.0.1:<free port>``.  It
speaks enough of protocol v2.1 to bring the node's :class:`ChassisClient`
through DRAINING -> HANDSHAKE -> READY:

* ``STOP``          -> ACK 0x82 status 0, then telemetry starts carrying the
  ``ARMED`` flag (never before STOP);
* ``SET_VELOCITY``  -> ACK 0x81 status 0, updates a rate-limited speed
  integrator;
* ``SET_LASER``     -> ACK 0x83 status 0;
* ``TELEMETRY`` (0xC0, 22 B) pushed at 100 Hz with vx/yaw/gyro/flags/age.

The node is created with ``transport=socket`` and the fake port, its real
``/odom`` publication is observed through rclpy, ``/imu/data`` is injected by
the test (standing in for the WHEELTEC H30), ``/cmd_vel`` is published once it
is READY, and ``node.shutdown()`` must put a STOP frame on the wire.

The chassis IMU is not part of the odometry path any more: no test expects a
``/imu/chassis`` topic or an ``IMU_RAW`` query.

The test is skipped (not failed) when rclpy is unavailable, which keeps
``make test`` working on a machine without ROS 2.  Everything is bounded by
timeouts and the server thread is always joined, so pytest never hangs on a
dangling thread.
"""

import contextlib
import math
import select
import socket
import struct
import threading
import time

import pytest

from eprobot_base import protocol as P
from eprobot_base.client import State
from eprobot_base.kinematics import quaternion_from_yaw

#: Skip cleanly on a host without ROS 2 (e.g. ``make test``).
rclpy = pytest.importorskip("rclpy")

from geometry_msgs.msg import Twist  # noqa: E402
from nav_msgs.msg import Odometry  # noqa: E402
from rclpy.executors import MultiThreadedExecutor  # noqa: E402
from sensor_msgs.msg import Imu  # noqa: E402

from eprobot_base.node import EprobotBaseNode  # noqa: E402

TELEMETRY_PERIOD_S = 0.01  # protocol v2.1: 100 Hz
#: Speed ramp of the fake chassis, mm/s per second.  300 mm/s in 150 ms.
SPEED_RAMP_MM_S2 = 2000.0
BATTERY_MV = 11800
STEER_US = 1500


class FakeChassis:
    """Minimal protocol v2.1 chassis on a TCP socket, in its own thread."""

    def __init__(self) -> None:
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self._listener.settimeout(0.1)
        self.port = self._listener.getsockname()[1]

        self._stop = threading.Event()
        self._connected = threading.Event()
        self.stop_seen = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="fake-chassis", daemon=True
        )
        self.error = None
        self.stop_frames = 0
        self.velocity_frames = 0
        self.last_vx_mm_s = 0

        # Telemetry content a test may change while the server is running.
        # The ARMED bit is still added by _telemetry() once a STOP arrived.
        self.telemetry_flags = P.FLAG_IMU_OK | P.FLAG_GYRO_FS_OK
        self.telemetry_age_ms = 0
        self.telemetry_yaw_cdeg = 0
        self.telemetry_gyro_cdps = 0

    # -- lifecycle -------------------------------------------------------
    def start(self) -> "FakeChassis":
        self._thread.start()
        return self

    def close(self) -> None:
        self._stop.set()
        try:
            self._listener.close()
        except OSError:
            pass
        self._thread.join(timeout=5.0)
        assert not self._thread.is_alive(), "fake chassis thread did not stop"

    def wait_connected(self, timeout: float) -> bool:
        return self._connected.wait(timeout)

    # -- thread ----------------------------------------------------------
    def _run(self) -> None:
        conn = None
        try:
            deadline = time.monotonic() + 10.0
            while not self._stop.is_set():
                try:
                    conn, _ = self._listener.accept()
                    break
                except socket.timeout:
                    if time.monotonic() > deadline:
                        raise AssertionError("node never connected to the fake chassis")
                except OSError:
                    if self._stop.is_set():
                        return
                    raise
            if conn is None:
                return
            self._connected.set()
            with conn:
                conn.settimeout(0.0)
                self._serve(conn)
        except Exception as exc:  # surfaced by the test after cleanup
            if not self._stop.is_set():
                self.error = exc
        finally:
            if conn is not None:
                try:
                    conn.close()
                except OSError:
                    pass

    def _serve(self, conn: socket.socket) -> None:
        parser = P.FrameParser()
        telemetry_seq = 0
        speed_mm_s = 0.0
        target_mm_s = 0
        armed = False
        next_tx = time.monotonic()
        last_tx = next_tx

        while not self._stop.is_set():
            now = time.monotonic()
            timeout = max(0.0, min(0.005, next_tx - now))
            try:
                readable, _, _ = select.select([conn], [], [], timeout)
            except (OSError, ValueError):
                return
            if readable:
                try:
                    data = conn.recv(4096)
                except BlockingIOError:
                    data = None
                except OSError:
                    return
                if data == b"":
                    return
                if data:
                    for frame in parser.feed(data, time.monotonic()):
                        armed, target_mm_s = self._handle(
                            conn, frame, armed, target_mm_s
                        )

            now = time.monotonic()
            if now < next_tx:
                continue

            # Rate-limited speed integrator (mm/s), evaluated per telemetry tick.
            dt = min(max(now - last_tx, 0.0), 0.1)
            last_tx = now
            step = SPEED_RAMP_MM_S2 * dt
            if speed_mm_s < target_mm_s:
                speed_mm_s = min(float(target_mm_s), speed_mm_s + step)
            elif speed_mm_s > target_mm_s:
                speed_mm_s = max(float(target_mm_s), speed_mm_s - step)

            try:
                conn.sendall(self._telemetry(int(speed_mm_s), armed, telemetry_seq))
            except OSError:
                return
            telemetry_seq = (telemetry_seq + 1) & 0xFF
            next_tx += TELEMETRY_PERIOD_S
            if next_tx < now - 0.05:  # fell behind: resynchronise, don't burst
                next_tx = now + TELEMETRY_PERIOD_S

    def _handle(self, conn, frame, armed, target_mm_s):
        if frame.type == P.TYPE_STOP:
            self.stop_frames += 1
            self.stop_seen.set()
            self._send_ack(conn, P.TYPE_ACK_STOP, frame.seq)
            return True, 0  # ARMED only after STOP

        if frame.type == P.TYPE_SET_VELOCITY:
            self.velocity_frames += 1
            vx_mm_s = struct.unpack_from(">h", frame.payload, 0)[0]
            self.last_vx_mm_s = vx_mm_s
            self._send_ack(conn, P.TYPE_ACK_SET_VELOCITY, frame.seq)
            return armed, vx_mm_s

        if frame.type == P.TYPE_SET_LASER:
            self._send_ack(conn, P.TYPE_ACK_SET_LASER, frame.seq)
            return armed, target_mm_s

        if frame.type == P.TYPE_GET_IMU:
            self._send_imu_raw(conn)
            return armed, target_mm_s

        # GET_DIAG is not queried by these tests.
        return armed, target_mm_s

    @staticmethod
    def _send_imu_raw(conn) -> None:
        """Answer GET_IMU with a fresh, trusted IMU_RAW snapshot."""
        payload = (
            struct.pack(">B", P.ST_OK)
            + struct.pack(">3i", 0, 0, 500000)  # 1e-5 dps -> 5 dps on z
            + struct.pack(">3i", 0, 0, 9800)  # 1e-4 mm/s^2
            + struct.pack(">4h", 10000, 0, 0, 0)  # identity quaternion (w first)
        )
        assert len(payload) == 33
        try:
            conn.sendall(P.build_frame(P.TYPE_IMU_RAW, 0x00, payload))
        except OSError:
            pass

    @staticmethod
    def _send_ack(conn, type_: int, seq: int) -> None:
        try:
            conn.sendall(P.build_frame(type_, seq, bytes((P.ST_OK,))))
        except OSError:
            pass

    def _telemetry(self, vx_mm_s: int, armed: bool, seq: int) -> bytes:
        flags = self.telemetry_flags
        if armed:
            flags |= P.FLAG_ARMED
        payload = struct.pack(
            ">hhhhhHHBB",
            vx_mm_s,
            self.telemetry_yaw_cdeg,
            self.telemetry_gyro_cdps,
            0,  # pwm_left
            0,  # pwm_right
            STEER_US,
            BATTERY_MV,
            flags,
            self.telemetry_age_ms,
        )
        return P.build_frame(P.TYPE_TELEMETRY, seq, payload)


def _wait_for(predicate, timeout: float, period: float = 0.01) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(period)
    return predicate()


def _h30_msg(yaw_deg: float, gyro_z: float = 0.0) -> Imu:
    """Build one ``/imu/data`` sample the way the H30 driver publishes it."""
    msg = Imu()
    msg.header.frame_id = "imu_link"
    x, y, z, w = quaternion_from_yaw(math.radians(yaw_deg))
    msg.orientation.x = x
    msg.orientation.y = y
    msg.orientation.z = z
    msg.orientation.w = w
    msg.orientation_covariance = [4e-4, 0.0, 0.0, 0.0, 4e-4, 0.0, 0.0, 0.0, 1e-2]
    msg.angular_velocity.z = gyro_z
    msg.angular_velocity_covariance = [1e-4, 0.0, 0.0, 0.0, 1e-4, 0.0, 0.0, 0.0, 1e-4]
    msg.linear_acceleration_covariance = [
        0.01, 0.0, 0.0,
        0.0, 0.01, 0.0,
        0.0, 0.0, 0.02,
    ]
    return msg


def test_node_publishes_odom_over_tcp():
    server = FakeChassis().start()
    node = None
    executor = None
    spin_thread = None

    try:
        rclpy.init(
            args=[
                "--ros-args",
                "-p", "transport:=socket",
                "-p", "socket_host:=127.0.0.1",
                "-p", "socket_port:=%d" % server.port,
                "-p", "publish_tf:=false",
                "-p", "odom_rate_hz:=20.0",
                "-p", "diagnostics_rate_hz:=5.0",
            ]
        )

        node = EprobotBaseNode()  # constructor opens the socket immediately
        assert server.wait_connected(10.0), "fake chassis was never contacted"

        odom_msgs = []
        node.create_subscription(Odometry, "/odom", odom_msgs.append, 10)
        h30_pub = node.create_publisher(Imu, "/imu/data", 10)
        cmd_pub = node.create_publisher(Twist, "/cmd_vel", 10)

        executor = MultiThreadedExecutor(num_threads=2)
        executor.add_node(node)
        spin_thread = threading.Thread(
            target=executor.spin, name="rclpy-spin", daemon=True
        )
        spin_thread.start()

        # DRAINING (200 ms) + STOP/ACK/ARMED handshake.
        assert _wait_for(lambda: node.client.state is State.READY, 10.0), (
            "node never reached READY (state=%s, events=%s)"
            % (node.client.state.value, list(node.client.events))
        )

        h30 = _h30_msg(0.0)
        twist = Twist()
        twist.linear.x = 0.3

        def moved() -> bool:
            return any(m.pose.pose.position.x > 0.05 for m in odom_msgs)

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not moved():
            h30_pub.publish(h30)
            cmd_pub.publish(twist)
            time.sleep(0.05)

        assert odom_msgs, "no /odom messages received"
        assert moved(), (
            "no /odom pose with x > 0.05 (last x=%r, vx frames=%d)"
            % (odom_msgs[-1].pose.pose.position.x, server.velocity_frames)
        )
        assert node.client.state is State.READY
        assert server.velocity_frames > 0, "fake chassis never saw SET_VELOCITY"
        assert server.last_vx_mm_s > 0, "SET_VELOCITY never carried a forward speed"
        assert node._yaw_source_used == "h30", "odom never used the injected H30 yaw"
        assert node.get_publishers_info_by_topic("/imu/chassis") == [], (
            "the node still publishes a chassis IMU topic"
        )
        assert node.client.imu_raw is None, "the node still queried IMU_RAW"

        node.shutdown()
        assert server.stop_seen.wait(3.0), "shutdown() did not send a STOP frame"
    finally:
        if node is not None:
            try:
                node.shutdown()
            except Exception:
                pass
        if executor is not None:
            executor.shutdown()
        if spin_thread is not None:
            spin_thread.join(timeout=5.0)
            assert not spin_thread.is_alive(), "rclpy executor thread did not stop"
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        server.close()

    assert server.error is None, "fake chassis failed: %r" % (server.error,)
    assert server.stop_frames >= 1


@contextlib.contextmanager
def _node_session(extra_params=()):
    """Fake chassis + ``EprobotBaseNode`` + spinning executor, already READY.

    Yields ``(server, node, odom_msgs, h30_msgs, cmd_pub)``.  ``h30_msgs`` is a
    loopback subscription to ``/imu/data`` used to confirm the injected H30
    stream is flowing.  Cleanup is
    identical to the long-form test above, so a failed assertion still joins
    the server and executor threads.
    """
    server = FakeChassis().start()
    node = None
    executor = None
    spin_thread = None

    try:
        params = [
                "--ros-args",
                "-p", "transport:=socket",
                "-p", "socket_host:=127.0.0.1",
                "-p", "socket_port:=%d" % server.port,
                "-p", "publish_tf:=false",
                "-p", "odom_rate_hz:=20.0",
                "-p", "diagnostics_rate_hz:=5.0",
        ]
        for parameter in extra_params:
            params.extend(["-p", parameter])
        rclpy.init(args=params)

        node = EprobotBaseNode()
        assert server.wait_connected(10.0), "fake chassis was never contacted"

        odom_msgs = []
        h30_msgs = []
        node.create_subscription(Odometry, "/odom", odom_msgs.append, 10)
        node.create_subscription(Imu, "/imu/data", h30_msgs.append, 10)
        cmd_pub = node.create_publisher(Twist, "/cmd_vel", 10)

        executor = MultiThreadedExecutor(num_threads=2)
        executor.add_node(node)
        spin_thread = threading.Thread(
            target=executor.spin, name="rclpy-spin", daemon=True
        )
        spin_thread.start()

        assert _wait_for(lambda: node.client.state is State.READY, 10.0), (
            "node never reached READY (state=%s, events=%s)"
            % (node.client.state.value, list(node.client.events))
        )
        yield server, node, odom_msgs, h30_msgs, cmd_pub
    finally:
        if node is not None:
            try:
                node.shutdown()
            except Exception:
                pass
        if executor is not None:
            executor.shutdown()
        if spin_thread is not None:
            spin_thread.join(timeout=5.0)
            assert not spin_thread.is_alive(), "rclpy executor thread did not stop"
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        server.close()


def test_cmd_vel_zero_linear_stops_before_cmd_timeout():
    """A turn-in-place Twist must cancel the previous setpoint at once (M4)."""
    with _node_session() as (server, node, _odom_msgs, _imu_msgs, cmd_pub):
        forward = Twist()
        forward.linear.x = 0.3

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and server.last_vx_mm_s <= 0:
            cmd_pub.publish(forward)
            time.sleep(0.02)
        assert server.last_vx_mm_s > 0, "fake chassis never saw a forward speed"
        assert node.client.state is State.READY

        in_place = Twist()
        in_place.linear.x = 0.0
        in_place.angular.z = 0.5
        cmd_pub.publish(in_place)

        # 250 ms is half the 0.5 s cmd_timeout: seeing vx=0 this early proves
        # the in-place command cancelled the setpoint, not the watchdog.
        assert _wait_for(lambda: server.last_vx_mm_s == 0, 0.25), (
            "in-place cmd_vel did not reach the chassis within 250 ms "
            "(last vx=%d mm/s)" % server.last_vx_mm_s
        )
        assert node.client.state is State.READY

        time.sleep(0.1)
        assert server.last_vx_mm_s == 0, "previous setpoint came back"
        assert node.client.state is State.READY

    assert server.error is None, "fake chassis failed: %r" % (server.error,)
    assert server.stop_frames >= 1


def test_odom_ignores_chassis_imu_without_h30():
    """Chassis telemetry yaw/gyro must never steer odom when H30 is absent."""
    with _node_session() as (server, node, odom_msgs, _h30_msgs, _cmd_pub):
        server.telemetry_yaw_cdeg = 4200  # 42 deg
        server.telemetry_gyro_cdps = 500  # 5 deg/s

        assert _wait_for(lambda: len(odom_msgs) >= 5, 5.0), "no /odom messages"
        for msg in odom_msgs:
            orientation = msg.pose.pose.orientation
            assert abs(2.0 * math.atan2(orientation.z, orientation.w)) < 1e-6, (
                "chassis yaw leaked into odom"
            )
            assert msg.twist.twist.angular.z == 0.0, (
                "chassis gyro leaked into odom twist"
            )

        assert node._yaw_source_used == "hold"
        assert node._h30_yaw_rad is None
        assert node.get_publishers_info_by_topic("/imu/chassis") == [], (
            "the node still publishes a chassis IMU topic"
        )
        assert node.client.imu_raw is None, "the node still queried IMU_RAW"
        assert node.client.state is State.READY

    assert server.error is None, "fake chassis failed: %r" % (server.error,)
    assert server.stop_frames >= 1


def test_h30_is_only_yaw_source_and_holds_when_stale():
    """The H30 owns odom heading; expiry holds instead of using chassis yaw."""
    with _node_session(extra_params=("h30_timeout_s:=0.25",)) as (
        server,
        node,
        odom_msgs,
        h30_msgs,
        _cmd_pub,
    ):
        h30_pub = node.create_publisher(Imu, "/imu/data", 10)

        def publish_h30(yaw_deg, gyro_z=0.2):
            h30_pub.publish(_h30_msg(yaw_deg, gyro_z))

        def odom_yaw_rad():
            orientation = odom_msgs[-1].pose.pose.orientation
            return 2.0 * math.atan2(orientation.z, orientation.w)

        # Chassis telemetry claims 42 deg / 5 deg/s from the first frame.
        server.telemetry_yaw_cdeg = 4200
        server.telemetry_gyro_cdps = 500
        assert _wait_for(lambda: len(odom_msgs) >= 5, 5.0), "no /odom messages"
        assert abs(odom_yaw_rad()) < 1e-6, "chassis yaw leaked into odom"
        assert odom_msgs[-1].twist.twist.angular.z == 0.0
        assert node._yaw_source_used == "hold"

        # The first H30 sample only defines the odom offset: 10 deg absolute
        # maps to the current 0 deg odom heading.
        publish_h30(10.0)
        assert _wait_for(lambda: node._yaw_source_used == "h30", 5.0), (
            "H30 never became the yaw source (used=%s)" % node._yaw_source_used
        )
        assert h30_msgs, "the injected /imu/data stream never looped back"
        assert node._h30_yaw_offset_rad == pytest.approx(math.radians(-10.0), abs=0.02)
        assert abs(odom_yaw_rad()) < 0.01

        # +40 deg of H30 rotation is +40 deg of odom rotation.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            publish_h30(50.0)
            time.sleep(0.01)
        assert _wait_for(
            lambda: abs(odom_yaw_rad() - math.radians(40.0)) < 0.02, 2.0
        ), "odom did not follow the H30 rotation"
        assert odom_msgs[-1].twist.twist.angular.z == pytest.approx(0.2, abs=0.02)

        # Let the H30 stream expire and move the chassis yaw far away.  Odom
        # must hold the last H30 heading rather than jumping to chassis yaw.
        server.telemetry_yaw_cdeg = -12000
        time.sleep(0.4)
        assert _wait_for(lambda: node._yaw_source_used == "hold", 2.0)
        assert odom_yaw_rad() == pytest.approx(math.radians(40.0), abs=0.02)
        assert odom_msgs[-1].twist.twist.angular.z == 0.0
        assert node.client.imu_raw is None
        assert node.client.state is State.READY

    assert server.error is None, "fake chassis failed: %r" % (server.error,)
    assert server.stop_frames >= 1
