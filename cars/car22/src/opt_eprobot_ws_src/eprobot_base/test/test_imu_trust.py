"""Trust rules shared by the chassis node and any IMU consumer."""

from types import SimpleNamespace

import pytest

from eprobot_base import imu_trust


@pytest.mark.parametrize(
    "imu_ok,cal_failed,age_ms,expected",
    [
        (True, False, 0, True),
        (True, False, 254, True),
        (False, False, 0, False),
        (True, True, 0, False),
        (True, False, 255, False),
        (False, True, 255, False),
    ],
)
def test_telemetry_imu_trusted(imu_ok, cal_failed, age_ms, expected):
    assert (
        imu_trust.telemetry_imu_trusted(imu_ok, cal_failed, age_ms) is expected
    )


@pytest.mark.parametrize(
    "covariance,expected",
    [
        ([0.02, 0.0, 0.0, 0.0, 0.02, 0.0, 0.0, 0.0, 0.05], True),
        ([0.0], True),
        ([-1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], False),
        ([], False),
        ([float("nan")], False),
        ([float("inf")], False),
        (None, False),
    ],
)
def test_covariance_available(covariance, expected):
    assert imu_trust.covariance_available(covariance) is expected


def _imu(orientation=0.02, angular=0.01, linear=0.05):
    return SimpleNamespace(
        orientation_covariance=[orientation] + [0.0] * 8,
        angular_velocity_covariance=[angular] + [0.0] * 8,
        linear_acceleration_covariance=[linear] + [0.0] * 8,
    )


def test_imu_message_usable_when_all_covariances_available():
    """A fully trusted message is usable by a whole-state consumer."""
    assert imu_trust.imu_message_usable(_imu()) is True


def test_imu_message_unusable_when_untrusted():
    """The chassis marks every block -1 on IMU_OK=0 / CAL_FAILED / age=255."""
    assert imu_trust.imu_message_usable(_imu(-1.0, -1.0, -1.0)) is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"orientation": -1.0},
        {"angular": -1.0},
        {"linear": -1.0},
    ],
)
def test_imu_message_unusable_when_any_block_is_unavailable(kwargs):
    assert imu_trust.imu_message_usable(_imu(**kwargs)) is False


def test_imu_message_usable_requires_a_message():
    assert imu_trust.imu_message_usable(None) is False
    assert imu_trust.imu_message_usable(SimpleNamespace()) is False
