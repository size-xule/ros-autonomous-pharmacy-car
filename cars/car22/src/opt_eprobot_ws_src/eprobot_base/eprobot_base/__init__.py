"""ROS 2 driver for the ISCC_CAR EPRobot chassis (wire protocol v2.1).

The package is intentionally split so that the protocol, kinematics, transport
and client modules are plain Python (no ROS import), while
:mod:`eprobot_base.node` is the only ROS-aware module.  Importing this package
therefore works on a machine without ROS installed.

Modules
-------
``protocol``    frame layout, CRC-16/CCITT-FALSE, parsers (PROTOCOL.md 2/4)
``kinematics``  Ackermann conversion, yaw extrapolation, odometry
``scheduling``  jitter-tolerant rate-limited output deadlines
``transport``   serial / TCP / loopback byte transports
``client``      handshake, keepalive, safety state machine (PROTOCOL.md 5/6)
``imu_trust``   single trust rule for TELEMETRY and ``sensor_msgs/Imu``
``node``        rclpy node exposing topics, TF, diagnostics and ``~/stop``
"""

__version__ = "0.1.0"

# ``node`` is deliberately absent: importing it pulls in rclpy, while the
# remaining modules must stay usable without ROS (unit tests, backtest, tools).
__all__ = [
    "protocol",
    "kinematics",
    "scheduling",
    "transport",
    "client",
    "imu_trust",
]
