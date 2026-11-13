"""ROS 2 node for the EPRobot chassis (wire protocol v2.1).

This is the only ROS-aware module in the package.  Everything that touches the
wire format or the safety state machine lives in
:mod:`eprobot_base.protocol`, :mod:`eprobot_base.client`,
:mod:`eprobot_base.transport` and :mod:`eprobot_base.kinematics`, which stay
importable without ROS so they can be unit-tested anywhere.

Topics
------
``/cmd_vel`` (geometry_msgs/Twist)
    Ackermann setpoint.  ``angular.z`` is converted with
    ``delta = -atan(omega * L / vx)`` (PROTOCOL.md 6.3); turning in place is
    stopped (a zero-linear command cancels the previous setpoint) because the
    chassis cannot rotate on the spot.
``/laser_mode`` (std_msgs/UInt8)
    0 = off, 1 = eco, 2 = max (PROTOCOL.md 3.4).  Anything else is rejected.
``/chassis/stop`` (std_msgs/Empty)
    Immediate STOP: the only command that clears faults and re-arms the board.
``/odom``, ``/battery_state``, ``/diagnostics``
    Published state.  ``/odom`` is integrated from TELEMETRY speed and the
    WHEELTEC H30 on ``/imu/data``.  The chassis IMU is not queried, fused or
    republished.

Services
--------
``~/stop`` (std_srvs/Trigger)
    Same as ``/chassis/stop``, but synchronous so a caller can observe the
    resulting client state.
"""

from __future__ import annotations

import math
import signal
import threading
import time
from typing import List, Optional

import rclpy
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from geometry_msgs.msg import TransformStamped, Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from sensor_msgs.msg import BatteryState, Imu
from std_msgs.msg import Empty, UInt8
from std_srvs.srv import Trigger
from tf2_ros import TransformBroadcaster

from .client import ChassisClient, ClientConfig, State
from .imu_trust import covariance_available
from .kinematics import (
    OdomIntegrator,
    cmd_vel_to_setpoint,
    nearest_equivalent,
    quaternion_from_yaw,
    quaternion_to_yaw,
    wrap_rad,
)
from .protocol import status_name
from .scheduling import next_deadline_if_due
from .transport import (
    LoopbackTransport,
    SerialTransport,
    SocketTransport,
    TransportError,
)

try:  # pragma: no cover - depends on the rclpy version
    from rclpy.executors import ExternalShutdownException
except ImportError:  # very old rclpy: spin() returns instead of raising

    class ExternalShutdownException(Exception):
        """Fallback for rclpy versions without the real exception."""


#: Control / poll timer.
#:
#: Every timer tick costs rclpy a full wait-set rebuild (about 1.2 ms of
#: bookkeeping on the Pi 4 regardless of what the callback does), so the tick
#: rate is the single biggest lever on this node's CPU.  The chassis is polled
#: at 115200 baud where 100 Hz telemetry is only ~2.5 kB/s, so a 50 Hz tick
#: still drains every frame -- it just reads two of them per poll.  Everything
#: this node produces is 50 Hz (/odom, /tf) or slower (/cmd_vel 30 Hz), so the
#: old 100 Hz tick only bought 50 wasted wake-ups per second.
CONTROL_PERIOD_S = 0.02
#: A deadline may fire half a control tick early.  Without this, a rate whose
#: deadline falls between control ticks can miss by microseconds, skip a whole
#: tick and settle at roughly 80% of the requested rate.
DEADLINE_TOLERANCE_S = CONTROL_PERIOD_S * 0.5
#: How often a failed transport open is retried (PROTOCOL.md 6.1).
RECONNECT_INTERVAL_S = 2.0

#: 3S Li-ion pack used by the chassis: 3 x 3.5 V .. 3 x 4.2 V.
BATTERY_MIN_V = 10.5
BATTERY_MAX_V = 12.6
#: Warn below this pack voltage (about 3.67 V/cell).
BATTERY_LOW_MV = 11000
#: /battery_state publication period.
BATTERY_PERIOD_S = 1.0

ODOM_POSE_COVARIANCE = (0.02, 0.02, 1e6, 1e6, 1e6, 0.05)
ODOM_TWIST_COVARIANCE = (0.02, 1e6, 1e6, 1e6, 1e6, 0.05)


