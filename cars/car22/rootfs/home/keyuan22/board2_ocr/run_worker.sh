#!/bin/sh
# Let pharmacy_board2_node spawn the bundled runtime:
#   ocr_python:=/path/to/run_worker.sh
#   ocr_worker:=/path/to/board2_ocr_worker.py
# The node runs "<ocr_python> <ocr_worker>"; this wrapper prepends the
# aarch64 site-packages and execs the system Python 3.
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PYTHONPATH="$HERE/runtime_arm64${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 "$@"
