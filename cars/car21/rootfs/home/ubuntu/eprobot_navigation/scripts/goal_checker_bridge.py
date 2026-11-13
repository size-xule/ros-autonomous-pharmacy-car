#!/usr/bin/env python3
"""Switch the Nav2 goal checker per navigation target.

controller_server loads one goal checker for the whole session, but the
behavior tree already exposes `goal_checker_selector` (see
navigate_to_pose_no_spin.xml).  Republishing that topic rewrites the
`selected_goal_checker` blackboard entry that FollowPath forwards, so the
checker can be chosen per leg without touching the mission binary.

nav_pharmacy publishes `{"event": "navigating", "target": "A"}` on
/pharmacy/mission_status right before it sends each NavigateToPose goal.  While
the target is in `free_yaw_targets` this node selects `free_yaw_goal_checker`
(position only); every other event restores `general_goal_checker`, so the
strict 0.35 rad heading check still applies to the pickup and board legs.

The default list is empty: A must hold the same pi/2 heading as B and C.
The mechanism is kept for a future leg where heading is genuinely
unreachable.  (rclpy cannot infer the type of an empty list default, hence
the empty-string sentinel, which is filtered out below.)

Both topics are transient-local, so a bt_navigator (or this bridge) that
starts late still receives the last value.
"""

import json

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String


def latched_qos() -> QoSProfile:
    return QoSProfile(
        depth=1,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )


class GoalCheckerBridge(Node):
    def __init__(self) -> None:
        super().__init__("goal_checker_bridge")
        self.declare_parameter("status_topic", "/pharmacy/mission_status")
        self.declare_parameter("selector_topic", "goal_checker_selector")
        self.declare_parameter("default_checker", "general_goal_checker")
        self.declare_parameter("free_yaw_checker", "free_yaw_goal_checker")
        self.declare_parameter("free_yaw_targets", [""])

        status_topic = self.get_parameter("status_topic").value
        selector_topic = self.get_parameter("selector_topic").value
        self._default = self.get_parameter("default_checker").value
        self._free = self.get_parameter("free_yaw_checker").value
        self._targets = {target for target in self.get_parameter("free_yaw_targets").value
                         if target}
        self._selected = None

        qos = latched_qos()
        self._publisher = self.create_publisher(String, selector_topic, qos)
        self.create_subscription(String, status_topic, self._on_status, qos)
        self.get_logger().info(
            f"goal checker bridge: {status_topic} -> {selector_topic}, "
            f"free yaw for {sorted(self._targets)}")

    def _select(self, checker: str) -> None:
        if checker == self._selected:
            return
        message = String()
        message.data = checker
        self._publisher.publish(message)
        self._selected = checker
        self.get_logger().info(f"goal checker -> {checker}")

    def _on_status(self, message: String) -> None:
        try:
            status = json.loads(message.data)
        except (TypeError, ValueError):
            self.get_logger().warning("mission status is not JSON; ignoring")
            return
        if status.get("event") == "navigating" and status.get("target") in self._targets:
            self._select(self._free)
        else:
            self._select(self._default)


def main() -> None:
    rclpy.init()
    node = GoalCheckerBridge()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:  # signal handler already shut the context down
            pass


if __name__ == "__main__":
    main()
