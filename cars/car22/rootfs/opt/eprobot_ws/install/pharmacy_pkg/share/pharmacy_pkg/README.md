# pharmacy_pkg (ROS 2 C++17)

ROS 2 Lyrical migration of the pharmacy camera, QR/board-2 recognition,
speech, referee telemetry and F1 mission. The public task encoding, waypoint
names, speech assets and referee JSON contract follow the ROS 1
`car_src/pharmacy_pkg` implementation.

This package is deployed on the car at
`/opt/eprobot_ws/install/pharmacy_pkg` (aarch64 build, 2026-10-26). Do not copy
an x86 build to the Raspberry Pi, and do not start `mission.launch.py` in a
shared workspace: it starts the mission immediately and commands the robot
through Nav2.

## Nodes and launch files

| Executable | ROS node | Role |
| --- | --- | --- |
| `pharmacy_qr_node` | `detect_qrcode` | Four-panel QR detection and task decoding |
| `pharmacy_board2_fast_node` | `pharmacy_board2` | Default fixed FREE / BUSY_8 recognizer |
| `pharmacy_board2_node` | `pharmacy_board2_ocr` | Optional RapidOCR worker adapter |
| `pharmacy_speech_node` | `pharmacy_speech` | Pre-generated WAV playback queue |
| `judge_tcp_node` | `judge_tcp` | Referee TCP telemetry at 10 Hz |
| `f1_mission_node` | `nav_pharmacy` | F1 state machine using Nav2 `navigate_to_pose` |
| `board_benchmark` | none | Offline board-2 image benchmark |

| Launch file | What it starts | Moves the car? |
| --- | --- | --- |
| `camera.launch.py` | `v4l2_camera`, `/camera/rgb/image_raw`, optional camera TF | No |
| `competition.launch.py` | Camera by default plus QR, board-2, speech and judge; no mission | No |
| `mission.launch.py` | `nav_pharmacy` only | **Yes, immediately** |

The camera topic remains `/camera/rgb/image_raw` so the detection code keeps the
ROS 1 contract. `competition.launch.py` publishes `/pharmacy/board2_ready` and
`/pharmacy/speech_ready` with transient-local durability, matching ROS 1
latched semantics.

`camera.launch.py` publishes 640x480 `mono8` at 15 fps. `output_encoding` is
mono8 because `pharmacy_qr_node` and the default
`pharmacy_board2_fast_node` both ask `cv_bridge` for mono8, so their conversion
is a zero-copy view and the image topic is 307,200 B/frame instead of
921,600 B. Lyrical `v4l2_camera` has no fps parameter; the launch file runs
`v4l2-ctl --set-parm` before the node opens `/dev/video0`, because the device
rejects a rate change while streaming. The optional `rapidocr` backend still
requests `bgr8` and therefore converts (it is not the default).

## Local build (dev host, never the Pi)

The host has no native ROS 2. Build and test inside Docker using all host cores.
Create a build image once with the extra perception and camera dependencies:

```bash
cd /mnt/data/home/cca/Projects/ISCC_CAR

docker build -t iscc-pharmacy:lyrical - <<'EOF'
FROM eprobot-ros2:lyrical-gui
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ros-lyrical-cv-bridge ros-lyrical-v4l2-camera \
      libzbar-dev libopencv-dev libssl-dev nlohmann-json3-dev && \
    rm -rf /var/lib/apt/lists/*
EOF
```

If the host has no BuildKit/buildx, run the same command with
`DOCKER_BUILDKIT=0 docker build ...`. The image is only needed once per host.

Build only this package into a throwaway prefix. The source mount is read-only;
the build tree stays under `ros2_ws/.pharmacy-build/`.

```bash
mkdir -p ros2_ws/.pharmacy-build

docker run --rm --network host \
  -v "$PWD/ros2_ws/src:/ws/src:ro" \
  -v "$PWD/ros2_ws/.pharmacy-build:/work" \
  iscc-pharmacy:lyrical bash -lc '
    set -e
    source /opt/ros/lyrical/setup.bash
    colcon build \
      --base-paths /ws/src \
      --packages-select pharmacy_pkg \
      --build-base /work/build \
      --install-base /work/install \
      --parallel-workers $(nproc) \
      --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON
  '
```

`lib/libpharmacy_qr.so` is the car's aarch64 ZXing library. On an amd64 build
host it is not linked into the executable; QR runtime falls back to ZBar unless
`PHARMACY_QR_BACKEND=zxing` and a compatible library are supplied explicitly.

## Backtests

Run the C++ unit tests and the board-2 benchmark before any deployment. These
tests do not start the chassis, camera, lidar, Nav2 or the judge.

