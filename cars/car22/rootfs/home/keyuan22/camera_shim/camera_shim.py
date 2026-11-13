#!/usr/bin/env python3
"""Grayscale camera source for the pharmacy stack.

The Astra S on this chassis exposes no UVC video node, so the recognition
pipeline has nothing on /camera/rgb/image_raw.  This node publishes a mono8
640x480 stream on that topic so the competition stack starts and the pipeline
can be exercised end to end.

Set the `image_path` parameter to feed a real capture, otherwise it renders a
moving test pattern.  It is a stand-in, not a camera: detections derived from
it are meaningless.
"""

import os

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, Image


class CameraShim(Node):
    def __init__(self) -> None:
        super().__init__("camera_shim")
        self.declare_parameter("width", 640)
        self.declare_parameter("height", 480)
        self.declare_parameter("fps", 15.0)
        self.declare_parameter("frame_id", "camera_rgb_frame")
        self.declare_parameter("image_path", "")
        self.declare_parameter("topic", "/camera/rgb/image_raw")

        self.w = int(self.get_parameter("width").value)
        self.h = int(self.get_parameter("height").value)
        fps = float(self.get_parameter("fps").value)
        self.frame_id = str(self.get_parameter("frame_id").value)
        topic = str(self.get_parameter("topic").value)

        self.static = None
        path = str(self.get_parameter("image_path").value)
        if path and os.path.exists(path):
            self.static = self._load_gray(path)
            self.get_logger().info(f"publishing static image {path}")
        else:
            self.get_logger().warning("no image_path; publishing a synthetic test pattern")

        self.pub = self.create_publisher(Image, topic, 10)
        self.info_pub = self.create_publisher(CameraInfo, "/camera/rgb/camera_info", 10)
        self.info = CameraInfo()
        self.info.width = self.w
        self.info.height = self.h
        self.info.distortion_model = "plumb_bob"
        self.info.k = [float(self.w), 0.0, self.w / 2.0,
                       0.0, float(self.w), self.h / 2.0,
                       0.0, 0.0, 1.0]
        self.info.p = [float(self.w), 0.0, self.w / 2.0, 0.0,
                       0.0, float(self.w), self.h / 2.0, 0.0,
                       0.0, 0.0, 1.0, 0.0]
        self.tick = 0
        self.create_timer(1.0 / fps, self._tick)

    def _load_gray(self, path):
        try:
            from PIL import Image as PILImage
        except ImportError:
            self.get_logger().error("Pillow not installed; cannot load image_path")
            return None
        img = PILImage.open(path).convert("L").resize((self.w, self.h))
        return img.tobytes()

    def _pattern(self) -> bytes:
        # Vertical gradient with a bright moving bar: enough structure for the
        # pipeline to exercise decode paths without pretending to be a scene.
        self.tick = (self.tick + 3) % self.w
        row = bytes(int(255 * x / self.w) for x in range(self.w))
        bar = self.tick
        rows = []
        for y in range(self.h):
            line = bytearray(row)
            for dx in range(8):
                x = (bar + dx) % self.w
                line[x] = 255
            rows.append(bytes(line))
        return b"".join(rows)

    def _tick(self) -> None:
        msg = Image()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.frame_id
        msg.height = self.h
        msg.width = self.w
        msg.encoding = "mono8"
        msg.is_bigendian = 0
        msg.step = self.w
        msg.data = self.static if self.static is not None else self._pattern()
        self.pub.publish(msg)
        self.info.header = msg.header
        self.info_pub.publish(self.info)


def main() -> None:
    rclpy.init()
    node = CameraShim()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()