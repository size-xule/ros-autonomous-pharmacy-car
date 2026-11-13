#!/usr/bin/env python3
"""Cap the commanded speed while approaching the active navigation goal.

controller_server forwards nav2_msgs/SpeedLimit to Controller::setSpeedLimit;
MPPI scales vx_max, vx_min and wz_max by the same ratio.  The cap therefore
reaches the chassis before the goal checker accepts the pose, so the firmware
short-brake at `fine_xy_goal_tolerance` starts from a low speed instead of
from cruise speed.

nav_pharmacy publishes `{"event": "navigating", "target": "..."}` on
/pharmacy/mission_status before each NavigateToPose goal; the waypoint table
is read from the mission's own mission_waypoints.yaml.  Distance comes from
/amcl_pose in the map frame.

Limit schedule (absolute, percentage=false):

    d >= slow_radius             -> 0.0 (NO_SPEED_LIMIT, clears the cap)
    stop_radius < d < slow_radius-> linear from slow_speed to cruise_speed
    d <= stop_radius             -> slow_speed

With the defaults the cap is 1.2 m/s at 0.8 m and 0.4 m/s at 0.2 m, i.e. the
car enters the 0.20 m goal window at 0.4 m/s.
"""

import json
import math
import re
import time

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from rcl_interfaces.msg import SetParametersResult
from nav2_msgs.msg import SpeedLimit
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String


# nav2_costmap_2d::NO_SPEED_LIMIT == 0.0; MPPI restores base_constraints.
NO_SPEED_LIMIT = 0.0


def latched_qos() -> QoSProfile:
    return QoSProfile(
        depth=1,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )


def load_waypoints(path: str) -> dict:
    """Read `name: [x, y, yaw]` entries from mission_waypoints.yaml.

    The file is a flat ROS parameter table with comments; a full YAML parser
    would need PyYAML, which is not installed on the car, so match the
    entries directly and ignore everything else.
    """
    points = {}
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            if line.lstrip().startswith("#"):
                continue
            match = re.match(
                r"\s*'?([A-Za-z0-9_]+)'?\s*:\s*\[\s*([^\]]+)\]", line)
            if not match:
                continue
            values = [value.strip() for value in match.group(2).split(",")]
            if len(values) < 2:
                continue
            try:
                points[match.group(1)] = (float(values[0]), float(values[1]))
            except ValueError:
                continue
    return points


