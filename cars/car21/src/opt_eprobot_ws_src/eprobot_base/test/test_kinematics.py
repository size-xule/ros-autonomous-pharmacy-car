"""Kinematics / odometry tests for ``eprobot_base.kinematics``.

Sign conventions follow PROTOCOL.md §6.3: yaw positive = counter-clockwise,
steering positive = to the right, hence ``delta = -atan(omega * L / vx)``.
"""

import math

import pytest

from eprobot_base import kinematics as K


# ---------------------------------------------------------------------------
# cmd_vel_to_setpoint
# ---------------------------------------------------------------------------


def test_straight_forward():
    setpoint = K.cmd_vel_to_setpoint(0.5, 0.0)
    assert setpoint.vx_mm_s == 500
    assert setpoint.vx_mps == pytest.approx(0.5)
    assert setpoint.delta_mrad == 0
    assert setpoint.delta_rad == 0.0
    assert setpoint.omega_rad_s == pytest.approx(0.0, abs=1e-12)
    assert setpoint.limited is False
    assert setpoint.turning_in_place is False


def test_base_kv_scales_wire_speed_but_keeps_true_geometry():
    # 0.1 m/s true with 65/68 wheel calibration: the wire needs 105 mm/s,
    # while steering still uses 0.1 m/s.
    setpoint = K.cmd_vel_to_setpoint(0.1, 0.2, speed_scale=0.065 / 0.068)
    assert setpoint.vx_mm_s == 105
    assert setpoint.vx_mps == pytest.approx(0.1, abs=0.001)
    assert setpoint.delta_mrad == pytest.approx(-309, abs=1)


def test_left_turn_steers_left_negative_delta():
    setpoint = K.cmd_vel_to_setpoint(1.0, 0.5)
    expected_mrad = math.atan(0.5 * K.AXLE_M / 1.0) * 1000.0
    assert setpoint.delta_mrad < 0, "left turn (omega>0) must command negative (left) steer"
    assert abs(setpoint.delta_mrad) == pytest.approx(expected_mrad, abs=0.5)
    assert abs(setpoint.delta_mrad) == pytest.approx(79.8, abs=0.3)
    # Effective omega is recomputed from the quantised wire value.
    assert setpoint.omega_rad_s == pytest.approx(0.5, rel=0.01)


def test_right_turn_steers_right_positive_delta():
    setpoint = K.cmd_vel_to_setpoint(1.0, -0.5)
    expected_mrad = math.atan(0.5 * K.AXLE_M / 1.0) * 1000.0
    assert setpoint.delta_mrad > 0, "right turn (omega<0) must command positive (right) steer"
    assert setpoint.delta_mrad == pytest.approx(expected_mrad, abs=0.5)
    assert setpoint.omega_rad_s == pytest.approx(-0.5, rel=0.01)


def test_reverse_uses_vx_sign_in_formula():
    # delta = -atan(omega*L/vx) with vx<0 flips the steering sign, which is
    # exactly what reversing with a positive yaw rate needs.
    setpoint = K.cmd_vel_to_setpoint(-0.5, 0.5)
    expected_mrad = math.atan(0.5 * K.AXLE_M / 0.5) * 1000.0
    assert setpoint.vx_mm_s == -500
    assert setpoint.delta_mrad > 0
    assert setpoint.delta_mrad == pytest.approx(expected_mrad, abs=0.5)


def test_vx_clamped_to_host_limit():
    setpoint = K.cmd_vel_to_setpoint(2.0, 0.0)
    assert setpoint.vx_mm_s == 1000
    assert setpoint.vx_mps == pytest.approx(1.0)
    assert setpoint.limited is True
    assert "clamp" in setpoint.reason

    reverse = K.cmd_vel_to_setpoint(-2.0, 0.0)
    assert reverse.vx_mm_s == -1000
    assert reverse.limited is True


def test_steering_clamped_to_524_mrad():
    left = K.cmd_vel_to_setpoint(0.1, 10.0)
    assert left.delta_mrad == -524
    assert left.limited is True
    assert "steering clamped" in left.reason

    right = K.cmd_vel_to_setpoint(0.1, -10.0)
    assert right.delta_mrad == 524
    assert right.limited is True


def test_in_place_request_is_rejected():
    setpoint = K.cmd_vel_to_setpoint(0.0, 0.5)
    assert setpoint.vx_mm_s == 0
    assert setpoint.delta_mrad == 0
    assert setpoint.is_zero is True
    assert setpoint.turning_in_place is True
    assert setpoint.limited is True
    assert setpoint.omega_rad_s == 0.0


def test_zero_command_is_not_limited():
    setpoint = K.cmd_vel_to_setpoint(0.0, 0.0)
    assert setpoint.is_zero is True
    assert setpoint.limited is False
    assert setpoint.turning_in_place is False


