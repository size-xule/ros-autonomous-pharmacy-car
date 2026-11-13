import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


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
    default_params = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config", "slam_mapping.yaml")
    params_file = LaunchConfiguration("slam_params_file")
    use_sim_time = LaunchConfiguration("use_sim_time")

    slam_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory("slam_toolbox"),
            "launch", "online_async_launch.py")),
        launch_arguments={
            "slam_params_file": params_file,
            "use_sim_time": use_sim_time,
        }.items(),
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            "slam_params_file", default_value=default_params,
            description="SLAM Toolbox parameter file"),
        DeclareLaunchArgument(
            "use_sim_time", default_value="false",
            description="Use simulation clock"),
        _static_tf("base_to_laser_tf", ("0.14", "0.0", "0.11"), "laser_link"),
        _static_tf("base_to_imu_tf", ("0.08", "0.0", "0.0"), "imu_link"),
        slam_launch,
    ])
