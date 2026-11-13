"""Single source of truth for whether chassis IMU data may be used.

The STM32 marks a telemetry sample untrusted when ``IMU_OK`` is clear,
``CAL_FAILED`` is set, or ``age`` is saturated.  The ROS publisher mirrors that
state into REP-145: every ``sensor_msgs/Imu`` covariance block whose first
element is negative is unavailable.

Downstream code must not fuse zeroed fields from an untrusted sample.  Use
:func:`telemetry_imu_trusted` for TELEMETRY flags and
:func:`imu_message_usable` for a whole ``sensor_msgs/Imu`` message.  A consumer
that uses only one field may test :func:`covariance_available` on that field's
covariance instead.
"""

from __future__ import annotations

import math
from typing import Any, Optional, Sequence

#: TELEMETRY ``age`` saturation value: no usable snapshot.
IMU_AGE_INVALID = 255


def telemetry_imu_trusted(imu_ok: bool, cal_failed: bool, age_ms: int) -> bool:
    """Return whether TELEMETRY yaw/gyro may be used (PROTOCOL.md §6.2)."""
    try:
        age = int(age_ms)
    except (TypeError, ValueError):
        return False
    return bool(imu_ok) and not bool(cal_failed) and age != IMU_AGE_INVALID


def covariance_available(covariance: Optional[Sequence[float]]) -> bool:
    """REP-145: a negative or non-finite first element means unavailable."""
    if covariance is None:
        return False
    try:
        if len(covariance) < 1:
            return False
        first = float(covariance[0])
    except (TypeError, ValueError, IndexError):
        return False
    return math.isfinite(first) and first >= 0.0


def imu_message_usable(msg: Any) -> bool:
    """Return whether a whole ``sensor_msgs/Imu`` may be fused.

    The chassis publishes all three blocks as unavailable together, so a
    consumer that treats the message as one measurement must require all three
    to be available.  This is deliberately conservative: a partially available
    message is not a trustworthy source for a full-state IMU update.
    """
    if msg is None:
        return False
    return all(
        covariance_available(getattr(msg, field, None))
        for field in (
            "orientation_covariance",
            "angular_velocity_covariance",
            "linear_acceleration_covariance",
        )
    )
