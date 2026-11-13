from glob import glob
import os

from setuptools import setup

package_name = "eprobot_base"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        # ament index marker: makes `ros2 pkg` / launch find the package.
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        (os.path.join("share", package_name), ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.launch.py")),
        (os.path.join("share", package_name, "config"), glob("config/*.yaml")),
    ],
    install_requires=["setuptools"],
    # colcon's `test` verb selects its pytest step only when setup.py
    # advertises a `pytest` *test* dependency; otherwise it falls back to
    # `python -m unittest`, collects nothing and exits 5.  An
    # ``extras_require`` entry is the modern spelling (``tests_require`` is
    # dropped as an unknown option by setuptools >= 78, so colcon would not
    # see it) and keeps ``pip install .[test]`` working on Python 3.8.
    extras_require={"test": ["pytest"]},
    zip_safe=True,
    maintainer="ISCC_CAR Team",
    maintainer_email="iscc@ncut.edu.cn",
    description=(
        "ROS 2 driver for the EPRobot chassis: protocol v2.1 over serial, "
        "TCP or loopback"
    ),
    license="Apache-2.0",
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "eprobot_base = eprobot_base.node:main",
        ],
    },
)