```bash
docker run --rm --network none \
  -v "$PWD/ros2_ws/src:/ws/src:ro" \
  -v "$PWD/ros2_ws/.pharmacy-build:/work" \
  -v "$PWD/car_src/pharmacy_pkg/test/data/board2_real:/fixtures:ro" \
  iscc-pharmacy:lyrical bash -lc '
    set -e
    source /opt/ros/lyrical/setup.bash
    source /work/install/setup.bash
    colcon test --base-paths /ws/src --packages-select pharmacy_pkg \
      --build-base /work/build --install-base /work/install \
      --event-handlers console_direct+
    colcon test-result --verbose

    /work/install/pharmacy_pkg/lib/pharmacy_pkg/board_benchmark \
      --templates /work/install/pharmacy_pkg/share/pharmacy_pkg/assets/board2 \
      --image /work/install/pharmacy_pkg/share/pharmacy_pkg/assets/board2/pass.png \
      --image /work/install/pharmacy_pkg/share/pharmacy_pkg/assets/board2/wait8s.png \
      --image /fixtures/pass_oblique.png \
      --image /fixtures/wait8s_oblique.png \
      --repeat 20 --threads 1

    /work/install/pharmacy_pkg/lib/pharmacy_pkg/pharmacy_detection_backtest \
      --assets /work/install/pharmacy_pkg/share/pharmacy_pkg/assets/board2 \
      --real /fixtures
  '
```

The two oblique images are the legacy real-camera fixtures under
`car_src/pharmacy_pkg/test/data/board2_real/`. The benchmark proves the
recognizer runs and reports latency; it does not prove real-camera accuracy or
driving performance. `pharmacy_detection_backtest` replays the wire/decision
rules, the classifier and ZBar (`[rules]`, `[classifier]`, `[qr]`); its `[qr]`
section is skipped unless synthetic panels are supplied with `--qr-fixtures`
(generate them with `test/generate_qr_fixtures.sh`, which needs `qrencode`).

QR image smoke test (supply a captured four-panel frame):

```bash
docker run --rm --network none \
  -v "$PWD/ros2_ws/.pharmacy-build:/work:ro" \
  -v "$PWD/testdata:/testdata:ro" \
  iscc-pharmacy:lyrical bash -lc '
    source /opt/ros/lyrical/setup.bash
    source /work/install/setup.bash
    /work/install/pharmacy_pkg/lib/pharmacy_pkg/pharmacy_qr_node \
      --test-image /testdata/qr.png
  '
```

Task selection rule: among the four decoded panels, the node prefers the panel
with the most letters that still fits the remaining sample budget, and skips
panels already completed. AC and BC both ask for two windows, so a tie between
them resolves to **BC** instead of whichever panel happens to come first in the
camera grid; `buildResult` in `src/qr_pipeline.cpp` holds that rule.

Last-lap truncation: `eligibleLetters` in `include/pharmacy_pkg/mission_logic.hpp`
cuts an `ABC` task to `BC` when only two samples of the eight-sample budget
remain, so the third lap skips the A pickup. The pickup announcement speaks
`取到B、C窗口中的…` and `/pharmacy/task` carries `BC`.

## Runtime order

On the car, the chassis driver, H30 IMU, lidar and either SLAM or Nav2 must be
up before the mission is considered. The lidar is powered by the chassis LASER
PWM and is started separately from the ROS 2 stack.

1. Start the camera and providers (no motion):

   ```bash
   source /opt/ros/lyrical/setup.bash
   source /opt/eprobot_ws/install/setup.bash
   ros2 launch pharmacy_pkg competition.launch.py
   ```

   If another launch owns the camera, use
   `start_camera:=false`. For bench work, add `start_judge:=false` to avoid
   reconnecting to the referee server. On the car the referee id comes from
   `judge_car_id` (default `25`); set `judge_car_id:=24` for car 24. It is
   declared as a **string** because the judge node rejects an integer value.

2. Check readiness before enabling anything that can move:

   ```bash
   ros2 topic hz /camera/rgb/image_raw      # 15 Hz after the launch pre-step
   ros2 topic echo --once /pharmacy/board2_ready
   ros2 topic echo --once /pharmacy/speech_ready
   ros2 topic echo --once /pharmacy/board2_status
   ```

   The board-2 node publishes ready after loading its templates, not after the
   first image arrives. Confirm the image topic separately.

3. Start the mission only after localization, Nav2, provider readiness, the
   physical area and the referee setup have been checked:

   ```bash
   ros2 launch pharmacy_pkg mission.launch.py
   ```

   The mission starts immediately, sends `navigate_to_pose` goals in the `map`
   frame, and publishes zero `/cmd_vel` on shutdown. Use Ctrl-C to cancel.

### On the car: `eprobot-pharmacy.service` / `iscc pre`

The deployed stack runs the providers as the systemd unit
`eprobot-pharmacy.service` (`/etc/systemd/system/eprobot-pharmacy.service`),
which executes the same `competition.launch.py` as user `ubuntu`. It is
`After=`/`Wants=` `eprobot-base.service` and `eprobot-imu.service`, joins the
`video` group for `/dev/video0`, and does **not** start `mission.launch.py`.

