"""Tests for the rate-limited output deadline scheduler."""

import pytest

from eprobot_base.scheduling import next_deadline_if_due


def test_50hz_deadlines_are_not_lost_on_a_100hz_grid():
    deadline = 0.0
    fired = []
    for tick in range(101):
        now = tick * 0.01
        next_deadline = next_deadline_if_due(now, deadline, 0.02, 0.005)
        if next_deadline is not None:
            fired.append(now)
            deadline = next_deadline

    assert len(fired) == 51
    assert all(b - a == pytest.approx(0.02) for a, b in zip(fired, fired[1:]))


def test_deadline_fires_when_the_tick_arrives_slightly_early():
    next_deadline = next_deadline_if_due(0.019999, 0.02, 0.02, 0.005)
    assert next_deadline == pytest.approx(0.04)


def test_small_lateness_keeps_the_deadline_phase():
    next_deadline = next_deadline_if_due(0.027, 0.02, 0.02, 0.005)
    assert next_deadline == pytest.approx(0.04)


def test_more_than_one_period_late_rephases_instead_of_bursting():
    next_deadline = next_deadline_if_due(0.061, 0.02, 0.02, 0.005)
    assert next_deadline == pytest.approx(0.081)


def test_disabled_output_never_fires():
    assert next_deadline_if_due(100.0, 0.0, float("inf"), 0.005) is None
    assert next_deadline_if_due(100.0, 0.0, 0.0, 0.005) is None


def test_first_deadline_starts_one_period_after_now():
    next_deadline = next_deadline_if_due(100.0, 0.0, 0.02, 0.005)
    assert next_deadline == pytest.approx(100.02)
