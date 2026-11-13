#!/usr/bin/env python3

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    default_params_file = os.path.join(
        get_package_share_directory("lslidar_driver"), "params", "m10.yaml"
    )

    params_file = LaunchConfiguration("params_file")
    serial_port = LaunchConfiguration("serial_port")
    frame_id = LaunchConfiguration("frame_id")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "params_file",
                default_value=default_params_file,
                description="M10 driver parameter file",
            ),
            DeclareLaunchArgument(
                "serial_port",
                default_value="/dev/ttyUSB0",
                description="Serial device connected to the M10",
            ),
            DeclareLaunchArgument(
                "frame_id",
                default_value="laser_link",
                description="Frame id used by the published scan",
            ),
            Node(
                package="lslidar_driver",
                executable="lslidar_driver_node",
                name="lslidar_driver_node",
                output="screen",
                parameters=[
                    params_file,
                    {
                        "serial_port_": ParameterValue(serial_port, value_type=str),
                        "frame_id": ParameterValue(frame_id, value_type=str),
                    },
                ],
            ),
        ]
    )
