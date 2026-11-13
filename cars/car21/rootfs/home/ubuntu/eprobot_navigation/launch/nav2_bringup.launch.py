import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

LIFECYCLE_NODES = [
    "map_server",
    "amcl",
    "planner_server",
    "controller_server",
    "behavior_server",
    "bt_navigator",
]

LOG_ARGS = ["--ros-args", "--log-level", "warn"]


def _static_tf(node_name, translation, child_frame):
    return Node(
        package="tf2_ros",
        executable="static_transform_publisher",
        name=node_name,
        arguments=[
            "--x", translation[0],
            "--y", translation[1],
            "--z", translation[2],
            "--roll", "0",
            "--pitch", "0",
            "--yaw", "0",
            "--frame-id", "base_link",
            "--child-frame-id", child_frame,
            *LOG_ARGS,
        ],
        output="screen",
    )


def generate_launch_description():
    default_params = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config", "nav2_params.yaml")
    goal_checker_bridge = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "scripts", "goal_checker_bridge.py")
    goal_speed_limit = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "scripts", "goal_speed_limit.py")

    params_file = LaunchConfiguration("params_file")
    map_yaml = LaunchConfiguration("map")
    use_sim_time = LaunchConfiguration("use_sim_time")

    common = [params_file, {"use_sim_time": use_sim_time}]

    return LaunchDescription([
        DeclareLaunchArgument(
            "map", default_value="/home/ubuntu/maps/iscc_3.yaml",
            description="Saved map yaml"),
        DeclareLaunchArgument(
            "params_file", default_value=default_params,
            description="Nav2 parameter file"),
        DeclareLaunchArgument(
            "use_sim_time", default_value="false",
            description="Use simulation clock"),

        _static_tf("base_to_laser_tf", ("0.14", "0.0", "0.11"), "laser_link"),
        _static_tf("base_to_imu_tf", ("0.08", "0.0", "0.0"), "imu_link"),

        Node(
            package="nav2_map_server", executable="map_server", name="map_server",
            parameters=common + [{"yaml_filename": map_yaml}],
            arguments=LOG_ARGS, output="screen"),
        Node(
            package="nav2_amcl", executable="amcl", name="amcl",
            parameters=common, arguments=LOG_ARGS, output="screen"),
        Node(
            package="nav2_planner", executable="planner_server", name="planner_server",
            parameters=common, arguments=LOG_ARGS, output="screen"),
        Node(
            package="nav2_controller", executable="controller_server",
            name="controller_server", parameters=common,
            arguments=LOG_ARGS, output="screen"),
        Node(
            package="nav2_behaviors", executable="behavior_server", name="behavior_server",
            parameters=common, arguments=LOG_ARGS, output="screen"),
        Node(
            package="nav2_bt_navigator", executable="bt_navigator", name="bt_navigator",
            parameters=common, arguments=LOG_ARGS, output="screen"),
        # Picks free_yaw_goal_checker while nav_pharmacy drives to A (the C -> A
        # leg has no reachable final heading on this chassis) and restores the
        # strict checker for every other leg.
        ExecuteProcess(cmd=["python3", goal_checker_bridge, *LOG_ARGS], output="screen"),
        # Caps the commanded speed inside 0.8 m of the active goal (1.2 m/s at
        # 0.8 m, 0.4 m/s at 0.2 m) so the firmware short-brake at goal
        # acceptance starts from a low speed.
        ExecuteProcess(cmd=["python3", goal_speed_limit, *LOG_ARGS], output="screen"),
        Node(
            package="nav2_lifecycle_manager", executable="lifecycle_manager",
            name="lifecycle_manager_navigation",
            parameters=[{
                "use_sim_time": use_sim_time,
                "autostart": True,
                "bond_timeout": 0.0,
                "node_names": LIFECYCLE_NODES,
            }],
            arguments=LOG_ARGS, output="screen"),
    ])
