"""Transport-level tests: the in-memory loopback used by the other suites.

The real serial/TCP transports are only checked for their safe
"not open yet" behaviour, so the suite runs on a machine without a chassis.
"""

import pytest

from eprobot_base.transport import (
    LoopbackTransport,
    SerialTransport,
    SocketTransport,
    Transport,
    TransportError,
)


def test_loopback_lifecycle():
    transport = LoopbackTransport()
    assert transport.is_open is False
    assert transport.open_count == 0

    transport.open()
    assert transport.is_open is True
    assert transport.open_count == 1

    transport.close()
    assert transport.is_open is False
    assert transport.close_count == 1


def test_loopback_write_requires_open():
    transport = LoopbackTransport()
    with pytest.raises(TransportError):
        transport.write(b"\x5A")


def test_loopback_read_and_write_are_independent_directions():
    transport = LoopbackTransport()
    transport.open()

    transport.write(b"host-to-chassis")
    assert transport.pending_written == len(b"host-to-chassis")
    assert transport.read() == b""  # nothing fed yet

    transport.feed(b"chassis-to-host")
    assert transport.read() == b"chassis-to-host"
    assert transport.read() == b""
    assert transport.take_written() == b"host-to-chassis"
    assert transport.take_written() == b""
    assert transport.pending_written == 0


def test_loopback_read_honours_max_bytes():
    transport = LoopbackTransport()
    transport.open()
    transport.feed(b"abcdef")
    assert transport.read(2) == b"ab"
    assert transport.read(3) == b"cde"
    assert transport.read(10) == b"f"


def test_loopback_take_written_clears_buffer():
    transport = LoopbackTransport()
    transport.open()
    transport.write(b"one")
    transport.write(b"two")
    assert transport.take_written() == b"onetwo"
    assert transport.pending_written == 0


def test_serial_transport_is_inert_before_open():
    transport = SerialTransport("/dev/does-not-exist")
    assert isinstance(transport, Transport)
    assert transport.is_open is False
    assert transport.read() == b""
    with pytest.raises(TransportError):
        transport.write(b"\x5A")
    transport.close()  # must not raise when never opened


def test_socket_transport_is_inert_before_open():
    transport = SocketTransport("127.0.0.1", 1)
    assert transport.is_open is False
    assert transport.read() == b""
    with pytest.raises(TransportError):
        transport.write(b"\x5A")
    transport.close()  # must not raise when never opened


class _FakeSerial:
    """Stand-in for ``serial.Serial`` that raises a pyserial-style OSError.

    ``serial.SerialException`` is an ``OSError`` subclass; using ``OSError``
    keeps this test independent of whether pyserial is installed.
    """

    is_open = True
    in_waiting = 4

    def __init__(self, exc):
        self.exc = exc

    def read(self, size):
        raise self.exc

    def write(self, data):
        raise self.exc

    def close(self):
        self.is_open = False


def test_serial_transport_wraps_pyserial_read_error():
    transport = SerialTransport("/dev/fake")
    transport._serial = _FakeSerial(OSError("device disconnected during read"))
    with pytest.raises(TransportError) as excinfo:
        transport.read()
    assert "serial read failed" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, OSError)


def test_serial_transport_wraps_pyserial_write_error():
    transport = SerialTransport("/dev/fake")
    transport._serial = _FakeSerial(OSError("device disconnected during write"))
    with pytest.raises(TransportError) as excinfo:
        transport.write(b"\x5A")
    assert "serial write failed" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, OSError)
