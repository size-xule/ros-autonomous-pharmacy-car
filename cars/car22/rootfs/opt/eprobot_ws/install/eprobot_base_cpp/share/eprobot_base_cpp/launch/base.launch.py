"""Launch the C++ EPRobot chassis driver with its installed parameters."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    default_params_file = PathJoinSubstitution(
        [FindPackageShare("eprobot_base_cpp"), "config", "base.yaml"]
    )
    params_file = LaunchConfiguration("params_file")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "params_file",
                default_value=default_params_file,
                description=(
                    "YAML file with the eprobot_base parameters; defaults to the "
                    "installed config/base.yaml"
                ),
            ),
            Node(
                package="eprobot_base_cpp",
                executable="eprobot_base",
                name="eprobot_base",
                output="screen",
                parameters=[params_file],
            ),
        ]
    )