def test_min_turn_speed_turns_in_place_into_an_arc():
    setpoint = K.cmd_vel_to_setpoint(0.0, 0.5, min_turn_speed_mps=0.2)
    assert setpoint.vx_mm_s == 200
    assert setpoint.turning_in_place is False
    assert setpoint.limited is True
    assert setpoint.delta_mrad < 0


def test_min_vx_raises_small_forward_command():
    setpoint = K.cmd_vel_to_setpoint(0.01, 0.0, min_vx_mps=0.05)
    assert setpoint.vx_mm_s == 50
    assert setpoint.vx_mps == pytest.approx(0.05)
    assert setpoint.limited is True
    assert "min_vx" in setpoint.reason


def test_min_vx_preserves_reverse_sign():
    setpoint = K.cmd_vel_to_setpoint(-0.01, 0.0, min_vx_mps=0.05)
    assert setpoint.vx_mm_s == -50
    assert setpoint.vx_mps == pytest.approx(-0.05)
    assert setpoint.limited is True
    assert "min_vx" in setpoint.reason


def test_min_vx_does_not_start_a_zero_command():
    setpoint = K.cmd_vel_to_setpoint(0.0, 0.0, min_vx_mps=0.05)
    assert setpoint.is_zero is True
    assert setpoint.limited is False


def test_min_vx_does_not_change_faster_command():
    setpoint = K.cmd_vel_to_setpoint(0.2, 0.0, min_vx_mps=0.05)
    assert setpoint.vx_mm_s == 200
    assert setpoint.limited is False


def test_min_vx_zero_disables_floor():
    setpoint = K.cmd_vel_to_setpoint(0.01, 0.0, min_vx_mps=0.0)
    assert setpoint.vx_mm_s == 10
    assert setpoint.limited is False


def test_min_vx_combines_with_min_turn_speed():
    setpoint = K.cmd_vel_to_setpoint(
        0.0, 0.5, min_turn_speed_mps=0.02, min_vx_mps=0.05
    )
    assert setpoint.vx_mm_s == 50
    assert setpoint.vx_mps == pytest.approx(0.05)
    assert setpoint.delta_mrad < 0


def test_non_finite_command_is_rejected():
    setpoint = K.cmd_vel_to_setpoint(float("nan"), 0.0)
    assert setpoint.is_zero is True
    assert setpoint.limited is True
    assert "non-finite" in setpoint.reason


# ---------------------------------------------------------------------------
# extrapolate_yaw (PROTOCOL.md §6.2)
# ---------------------------------------------------------------------------


def test_extrapolate_yaw_golden_example():
    # 12.34 deg + 120.00 dps * (5 + 3.0) ms = 13.30 deg
    assert K.extrapolate_yaw(12.34, 120.0, 5) == pytest.approx(13.30, abs=1e-9)


def test_extrapolate_yaw_zero_gyro_is_identity():
    assert K.extrapolate_yaw(12.34, 0.0, 5) == pytest.approx(12.34, abs=1e-9)


def test_extrapolate_yaw_age_255_is_unchanged():
    assert K.extrapolate_yaw(12.34, 120.0, 255) == pytest.approx(12.34, abs=1e-9)


def test_extrapolate_yaw_imu_not_ok_is_unchanged():
    assert K.extrapolate_yaw(12.34, 120.0, 5, imu_ok=False) == pytest.approx(
        12.34, abs=1e-9
    )


def test_extrapolate_yaw_cal_failed_is_unchanged():
    assert K.extrapolate_yaw(12.34, 120.0, 5, cal_failed=True) == pytest.approx(
        12.34, abs=1e-9
    )


def test_extrapolate_yaw_wraps_at_180():
    # 179.9 deg + 125 dps * (5 + 3.0) ms = 179.9 + 1.0 = 180.9 -> -179.1
    assert K.extrapolate_yaw(179.9, 125.0, 5) == pytest.approx(-179.1, abs=1e-9)


# ---------------------------------------------------------------------------
# quaternions
# ---------------------------------------------------------------------------


def test_quaternion_from_yaw_90_degrees():
    x, y, z, w = K.quaternion_from_yaw(math.pi / 2.0)
    assert x == 0.0
    assert y == 0.0
    assert z == pytest.approx(math.sqrt(0.5), abs=1e-12)
    assert w == pytest.approx(math.sqrt(0.5), abs=1e-12)
    assert z == pytest.approx(0.7071067811865476, abs=1e-12)
    assert w == pytest.approx(0.7071067811865476, abs=1e-12)