```bash
sudo systemctl status eprobot-pharmacy
sudo journalctl -u eprobot-pharmacy -f
sudo systemctl restart eprobot-pharmacy
```

The referee id is read from `/etc/default/eprobot-pharmacy`
(`JUDGE_CAR_ID=25`; the `Environment=JUDGE_CAR_ID=25` line in the unit is the
fallback). `ROS_DOMAIN_ID` is fixed at `0`, matching the rest of the car.
The unit is **disabled at boot** (like `eprobot-nav`); `iscc pre` starts it
explicitly, so the camera does not grab `/dev/video0` unless the stack is up.

`iscc pre` drives this unit: it starts base + H30 IMU + lidar, stops SLAM,
restarts Nav2, then writes `JUDGE_CAR_ID=<CAR_ID>` to
`/etc/default/eprobot-pharmacy` and restarts the unit. It waits for
`/camera/rgb/image_raw` to have a publisher and lists the five provider nodes
before following the journal. A failure there is reported as a warning and does
not abort Nav2 bring-up. The unit is also included in `iscc stop`,
`iscc status` and `iscc logs`.

```bash
./scripts/iscc pre                 # ROBOT_IP comes from ~/.config/iscc/iscc.conf
ROBOT_IP=10.7.7.4 ./scripts/iscc pre   # explicit override
```

The camera defaults are `/dev/video0`, 640x480, YUYV. ROS 2 `v4l2_camera`
(Lyrical) has no fps parameter: the device selects the rate for that
size/format (the dev-host UVC camera ran at ~30 Hz), so verify the actual rate
with `ros2 topic hz`. The static camera transform defaults to `base_link ->
camera_rgb_frame` at `(0.14, 0, 0.11)` m with zero rotation. Override
`camera_x/y/z` and `camera_roll/pitch/yaw` after measuring the mount; disable
the transform with `use_camera_tf:=false` when another launch owns it.

## Configuration

- `config/camera.yaml` — `v4l2_camera` device geometry and image frame.
- `config/pharmacy.yaml` — provider, speech, judge and mission parameters.
- `config/mission_waypoints.yaml` — Nav2 map-frame `[x, y, yaw]` waypoints.
- `../../docs/SOFTWARE_PARAMETERS.md` — operator-facing parameter mirror.

The provider node names in `pharmacy.yaml`, the launch files and each C++
`Node(...)` constructor must stay identical. Renaming a node without updating
the YAML silently prevents its parameter overrides from loading.

## Deployment status (2026-10-26)

The aarch64 install prefix was built on the dev host with the prebuilt
`lib/libpharmacy_qr.so` and copied to `/opt/eprobot_ws/install/pharmacy_pkg`.
The car also has `ros-lyrical-v4l2-camera`, `libzbar0t64` and `alsa-utils`
installed.

Verified on the car:

- `pharmacy_detection_backtest --assets ... --real ... --qr-fixtures ...`:
  173 checks, 0 failed, QR end-to-end on the native aarch64 binary.
- `board_benchmark`: FREE / BUSY_8 at ~16 ms/frame, p95 ~19 ms.
- `competition.launch.py start_camera:=false start_judge:=false`:
  `/detect_qrcode`, `/pharmacy_board2` and `/pharmacy_speech` start, and both
  `/pharmacy/board2_ready` and `/pharmacy/speech_ready` are `true`; the QR node
  reports `backend=zxing-cpp-2.2.1`.
- `eprobot-pharmacy.service` with the real Astra Pro HD on `/dev/video0`:
  `/camera/rgb/image_raw` publishes 640x480 `mono8` at 15 Hz with two
  subscribers (QR + board-2) as measured on 2026-10-27 (before the change it was
  `rgb8` at ~30 Hz); `/detect_qrcode`, `/pharmacy_board2`,
  `/pharmacy_speech` and `/judge_tcp` are all up, and a captured frame rendered
  a sane room image (camera path verified; no QR sign in view).
- Speech playback uses direct ALSA (`aplay -q -D plughw:0,0`); the pre-generated
  WAV plays successfully as `ubuntu` and `eprobot-pharmacy.service` runs with
  the `audio` supplementary group.  The unit sets the BCM2835 `PCM` control to
  100 % unmuted at start.  No PulseAudio/PipeWire server is required.
- `v4l2_camera` logs `Unable to open camera calibration file ...` because
  `camera_info_url` is empty; this is non-fatal and only means
  `/camera/rgb/camera_info` carries no intrinsics.

Not yet validated:

- The F1 mission has not completed a full pickup/delivery run on the car.
- QR/board-2 accuracy with physical four-panel QR and board-2 signs in front of
  the camera; only synthetic fixtures have run on the car.
- Referee reachability at `10.211.121.38:8888` and the exact judge protocol; the
  judge node stays up but logs `Judge TCP connect failed` without the referee
  network.
- Nav2 motion, waypoint accuracy, board recognition on the field and sample
  pickup/delivery timing.
