#!/bin/sh
# Run the bundled aarch64 runtime against the sample images.
set -e
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHONPATH="$HERE/runtime_arm64" /usr/bin/python3 "$HERE/board2_ocr_worker.py" --dir "$HERE/samples"