def _diagonal_covariance(diagonal) -> List[float]:
    covariance = [0.0] * 36
    for index, value in enumerate(diagonal):
        covariance[index * 7] = float(value)
    return covariance


# Both covariances are constant, so build the 36-element arrays once instead of
# re-converting 72 floats on every /odom publish.
ODOM_POSE_COVARIANCE_FULL = _diagonal_covariance(ODOM_POSE_COVARIANCE)
ODOM_TWIST_COVARIANCE_FULL = _diagonal_covariance(ODOM_TWIST_COVARIANCE)


class EprobotBaseNode(Node):
    """Chassis driver: owns a :class:`ChassisClient` and the ROS interfaces."""

    def __init__(self) -> None:
        super().__init__("eprobot_base")

        self._shutdown_lock = threading.Lock()
        self._shutdown_done = False

        self._declare_parameters()
        self._read_parameters()

        self._client_config = ClientConfig(
            cmd_period=1.0 / self.cmd_rate_hz,
            cmd_timeout=self.cmd_timeout,
            telemetry_stale_timeout=self.telemetry_timeout,
            link_timeout=self.link_timeout,
            max_vx_mm_s=int(round(self.max_vx * 1000.0)),
            max_steer_mrad=self.max_steer_mrad,
            # ClientConfig gains are in wire units of 0.1.
            kp=int(round(self.kp * 10.0)),
            ki=int(round(self.ki * 10.0)),
            kd=int(round(self.kd * 10.0)),
            auto_clear_faults=self.auto_clear_faults,
            laser_mode=self.laser_mode,
        )

        # Monotonic time of the last valid uplink frame, maintained from the
        # client's public callbacks (used for the diagnostics link age).
        self._last_rx_mono = 0.0

        transport = self._make_transport()
        self.client = ChassisClient(
            transport,
            self._client_config,
            on_telemetry=self._on_telemetry,
            on_diag=self._on_diag_frame,
            on_status=self._on_status_frame,
            on_state=self._on_client_state,
            on_error=self._on_client_error,
        )

        # Odometry state, fed by TELEMETRY inside _on_telemetry().
        self._odom = OdomIntegrator()
        self._last_telemetry_rx = None  # type: Optional[float]
        self._last_vx_true = 0.0
        self._last_gyro_rad_s = 0.0

        # H30 is the only IMU/yaw source.  It reports absolute magnetic yaw; the first
        # sample after startup is used to make /odom start at its current
        # heading (normally zero) without rotating the map frame.
        self._last_h30_rx = 0.0
        self._h30_yaw_rad = None  # type: Optional[float]
        self._h30_yaw_offset_rad = 0.0
        self._h30_gyro_z_rad_s = 0.0
        self._h30_last_accept = 0.0
        self._h30_messages = 0
        self._yaw_source_used = "hold"

        # /cmd_vel watchdog (the client has its own, kept in sync).
        self._setpoint_active = False
        self._last_cmd_time = 0.0

        # Rate schedulers (monotonic seconds).
        self._next_odom = 0.0
        self._next_diag = 0.0
        self._next_battery = 0.0
        self._next_open_attempt = 0.0

        self._odom_period = 1.0 / self.odom_rate_hz
        self._diag_period = (
            1.0 / self.diagnostics_rate_hz if self.diagnostics_rate_hz > 0.0 else float("inf")
        )
        self._desired_laser = self.laser_mode if self.laser_mode in (0, 1, 2) else 0

        self._create_interfaces()

        # Best effort: the context may already be shutting down.
        try:
            self.context.on_shutdown(self.shutdown)
        except Exception as exc:  # pragma: no cover - defensive
            self.get_logger().warning("could not register on_shutdown callback: %s" % exc)

        self._control_timer = self.create_timer(CONTROL_PERIOD_S, self._control_loop)

        # Startup: try once without blocking; the control loop retries every 2 s.
        self._next_open_attempt = time.monotonic()
        self._try_open()

    # ------------------------------------------------------------------
    # parameters
    # ------------------------------------------------------------------
    def _declare_parameters(self) -> None:
        self.declare_parameter("transport", "serial")
        self.declare_parameter("port", "/dev/EPRobot_base")
        self.declare_parameter("baudrate", 115200)
        self.declare_parameter("socket_host", "127.0.0.1")
        self.declare_parameter("socket_port", 15461)
        self.declare_parameter("base_kv", 1.0)
        # Effective value: physical 0.160 m plus the measured steering-link
        # scale error.  Keep BM_AXLE_M/physical geometry at 0.160 m.
        self.declare_parameter("axle_length", 0.171)
        self.declare_parameter("track_width", 0.155)
        self.declare_parameter("max_vx", 1.0)
        self.declare_parameter("max_steer_mrad", 524)
        self.declare_parameter("min_turn_speed", 0.0)
        self.declare_parameter("min_vx", 0.05)
        self.declare_parameter("cmd_rate_hz", 30.0)
        self.declare_parameter("cmd_timeout", 0.5)
        self.declare_parameter("telemetry_timeout", 0.2)
        self.declare_parameter("link_timeout", 0.4)
        self.declare_parameter("kp", 35.0)
        self.declare_parameter("ki", 50.0)
        self.declare_parameter("kd", 0.0)
        self.declare_parameter("publish_tf", True)
        self.declare_parameter("odom_frame", "odom")
        self.declare_parameter("base_frame", "base_link")
        self.declare_parameter("h30_topic", "/imu/data")
        self.declare_parameter("h30_timeout_s", 0.3)
        self.declare_parameter("h30_rate_hz", 100.0)
        self.declare_parameter("odom_rate_hz", 100.0)
        self.declare_parameter("diagnostics_rate_hz", 1.0)
        self.declare_parameter("auto_clear_faults", True)
        self.declare_parameter("laser_mode", 0)

    def _read_parameters(self) -> None:
        self.transport_kind = str(self.get_parameter("transport").value)
        self.serial_port = str(self.get_parameter("port").value)
        self.baudrate = int(self.get_parameter("baudrate").value)
        self.socket_host = str(self.get_parameter("socket_host").value)
        self.socket_port = int(self.get_parameter("socket_port").value)
        self.base_kv = float(self.get_parameter("base_kv").value)
        self.axle_length = float(self.get_parameter("axle_length").value)
        # TELEMETRY only carries the mean wheel speed; track_width is kept for
        # differential diagnostics / future per-wheel speed reporting.
        self.track_width = float(self.get_parameter("track_width").value)
        self.max_vx = float(self.get_parameter("max_vx").value)
        self.max_steer_mrad = int(self.get_parameter("max_steer_mrad").value)
        self.min_turn_speed = float(self.get_parameter("min_turn_speed").value)
        self.min_vx = max(0.0, float(self.get_parameter("min_vx").value))
        self.cmd_rate_hz = self._positive(
            "cmd_rate_hz", float(self.get_parameter("cmd_rate_hz").value), 30.0
        )
        self.cmd_timeout = float(self.get_parameter("cmd_timeout").value)
        self.telemetry_timeout = float(self.get_parameter("telemetry_timeout").value)
        self.link_timeout = float(self.get_parameter("link_timeout").value)
        self.kp = float(self.get_parameter("kp").value)
        self.ki = float(self.get_parameter("ki").value)
        self.kd = float(self.get_parameter("kd").value)
        self.publish_tf = bool(self.get_parameter("publish_tf").value)
        self.odom_frame = str(self.get_parameter("odom_frame").value)
        self.base_frame = str(self.get_parameter("base_frame").value)
        self.h30_topic = str(self.get_parameter("h30_topic").value)
        self.h30_timeout_s = self._positive(
            "h30_timeout_s", float(self.get_parameter("h30_timeout_s").value), 0.3
        )
        # The H30 driver publishes at 400 Hz.  Only this many samples per
        # second are parsed; the rest are dropped before any quaternion work.
        self.h30_rate_hz = self._positive(
            "h30_rate_hz", float(self.get_parameter("h30_rate_hz").value), 100.0
        )
        self._h30_min_period_s = 1.0 / self.h30_rate_hz
        self.odom_rate_hz = self._positive(
            "odom_rate_hz", float(self.get_parameter("odom_rate_hz").value), 100.0
        )
        self.diagnostics_rate_hz = max(
            0.0, float(self.get_parameter("diagnostics_rate_hz").value)
        )
        self.auto_clear_faults = bool(self.get_parameter("auto_clear_faults").value)
        self.laser_mode = int(self.get_parameter("laser_mode").value)

        if self.laser_mode not in (0, 1, 2):
            self.get_logger().warning(
                "laser_mode=%d is not 0/1/2 (PROTOCOL.md 3.4); using 0" % self.laser_mode
            )
            self.laser_mode = 0

    def _positive(self, name: str, value: float, fallback: float) -> float:
        if not math.isfinite(value) or value <= 0.0:
            self.get_logger().warning(
                "parameter %s=%r must be > 0; using %.3f" % (name, value, fallback)
            )
            return fallback
        return value

    # ------------------------------------------------------------------
    # setup
    # ------------------------------------------------------------------
    def _make_transport(self):
        if self.transport_kind == "serial":
            return SerialTransport(self.serial_port, self.baudrate)
        if self.transport_kind == "socket":
            return SocketTransport(self.socket_host, self.socket_port)
        if self.transport_kind == "loopback":
            return LoopbackTransport()
        self.get_logger().error(
            "unknown transport %r (expected serial/socket/loopback); "
            "using loopback so the chassis cannot move" % self.transport_kind
        )
        return LoopbackTransport()

    def _create_interfaces(self) -> None:
        # depth 2 instead of 10: a 50 Hz odometry stream that is 200 ms behind
        # is useless anyway, and the smaller history keeps the DDS writer cheap.
        self._odom_pub = self.create_publisher(Odometry, "/odom", 2)
        self._battery_pub = self.create_publisher(BatteryState, "/battery_state", 10)
        self._diag_pub = self.create_publisher(DiagnosticArray, "/diagnostics", 10)

        self.create_subscription(Twist, "/cmd_vel", self._on_cmd_vel, 1)
        self.create_subscription(UInt8, "/laser_mode", self._on_laser_mode, 1)
        self.create_subscription(Empty, "/chassis/stop", self._on_stop_topic, 10)
        # Only the newest heading matters at 400 Hz; depth 1 avoids a stale
        # backlog if the executor is briefly busy.
        self.create_subscription(Imu, self.h30_topic, self._on_h30_imu, 1)

        self.create_service(Trigger, "~/stop", self._on_stop_service)

        self._tf_broadcaster = TransformBroadcaster(self)

        self._create_message_templates()

    # ------------------------------------------------------------------
    # subscriptions
    # ------------------------------------------------------------------
    def _on_cmd_vel(self, msg: Twist) -> None:
        setpoint = cmd_vel_to_setpoint(
            float(msg.linear.x),
            float(msg.angular.z),
            wheelbase_m=self.axle_length,
            max_vx_mps=self.max_vx,
            steer_max_mrad=self.max_steer_mrad,
            min_turn_speed_mps=self.min_turn_speed,
            min_vx_mps=self.min_vx,
            speed_scale=self.base_kv,
        )

        if setpoint.turning_in_place:
            # Ackermann: no way to honour omega without forward motion.  A
            # zero-linear command still means "stop": cancel any previous
            # setpoint immediately instead of letting it run until cmd_timeout.
            self.client.set_setpoint(0, 0)
            self._setpoint_active = False
            self.get_logger().warning(
                "turn-in-place request (vx=0, omega=%.2f rad/s) cannot be "
                "honoured by an Ackermann chassis; stopping" % float(msg.angular.z),
                throttle_duration_sec=2.0,
            )
            return

        if setpoint.limited:
            self.get_logger().debug(
                "cmd_vel limited: %s (vx=%.3f m/s, delta=%d mrad)"
                % (setpoint.reason, setpoint.vx_mps, setpoint.delta_mrad)
            )

        self.client.set_setpoint(setpoint.vx_mm_s, setpoint.delta_mrad)
        self._last_cmd_time = time.monotonic()
        self._setpoint_active = True

    def _on_laser_mode(self, msg: UInt8) -> None:
        mode = int(msg.data)
        if mode not in (0, 1, 2):
            self.get_logger().error(
                "invalid /laser_mode %d: expected 0 (off), 1 (eco) or 2 (max)" % mode,
                throttle_duration_sec=2.0,
            )
            return
        self._desired_laser = mode
        if not self.client.set_laser(mode):
            self.get_logger().info(
                "laser mode %d queued until the chassis is READY" % mode,
                throttle_duration_sec=2.0,
            )

    def _on_stop_topic(self, _msg: Empty) -> None:
        self.get_logger().warning("STOP requested on /chassis/stop")
        self.client.stop(reason="/chassis/stop")
        self._setpoint_active = False

    def _on_stop_service(self, _request: Trigger.Request, response: Trigger.Response):
        self.client.stop(reason="~/stop service")
        self._setpoint_active = False
        state = self.client.state
        response.success = bool(self.client.transport.is_open) and state is not State.ERROR
        response.message = (
            "STOP sent; chassis state=%s, stop_acked=%d, tx_frames=%d"
            % (state.value, self.client.stats.stop_acked, self.client.stats.tx_frames)
        )
        return response

    # ------------------------------------------------------------------
    # client callbacks
    # ------------------------------------------------------------------
    def _on_client_state(self, old: State, new: State, reason: str) -> None:
        if new in (State.ERROR, State.FAULT):
            self.get_logger().error("chassis %s -> %s: %s" % (old.value, new.value, reason))
        else:
            self.get_logger().info("chassis %s -> %s: %s" % (old.value, new.value, reason))
        if new is State.READY:
            # Re-apply the configured laser mode: STOP (and every re-handshake)
            # turns the laser off (PROTOCOL.md 3.3).
            self.client.set_laser(self._desired_laser)

    def _on_client_error(self, message: str) -> None:
        self.get_logger().error("chassis link error: %s" % message, throttle_duration_sec=2.0)

    def _on_diag_frame(self, _diag, frame) -> None:
        self._last_rx_mono = frame.rx_time

    def _on_status_frame(self, _command: int, _seq: int, _status: int) -> None:
        # ACKs carry no frame object; the callback runs inside poll(), so the
        # current monotonic time is the arrival time.
        self._last_rx_mono = time.monotonic()

    def _on_telemetry(self, telemetry, frame) -> None:
        now = frame.rx_time
        self._last_rx_mono = now
        dt = 0.0
        if self._last_telemetry_rx is not None:
            dt = now - self._last_telemetry_rx
        self._last_telemetry_rx = now
        if not math.isfinite(dt) or dt < 0.0:
            dt = 0.0
        dt = min(dt, 0.2)

        vx_true = telemetry.vx_mps * self.base_kv
        h30_fresh = self._h30_fresh(now)
        if h30_fresh:
            # The H30 yaw is absolute; offset it into the odom frame using the
            # first sample's heading so a map saved in odom never rotates.
            target = nearest_equivalent(
                self._h30_yaw_rad + self._h30_yaw_offset_rad, self._odom.yaw
            )
            self._odom.update(vx_true, math.degrees(target), dt)
            self._last_gyro_rad_s = self._h30_gyro_z_rad_s
            self._yaw_source_used = "h30"
        else:
            # No H30 at startup or the stream expired.  Hold the last heading
            # and keep integrating translation along it.  The chassis IMU is
            # deliberately never used as a fallback.
            self._odom.update(vx_true, None, dt)
            self._last_gyro_rad_s = 0.0
            self._yaw_source_used = "hold"

        self._last_vx_true = vx_true

    def _on_h30_imu(self, msg: Imu) -> None:
        """Consume the H30's fused orientation for the odometry heading.

        The yaw is absolute (VRU fused), not integrated here, and /odom runs
        at 50 Hz, so samples above ``h30_rate_hz`` add nothing but CPU.  They
        are dropped before the quaternion is touched.
        """
        now = time.monotonic()
        if now - self._h30_last_accept < self._h30_min_period_s:
            return
        self._h30_last_accept = now
        if not covariance_available(msg.orientation_covariance):
            return
        q = msg.orientation
        norm = math.sqrt(q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w)
        if not math.isfinite(norm) or norm < 1e-6:
            return
        yaw = quaternion_to_yaw((q.x, q.y, q.z, q.w))
        if not math.isfinite(yaw):
            return

        if self._h30_yaw_rad is None:
            self._h30_yaw_offset_rad = wrap_rad(self._odom.yaw - yaw)
            self.get_logger().info(
                "H30 yaw acquired: %.3f deg; odom offset %.3f deg"
                % (math.degrees(yaw), math.degrees(self._h30_yaw_offset_rad))
            )
        self._h30_yaw_rad = yaw
        self._h30_gyro_z_rad_s = float(msg.angular_velocity.z)
        self._last_h30_rx = now
        self._h30_messages += 1

    def _h30_fresh(self, now: float) -> bool:
        return (
            self._h30_yaw_rad is not None
            and (now - self._last_h30_rx) <= self.h30_timeout_s
        )

    # ------------------------------------------------------------------
    # publishers
    # ------------------------------------------------------------------
    def _publish_odom(self) -> None:
        # Both messages are reused: rclpy copies the payload when it publishes,
        # so only the fields that actually change are touched here.  Rebuilding
        # an Odometry (including two 36-element covariance conversions) was the
        # most expensive thing this node did at 50 Hz.
        stamp = self.get_clock().now().to_msg()
        msg = self._odom_msg
        msg.header.stamp = stamp
        msg.pose.pose.position.x = self._odom.x
        msg.pose.pose.position.y = self._odom.y
        qx, qy, qz, qw = quaternion_from_yaw(self._odom.yaw)
        msg.pose.pose.orientation.x = qx
        msg.pose.pose.orientation.y = qy
        msg.pose.pose.orientation.z = qz
        msg.pose.pose.orientation.w = qw
        msg.twist.twist.linear.x = self._last_vx_true
        msg.twist.twist.angular.z = self._last_gyro_rad_s
        self._odom_pub.publish(msg)

        if not self.publish_tf:
            return

        transform = self._tf_msg
        transform.header.stamp = stamp
        transform.transform.translation.x = self._odom.x
        transform.transform.translation.y = self._odom.y
        transform.transform.rotation.x = qx
        transform.transform.rotation.y = qy
        transform.transform.rotation.z = qz
        transform.transform.rotation.w = qw
        self._tf_broadcaster.sendTransform(transform)

    def _create_message_templates(self) -> None:
        """Pre-fill the constant parts of the two 50 Hz messages."""
        odom = Odometry()
        odom.header.frame_id = self.odom_frame
        odom.child_frame_id = self.base_frame
        odom.pose.pose.position.z = 0.0
        odom.twist.twist.linear.y = 0.0
        odom.twist.twist.linear.z = 0.0
        odom.twist.twist.angular.x = 0.0
        odom.twist.twist.angular.y = 0.0
        odom.pose.covariance = list(ODOM_POSE_COVARIANCE_FULL)
        odom.twist.covariance = list(ODOM_TWIST_COVARIANCE_FULL)
        self._odom_msg = odom

        transform = TransformStamped()
        transform.header.frame_id = self.odom_frame
        transform.child_frame_id = self.base_frame
        transform.transform.translation.z = 0.0
        self._tf_msg = transform

    def _publish_battery(self) -> None:
        telemetry = self.client.telemetry
        fresh = telemetry is not None and not self.client.telemetry_stale()

        msg = BatteryState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.base_frame
        msg.present = True
        # sensor_msgs/msg/BatteryState in ROS 2 Lyrical spells the chemistry
        # constant POWER_SUPPLY_TECHNOLOGY_LION (value 2); the old
        # POWER_SUPPLY_TECHNOLOGY_LITHIUM_ION alias does not exist there.
        msg.power_supply_technology = BatteryState.POWER_SUPPLY_TECHNOLOGY_LION
        msg.power_supply_health = BatteryState.POWER_SUPPLY_HEALTH_UNKNOWN

        if telemetry is not None:
            msg.voltage = telemetry.battery_mv / 1000.0
        else:
            msg.voltage = 0.0

        if fresh:
            fraction = (msg.voltage - BATTERY_MIN_V) / (BATTERY_MAX_V - BATTERY_MIN_V)
            msg.percentage = max(0.0, min(1.0, fraction))
            # BatteryState has no STATUS_OK: the pack is supplying the motors.
            msg.power_supply_status = BatteryState.POWER_SUPPLY_STATUS_DISCHARGING
        else:
            msg.percentage = 0.0
            msg.power_supply_status = BatteryState.POWER_SUPPLY_STATUS_UNKNOWN

        msg.temperature = float("nan")
        msg.current = 0.0
        msg.charge = 0.0
        msg.capacity = 0.0
        msg.design_capacity = 0.0
        self._battery_pub.publish(msg)

    def _publish_diagnostics(self) -> None:
        now = time.monotonic()
        telemetry = self.client.telemetry
        link_age = self._link_age(now)
        telemetry_age = self.client.telemetry_age(now)
        state = self.client.state
        link_stale = telemetry is not None and link_age > self.link_timeout
        faulted = telemetry is not None and telemetry.flags.fault
        h30_age = (
            max(0.0, now - self._last_h30_rx)
            if self._last_h30_rx > 0.0
            else float("inf")
        )
        h30_fresh = self._h30_fresh(now)

        if state in (State.ERROR, State.FAULT):
            level = DiagnosticStatus.ERROR
            message = "chassis state %s" % state.value
        elif faulted:
            level = DiagnosticStatus.ERROR
            message = "chassis fault flag set (state %s)" % state.value
        elif link_stale:
            level = DiagnosticStatus.ERROR
            message = "link stale: no valid frame for %.0f ms" % (link_age * 1000.0)
        elif telemetry is None:
            level = DiagnosticStatus.WARN
            message = "waiting for telemetry (state %s)" % state.value
        else:
            warnings = []  # type: List[str]
            if not telemetry.flags.armed:
                warnings.append("disarmed")
            if not h30_fresh:
                warnings.append("H30 yaw stale/absent; holding heading")
            if 0 < telemetry.battery_mv <= BATTERY_LOW_MV:
                warnings.append("battery low (%.2f V)" % (telemetry.battery_mv / 1000.0))
            level = DiagnosticStatus.WARN if warnings else DiagnosticStatus.OK
            message = "; ".join(warnings) if warnings else "ok"

        values = []  # type: List[KeyValue]

        def add(key: str, value: str) -> None:
            item = KeyValue()
            item.key = key
            item.value = value
            values.append(item)

        def number(value, spec: str) -> str:
            return "n/a" if value is None else spec % value

        add("state", state.value)
        add("armed", "true" if (telemetry is not None and telemetry.flags.armed) else "false")
        add("fault", "true" if (telemetry is not None and telemetry.flags.fault) else "false")
        add("yaw_source", "h30")
        add("yaw_source_used", self._yaw_source_used)
        add("h30_fresh", "true" if h30_fresh else "false")
        add(
            "h30_age_ms",
            "inf" if math.isinf(h30_age) else "%.1f" % (h30_age * 1000.0),
        )
        add("h30_messages", "%d" % self._h30_messages)
        add(
            "braking",
            "true" if (telemetry is not None and telemetry.flags.braking) else "false",
        )
        add(
            "stalled",
            "true" if (telemetry is not None and telemetry.flags.stalled) else "false",
        )
        add(
            "laser_on",
            "true" if (telemetry is not None and telemetry.flags.laser_on) else "false",
        )
        add("battery_mv", number(telemetry.battery_mv if telemetry else None, "%d"))
        # True m/s (base_kv applied), matching /odom's twist.linear.x.
        add("vx_mps", number(self._last_vx_true if telemetry else None, "%.4f"))
        add("pwm_left", number(telemetry.pwm_left if telemetry else None, "%d"))
        add("pwm_right", number(telemetry.pwm_right if telemetry else None, "%d"))
        add("steer_us", number(telemetry.steer_us if telemetry else None, "%d"))
        add("age_ms", number(telemetry.age_ms if telemetry else None, "%d"))
        add(
            "telemetry_age",
            "inf" if math.isinf(telemetry_age) else "%.1f ms" % (telemetry_age * 1000.0),
        )
        add(
            "link_age",
            "inf" if math.isinf(link_age) else "%.1f ms" % (link_age * 1000.0),
        )
        add("rx_frames", "%d" % self.client.stats.rx_frames)
        add("tx_frames", "%d" % self.client.stats.tx_frames)
        add("crc_errors", "%d" % self.client.stats.crc_errors)
        add("status_counts", self._status_counts_text())
        add("last_error", self.client.stats.last_error or "none")

        status = DiagnosticStatus()
        status.name = "eprobot_base: chassis"
        status.hardware_id = "eprobot_base"
        status.level = level
        status.message = message
        status.values = values

        msg = DiagnosticArray()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.status = [status]
        self._diag_pub.publish(msg)

    def _status_counts_text(self) -> str:
        counts = self.client.stats.status_counts
        if not counts:
            return "none"
        return ", ".join(
            "%s=%d" % (status_name(status), count)
            for status, count in sorted(counts.items())
        )

    # ------------------------------------------------------------------
    # control loop
    # ------------------------------------------------------------------
    def _control_loop(self) -> None:
        if self._shutdown_done:
            return

        now = time.monotonic()
        if self.client.state is State.CLOSED:
            if now >= self._next_open_attempt:
                self._try_open()
        else:
            try:
                self.client.poll(now)
            except (TransportError, OSError, ValueError) as exc:
                # ValueError covers ProtocolError from a malformed payload.
                self.get_logger().error(
                    "chassis I/O error: %s" % exc, throttle_duration_sec=2.0
                )
            except Exception as exc:  # keep the 100 Hz timer alive
                self.get_logger().error(
                    "unexpected chassis callback error: %s" % exc,
                    throttle_duration_sec=2.0,
                )

        # poll() can spend a few milliseconds draining the UART; schedule the
        # rate-limited outputs from the time work actually finished.
        now = time.monotonic()
        self._expire_setpoint(now)
        self._publish_due(now)

    def _try_open(self) -> bool:
        now = time.monotonic()
        if self.client.state is not State.CLOSED:
            return True
        try:
            self.client.open(now)
        except (TransportError, OSError) as exc:
            self._next_open_attempt = now + RECONNECT_INTERVAL_S
            self.get_logger().error(
                "cannot open %s transport: %s (retrying every %.0f s)"
                % (self.transport_kind, exc, RECONNECT_INTERVAL_S),
                throttle_duration_sec=10.0,
            )
            return False
        self.get_logger().info("opened %s transport" % self.transport_kind)
        return True

    def _expire_setpoint(self, now: float) -> None:
        if not self._setpoint_active:
            return
        if now - self._last_cmd_time <= self.cmd_timeout:
            return
        self.client.clear_setpoint()
        self._setpoint_active = False
        self.get_logger().warning(
            "no /cmd_vel for %.2f s; setpoint cleared" % self.cmd_timeout,
            throttle_duration_sec=5.0,
        )

    def _publish_due(self, now: float) -> None:
        next_deadline = next_deadline_if_due(
            now, self._next_odom, self._odom_period, DEADLINE_TOLERANCE_S
        )
        if next_deadline is not None:
            self._next_odom = next_deadline
            self._publish_odom()

        next_deadline = next_deadline_if_due(
            now, self._next_diag, self._diag_period, DEADLINE_TOLERANCE_S
        )
        if next_deadline is not None:
            self._next_diag = next_deadline
            self._publish_diagnostics()

        next_deadline = next_deadline_if_due(
            now, self._next_battery, BATTERY_PERIOD_S, DEADLINE_TOLERANCE_S
        )
        if next_deadline is not None:
            self._next_battery = next_deadline
            self._publish_battery()

    def _link_age(self, now: float) -> float:
        """Seconds since the last valid uplink frame (any known type)."""
        if not self._last_rx_mono:
            return float("inf")
        return max(0.0, now - self._last_rx_mono)

    # ------------------------------------------------------------------
    # shutdown
    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        """Send STOP and close the link.  Safe to call more than once."""
        with self._shutdown_lock:
            if self._shutdown_done:
                return
            self._shutdown_done = True

        try:
            self.client.stop(reason="shutdown")
        except Exception as exc:  # pragma: no cover - best effort on exit
            self.get_logger().warning("STOP on shutdown failed: %s" % exc)
        try:
            self.client.close()
        except Exception as exc:  # pragma: no cover - best effort on exit
            self.get_logger().warning("closing the chassis link failed: %s" % exc)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = None
    try:
        node = EprobotBaseNode()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        # `ros2 launch` forwards SIGINT to the child, and the terminal may
        # deliver a second one while rclpy is tearing down its guard
        # conditions.  STOP has already been sent by shutdown(); ignore any
        # further SIGINT so destroy_node() cannot die with a traceback.
        try:
            signal.signal(signal.SIGINT, signal.SIG_IGN)
        except (ValueError, OSError):  # not the main thread / unsupported
            pass
        if node is not None:
            try:
                node.shutdown()
            except Exception:
                pass
            try:
                node.destroy_node()
            except (KeyboardInterrupt, ExternalShutdownException):
                pass
        try:
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
