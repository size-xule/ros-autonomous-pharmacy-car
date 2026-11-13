"""Byte transports for the chassis link.

The client only needs four operations: ``open``, ``close``, ``read`` and
``write``.  Keeping them behind this tiny interface lets the exact same driver
run over a real UART on the Pi 4, over TCP in the Renode hardware-in-the-loop
backtest, or over an in-memory loopback in unit tests.
"""

from __future__ import annotations

import socket
from typing import Optional


class TransportError(RuntimeError):
    pass


class Transport:
    def open(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def read(self, max_bytes: int = 4096) -> bytes:  # pragma: no cover
        raise NotImplementedError

    def write(self, data: bytes) -> None:  # pragma: no cover
        raise NotImplementedError

    @property
    def is_open(self) -> bool:  # pragma: no cover - interface
        raise NotImplementedError


class SerialTransport(Transport):
    """115200 8N1 over pyserial.

    ``timeout=0`` makes :meth:`read` non-blocking, which is what the 100 Hz
    control timer wants: never block the executor on a silent UART.
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        read_timeout: float = 0.0,
        write_timeout: float = 0.1,
    ) -> None:
        self.port = port
        self.baudrate = int(baudrate)
        self.read_timeout = float(read_timeout)
        self.write_timeout = float(write_timeout)
        self._serial = None

    def open(self) -> None:
        if self._serial is not None:
            return
        try:
            import serial  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise TransportError(
                "pyserial is required for SerialTransport (pip install pyserial)"
            ) from exc
        try:
            self._serial = serial.Serial(
                self.port,
                self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.read_timeout,
                write_timeout=self.write_timeout,
            )
        except Exception as exc:  # serial.SerialException and OSError
            raise TransportError("cannot open %s: %s" % (self.port, exc)) from exc

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            finally:
                self._serial = None

    def read(self, max_bytes: int = 4096) -> bytes:
        if self._serial is None:
            return b""
        try:
            waiting = getattr(self._serial, "in_waiting", 0)
            if waiting <= 0:
                return b""
            return self._serial.read(min(int(waiting), int(max_bytes)))
        except Exception as exc:  # SerialException subclasses OSError
            raise TransportError("serial read failed: %s" % exc) from exc

    def write(self, data: bytes) -> None:
        if self._serial is None:
            raise TransportError("serial port is not open")
        try:
            self._serial.write(data)
        except Exception as exc:  # unplugged adapter, write timeout, ...
            raise TransportError("serial write failed: %s" % exc) from exc

    @property
    def is_open(self) -> bool:
        return self._serial is not None and bool(getattr(self._serial, "is_open", True))


class SocketTransport(Transport):
    """TCP stream transport used by the Renode HIL bridge and remote UARTs."""

    def __init__(self, host: str, port: int, connect_timeout: float = 2.0) -> None:
        self.host = host
        self.port = int(port)
        self.connect_timeout = float(connect_timeout)
        self._sock: Optional[socket.socket] = None

    def open(self) -> None:
        if self._sock is not None:
            return
        try:
            self._sock = socket.create_connection(
                (self.host, self.port), timeout=self.connect_timeout
            )
            self._sock.settimeout(0.0)
        except OSError as exc:
            self._sock = None
            raise TransportError(
                "cannot connect to %s:%d: %s" % (self.host, self.port, exc)
            ) from exc

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def read(self, max_bytes: int = 4096) -> bytes:
        if self._sock is None:
            return b""
        try:
            return self._sock.recv(int(max_bytes))
        except BlockingIOError:
            return b""
        except OSError as exc:
            raise TransportError("socket read failed: %s" % exc) from exc

    def write(self, data: bytes) -> None:
        if self._sock is None:
            raise TransportError("socket is not open")
        try:
            self._sock.sendall(data)
        except OSError as exc:
            raise TransportError("socket write failed: %s" % exc) from exc

    @property
    def is_open(self) -> bool:
        return self._sock is not None


class LoopbackTransport(Transport):
    """In-memory transport for unit tests and the software backtest.

    ``feed()`` injects chassis->host bytes; ``take_written()`` returns and
    clears the host->chassis bytes.  A test can therefore play the chassis
    without any thread or real time.
    """

    def __init__(self) -> None:
        self._open = False
        self._rx = bytearray()
        self._tx = bytearray()
        self.open_count = 0
        self.close_count = 0

    def open(self) -> None:
        self._open = True
        self.open_count += 1

    def close(self) -> None:
        self._open = False
        self.close_count += 1

    def read(self, max_bytes: int = 4096) -> bytes:
        if not self._rx:
            return b""
        n = min(len(self._rx), int(max_bytes))
        out = bytes(self._rx[:n])
        del self._rx[:n]
        return out

    def write(self, data: bytes) -> None:
        if not self._open:
            raise TransportError("loopback transport is not open")
        self._tx.extend(data)

    def feed(self, data: bytes) -> None:
        self._rx.extend(data)

    def take_written(self) -> bytes:
        out = bytes(self._tx)
        del self._tx[:]
        return out

    @property
    def pending_written(self) -> int:
        return len(self._tx)

    @property
    def is_open(self) -> bool:
        return self._open
