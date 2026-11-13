#!/usr/bin/env python3
"""Nav2 live-parameter tuning page.

Run it on the car (``--local``, as ``nav-tune-web.service`` does) and it talks
to the node parameter services through one rclpy node.  Run it on the dev host
and it shells out to the car over SSH, because tunx is TCP-only and does not
carry the DDS graph.

Start the host copy with ``iscc tune-web host`` or directly::

    python3 tools/nav_tune_web.py --port 8766
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import shlex
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
NAV_YAML = ROOT / "ros2_ws/deploy/eprobot_navigation/config/nav2_params.yaml"
NAV_BASELINE_ENV = os.environ.get("NAV_TUNE_BASELINE")
CAR_NAV_YAML = Path("/home/ubuntu/eprobot_navigation/config/nav2_params.yaml")
PAGE = Path(__file__).with_name("nav_tune_web.html")

LOCAL = False
_DIRECT = False
_ROS_NODE = None
_ROS_EXECUTOR = None
_ROS_CLIENTS = {}
_ROS_LOCK = threading.Lock()

_DEFAULT_NODES = [
    "/controller_server",
    "/planner_server",
    "/behavior_server",
    "/bt_navigator",
    "/map_server",
    "/amcl",
    "/global_costmap/global_costmap",
    "/local_costmap/local_costmap",
]

NAV_NODES = [n.strip() for n in os.environ.get("NAV_TUNE_NODES", "").split(",") if n.strip()] or _DEFAULT_NODES


def _conf_paths():
    if os.environ.get("ISCC_CONFIG"):
        yield Path(os.environ["ISCC_CONFIG"])
    if os.environ.get("XDG_CONFIG_HOME"):
        yield Path(os.environ["XDG_CONFIG_HOME"]) / "iscc/iscc.conf"
    yield Path.home() / ".config/iscc/iscc.conf"
    yield ROOT / "iscc.conf"


def _read_conf():
    for path in _conf_paths():
        if not path.is_file():
            continue
        conf = {}
        for line in path.read_text(errors="replace").splitlines():
            match = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
            if not match:
                continue
            value = match.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            conf[match.group(1)] = value
        return conf
    return {}


CONF = _read_conf()


def _cfg(key, default):
    return os.environ.get(key) or CONF.get(key) or default


ROBOT_IP = _cfg("ROBOT_IP", "10.7.7.2")
ROBOT_USER = _cfg("ROBOT_USER", "EPRobot")
ROBOT_PASS = _cfg("ROBOT_PASS", "<REDACTED>")
ROS_DOMAIN_ID = _cfg("ROS_DOMAIN_ID", "0")
ROS2_WS_SETUP = _cfg("ROS2_WS_SETUP", "/opt/eprobot_ws/install/setup.bash")

SSH_OPTS = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "ConnectTimeout=8",
    "-o", "LogLevel=ERROR",
    "-o", "PreferredAuthentications=password",
    "-o", "PubkeyAuthentication=no",
]

ROS_ENV = (
    "source /opt/ros/lyrical/setup.bash; "
    f"source {shlex.quote(ROS2_WS_SETUP)}; "
    f"export ROS_DOMAIN_ID={shlex.quote(ROS_DOMAIN_ID)}; "
)


def rsh(command, timeout=60):
    if LOCAL:
        try:
            proc = subprocess.run(
                ["bash", "-lc", command],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            return 124, "", f"local command timed out after {timeout:.0f}s"
    env = dict(os.environ)
    env["SSHPASS"] = ROBOT_PASS
    try:
        proc = subprocess.run(
            ["sshpass", "-e", "ssh", *SSH_OPTS, f"{ROBOT_USER}@{ROBOT_IP}", command],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"ssh timed out after {timeout:.0f}s"
    except FileNotFoundError:
        return 127, "", "sshpass not found on the host"


def robot_label():
    if LOCAL:
        return f"{socket.gethostname()} (local)"
    return f"{ROBOT_USER}@{ROBOT_IP}"


def _init_direct_ros():
    """Start one rclpy node so local mode does not fork eight ros2 CLIs."""
    global _DIRECT, _ROS_NODE, _ROS_EXECUTOR
    try:
        import rclpy
        from rclpy.executors import MultiThreadedExecutor
        from rclpy.node import Node
    except ImportError:
        return False
    if not rclpy.ok():
        rclpy.init(args=None)
    node = Node("nav_tune_web")
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    thread = threading.Thread(target=executor.spin, name="nav-tune-ros", daemon=True)
    thread.start()
    _ROS_NODE = node
    _ROS_EXECUTOR = executor
    _DIRECT = True
    return True


def _wait_future(future, timeout):
    deadline = time.monotonic() + timeout
    while not future.done() and time.monotonic() < deadline:
        time.sleep(0.005)
    if not future.done():
        return None
    try:
        return future.result()
    except Exception:
        return None


def _ros_client(node_name, srv_type, suffix):
    key = (node_name, suffix)
    with _ROS_LOCK:
        client = _ROS_CLIENTS.get(key)
        if client is None:
            client = _ROS_NODE.create_client(srv_type, f"{node_name}/{suffix}")
            _ROS_CLIENTS[key] = client
    return client


def _ros_call(node_name, srv_type, suffix, request, timeout=5.0):
    if not _DIRECT or _ROS_NODE is None:
        return None
    client = _ros_client(node_name, srv_type, suffix)
    if not client.wait_for_service(timeout_sec=min(timeout, 2.0)):
        return None
    return _wait_future(client.call_async(request), timeout)


def _parameter_value_to_py(value):
    from rcl_interfaces.msg import ParameterType
    kind = value.type
    if kind == ParameterType.PARAMETER_BOOL:
        return bool(value.bool_value)
    if kind == ParameterType.PARAMETER_INTEGER:
        return int(value.integer_value)
    if kind == ParameterType.PARAMETER_DOUBLE:
        return float(value.double_value)
    if kind == ParameterType.PARAMETER_STRING:
        return value.string_value
    if kind == ParameterType.PARAMETER_BYTE_ARRAY:
        return list(value.byte_array_value)
    if kind == ParameterType.PARAMETER_BOOL_ARRAY:
        return list(value.bool_array_value)
    if kind == ParameterType.PARAMETER_INTEGER_ARRAY:
        return list(value.integer_array_value)
    if kind == ParameterType.PARAMETER_DOUBLE_ARRAY:
        return list(value.double_array_value)
    if kind == ParameterType.PARAMETER_STRING_ARRAY:
        return list(value.string_array_value)
    return None


def _dump_nodes_direct(nodes):
    from rcl_interfaces.srv import GetParameters, ListParameters
    running = set()
    try:
        for name, namespace in _ROS_NODE.get_node_names_and_namespaces():
            prefix = namespace.rstrip("/")
            running.add(f"{prefix}/{name}" if prefix else f"/{name}")
    except Exception:
        pass
    result = {}
    for node in nodes:
        if node not in running:
            result[node] = {"error": "node not running"}
            continue
        request = ListParameters.Request()
        request.depth = 0
        response = _ros_call(node, ListParameters, "list_parameters", request, timeout=5.0)
        if response is None:
            result[node] = {"error": "list_parameters failed"}
            continue
        names = list(response.result.names)
        if not names:
            result[node] = {"params": {}}
            continue
        request = GetParameters.Request()
        request.names = names
        response = _ros_call(node, GetParameters, "get_parameters", request, timeout=8.0)
        if response is None or len(response.values) != len(names):
            result[node] = {"error": "get_parameters failed"}
            continue
        result[node] = {
            "params": {
                name: _parameter_value_to_py(value)
                for name, value in zip(names, response.values)
            }
        }
    return result


def list_running_nodes():
    rc, out, err = rsh(ROS_ENV + "timeout 8 ros2 node list", timeout=16)
    if rc != 0:
        return set(), err.strip()
    return {line.strip() for line in out.splitlines() if line.strip().startswith("/")}, ""


def _flatten(value, prefix=""):
    flat = {}
    for key, item in value.items():
        name = f"{prefix}{key}"
        if isinstance(item, dict):
            flat.update(_flatten(item, name + "."))
        else:
            flat[name] = item
    return flat


def _parse_dump(node, text):
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        tail = text.strip().splitlines()[-1:] or ["invalid YAML"]
        return {"error": tail[0]}
    if not isinstance(doc, dict):
        return {"error": "empty dump"}
    block = doc.get(node)
    if block is None and len(doc) == 1:
        block = next(iter(doc.values()))
    if isinstance(block, dict) and isinstance(block.get("ros__parameters"), dict):
        block = block["ros__parameters"]
    if not isinstance(block, dict):
        return {"error": "unexpected dump format"}
    return {"params": _flatten(block)}


_CACHE = {}


def dump_nodes(nodes=None):
    nodes = list(nodes or NAV_NODES)
    key = tuple(nodes)
    cached = _CACHE.get(key)
    if cached and time.time() - cached[0] < 3:
        return cached[1], cached[2]

    if LOCAL and _DIRECT:
        result = _dump_nodes_direct(nodes)
        _CACHE[key] = (time.time(), result, "")
        return result, ""

    # Fast path: the unit check is ~0.5 s, while ros2 node list can block for
    # several seconds when the daemon has gone stale after a nav shutdown.
    if set(nodes) & set(_DEFAULT_NODES):
        _, unit_out, _ = rsh("systemctl is-active eprobot-nav", timeout=8)
        if unit_out.strip() != "active":
            result = {node: {"error": "eprobot-nav is not running"} for node in nodes}
            _CACHE[key] = (time.time(), result, "eprobot-nav is not running")
            return result, "eprobot-nav is not running"

    running, list_err = list_running_nodes()
    result = {}
    todo = []
    for node in nodes:
        if node in running:
            todo.append(node)
        else:
            result[node] = {"error": "node not running"}

    if todo:
        # Two dumps at a time: one takes ~4-8 s on an idle Pi 4, but eight
        # concurrent ros2 processes saturate all four cores and push each past
        # the timeout while Nav2 is driving.  Pairing halves the CPU spike and
        # still finishes the eight-node graph in roughly half a minute.
        script = ["d=$(mktemp -d /tmp/iscctune.XXXXXX) || exit 1; "]
        batch = 2
        for start in range(0, len(todo), batch):
            for index in range(start, min(start + batch, len(todo))):
                qnode = shlex.quote(todo[index])
                script.append(
                    f"( timeout 30 ros2 param dump {qnode} "
                    f">$d/{index}.out 2>$d/{index}.err; "
                    f"echo $? >$d/{index}.rc ) & "
                )
            script.append("wait; ")
        for index, node in enumerate(todo):
            script.append(
                f"echo '@@@NODE {node}'; "
                f"echo '@@@RC '$(cat $d/{index}.rc 2>/dev/null); "
                f"echo '@@@OUT'; cat $d/{index}.out 2>/dev/null; "
                f"echo '@@@ERR'; cat $d/{index}.err 2>/dev/null; "
                "echo '@@@END'; "
            )
        script.append("rm -rf $d; ")
        rc, out, err = rsh(ROS_ENV + "".join(script), timeout=150)
        current = None
        phase = "out"
        rc_value = ""
        out_buf, err_buf = [], []
        for line in out.splitlines():
            if line.startswith("@@@NODE "):
                current = line[len("@@@NODE "):].strip()
                rc_value = ""
                out_buf, err_buf = [], []
                phase = "out"
            elif line.startswith("@@@RC ") and current:
                rc_value = line[len("@@@RC "):].strip()
            elif line == "@@@OUT" and current:
                phase = "out"
            elif line == "@@@ERR" and current:
                phase = "err"
            elif line == "@@@END" and current:
                text = "\n".join(out_buf).strip()
                if rc_value == "0" and text:
                    result[current] = _parse_dump(current, text)
                else:
                    msg = "\n".join(err_buf).strip() or f"param dump failed (rc={rc_value or '?'})"
                    result[current] = {"error": msg.splitlines()[-1]}
                current = None
            elif current is not None:
                (out_buf if phase == "out" else err_buf).append(line)
        for node in todo:
            if node not in result:
                result[node] = {"error": (err.strip() or "no response from car").splitlines()[-1]}

    _CACHE[key] = (time.time(), result, list_err)
    return result, list_err


def load_baseline():
    if NAV_BASELINE_ENV:
        path = Path(NAV_BASELINE_ENV)
    elif LOCAL and CAR_NAV_YAML.is_file():
        path = CAR_NAV_YAML
    else:
        path = NAV_YAML
    try:
        doc = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        return {}
    base = {}
    for node in NAV_NODES:
        block = doc
        for part in [p for p in node.split("/") if p]:
            block = block.get(part) if isinstance(block, dict) else None
        if isinstance(block, dict) and isinstance(block.get("ros__parameters"), dict):
            base[node] = _flatten(block["ros__parameters"])
    return base


def set_param(node, param, value):
    if node not in NAV_NODES:
        return {"ok": False, "message": f"unknown node: {node}"}
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", param):
        return {"ok": False, "message": f"invalid parameter name: {param}"}
    if LOCAL and _DIRECT:
        try:
            result = _set_param_direct(node, param, value)
        except Exception as exc:
            return {"ok": False, "message": f"direct set failed: {exc}"}
        if result.get("ok"):
            _CACHE.clear()
        return result
    command = (
        ROS_ENV
        + f"timeout 12 ros2 param set {shlex.quote(node)} {shlex.quote(param)} {shlex.quote(str(value))}"
    )
    rc, out, err = rsh(command, timeout=40)
    combined = "\n".join(part for part in (out.strip(), err.strip()) if part)
    if "Wrong parameter type" in combined:
        rc_get, out_get, _ = rsh(
            ROS_ENV + f"timeout 12 ros2 param get {shlex.quote(node)} {shlex.quote(param)}",
            timeout=40,
        )
        if rc_get == 0:
            coerced = _coerce_like(_parse_get(out_get), value)
            if coerced != str(value):
                command = (
                    ROS_ENV
                    + f"timeout 12 ros2 param set {shlex.quote(node)} {shlex.quote(param)} {shlex.quote(coerced)}"
                )
                rc, out, err = rsh(command, timeout=40)
                combined = "\n".join(part for part in (out.strip(), err.strip()) if part)
    ok = rc == 0 and "successful" in combined.lower() and "failed" not in combined.lower()
    reply = {"ok": ok, "message": "\n".join(combined.splitlines()[-3:])}
    if ok:
        _CACHE.clear()
        rc2, out2, _ = rsh(
            ROS_ENV + f"timeout 12 ros2 param get {shlex.quote(node)} {shlex.quote(param)}",
            timeout=40,
        )
        if rc2 == 0:
            reply["readback"] = out2.strip()
            reply["value"] = _parse_get(out2)
    return reply


def _coerce_python(current, value):
    if isinstance(current, bool):
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"not a bool: {value}")
    if isinstance(current, int):
        return int(float(value))
    if isinstance(current, float):
        return float(value)
    if isinstance(current, str):
        return str(value)
    if isinstance(current, list):
        parsed = value if isinstance(value, list) else yaml.safe_load(str(value))
        if not isinstance(parsed, list):
            raise ValueError("expected a list")
        if current and isinstance(current[0], bool):
            return [bool(item) for item in parsed]
        if current and isinstance(current[0], int):
            return [int(item) for item in parsed]
        if current and isinstance(current[0], float):
            return [float(item) for item in parsed]
        return [str(item) for item in parsed]
    return value


def _set_param_direct(node, param, value):
    from rcl_interfaces.srv import GetParameters, SetParameters
    from rclpy.parameter import Parameter

    request = GetParameters.Request()
    request.names = [param]
    response = _ros_call(node, GetParameters, "get_parameters", request, timeout=5.0)
    if response is None or len(response.values) != 1:
        return {"ok": False, "message": f"cannot read {param} from {node}"}
    current = _parameter_value_to_py(response.values[0])
    try:
        converted = _coerce_python(current, value)
        parameter = Parameter(name=param, value=converted).to_parameter_msg()
    except (TypeError, ValueError) as exc:
        return {"ok": False, "message": f"bad value for {param}: {exc}"}

    request = SetParameters.Request()
    request.parameters = [parameter]
    response = _ros_call(node, SetParameters, "set_parameters", request, timeout=8.0)
    if response is None or len(response.results) != 1:
        return {"ok": False, "message": "set_parameters failed"}
    result = response.results[0]
    if not result.successful:
        return {"ok": False, "message": result.reason or "set failed"}

    request = GetParameters.Request()
    request.names = [param]
    response = _ros_call(node, GetParameters, "get_parameters", request, timeout=5.0)
    reply = {"ok": True, "message": "Set parameter successful"}
    if response is not None and len(response.values) == 1:
        readback = _parameter_value_to_py(response.values[0])
        reply["value"] = readback
        reply["readback"] = f"{type(readback).__name__}: {readback}"
    return reply


def _coerce_scalar(like, value):
    if isinstance(like, bool):
        return "true" if bool(value) else "false"
    if isinstance(like, float):
        try:
            return repr(float(value))
        except (TypeError, ValueError):
            return str(value)
    if isinstance(like, int):
        try:
            return str(int(float(value)))
        except (TypeError, ValueError):
            return str(value)
    if isinstance(like, str):
        return json.dumps(str(value))
    return str(value)


def _coerce_like(current, value):
    text = str(value)
    if isinstance(current, list):
        try:
            parsed = yaml.safe_load(text)
        except yaml.YAMLError:
            return text
        if not isinstance(parsed, list):
            return text
        items = [
            _coerce_scalar(current[i] if i < len(current) else None, item)
            for i, item in enumerate(parsed)
        ]
        return "[" + ", ".join(items) + "]"
    if isinstance(current, str) and re.fullmatch(r"[-+]?\d+(\.\d+)?([eE][-+]?\d+)?|true|false|null", text.strip()):
        return json.dumps(text)
    return _coerce_scalar(current, value)


def _parse_get(text):
    for line in text.splitlines():
        marker = "value is: "
        if marker in line:
            try:
                return yaml.safe_load(line.split(marker, 1)[1])
            except yaml.YAMLError:
                return line.split(marker, 1)[1]
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "iscc-navtune/1.0"

    def log_message(self, fmt, *args):
        pass

    def _write(self, code, payload, content_type="application/json; charset=utf-8"):
        body = payload.encode("utf-8") if isinstance(payload, str) else payload
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._write(code, json.dumps(obj, ensure_ascii=False))

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            try:
                self._write(200, PAGE.read_text(), "text/html; charset=utf-8")
            except OSError as exc:
                self._write(500, f"page missing: {exc}", "text/plain; charset=utf-8")
            return
        if path == "/api/health":
            self._json(200, {"ok": True, "robot": robot_label()})
            return
        if path == "/api/params":
            started = time.time()
            nodes, list_err = dump_nodes()
            self._json(200, {
                "ok": True,
                "robot": robot_label(),
                "elapsed": round(time.time() - started, 2),
                "list_error": list_err,
                "nodes": nodes,
                "baseline": load_baseline(),
            })
            return
        self._json(404, {"ok": False, "message": "not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path != "/api/set":
            self._json(404, {"ok": False, "message": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length) or b"{}")
            node = str(data["node"])
            param = str(data["param"])
            value = data["value"]
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"ok": False, "message": f"bad request: {exc}"})
            return
        result = set_param(node, param, value)
        self._json(200 if result["ok"] else 400, result)


def main():
    global LOCAL
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--local", action="store_true",
                        help="run ros2 on this machine instead of over SSH (car-side mode)")
    args = parser.parse_args()
    LOCAL = args.local
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
    if LOCAL and not _init_direct_ros():
        print("[navtune] rclpy unavailable; falling back to the ros2 CLI", flush=True)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    print(f"[navtune] {robot_label()} -> http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
