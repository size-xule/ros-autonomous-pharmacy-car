#!/usr/bin/env python3
"""Board-2 OCR worker: line recognition with PP-OCR, detector as backstop.

Two paths, both validated by parsing the recognised text:

  1. Fast path: locate a bright sign panel with contours, rank the candidates
     by how much text ink their lower band contains, and run the recogniser
     only.  ~110 ms on a Pi 4.  This assumes the usual two-line sign, so it is
     purely an optimisation.
  2. General path: full-frame PP-OCR detection (no layout assumption) followed
     by recognition.  ~0.5 s at native resolution, with a second pass at
     min-side 736 for small/distant signs.  This is what makes the worker
     usable on a different board, a printed A4 sheet, a monitor, or another
     angle.

Speed/accuracy knobs (measured on the car's Pi 4B, 640x480 mono8 frames):
  * Recognition input width: 192 instead of the default 320.  112 ms vs
    178 ms for the same 9/9 correct readings on a live board, 0/143 errors on
    the augmented sample set.
  * intra_op_num_threads=2: one thread loses ~1.6x; two leave two of the four
    cores for the 1 kHz chassis loop.
  * Detection uses PP-OCRv6 det_tiny (1.8 MB): same 736-upscale accuracy as
    det_small on distant-sign tests, but 1.0 s instead of 2.1 s.  The default
    det_small at limit 736 costs ~2.35 s.
  * The 4.5 MB rec_tiny model is 3x faster again but misread 通过 on 4/9 live
    board frames, so it is not used.  A smaller board/font is even harder.

Protocol (matches pharmacy_pkg/pharmacy_board2_node):
  stdout:  "READY" once after the model is warm,
           then one status line per request: FREE | BUSY_<n> | UNKNOWN
  stdin :  one PNG path per line (QUIT exits)

Standalone use:
  python3 board2_ocr_worker.py --image samples/wait8.png
  python3 board2_ocr_worker.py --dir samples
"""

import argparse
import os
import re
import sys
import time

import cv2
import numpy as np
from rapidocr import RapidOCR

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(HERE, "models")
SMALL_REC = os.path.join(MODEL_DIR, "PP-OCRv6_rec_small.onnx")
TINY_DET = os.path.join(MODEL_DIR, "PP-OCRv6_det_tiny.onnx")
# The line is five characters wide.  320 is the model's default padding width
# and costs 2x more for no accuracy gain here; 192 keeps room for longer text.
REC_WIDTH = 192
FALLBACK_SIDE = 480

DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def parse_status(text: str) -> str:
    """Map recognised text to the mission's FREE / BUSY_<n> status."""
    compact = text.translate(DIGITS).replace(" ", "").replace("　", "")
    compact = compact.replace("O", "0").replace("o", "0")
    if "通过" in compact or "空闲" in compact:
        return "FREE"
    match = re.search(r"(\d{1,2})秒", compact)
    if match:
        return "BUSY_" + str(int(match.group(1)))
    return ""


MIN_INK = 0.012
MAX_CANDIDATES = 3


def _ink(band: np.ndarray) -> float:
    """Fraction of clearly darker pixels: text ink on a bright sign panel."""
    if band.size == 0:
        return 0.0
    median = float(np.median(band))
    return float((band < median - 40).mean())


