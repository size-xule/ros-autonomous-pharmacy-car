#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Measure speed-loop step response on a jacked-up v2.1 chassis.

The script talks to the UART directly, so ``eprobot-base.service`` must be
stopped and the caller must be able to open ``/dev/EPRobot_base``.  It sends
the tested gains in every SET_VELOCITY frame and records the 0xC0 telemetry.

Example (run as the workspace user on the car):

    PYTHONPATH=/opt/eprobot_ws/src/eprobot_base \
      python3 lifted_pid_sweep.py --candidates 35:50,50:60,70:80

The car must be lifted.  Every run is bounded and the script sends zero and
STOP in ``finally``; it also aborts on FAULT/STALLED, disarm, stale telemetry,
battery cutoff, or a speed above ``--runaway-mm-s``.
"""

from __future__ import division, print_function

import argparse
import json
import math
import signal
import statistics
import sys
import time

from eprobot_base.client import ChassisClient, ClientConfig, State
from eprobot_base.transport import SerialTransport


class Recorder(object):
    def __init__(self):
        self.rows = []
        self.enabled = False

    def __call__(self, telemetry, frame):
        if not self.enabled:
            return
        self.rows.append(
            {
                "t": frame.rx_time,
                "vx_mm_s": telemetry.vx_mm_s,
                "pwm_left": telemetry.pwm_left,
                "pwm_right": telemetry.pwm_right,
                "steer_us": telemetry.steer_us,
                "battery_mv": telemetry.battery_mv,
                "flags": telemetry.flags.names(),
            }
        )


def mean(values):
    return statistics.fmean(values) if values else None


def stdev(values):
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def interpolate_crossing(rows, t0, threshold):
    previous = None
    for row in rows:
        value = row["signed_vx_mm_s"]
        if value >= threshold:
            if previous is None or previous[1] >= threshold:
                return 1000.0 * (row["t"] - t0)
            span = value - previous[1]
            if span <= 0.0:
                return 1000.0 * (row["t"] - t0)
            fraction = (threshold - previous[1]) / span
            return 1000.0 * (
                previous[0] + fraction * (row["t"] - previous[0]) - t0
            )
        previous = (row["t"], value)
    return None


def summarize(rows, t0, target, hold_s, measure_s):
    for row in rows:
        row["signed_vx_mm_s"] = row["vx_mm_s"] if target > 0 else -row["vx_mm_s"]

    magnitude = abs(target)
    active = [row for row in rows if 0.0 <= row["t"] - t0 <= hold_s]
    peak = max(row["signed_vx_mm_s"] for row in active)
    t10 = interpolate_crossing(active, t0, 0.10 * magnitude)
    t50 = interpolate_crossing(active, t0, 0.50 * magnitude)
    t90 = interpolate_crossing(active, t0, 0.90 * magnitude)
    rise_ms = None if t10 is None or t90 is None else t90 - t10

    settle_ms = None
    tolerance = 0.05 * magnitude
    for index, row in enumerate(active):
        if abs(row["signed_vx_mm_s"] - magnitude) > tolerance:
            continue
        remainder = active[index:]
        if all(abs(item["signed_vx_mm_s"] - magnitude) <= tolerance for item in remainder):
            settle_ms = 1000.0 * (row["t"] - t0)
            break

    steady = [
        row
        for row in active
        if row["t"] - t0 >= max(0.0, hold_s - measure_s)
    ]
    steady_values = [row["signed_vx_mm_s"] for row in steady]
    steady_mean = mean(steady_values)
    pwm = [abs(row["pwm_left"]) for row in active] + [
        abs(row["pwm_right"]) for row in active
    ]
    saturation = sum(1 for value in pwm if value >= 700) / len(pwm)
    asymmetry = mean([abs(row["pwm_left"] - row["pwm_right"]) for row in active])
    flags = sorted({flag for row in active for flag in row["flags"]})

    return {
        "samples": len(rows),
        "peak_mm_s": peak,
        "overshoot_pct": max(0.0, 100.0 * (peak - magnitude) / magnitude),
        "t10_ms": t10,
        "t50_ms": t50,
        "t90_ms": t90,
        "rise_10_90_ms": rise_ms,
        "settle_5pct_ms": settle_ms,
        "steady_mean_mm_s": steady_mean,
        "steady_error_pct": (
            None
            if steady_mean is None
            else 100.0 * (magnitude - steady_mean) / magnitude
        ),
        "steady_std_mm_s": stdev(steady_values),
        "pwm_abs_max": max(pwm),
        "pwm_saturation_fraction": saturation,
        "pwm_mean_abs_difference": asymmetry,
        "battery_min_mv": min(row["battery_mv"] for row in active),
        "flags": flags,
        "trace": [
            {
                "t_ms": 1000.0 * (row["t"] - t0),
                "vx_mm_s": row["vx_mm_s"],
                "pwm_left": row["pwm_left"],
                "pwm_right": row["pwm_right"],
            }
            for row in rows
        ],
    }


def stop_summary(rows, t_stop):
    after = [row for row in rows if row["t"] >= t_stop]
    if not after:
        return {"stop_ms": None, "stop_peak_mm_s": None}
    stopped = next((row for row in after if abs(row["vx_mm_s"]) <= 20), None)
    return {
        "stop_ms": None if stopped is None else 1000.0 * (stopped["t"] - t_stop),
        "stop_peak_mm_s": max(abs(row["vx_mm_s"]) for row in after),
    }


def pump(client, seconds, stop_event, target, runaway_mm_s, battery_cutoff_mv):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if stop_event["requested"]:
            raise RuntimeError("interrupted")
        now = time.monotonic()
        client.poll(now)
        telemetry = client.telemetry
        if telemetry is None:
            raise RuntimeError("no telemetry")
        if client.state is not State.READY:
            raise RuntimeError("client state %s" % client.state.value)
        if telemetry.flags.fault:
            raise RuntimeError("telemetry FAULT")
        if telemetry.flags.stalled:
            raise RuntimeError("telemetry STALLED")
        if not telemetry.flags.armed:
            raise RuntimeError("telemetry disarmed")
        if abs(telemetry.vx_mm_s) > runaway_mm_s:
            raise RuntimeError("runaway speed %d mm/s" % telemetry.vx_mm_s)
        if telemetry.battery_mv and telemetry.battery_mv < battery_cutoff_mv:
            raise RuntimeError("battery %d mV below cutoff" % telemetry.battery_mv)
        time.sleep(0.002)


def wait_ready(client, stop_event, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if stop_event["requested"]:
            raise RuntimeError("interrupted")
        client.poll(time.monotonic())
        if client.ready:
            return
        time.sleep(0.002)
    raise RuntimeError("chassis did not reach READY: %s" % list(client.events))


def stop_and_settle(client, stop_event, duration, battery_cutoff_mv):
    client.set_setpoint(0, 0)
    pump(client, duration, stop_event, 0, 900, battery_cutoff_mv)


def run_direction(
    client,
    recorder,
    target,
    hold_s,
    measure_s,
    stop_event,
    runaway_mm_s,
    battery_cutoff_mv,
):
    client.set_setpoint(0, 0)
    pump(client, 0.6, stop_event, 0, runaway_mm_s, battery_cutoff_mv)
    telemetry = client.telemetry
    if abs(telemetry.vx_mm_s) > 10 or max(abs(telemetry.pwm_left), abs(telemetry.pwm_right)) > 10:
        raise RuntimeError(
            "chassis not at rest: vx=%d pwm=%d/%d"
            % (telemetry.vx_mm_s, telemetry.pwm_left, telemetry.pwm_right)
        )

    recorder.rows = []
    recorder.enabled = True
    t0 = time.monotonic()
    client.set_setpoint(target, 0, t0)
    next_refresh = t0
    deadline = t0 + hold_s
    while time.monotonic() < deadline:
        now = time.monotonic()
        if now >= next_refresh:
            client.set_setpoint(target, 0, now)
            next_refresh = now + 0.1
        pump(client, 0.004, stop_event, target, runaway_mm_s, battery_cutoff_mv)

    t_stop = time.monotonic()
    client.set_setpoint(0, 0, t_stop)
    stop_deadline = t_stop + 2.0
    while time.monotonic() < stop_deadline:
        pump(client, 0.004, stop_event, 0, runaway_mm_s, battery_cutoff_mv)
    recorder.enabled = False
    rows = list(recorder.rows)
    result = summarize(rows, t0, target, hold_s, measure_s)
    result["stop"] = stop_summary(rows, t_stop)
    result["command"] = target
    return result


def parse_candidates(text):
    candidates = []
    for item in text.split(","):
        parts = [part.strip() for part in item.split(":")]
        if len(parts) not in (2, 3):
            raise argparse.ArgumentTypeError("candidate must be kp:ki[:kd]")
        values = [float(part) for part in parts]
        while len(values) < 3:
            values.append(0.0)
        candidates.append(tuple(values))
    return candidates


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="/dev/EPRobot_base")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument(
        "--candidates",
        type=parse_candidates,
        default=parse_candidates("35:50,50:60,70:80"),
        help="comma-separated physical kp:ki[:kd] groups",
    )
    parser.add_argument("--target-mm-s", type=int, default=500)
    parser.add_argument("--hold", type=float, default=4.0)
    parser.add_argument("--measure", type=float, default=1.0)
    parser.add_argument(
        "--directions",
        choices=("forward", "reverse", "both"),
        default="both",
    )
    parser.add_argument("--runaway-mm-s", type=int, default=800)
    parser.add_argument("--battery-cutoff-mv", type=int, default=10000)
    parser.add_argument("--out", default="-")
    args = parser.parse_args(argv)

    if args.hold <= args.measure:
        parser.error("--hold must be greater than --measure")

    stop_event = {"requested": False}

    def request_stop(_signum, _frame):
        stop_event["requested"] = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    recorder = Recorder()
    config = ClientConfig(laser_mode=0)
    client = ChassisClient(
        SerialTransport(args.port, args.baud),
        config,
        on_telemetry=recorder,
    )

    report = {
        "port": args.port,
        "target_mm_s": args.target_mm_s,
        "hold_s": args.hold,
        "measure_s": args.measure,
        "directions": args.directions,
        "candidates": [],
        "aborted": None,
        "final": None,
    }

    try:
        client.open()
        client.stop(reason="pid sweep start")
        wait_ready(client, stop_event)
        pump(client, 1.0, stop_event, 0, args.runaway_mm_s, args.battery_cutoff_mv)

        for kp, ki, kd in args.candidates:
            label = "%g/%g/%g" % (kp, ki, kd)
            print("testing %s" % label, file=sys.stderr, flush=True)
            client.config.kp = int(round(kp * 10.0))
            client.config.ki = int(round(ki * 10.0))
            client.config.kd = int(round(kd * 10.0))
            runs = []
            directions = []
            if args.directions in ("forward", "both"):
                directions.append(args.target_mm_s)
            if args.directions in ("reverse", "both"):
                directions.append(-args.target_mm_s)
            for target in directions:
                run = run_direction(
                    client,
                    recorder,
                    target,
                    args.hold,
                    args.measure,
                    stop_event,
                    args.runaway_mm_s,
                    args.battery_cutoff_mv,
                )
                runs.append(run)
                print(
                    "  %+d mm/s rise=%s ms overshoot=%.1f%% steady_err=%.1f%%"
                    % (
                        target,
                        "?" if run["rise_10_90_ms"] is None else "%.0f" % run["rise_10_90_ms"],
                        run["overshoot_pct"],
                        run["steady_error_pct"] if run["steady_error_pct"] is not None else float("nan"),
                    ),
                    file=sys.stderr,
                    flush=True,
                )
                stop_and_settle(client, stop_event, 1.2, args.battery_cutoff_mv)

            fins = [run for run in runs if run["rise_10_90_ms"] is not None]
            report["candidates"].append(
                {
                    "kp": kp,
                    "ki": ki,
                    "kd": kd,
                    "runs": runs,
                    "summary": {
                        "mean_rise_10_90_ms": mean(
                            [run["rise_10_90_ms"] for run in fins]
                        ),
                        "max_overshoot_pct": max(run["overshoot_pct"] for run in runs),
                        "max_abs_steady_error_pct": max(
                            abs(run["steady_error_pct"]) for run in runs
                        ),
                        "max_settle_5pct_ms": max(
                            run["settle_5pct_ms"]
                            for run in runs
                            if run["settle_5pct_ms"] is not None
                        )
                        if any(run["settle_5pct_ms"] is not None for run in runs)
                        else None,
                        "max_pwm_abs": max(run["pwm_abs_max"] for run in runs),
                        "max_stop_ms": max(
                            run["stop"]["stop_ms"]
                            for run in runs
                            if run["stop"]["stop_ms"] is not None
                        )
                        if any(run["stop"]["stop_ms"] is not None for run in runs)
                        else None,
                    },
                }
            )
    except Exception as exc:
        report["aborted"] = "%s: %s" % (type(exc).__name__, exc)
        print("ABORT: %s" % report["aborted"], file=sys.stderr, flush=True)
    finally:
        try:
            stop_event["requested"] = False
            recorder.enabled = True
            client.set_setpoint(0, 0)
            for _ in range(100):
                client.poll(time.monotonic())
                time.sleep(0.002)
            client.stop(reason="pid sweep end")
            stop_deadline = time.monotonic() + 4.0
            while time.monotonic() < stop_deadline and not client.ready:
                client.poll(time.monotonic())
                time.sleep(0.002)
            telemetry = client.telemetry
            report["final"] = {
                "state": client.state.value,
                "armed": bool(telemetry.flags.armed) if telemetry else None,
                "vx_mm_s": telemetry.vx_mm_s if telemetry else None,
                "pwm_left": telemetry.pwm_left if telemetry else None,
                "pwm_right": telemetry.pwm_right if telemetry else None,
                "battery_mv": telemetry.battery_mv if telemetry else None,
            }
        except Exception as exc:
            report["final"] = {"cleanup_error": repr(exc)}
        finally:
            try:
                client.close()
            except Exception:
                pass
        report["events"] = list(client.events)
        report["stats"] = {
            "telemetry_frames": client.stats.telemetry_frames,
            "velocity_sent": client.stats.velocity_sent,
            "stop_acked": client.stats.stop_acked,
            "crc_errors": client.stats.crc_errors,
            "length_errors": client.stats.length_errors,
        }

    text = json.dumps(report, indent=2, sort_keys=False)
    if args.out == "-":
        print(text)
    else:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        print("wrote %s" % args.out, file=sys.stderr)
    return 0 if report["aborted"] is None else 1


if __name__ == "__main__":
    sys.exit(main())