@pytest.mark.parametrize(
    "yaw", [-3.0, -math.pi / 2.0, -0.5, 0.0, 0.3, math.pi / 2.0, 3.0]
)
def test_quaternion_yaw_round_trip(yaw):
    quaternion = K.quaternion_from_yaw(yaw)
    assert math.sqrt(sum(c * c for c in quaternion)) == pytest.approx(1.0)
    assert K.quaternion_to_yaw(quaternion) == pytest.approx(yaw, abs=1e-12)


def test_quaternion_to_yaw_handles_zero_quaternion():
    assert K.quaternion_to_yaw((0.0, 0.0, 0.0, 0.0)) == 0.0


def test_quaternion_to_yaw_normalises_input():
    scale = 2.0
    quaternion = tuple(c * scale for c in K.quaternion_from_yaw(0.7))
    assert K.quaternion_to_yaw(quaternion) == pytest.approx(0.7, abs=1e-12)


# ---------------------------------------------------------------------------
# angle helpers
# ---------------------------------------------------------------------------


def test_wrap_deg():
    assert K.wrap_deg(0.0) == pytest.approx(0.0)
    assert K.wrap_deg(180.0) == pytest.approx(-180.0)
    assert K.wrap_deg(-180.0) == pytest.approx(-180.0)
    assert K.wrap_deg(181.0) == pytest.approx(-179.0)
    assert K.wrap_deg(540.0) == pytest.approx(-180.0)


def test_nearest_equivalent_keeps_yaw_continuous():
    reference = math.radians(179.0)
    assert K.nearest_equivalent(math.radians(-179.0), reference) == pytest.approx(
        math.radians(181.0)
    )


# ---------------------------------------------------------------------------
# OdomIntegrator
# ---------------------------------------------------------------------------


def test_odom_one_second_straight():
    odom = K.OdomIntegrator()
    odom.update(0.5, 0.0, 1.0)
    assert odom.x == pytest.approx(0.5)
    assert odom.y == pytest.approx(0.0, abs=1e-12)
    assert odom.yaw == pytest.approx(0.0, abs=1e-12)


def test_odom_heading_90_degrees_moves_left():
    odom = K.OdomIntegrator()
    odom.update(0.0, 90.0, 1.0)          # rotate in place, no translation
    odom.update(0.5, 90.0, 1.0)          # drive forward for one second
    assert odom.yaw == pytest.approx(math.pi / 2.0)
    assert odom.y == pytest.approx(0.5)
    assert odom.x == pytest.approx(0.0, abs=1e-12)


def test_odom_yaw_unwraps_across_plus_minus_180():
    odom = K.OdomIntegrator()
    odom.update(0.0, 179.0, 0.1)
    odom.update(0.5, -179.0, 1.0)        # crossed +180, not jumped back to -179
    assert odom.yaw == pytest.approx(math.radians(181.0))
    # Heading is now due west: one second at 0.5 m/s moves x by -0.5.
    assert odom.x == pytest.approx(-0.5, abs=1e-3)
    assert odom.y == pytest.approx(0.0, abs=1e-3)


def test_odom_yaw_unwraps_across_minus_180():
    odom = K.OdomIntegrator()
    odom.update(0.0, -179.0, 0.1)
    odom.update(0.0, 179.0, 0.1)         # crossed -180 -> -181, not +179
    assert odom.yaw == pytest.approx(math.radians(-181.0))


def test_odom_ignores_non_positive_dt():
    odom = K.OdomIntegrator()
    odom.update(0.5, 0.0, 0.0)
    odom.update(0.5, 0.0, -1.0)
    assert odom.x == 0.0
    assert odom.y == 0.0
    assert odom.yaw == 0.0


def test_odom_reset():
    odom = K.OdomIntegrator()
    odom.update(0.5, 0.0, 1.0)
    odom.reset(1.0, 2.0, 0.5)
    assert (odom.x, odom.y, odom.yaw) == (1.0, 2.0, 0.5)
    assert odom.last_update is None


def test_odom_gyro_fallback_integrates_yaw_rate():
    odom = K.OdomIntegrator()
    odom.update_gyro(0.5, 90.0, 1.0)
    assert odom.yaw == pytest.approx(math.pi / 2.0)
    # Midpoint heading is 45 degrees.
    assert odom.x == pytest.approx(0.5 * math.cos(math.pi / 4.0))
    assert odom.y == pytest.approx(0.5 * math.sin(math.pi / 4.0))


def test_wheel_speeds_differential():
    left, right = K.wheel_speeds(0.5, 0.5)
    assert left == pytest.approx(0.5 - 0.5 * K.WHEEL_BASE_M / 2.0)
    assert right == pytest.approx(0.5 + 0.5 * K.WHEEL_BASE_M / 2.0)
