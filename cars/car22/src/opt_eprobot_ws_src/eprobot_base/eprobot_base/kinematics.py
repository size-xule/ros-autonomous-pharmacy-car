"""Kinematics and odometry helpers for the ISCC_CAR chassis.

Coordinate convention is REP-103: x forward, y left, z up, yaw positive
counter-clockwise.  The chassis wire protocol uses the same yaw sign, but its
steering angle is positive to the **right** (PROTOCOL.md 6.3), hence the minus
sign in :func:`cmd_vel_to_setpoint`.

The firmware reports speed using its compiled wheel diameter (0.065 m), which
matches the measured wheels on the car.  The host-side ``base_kv`` is 1.0
(PROTOCOL.md 6.4).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .imu_trust import telemetry_imu_trusted
from .protocol import STEER_MAX_MRAD, VX_MAX_MM_S

#: Firmware constants (bm_config.h).  Kept here so the host does not guess.
WHEEL_DIAMETER_M = 0.065  # BM_WHEEL_DIAM_M in the deployed firmware
PHYSICAL_WHEEL_DIAMETER_M = 0.065  # measured tyre diameter on the car
WHEEL_BASE_M = 0.155  # left/right track, BM_WHEEL_BASE_M
AXLE_M = 0.160  # front/rear axle, BM_AXLE_M
DEFAULT_BASE_KV = 1.0
DEFAULT_MAX_VX_MPS = 1.0  # host-side limit until the chassis is re-calibrated
FIRMWARE_MAX_VX_MPS = 1.5


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def wrap_deg(angle_deg: float) -> float:
    """Wrap to [-180, 180)."""
    return (angle_deg + 180.0) % 360.0 - 180.0


def wrap_rad(angle_rad: float) -> float:
    return (angle_rad + math.pi) % (2.0 * math.pi) - math.pi


def nearest_equivalent(angle_rad: float, reference_rad: float) -> float:
    """Return the representation of ``angle_rad`` closest to ``reference_rad``."""
    return reference_rad + wrap_rad(angle_rad - reference_rad)


def extrapolate_yaw(
    yaw_deg: float,
    gyro_dps: float,
    age_ms: int,
    imu_ok: bool = True,
    cal_failed: bool = False,
    dlpf_delay_ms: float = 3.0,
) -> float:
    """Compensate the IMU pipeline delay (PROTOCOL.md 6.2).

    ``yaw_now = yaw + gyro_z * (age + 3.0 ms)``.  No extrapolation is allowed
    when the snapshot is invalid (``age == 255``), the IMU is not OK, or the
    gyro bias calibration failed.
    """
    if not telemetry_imu_trusted(imu_ok, cal_failed, age_ms):
        return wrap_deg(yaw_deg)
    return wrap_deg(yaw_deg + gyro_dps * (age_ms + dlpf_delay_ms) / 1000.0)


@dataclass(frozen=True)
class Setpoint:
    """Result of converting a ROS ``Twist`` into chassis wire values."""

    vx_mm_s: int  # wire speed to send in SET_VELOCITY
    delta_mrad: int
    vx_mps: float  # effective true speed after quantisation
    omega_rad_s: float
    limited: bool = False
    turning_in_place: bool = False
    reason: str = ""

    @property
    def delta_rad(self) -> float:
        return self.delta_mrad / 1000.0

    @property
    def is_zero(self) -> bool:
        return self.vx_mm_s == 0 and self.delta_mrad == 0


def cmd_vel_to_setpoint(
    vx_mps: float,
    omega_rad_s: float,
    *,
    wheelbase_m: float = AXLE_M,
    max_vx_mps: float = DEFAULT_MAX_VX_MPS,
    steer_max_mrad: int = STEER_MAX_MRAD,
    min_turn_speed_mps: float = 0.0,
    min_vx_mps: float = 0.0,
    speed_scale: float = 1.0,
) -> Setpoint:
    """Convert ``(vx, omega)`` to the chassis' ``(vx mm/s, steering mrad)``.

    ``delta = -atan(omega * L / vx)`` because positive steering is to the
    right while positive yaw is counter-clockwise.  An Ackermann chassis
    cannot rotate in place: if ``vx`` is zero and ``omega`` is not, the request
    is rejected unless ``min_turn_speed_mps > 0`` (then a slow forward arc is
    used).  Steering is clamped to +/-524 mrad and the returned
    ``omega_rad_s`` reflects the clamped, quantised steering angle.

    ``min_vx_mps`` raises a non-zero commanded speed to the smallest useful
    chassis speed.  It deliberately does not turn a zero command into motion;
    ``min_turn_speed_mps`` remains the separate opt-in for a pure rotation.

    ``speed_scale`` is true speed / wire speed (the same ``base_kv`` used for
    telemetry).  A value below 1.0 raises the wire command so the physical
    wheel speed matches the requested true m/s; steering geometry still uses
    the true speed.
    """
    if not math.isfinite(vx_mps) or not math.isfinite(omega_rad_s):
        return Setpoint(0, 0, 0.0, 0.0, limited=True, reason="non-finite command")
    if not math.isfinite(speed_scale) or speed_scale <= 0.0:
        return Setpoint(0, 0, 0.0, 0.0, limited=True, reason="invalid speed scale")

    max_vx = max(0.0, min(float(max_vx_mps), FIRMWARE_MAX_VX_MPS))
    min_vx = min(max(0.0, float(min_vx_mps)), max_vx)
    steer_limit = max(0, min(int(steer_max_mrad), STEER_MAX_MRAD))
    limited = False
    reason = ""

    vx = float(vx_mps)
    if abs(vx) > max_vx:
        vx = math.copysign(max_vx, vx)
        limited = True
        reason = "vx clamped to %.3f m/s" % max_vx

    if abs(vx) < 1e-4:
        if abs(omega_rad_s) < 1e-4:
            return Setpoint(0, 0, 0.0, 0.0)
        if min_turn_speed_mps <= 0.0:
            return Setpoint(
                0,
                0,
                0.0,
                0.0,
                limited=True,
                turning_in_place=True,
                reason="Ackermann chassis cannot rotate in place",
            )
        vx = min(float(min_turn_speed_mps), max_vx)
        if vx <= 0.0:
            return Setpoint(
                0,
                0,
                0.0,
                0.0,
                limited=True,
                turning_in_place=True,
                reason="min_turn_speed is zero",
            )
        limited = True
        reason = "vx raised to min_turn_speed %.3f m/s" % vx

    if min_vx > 0.0 and 0.0 < abs(vx) < min_vx:
        vx = math.copysign(min_vx, vx)
        limited = True
        reason = "vx raised to min_vx %.3f m/s" % min_vx

    delta_rad = -math.atan(omega_rad_s * wheelbase_m / vx)
    delta_mrad_float = delta_rad * 1000.0
    delta_mrad = int(round(delta_mrad_float))
    if abs(delta_mrad) > steer_limit:
        delta_mrad = steer_limit if delta_mrad > 0 else -steer_limit
        limited = True
        reason = "steering clamped to %d mrad" % steer_limit

    wire_vx_mm_s = int(round(vx / speed_scale * 1000.0))
    vx_mm_s = wire_vx_mm_s
    vx_mm_s = int(clamp(vx_mm_s, -VX_MAX_MM_S, VX_MAX_MM_S))
    if vx_mm_s != wire_vx_mm_s:
        limited = True
        reason = "wire vx clamped to %d mm/s" % vx_mm_s

    # Recompute omega from the true speed represented by the quantised wire value.
    true_vx = (vx_mm_s / 1000.0) * speed_scale
    quantised_delta = delta_mrad / 1000.0
    effective_omega = -math.tan(quantised_delta) * true_vx / wheelbase_m

    return Setpoint(
        vx_mm_s=vx_mm_s,
        delta_mrad=delta_mrad,
        vx_mps=true_vx,
        omega_rad_s=effective_omega,
        limited=limited,
        reason=reason,
    )


def wheel_speeds(vx_mps: float, omega_rad_s: float, track_m: float = WHEEL_BASE_M):
    """Differential wheel speeds for diagnostics (not sent on the wire)."""
    return (
        vx_mps - omega_rad_s * track_m / 2.0,
        vx_mps + omega_rad_s * track_m / 2.0,
    )


def ackermann_radius(vx_mps: float, delta_mrad: int, wheelbase_m: float = AXLE_M) -> float:
    """Signed turning radius; ``inf`` for straight travel."""
    delta = delta_mrad / 1000.0
    if abs(delta) < 1e-9 or abs(vx_mps) < 1e-9:
        return math.inf
    return wheelbase_m / math.tan(abs(delta))


def quaternion_from_yaw(yaw_rad: float):
    """(x, y, z, w) for a pure yaw rotation."""
    half = yaw_rad / 2.0
    return (0.0, 0.0, math.sin(half), math.cos(half))


def quaternion_to_yaw(q) -> float:
    """Yaw from (x, y, z, w), normalised internally."""
    x, y, z, w = q
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm < 1e-12:
        return 0.0
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


class OdomIntegrator:
    """Planar odometry driven by chassis speed and IMU yaw.

    The chassis reports only a signed scalar speed (no per-wheel speeds in
    TELEMETRY), so translation is integrated along the IMU heading.  Yaw is
    taken directly from the H30 (unwrapped); there is no EKF and no fallback
    to chassis gyro integration.  ``update_gyro`` is kept as a standalone
    utility but the node does not call it.
    """

    def __init__(self, x: float = 0.0, y: float = 0.0, yaw_rad: float = 0.0) -> None:
        self.x = float(x)
        self.y = float(y)
        self.yaw = float(yaw_rad)
        self.last_update: Optional[float] = None

    def reset(self, x: float = 0.0, y: float = 0.0, yaw_rad: float = 0.0) -> None:
        self.x = float(x)
        self.y = float(y)
        self.yaw = float(yaw_rad)
        self.last_update = None

    def update(self, vx_mps: float, yaw_deg: Optional[float], dt: float) -> None:
        if dt <= 0.0 or not math.isfinite(dt):
            return
        if yaw_deg is not None:
            new_yaw = nearest_equivalent(math.radians(yaw_deg), self.yaw)
        else:
            new_yaw = self.yaw
        mid_yaw = (self.yaw + new_yaw) / 2.0
        self.x += vx_mps * math.cos(mid_yaw) * dt
        self.y += vx_mps * math.sin(mid_yaw) * dt
        self.yaw = new_yaw

    def update_gyro(self, vx_mps: float, gyro_dps: float, dt: float) -> None:
        """Fallback when only the gyro is trusted: integrate yaw rate."""
        if dt <= 0.0 or not math.isfinite(dt):
            return
        mid_yaw = self.yaw + math.radians(gyro_dps) * dt / 2.0
        self.x += vx_mps * math.cos(mid_yaw) * dt
        self.y += vx_mps * math.sin(mid_yaw) * dt
        self.yaw = wrap_rad(self.yaw + math.radians(gyro_dps) * dt)