class GoalSpeedLimit(Node):
    def __init__(self) -> None:
        super().__init__("goal_speed_limit")
        self.declare_parameter("status_topic", "/pharmacy/mission_status")
        self.declare_parameter("pose_topic", "/amcl_pose")
        self.declare_parameter("speed_limit_topic", "/speed_limit")
        self.declare_parameter(
            "waypoints_file",
            "/opt/eprobot_ws/install/pharmacy_pkg/share/pharmacy_pkg/config/"
            "mission_waypoints.yaml")
        self.declare_parameter("slow_radius", 1.10)
        self.declare_parameter("stop_radius", 0.35)
        self.declare_parameter("slow_speed", 0.20)
        self.declare_parameter("cruise_speed", 1.0)
        # AMCL only publishes /amcl_pose when the robot has moved
        # update_min_d (0.05 m), so a 1 s window expires while the car
        # creeps into a bay and the limiter drops back to NO_SPEED_LIMIT.
        # 5 s keeps the last known pose through a slow approach.
        # AMCL is latched but only publishes on motion (update_min_d 0.05 m),
        # so while the robot waits at a standstill the pose can be minutes
        # old.  A speed cap derived from a stationary pose is still valid,
        # so only treat it as lost after 30 s.
        self.declare_parameter("pose_timeout", 30.0)
        # Cap at the outer edge of the approach zone: the car eases from
        # cruise (1.2) to this value at slow_radius instead of running
        # unconstrained until it is already close.
        self.declare_parameter("entry_speed", 1.0)
        self.declare_parameter("rate_hz", 20.0)
        # Per-waypoint caps (JSON: {"B": 0.20}).  The tight legs (C->B, B->A)
        # get a much lower approach speed than the long straights.
        # Keys are "to" or "from>to"; the same waypoint is approached from
        # different sides (C->B is fine at 0.20, A->B needs to crawl).
        self.declare_parameter(
            # "4" overshoots its bay, so it gets a much slower entry than the
            # global 0.25 m/s default: it approaches at 0.12 m/s and starts
            # crawling 0.55 m out instead of 0.30 m.
            "target_speeds",
            '{"C>B": 0.12, "A>B": 0.12, "B": 0.10, "A": 0.22, "4": 0.12}')
        self.declare_parameter(
            "target_stop_radius",
            '{"A>B": 0.65, "B": 0.65, "A": 0.35, "4": 0.55}')

        status_topic = self.get_parameter("status_topic").value
        pose_topic = self.get_parameter("pose_topic").value
        limit_topic = self.get_parameter("speed_limit_topic").value
        waypoints_file = self.get_parameter("waypoints_file").value
        self._slow_radius = float(self.get_parameter("slow_radius").value)
        self._stop_radius = float(self.get_parameter("stop_radius").value)
        self._slow_speed = float(self.get_parameter("slow_speed").value)
        self._cruise_speed = float(self.get_parameter("cruise_speed").value)
        self._entry_speed = float(self.get_parameter("entry_speed").value)
        self._pose_timeout = float(self.get_parameter("pose_timeout").value)
        rate_hz = max(1.0, float(self.get_parameter("rate_hz").value))
        try:
            self._target_speeds = {
                str(k): float(v) for k, v in
                json.loads(self.get_parameter("target_speeds").value).items()}
        except (TypeError, ValueError):
            self._target_speeds = {}
        try:
            self._target_stop = {
                str(k): float(v) for k, v in
                json.loads(self.get_parameter("target_stop_radius").value).items()}
        except (TypeError, ValueError):
            self._target_stop = {}
        self._active_slow_speed = self._slow_speed
        self._active_stop_radius = self._stop_radius
        self._prev_target = None

        if self._slow_radius <= self._stop_radius:
            self.get_logger().warning(
                "slow_radius <= stop_radius; using the slow speed everywhere")

        self._points = load_waypoints(waypoints_file)
        if not self._points:
            self.get_logger().error(
                f"no waypoints parsed from {waypoints_file}; the cap stays clear")

        self._goal = None
        self._goal_name = None
        self._pose = None
        self._pose_time = None
        self._last_limit = None
        self._last_publish = 0.0

        self._publisher = self.create_publisher(SpeedLimit, limit_topic, 10)
        self.add_on_set_parameters_callback(self._on_set_parameters)
        self.create_subscription(String, status_topic, self._on_status, latched_qos())
        # AMCL publishes /amcl_pose TRANSIENT_LOCAL and only on motion
        # (update_min_d/a = 0.05), so a VOLATILE subscriber sees nothing while
        # the robot is parked -- the limiter then had no pose at the start of a
        # new leg and applied no cap.  Match the latched QoS instead.
        self.create_subscription(
            PoseWithCovarianceStamped, pose_topic, self._on_pose, latched_qos())
        self.create_timer(1.0 / rate_hz, self._tick)
        self.get_logger().info(
            f"goal speed limit: {status_topic} + {pose_topic} -> {limit_topic}; "
            f"{self._cruise_speed:.2f} m/s at {self._slow_radius:.2f} m -> "
            f"{self._slow_speed:.2f} m/s at {self._stop_radius:.2f} m; "
            f"{len(self._points)} waypoints")

    def _on_set_parameters(self, parameters):
        """Allow live tuning without restarting Nav2."""
        update = {
            "slow_radius": self._slow_radius,
            "stop_radius": self._stop_radius,
            "slow_speed": self._slow_speed,
            "cruise_speed": self._cruise_speed,
        }
        for parameter in parameters:
            if parameter.name in update:
                try:
                    update[parameter.name] = float(parameter.value)
                except (TypeError, ValueError):
                    return SetParametersResult(
                        successful=False,
                        reason=f"{parameter.name} must be a number")
        if update["slow_radius"] <= update["stop_radius"]:
            return SetParametersResult(
                successful=False, reason="slow_radius must exceed stop_radius")
        if update["slow_speed"] <= 0.0:
            return SetParametersResult(
                successful=False, reason="slow_speed must be positive")
        if update["cruise_speed"] < update["slow_speed"]:
            return SetParametersResult(
                successful=False, reason="cruise_speed must be >= slow_speed")

        changed = any(abs(update[key] - getattr(self, "_" + key)) > 1e-9
                      for key in update)
        self._slow_radius = update["slow_radius"]
        self._stop_radius = update["stop_radius"]
        self._slow_speed = update["slow_speed"]
        self._cruise_speed = update["cruise_speed"]
        if changed:
            self._last_limit = None
            self.get_logger().info(
                f"goal speed limit updated: {self._cruise_speed:.2f} m/s at "
                f"{self._slow_radius:.2f} m -> {self._slow_speed:.2f} m/s at "
                f"{self._stop_radius:.2f} m")
        return SetParametersResult(successful=True)

    def _on_status(self, message: String) -> None:
        try:
            status = json.loads(message.data)
        except (TypeError, ValueError):
            return
        event = status.get("event")
        if event == "navigating":
            target = status.get("target")
            self._goal_name = target
            self._goal = self._points.get(target)
            if self._goal is None:
                self.get_logger().warning(
                    f"target {target!r} has no waypoint; clearing the cap")
            else:
                self.get_logger().info(
                    f"target {target}: goal ({self._goal[0]:.2f}, {self._goal[1]:.2f})")
                key = (f"{self._prev_target}>{target}"
                       if self._prev_target else str(target))
                self._active_slow_speed = self._target_speeds.get(
                    key, self._target_speeds.get(str(target), self._slow_speed))
                self._active_stop_radius = self._target_stop.get(
                    key, self._target_stop.get(str(target), self._stop_radius))
                self.get_logger().info(
                    f"  approach cap [{key}]: {self._active_slow_speed:.2f} m/s "
                    f"inside {self._active_stop_radius:.2f} m")
                self._prev_target = str(target)
        elif event in ("home_returned", "match_completed", "return_failed",
                       "mission_aborted", "match_timeout",
                       "mission_exception"):
            self._goal = None
            self._goal_name = None

    def _on_pose(self, message: PoseWithCovarianceStamped) -> None:
        position = message.pose.pose.position
        self._pose = (position.x, position.y)
        self._pose_time = time.monotonic()

    def _limit(self, distance: float) -> float:
        if distance >= self._slow_radius:
            return NO_SPEED_LIMIT
        if distance <= self._active_stop_radius:
            return self._active_slow_speed
        span = self._slow_radius - self._active_stop_radius
        ratio = (distance - self._active_stop_radius) / span
        return self._active_slow_speed + ratio * (
            self._entry_speed - self._active_slow_speed)

    def _tick(self) -> None:
        now = time.monotonic()
        if (self._goal is None or self._pose is None or
                now - self._pose_time > self._pose_timeout):
            self._publish(NO_SPEED_LIMIT, now)
            return
        distance = math.hypot(self._goal[0] - self._pose[0],
                              self._goal[1] - self._pose[1])
        self._publish(self._limit(distance), now)

    def _publish(self, limit: float, now: float) -> None:
        # 1 Hz heartbeat in case controller_server restarted or missed a drop.
        if (self._last_limit is not None and
                abs(limit - self._last_limit) < 0.01 and
                now - self._last_publish < 1.0):
            return
        message = SpeedLimit()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = "map"
        message.percentage = False
        message.speed_limit = float(limit)
        self._publisher.publish(message)
        self._last_limit = limit
        self._last_publish = now


def main() -> None:
    rclpy.init()
    node = GoalSpeedLimit()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        try:
            node._publish(NO_SPEED_LIMIT, time.monotonic())
        except Exception:
            pass
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:  # signal handler already shut the context down
            pass


if __name__ == "__main__":
    main()
