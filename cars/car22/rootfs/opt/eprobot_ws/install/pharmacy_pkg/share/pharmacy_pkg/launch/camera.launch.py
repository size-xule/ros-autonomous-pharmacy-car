import os
import subprocess

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.conditions import IfCondition
from launch.logging import get_logger
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def _set_frame_rate(context, *_args, **_kwargs):
    """Fix the V4L2 rate before the camera node opens the device.

    v4l2_camera has no fps parameter and leaves whatever rate the device
    already has, so this has to run while /dev/video0 is still free.  A failed
    call is not fatal (for example when the camera is already streaming).
    """
    device = context.perform_substitution(LaunchConfiguration("video_device"))
    frame_rate = context.perform_substitution(LaunchConfiguration("frame_rate"))
    command = ["/usr/bin/v4l2-ctl", "--device", device,
               "--set-parm={}".format(frame_rate)]
    logger = get_logger("camera.launch")
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as error:
        logger.warning("could not set {} to {} fps: {}".format(device, frame_rate, error))
        return []
    detail = (result.stderr or result.stdout).strip()
    if result.returncode == 0:
        logger.info("{}: {} fps".format(device, frame_rate))
    else:
        logger.warning("could not set {} to {} fps: {}".format(device, frame_rate, detail))
    return []


def generate_launch_description():
    package_share = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_params = os.path.join(package_share, "config", "camera.yaml")

    video_device = LaunchConfiguration("video_device")
    frame_rate = LaunchConfiguration("frame_rate")
    pixel_format = LaunchConfiguration("pixel_format")
    camera_frame = LaunchConfiguration("camera_frame")
    params_file = LaunchConfiguration("params_file")
    camera_info_url = LaunchConfiguration("camera_info_url")
    use_camera_tf = LaunchConfiguration("use_camera_tf")
    camera_x = LaunchConfiguration("camera_x")
    camera_y = LaunchConfiguration("camera_y")
    camera_z = LaunchConfiguration("camera_z")
    camera_roll = LaunchConfiguration("camera_roll")
    camera_pitch = LaunchConfiguration("camera_pitch")
    camera_yaw = LaunchConfiguration("camera_yaw")

    return LaunchDescription([
        DeclareLaunchArgument("video_device", default_value="/dev/video0",
                              description="UVC camera device"),
        DeclareLaunchArgument("pixel_format", default_value="YUYV",
                              description="V4L2 pixel format (YUYV or MJPG)"),
        DeclareLaunchArgument("frame_rate", default_value="15",
                              description="V4L2 frame rate applied before the node starts"),
        DeclareLaunchArgument("camera_frame", default_value="camera_rgb_frame",
                              description="Image frame id; match the v4l2_camera frame_id"),
        DeclareLaunchArgument("params_file", default_value=default_params,
                              description="v4l2_camera parameter file"),
        DeclareLaunchArgument("camera_info_url", default_value="",
                              description="Optional camera_info YAML URL"),
        DeclareLaunchArgument("use_camera_tf", default_value="true",
                              description="Publish base_link -> camera_frame static TF"),
        DeclareLaunchArgument("camera_x", default_value="0.14",
                              description="Camera x position from base_link"),
        DeclareLaunchArgument("camera_y", default_value="0.0",
                              description="Camera y position from base_link"),
        DeclareLaunchArgument("camera_z", default_value="0.11",
                              description="Camera z position from base_link"),
        DeclareLaunchArgument("camera_roll", default_value="0.0",
                              description="Camera roll in radians"),
        DeclareLaunchArgument("camera_pitch", default_value="0.0",
                              description="Camera pitch in radians"),
        DeclareLaunchArgument("camera_yaw", default_value="0.0",
                              description="Camera yaw in radians"),

        OpaqueFunction(function=_set_frame_rate),
        Node(
            package="v4l2_camera",
            executable="v4l2_camera_node",
            name="camera",
            parameters=[
                params_file,
                {
                    "video_device": ParameterValue(video_device, value_type=str),
                    "pixel_format": ParameterValue(pixel_format, value_type=str),
                    "camera_frame_id": ParameterValue(camera_frame, value_type=str),
                    "camera_info_url": ParameterValue(camera_info_url, value_type=str),
                },
            ],
            remappings=[
                ("image_raw", "/camera/rgb/image_raw"),
                ("camera_info", "/camera/rgb/camera_info"),
            ],
            output="screen",
            emulate_tty=True,
        ),
        Node(
            package="tf2_ros",
            executable="static_transform_publisher",
            name="base_to_camera_tf",
            arguments=[
                "--x", camera_x,
                "--y", camera_y,
                "--z", camera_z,
                "--roll", camera_roll,
                "--pitch", camera_pitch,
                "--yaw", camera_yaw,
                "--frame-id", "base_link",
                "--child-frame-id", camera_frame,
            ],
            condition=IfCondition(use_camera_tf),
            output="screen",
        ),
    ])
