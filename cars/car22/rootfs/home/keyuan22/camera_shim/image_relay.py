#!/usr/bin/env python3
"""Relay: Orbbec color (rgb8) -> mono8 on /camera/rgb/image_raw.

The pharmacy recognition nodes request mono8 via cv_bridge (see camera.yaml
output_encoding).  openni2_camera publishes rgb8, so convert here instead of
touching the competition code.
"""
import os

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import CameraInfo, Image

SRC = "/camera/color/image_raw"
DST = "/camera/rgb/image_raw"
INFO = "/camera/rgb/camera_info"
ENHANCE = os.environ.get("ISCC_ENHANCE", "1") not in ("0", "false", "off")
SCALE = int(os.environ.get("ISCC_SCALE", "1"))
MAX_FPS = float(os.environ.get("ISCC_MAX_FPS", "15"))


def _clahe(gray: np.ndarray, clip: float = 2.0, tiles: int = 8) -> np.ndarray:
    """Contrast-limited adaptive histogram equalisation (numpy only)."""
    h, w = gray.shape
    ys = np.linspace(0, h, tiles + 1).astype(int)
    xs = np.linspace(0, w, tiles + 1).astype(int)
    lut_cache = {}
    out = gray.copy()
    for i in range(tiles):
        for j in range(tiles):
            block = gray[ys[i]:ys[i + 1], xs[j]:xs[j + 1]]
            if block.size == 0:
                continue
            hist = np.bincount(block.ravel(), minlength=256).astype(np.float64)
            limit = clip * block.size / 256.0
            excess = np.maximum(hist - limit, 0).sum()
            hist = np.minimum(hist, limit) + excess / 256.0
            cdf = np.cumsum(hist)
            cdf /= max(cdf[-1], 1e-9)
            lut = np.clip(cdf * 255.0, 0, 255).astype(np.uint8)
            out[ys[i]:ys[i + 1], xs[j]:xs[j + 1]] = lut[block]
    return out


def _upscale(gray: np.ndarray, factor: int = 2) -> np.ndarray:
    """Bilinear upscale (numpy only) so OCR sees larger glyphs."""
    if factor <= 1:
        return gray
    h, w = gray.shape
    nh, nw = h * factor, w * factor
    ys = (np.arange(nh) + 0.5) / factor - 0.5
    xs = (np.arange(nw) + 0.5) / factor - 0.5
    y0 = np.clip(np.floor(ys).astype(int), 0, h - 1); y1 = np.clip(y0 + 1, 0, h - 1)
    x0 = np.clip(np.floor(xs).astype(int), 0, w - 1); x1 = np.clip(x0 + 1, 0, w - 1)
    wy = np.clip(ys - y0, 0, 1)[:, None]; wx = np.clip(xs - x0, 0, 1)[None, :]
    top = gray[y0][:, x0] * (1 - wx) + gray[y0][:, x1] * wx
    bot = gray[y1][:, x0] * (1 - wx) + gray[y1][:, x1] * wx
    return np.clip(top * (1 - wy) + bot * wy, 0, 255).astype(np.uint8)

def _equalize(gray: np.ndarray, clip_gain: float = 2.5) -> np.ndarray:
    """Global histogram equalisation with a bounded gain (no tile seams)."""
    hist = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    cdf = np.cumsum(hist) / max(gray.size, 1)
    lut = np.clip(cdf * 255.0, 0, 255)
    # Blend between the identity and the equalised LUT so flat scenes do not explode.
    x = np.arange(256, dtype=np.float64)
    gain = np.clip(lut - x, -255 * clip_gain, 255 * clip_gain)
    out = np.clip(x + 0.5 * gain, 0, 255).astype(np.uint8)
    return out[gray]

def _unsharp(gray: np.ndarray, amount: float = 0.6, radius: int = 1) -> np.ndarray:
    k = radius * 2 + 1
    pad = radius
    p = np.pad(gray.astype(np.float32), pad, mode="edge")
    acc = np.zeros_like(gray, dtype=np.float32)
    for dy in range(k):
        for dx in range(k):
            acc += p[dy:dy + gray.shape[0], dx:dx + gray.shape[1]]
    blur = acc / (k * k)
    sharp = gray.astype(np.float32) + amount * (gray.astype(np.float32) - blur)
    return np.clip(sharp, 0, 255).astype(np.uint8)

class Relay(Node):
    def __init__(self):
        super().__init__("image_relay")
        q = QoSProfile(depth=5, history=HistoryPolicy.KEEP_LAST,
                       reliability=ReliabilityPolicy.BEST_EFFORT)
        self.pub = self.create_publisher(Image, DST, q)
        self.info_pub = self.create_publisher(CameraInfo, INFO, q)
        self.create_subscription(Image, SRC, self.cb, q)
        self.info = None
        self.create_subscription(CameraInfo, "/cam/rgb/camera_info", self.cb_info, q)
        self.n = 0
        self._last = 0.0
        self.get_logger().info(f"relay {SRC} -> {DST} (mono8)")

    def cb_info(self, msg):
        self.info = msg

    def cb(self, msg):
        import time as _t
        now = _t.time()
        if MAX_FPS > 0 and (now - self._last) < 1.0 / MAX_FPS:
            return
        self._last = now
        w, h, step = msg.width, msg.height, msg.step
        enc = msg.encoding
        buf = np.frombuffer(bytes(msg.data), dtype=np.uint8)
        if enc in ("rgb8", "bgr8"):
            a = buf.reshape(h, step)[:, : w * 3].reshape(h, w, 3).astype(np.float32)
            if enc == "bgr8":
                a = a[:, :, ::-1]
            gray = (0.299 * a[:, :, 0] + 0.587 * a[:, :, 1] + 0.114 * a[:, :, 2])
            out = np.clip(gray, 0, 255).astype(np.uint8).tobytes()
        elif enc in ("mono8", "8UC1"):
            out = buf[: w * h].tobytes()
        else:
            self.get_logger().warning(f"unsupported source encoding {enc}", throttle_duration_sec=5.0)
            return
        if ENHANCE:
            try:
                g = np.frombuffer(out, np.uint8).reshape(h, w)
                g = _upscale(_unsharp(_equalize(g), amount=0.5), SCALE)
                out = g.tobytes()
                h, w = g.shape
            except Exception as exc:  # never break the stream for cosmetics
                self.get_logger().warning(f"enhance failed: {exc}", throttle_duration_sec=10.0)
        m = Image()
        m.header = msg.header
        m.height, m.width, m.encoding, m.is_bigendian, m.step = h, w, "mono8", 0, w
        m.data = out
        self.pub.publish(m)
        if self.info is not None:
            ci = CameraInfo()
            ci.header = msg.header
            ci.width, ci.height = w, h
            ci.distortion_model = self.info.distortion_model
            ci.d, ci.k, ci.r, ci.p = self.info.d, self.info.k, self.info.r, self.info.p
            self.info_pub.publish(ci)
        self.n += 1
        if self.n % 150 == 0:
            self.get_logger().info(f"relayed {self.n} frames ({w}x{h} {enc}->mono8)")


def main():
    rclpy.init()
    n = Relay()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
    finally:
        n.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()