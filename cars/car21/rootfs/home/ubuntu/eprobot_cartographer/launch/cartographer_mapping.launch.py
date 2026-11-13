import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


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
        ],
        output="screen",
    )


def generate_launch_description():
    default_config_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
    config_dir = LaunchConfiguration("configuration_directory")
    config_basename = LaunchConfiguration("configuration_basename")
    resolution = LaunchConfiguration("resolution")

    return LaunchDescription([
        DeclareLaunchArgument(
            "configuration_directory", default_value=default_config_dir,
            description="Directory holding the Cartographer Lua configuration"),
        DeclareLaunchArgument(
            "configuration_basename", default_value="iscc_2d.lua",
            description="Cartographer Lua file name"),
        DeclareLaunchArgument(
            "resolution", default_value="0.05",
            description="OccupancyGrid resolution in metres"),
        _static_tf("base_to_laser_tf", ("0.14", "0.0", "0.11"), "laser_link"),
        _static_tf("base_to_imu_tf", ("0.08", "0.0", "0.0"), "imu_link"),
        Node(
            package="cartographer_ros",
            executable="cartographer_node",
            name="cartographer_node",
            parameters=[{
                "configuration_directory": ParameterValue(
                    config_dir, value_type=str),
                "configuration_basename": ParameterValue(
                    config_basename, value_type=str),
            }],
            remappings=[("scan", "/scan")],
            output="screen",
        ),
        Node(
            package="cartographer_ros",
            executable="cartographer_occupancy_grid_node",
            name="cartographer_occupancy_grid_node",
            parameters=[{
                "resolution": ParameterValue(resolution, value_type=float),
                "publish_period_sec": 1.0,
            }],
            output="screen",
        ),
    ])
