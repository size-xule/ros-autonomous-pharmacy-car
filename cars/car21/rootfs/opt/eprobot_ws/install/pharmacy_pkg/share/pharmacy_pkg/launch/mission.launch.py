import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    package_share = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    params_file = LaunchConfiguration("params_file")
    waypoints_file = LaunchConfiguration("waypoints_file")
    match_seconds = LaunchConfiguration("match_seconds")

    # Explicit motion entry point: the mission starts immediately and commands
    # /cmd_vel through Nav2. Keep providers and this launch separate.
    return LaunchDescription([
        DeclareLaunchArgument(
            "params_file",
            default_value=os.path.join(package_share, "config", "pharmacy.yaml"),
            description="Shared pharmacy parameter file"),
        DeclareLaunchArgument(
            "waypoints_file",
            default_value=os.path.join(package_share, "config", "mission_waypoints.yaml"),
            description="Nav2 map-frame waypoints"),
        DeclareLaunchArgument(
            "match_seconds", default_value="1800.0",
            description="Safety time cap in seconds; 0.0 = continuous practice mode "
                        "(round/sample budget ignored)"),

        Node(
            package="pharmacy_pkg",
            executable="f1_mission_node",
            name="nav_pharmacy",
            parameters=[
                params_file,
                waypoints_file,
                {"match_seconds": ParameterValue(match_seconds, value_type=float)},
            ],
            output="screen",
            emulate_tty=True,
        ),
    ])
