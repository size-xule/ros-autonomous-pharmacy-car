# ROS 2 mapping / navigation helpers

`slam_mapping.launch.py` starts:

- `base_link -> laser_link` static TF (`0.14, 0, 0.11`)
- `base_link -> imu_link` static TF (`0.08, 0, 0`)
- SLAM Toolbox in online-async mapping mode on `/scan`

It uses `/odom` and `odom -> base_link` from `eprobot_base`.  Cartographer ROS
is not packaged for ROS 2 Lyrical; this is the ROS 2 mapping path that
produces a standard `/map` for RViz2 and Nav2.

SLAM Toolbox and Nav2 AMCL consume `/odom` + `/scan` and do not subscribe to an
IMU; the Cartographer config sets `TRAJECTORY_BUILDER_2D.use_imu_data = false`.
The only IMU consumer is `eprobot_base`, which subscribes to the WHEELTEC H30
on `/imu/data` and folds its yaw into `/odom`.  The chassis IMU is not queried
or published at all (no `/imu/chassis`).

Start/stop on the car:

```bash
sudo systemctl start eprobot-slam.service
ros2 topic hz /map
sudo systemctl stop eprobot-slam.service
```

`minimum_travel_distance` / `minimum_travel_heading` are 0.30 m / 0.30 rad.
**Never set them back to 0.0**: slam_toolbox then accepts a scan on every
`minimum_time_interval` tick (5 Hz) even while the car is parked.  Karto adds a
pose-graph node for each one, so a stationary car grew ~2.7 nodes/s (3500 nodes
in 10 min), pinned one Pi 4 core at 100 %, and the scan/TF `MessageFilter`
queue overflowed every few seconds with `discarding message because the queue
is full`.  With 0.30 m the graph stops growing when parked and puts ~1.5
nodes/s on it at the 0.45 m/s cruise speed.  Lower to 0.10 / 0.05 only for a
short, slow scan; raise further if a long run still saturates the CPU.

The same spacing matters for loop closure.  At 0.20 m / 0.15 rad the start
point accumulated a dense ring of near-identical nodes (40 per in-place turn),
so returning to the start gave the loop detector dozens of equally-plausible
candidates.  With the old loose thresholds (`link_match_minimum_response_fine`
0.1, `loop_match_minimum_response_fine` 0.45) one bad constraint was accepted
and Ceres smeared the error over the whole graph: the map visibly "flew away"
only on runs that closed the loop at the start.  Current values are 0.3 for
the link threshold, 0.50/0.60 for coarse/fine loop matches,
`loop_search_maximum_distance` 2.0 m and `loop_search_space_dimension` 4.0 m.
`/tmp/jumpwatch.py` (see `docs/`) logs `loop_closure_event` plus
`map->odom` correction jumps if the symptom ever returns.

Watch it on the dev host (Docker, `--network host`):

```bash
iscc rviz          # auto-selects RViz2 for Lyrical; loads navigation_ros2.rviz
```

The config shows `/map`, `/scan`, `/odom`, `/imu/data` and TF in `odom`.  Static
TF for `laser_link` / `imu_link` is published by the launch file, so no extra
robot_state_publisher is needed.

Save the map after the run:

```bash
ros2 run nav2_map_server map_saver_cli -f /home/ubuntu/maps/iscc_ros2
```

## Navigation (AMCL + saved map)

```bash
sudo systemctl start eprobot-nav.service     # stops slam via Conflicts=
sudo systemctl stop  eprobot-nav.service
```

Both units `Wants=`/`After=` `eprobot-base.service`, `eprobot-imu.service` and
`lslidar.service`; `iscc pre` and `iscc create` start the H30 unit explicitly
and wait until `/diagnostics` reports `yaw_source_used=h30` before continuing,
so a missing IMU fails loudly instead of leaving `/odom` with a frozen heading.

`nav2_bringup.launch.py` starts only `map_server`, `amcl`,
`planner_server` (SMAC Hybrid-A*, Dubins, min radius 0.36 m),
`controller_server` (Regulated Pure Pursuit), `behavior_server` and
`bt_navigator`, plus the two static TFs.  The default map is
`/home/ubuntu/maps/iscc_ros2.yaml`.

Car-like kinematic choices:

- `enable_stamped_cmd_vel: false` - the chassis subscribes to
  `geometry_msgs/Twist`, Nav2 1.5 defaults to `TwistStamped`; without this the
  base never receives a command.
- no in-place Spin recovery (`config/navigate_to_pose_no_spin.xml`),
  `use_rotate_to_heading: false`, `allow_reversing: false`.
- footprint `[[-0.06,-0.11],[-0.06,0.11],[0.24,0.11],[0.24,-0.11]]`
  (base_link at the rear axle), inflation 0.30 local / 0.35 global.
- cruise speed 0.45 m/s (`desired_linear_vel`).

AMCL starts with the pose recorded when the map was saved
(`set_initial_pose: true`, -1.532 / -2.578 / 0.491 rad).  **If the car is moved
before navigation starts, use RViz "2D Pose Estimate" first** - otherwise it
will localise at the old pose.

Send goals from RViz (`2D Goal Pose`, Navigation 2 panel) or:

```bash
ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose \
  "{pose: {header: {frame_id: map}, pose: {position: {x: -1.0, y: -2.3}, \
   orientation: {w: 1.0}}}}"
```
