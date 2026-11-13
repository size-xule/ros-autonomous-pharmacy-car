import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import EqualsSubstitution, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    package_share = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_params = os.path.join(package_share, "config", "pharmacy.yaml")
    # Car 1 keeps the bundle under /home/EPRobot; car 2 runs as keyuan22 and
    # sets PHARMACY_OCR_DIR in its unit drop-in.
    ocr_dir = os.environ.get("PHARMACY_OCR_DIR", "/home/EPRobot/board2_ocr")
    default_camera_params = os.path.join(package_share, "config", "camera.yaml")

    params_file = LaunchConfiguration("params_file")
    camera_params_file = LaunchConfiguration("camera_params_file")
    image_topic = LaunchConfiguration("image_topic")
    start_camera = LaunchConfiguration("start_camera")
    start_judge = LaunchConfiguration("start_judge")
    board2_backend = LaunchConfiguration("board2_backend")
    ocr_python = LaunchConfiguration("ocr_python")
    ocr_worker = LaunchConfiguration("ocr_worker")
    audio_dir = LaunchConfiguration("audio_dir")

    fixed_board = IfCondition(EqualsSubstitution(board2_backend, "fixed"))
    ocr_board = IfCondition(EqualsSubstitution(board2_backend, "rapidocr"))

    providers = [
        Node(
            package="pharmacy_pkg",
            executable="pharmacy_qr_node",
            name="detect_qrcode",
            parameters=[params_file, {"image_topic": image_topic}],
            output="screen",
            emulate_tty=True,
        ),
        Node(
            package="pharmacy_pkg",
            executable="pharmacy_board2_fast_node",
            name="pharmacy_board2",
            parameters=[params_file, {"image_topic": image_topic}],
            condition=fixed_board,
            output="screen",
            emulate_tty=True,
        ),
        Node(
            package="pharmacy_pkg",
            executable="pharmacy_board2_node",
            name="pharmacy_board2_ocr",
            parameters=[
                params_file,
                {
                    "image_topic": image_topic,
                    "python": ocr_python,
                    "worker": ocr_worker,
                },
            ],
            condition=ocr_board,
            output="screen",
            emulate_tty=True,
        ),
        Node(
            package="pharmacy_pkg",
            executable="pharmacy_speech_node",
            name="pharmacy_speech",
            parameters=[params_file, {"audio_dir": audio_dir}],
            output="screen",
            emulate_tty=True,
        ),
    ]

    judge = Node(
        package="pharmacy_pkg",
        executable="judge_tcp_node",
        name="judge_tcp",
        parameters=[params_file, {"car_id": ParameterValue(
            LaunchConfiguration("judge_car_id"), value_type=str)}],
        condition=IfCondition(start_judge),
        output="screen",
        emulate_tty=True,
    )

    camera = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(package_share, "launch", "camera.launch.py")
        ),
        launch_arguments={
            "video_device": LaunchConfiguration("video_device"),
            "pixel_format": LaunchConfiguration("pixel_format"),
            "camera_frame": LaunchConfiguration("camera_frame"),
            "params_file": camera_params_file,
            "camera_info_url": LaunchConfiguration("camera_info_url"),
            "use_camera_tf": LaunchConfiguration("use_camera_tf"),
            "camera_x": LaunchConfiguration("camera_x"),
            "camera_y": LaunchConfiguration("camera_y"),
            "camera_z": LaunchConfiguration("camera_z"),
            "camera_roll": LaunchConfiguration("camera_roll"),
            "camera_pitch": LaunchConfiguration("camera_pitch"),
            "camera_yaw": LaunchConfiguration("camera_yaw"),
        }.items(),
        condition=IfCondition(start_camera),
    )

    return LaunchDescription([
        DeclareLaunchArgument("params_file", default_value=default_params,
                              description="Provider parameter file"),
        DeclareLaunchArgument("camera_params_file", default_value=default_camera_params,
                              description="v4l2_camera parameter file"),
        DeclareLaunchArgument("image_topic", default_value="/camera/rgb/image_raw",
                              description="Image topic shared by QR and board-2 nodes"),
        DeclareLaunchArgument("start_camera", default_value="true",
                              description="Also start the UVC camera driver"),
        DeclareLaunchArgument("start_judge", default_value="true",
                              description="Start referee TCP telemetry"),
        DeclareLaunchArgument("judge_car_id", default_value="25",
                              description="Referee car id (24 or 25)"),
        DeclareLaunchArgument("video_device", default_value="/dev/video0"),
        DeclareLaunchArgument("pixel_format", default_value="YUYV"),
        DeclareLaunchArgument("camera_frame", default_value="camera_rgb_frame"),
        DeclareLaunchArgument("camera_info_url", default_value="",
                              description="Optional camera_info YAML URL"),
        DeclareLaunchArgument("use_camera_tf", default_value="true",
                              description="Publish base_link -> camera_frame static TF"),
        DeclareLaunchArgument("camera_x", default_value="0.14"),
        DeclareLaunchArgument("camera_y", default_value="0.0"),
        DeclareLaunchArgument("camera_z", default_value="0.11"),
        DeclareLaunchArgument("camera_roll", default_value="0.0"),
        DeclareLaunchArgument("camera_pitch", default_value="0.0"),
        DeclareLaunchArgument("camera_yaw", default_value="0.0"),
        DeclareLaunchArgument("board2_backend", default_value="rapidocr",
                              description="rapidocr (default) or fixed template fallback"),
        DeclareLaunchArgument(
            "ocr_python", default_value=os.path.join(ocr_dir, "run_worker.sh")),
        DeclareLaunchArgument(
            "ocr_worker", default_value=os.path.join(ocr_dir, "board2_ocr_worker.py")),
        DeclareLaunchArgument(
            "audio_dir",
            default_value=os.path.join(package_share, "audio", "competition")),
        *providers,
        judge,
        camera,
    ])