def line_candidates(gray: np.ndarray, limit: int = MAX_CANDIDATES):
    """Return up to `limit` bottom-line crops, most text-like first.

    A single Otsu threshold is not enough: in daylight the wall behind the
    sign is also bright and becomes the largest blob.  Score a few high
    percentile thresholds instead and keep every sign-like rectangle
    (2-40 % of the frame, aspect 1.05-2.6, mostly filled).  The rectangles are
    then ranked by the ink fraction of their lower text band, because the
    largest bright blob is often a wall with no text on it.

    Returns [] when nothing looks like printed text; the caller must not fall
    back to full-frame detection in that case (the wall would be scanned on
    every frame while the car is driving).
    """
    height, width = gray.shape[:2]
    frame_area = float(height * width)
    otsu, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    thresholds = [np.percentile(gray, 90), otsu, np.percentile(gray, 85)]
    found = {}
    for threshold in thresholds:
        if not np.isfinite(threshold) or threshold >= 255.0:
            continue
        _, binary = cv2.threshold(gray, float(threshold), 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w < 0.15 * width or h < 0.08 * height:
                continue
            area = float(w * h)
            fraction = area / frame_area
            aspect = float(w) / float(max(1, h))
            fill = cv2.contourArea(contour) / max(1.0, area)
            if not (0.02 <= fraction <= 0.40 and 1.05 <= aspect <= 2.6 and fill >= 0.50):
                continue
            band = gray[y + int(h * 0.50):y + int(h * 0.92),
                        x + int(w * 0.06):x + int(w * 0.94)]
            key = (x, y, w, h)
            score = _ink(band)
            if key not in found or score > found[key][0]:
                found[key] = (score, area, band)
    ranked = sorted(found.items(), key=lambda item: (item[1][0], item[1][1]),
                    reverse=True)
    crops = []
    for _, (score, _, band) in ranked:
        if score < MIN_INK:
            break
        if band.size and band.shape[0] >= 8 and band.shape[1] >= 24:
            crops.append(band)
        if len(crops) >= limit:
            break
    return crops


def bottom_line(gray: np.ndarray):
    """Single best bottom-line crop, or None (kept for single-image tools)."""
    crops = line_candidates(gray, 1)
    return crops[0] if crops else None


DETECT_LIMITS = (480, 736)
DETECT_BACKOFF = 0.8
DETECT_BACKOFF_MAX = 3.0


def engine_params(det: bool, threads: int, limit: int = 480) -> dict:
    """Common ONNX Runtime tuning plus the bundled tiny models when present."""
    params = {
        "EngineConfig.onnxruntime.intra_op_num_threads": threads,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
    }
    params["Rec.rec_img_shape"] = [3, 48, REC_WIDTH]
    if os.path.exists(SMALL_REC):
        params["Rec.model_path"] = SMALL_REC
    if det:
        params["Det.limit_side_len"] = limit
        if os.path.exists(TINY_DET):
            params["Det.model_path"] = TINY_DET
    return params


class Recognizer:
    """Fast crop-first reader with a general full-frame detector behind it.

    The crop is only an optimisation: it assumes a bright two-line panel and
    is validated by parsing its text, so a wrong crop costs one cheap
    recognition pass and falls through to detection.  Detection has no layout
    assumption, which is what makes the reader work on a different board,
    a printed A4 sheet, or a monitor at another angle.

    Two detector passes are used: native resolution first (fast), then a
    min-side 736 upscale for small/distant text.  A real 640x480 frame cannot
    resolve Chinese text much below a ~160 px wide sign; beyond that the
    result is genuinely unreadable, so the mission should stop closer.
    """

    def __init__(self, fallback: bool = True, scale: int = 2, threads: int = 2,
                 detect_backoff: float = DETECT_BACKOFF):
        self.scale = scale
        self.fallback = fallback
        # Recognition only: no detector, no angle classifier.  The camera is
        # bolted upright, so the 180-degree classifier buys nothing here.
        params = engine_params(det=False, threads=threads)
        params.update({"Global.use_det": False, "Global.use_cls": False})
        self.rec = RapidOCR(params=params)
        self.threads = threads
        self._detectors = {}
        self._next_detect = 0.0
        self._backoff = detect_backoff
        self._backoff_max = max(detect_backoff, DETECT_BACKOFF_MAX)

    def _detector(self, limit: int):
        if limit not in self._detectors:
            params = engine_params(det=True, threads=self.threads, limit=limit)
            params["Global.use_cls"] = True
            self._detectors[limit] = RapidOCR(params=params)
        return self._detectors[limit]

    def _full_engine(self):
        """Native-resolution detector (kept for single-image tools/tests)."""
        return self._detector(DETECT_LIMITS[0])

    def reset(self) -> None:
        """Clear the detection backoff (single-image tools, benchmarks)."""
        self._next_detect = 0.0
        self._backoff = DETECT_BACKOFF

    def warmup(self) -> None:
        blank = np.full((96, 320), 255, np.uint8)
        cv2.putText(blank, "0", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 2.0, 0, 4)
        self.rec(blank)

    def read(self, path: str):
        """Return (status, elapsed_ms); status is '' when nothing was read."""
        start = time.perf_counter()
        image = cv2.imread(path, cv2.IMREAD_COLOR)
        if image is None:
            return "", 0.0
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image

        for crop in line_candidates(gray):
            upscaled = cv2.resize(crop, None, fx=self.scale, fy=self.scale,
                                  interpolation=cv2.INTER_CUBIC)
            result = self.rec(upscaled)
            status = parse_status("".join(result.txts or ()))
            if status:
                self._backoff = DETECT_BACKOFF
                return status, (time.perf_counter() - start) * 1000.0

        if self.fallback and time.monotonic() >= self._next_detect:
            status = ""
            for limit in DETECT_LIMITS:
                result = self._detector(limit)(image)
                status = parse_status("".join(result.txts or ()))
                if status:
                    break
            if status:
                self._backoff = DETECT_BACKOFF
                return status, (time.perf_counter() - start) * 1000.0
            # Nothing readable: keep searching, but back off so a wall in view
            # does not pin a CPU core on every scan.
            self._backoff = min(self._backoff * 1.7, self._backoff_max)
            self._next_detect = time.monotonic() + self._backoff
        return "", (time.perf_counter() - start) * 1000.0


def expected_from_name(name: str) -> str:
    base = os.path.basename(name).lower()
    if base.startswith("pass"):
        return "FREE"
    match = re.match(r"wait(\d+)", base)
    if match:
        return "BUSY_" + str(int(match.group(1)))
    return ""


def run_dir(engine: Recognizer, directory: str, verbose: bool) -> int:
    images = sorted(os.path.join(directory, name) for name in os.listdir(directory)
                    if name.lower().endswith((".png", ".jpg", ".jpeg")))
    failures = 0
    times = []
    for path in images:
        engine.reset()
        status, ms = engine.read(path)
        times.append(ms)
        expected = expected_from_name(path)
        ok = not expected or status == expected
        failures += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'} {os.path.basename(path):32s} "
              f"{status or 'UNKNOWN':8s} {ms:6.1f} ms"
              + ("" if expected else "  (no expected label)"))
        if verbose:
            print(f"     expected={expected or '-'}", file=sys.stderr)
    if times:
        times.sort()
        p50 = times[len(times) // 2]
        print(f"\n{len(images) - failures}/{len(images)} correct; "
              f"p50 {p50:.1f} ms, max {times[-1]:.1f} ms")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", help="recognise one image and exit")
    parser.add_argument("--dir", help="recognise every image in a directory")
    parser.add_argument("--scale", type=int, default=2, help="bottom-line upscale (default 2)")
    parser.add_argument("--no-fallback", action="store_true",
                        help="disable the full-frame detector fallback")
    parser.add_argument("--serve", action="store_true",
                        help="stdin protocol used by pharmacy_board2_node")
    parser.add_argument("--threads", type=int, default=2,
                        help="ONNX Runtime intra-op threads (default 2)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    # Keep the Pi's four cores available to the control loop; 2 threads is
    # enough for a 200x100 recognition crop.
    cv2.setNumThreads(2)
    engine = Recognizer(fallback=not args.no_fallback, scale=args.scale,
                        threads=max(1, args.threads))
    engine.warmup()

    if args.image:
        engine.reset()
        status, ms = engine.read(args.image)
        print(f"{status or 'UNKNOWN'} ({ms:.1f} ms)")
        return 0 if status else 1
    if args.dir:
        return run_dir(engine, args.dir, args.verbose)

    # Default: the ROS worker protocol.
    print("READY", flush=True)
    for line in sys.stdin:
        path = line.strip()
        if not path:
            continue
        if path.lower() in ("quit", "exit"):
            break
        status, ms = engine.read(path)
        print(status or "UNKNOWN", flush=True)
        if args.verbose:
            print(f"{path}: {status or 'UNKNOWN'} {ms:.1f} ms", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
