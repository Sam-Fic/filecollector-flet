"""Single-instance IPC across all platforms.

Transport selection (transparent to callers):
  Linux / macOS  →  Unix domain socket (AF_UNIX)
  Windows        →  TCP on 127.0.0.1 (random ephemeral port)

A small address file (~/.cache/filecollector/ipc_addr.txt or
%LOCALAPPDATA%/filecollector/ipc_addr.txt on Windows) stores the transport
mode and address so that late-starting CLI processes know how to connect.
"""

import json
import os
import socket
import struct
import sys
import threading

# ---------------------------------------------------------------------------
# Platform paths
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    _CACHE_DIR = os.path.join(
        os.environ.get(
            "LOCALAPPDATA",
            os.path.join(os.path.expanduser("~"), "AppData", "Local"),
        ),
        "filecollector",
    )
elif sys.platform == "darwin":
    _CACHE_DIR = os.path.expanduser("~/Library/Caches/filecollector")
else:
    _CACHE_DIR = os.path.expanduser("~/.cache/filecollector")

_ADDR_FILE = os.path.join(_CACHE_DIR, "ipc_addr.txt")
_UNIX_SOCK_PATH = os.path.join(_CACHE_DIR, "ipc.sock")


def _supports_unix():
    """Can this platform create Unix domain sockets reliably?"""
    if not hasattr(socket, "AF_UNIX"):
        return False
    if sys.platform == "win32":
        return False
    return True


def _write_addr(mode, value):
    """Persist the active transport address so clients can find us."""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    with open(_ADDR_FILE, "w") as f:
        f.write(f"{mode}:{value}\n")


def _read_addr():
    """Read the active transport address.
    Returns (mode, value) or raises FileNotFoundError / ValueError.
    """
    with open(_ADDR_FILE) as f:
        line = f.read().strip()
    if ":" not in line:
        raise ValueError(f"Invalid address file format: {line!r}")
    return line.split(":", 1)


def _cleanup_stale():
    """Remove a stale address file so future clients don't attempt a dead
    connection."""
    try:
        if os.path.exists(_ADDR_FILE):
            os.unlink(_ADDR_FILE)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Client  (called from the CLI process)
# ---------------------------------------------------------------------------

def send_to_running_instance(args):
    """Send CLI *args* to the running GUI instance.

    Returns True if the message was delivered, False if no instance is
    running or the connection failed.
    """
    if not os.path.exists(_ADDR_FILE):
        return False

    try:
        mode, value = _read_addr()
    except (FileNotFoundError, ValueError):
        return False

    try:
        if mode == "unix" and _supports_unix():
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.connect(value)
        elif mode == "tcp":
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.connect(("127.0.0.1", int(value)))
        else:
            return False

        data = json.dumps(args).encode("utf-8")
        sock.sendall(struct.pack("!I", len(data)))
        sock.sendall(data)

        ack = sock.recv(1)
        return ack == b"\x00"

    except (ConnectionRefusedError, FileNotFoundError, OSError, socket.timeout):
        _cleanup_stale()
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Server  (called from the GUI process)
# ---------------------------------------------------------------------------

def start_ipc_server(callback):
    """Start a background IPC server for receiving CLI commands.

    *callback* is invoked from a **background thread** with the parsed list
    of argument strings.  Use a :class:`queue.Queue` + :class:`QTimer` to
    dispatch onto the Qt main thread.

    Returns a no-argument ``stop()`` function.
    """
    os.makedirs(_CACHE_DIR, exist_ok=True)

    # Try Unix socket on Linux / macOS; fall back to TCP everywhere.
    if _supports_unix():
        try:
            server_sock = _create_unix_server()
        except OSError:
            server_sock = _create_tcp_server()
    else:
        server_sock = _create_tcp_server()

    _running = [True]

    def _server_loop():
        while _running[0]:
            try:
                conn, _ = server_sock.accept()
                _handle_connection(conn, callback)
            except socket.timeout:
                continue
            except OSError:
                break
        _cleanup_server(server_sock)

    thread = threading.Thread(target=_server_loop, daemon=True)
    thread.start()

    def stop():
        _running[0] = False

    return stop


def _create_unix_server():
    """Bind a Unix domain socket and write the address file."""
    if os.path.exists(_UNIX_SOCK_PATH):
        os.unlink(_UNIX_SOCK_PATH)

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(_UNIX_SOCK_PATH)
    sock.listen(5)
    sock.settimeout(1)

    _write_addr("unix", _UNIX_SOCK_PATH)
    return sock


def _create_tcp_server():
    """Bind a TCP socket on 127.0.0.1 with an ephemeral port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(5)
    sock.settimeout(1)

    port = sock.getsockname()[1]
    _write_addr("tcp", str(port))
    return sock


def _cleanup_server(server_sock):
    """Clean up resources after the server loop exits."""
    try:
        server_sock.close()
    except Exception:
        pass
    _cleanup_stale()
    if _supports_unix():
        try:
            if os.path.exists(_UNIX_SOCK_PATH):
                os.unlink(_UNIX_SOCK_PATH)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Wire protocol  (shared)
# ---------------------------------------------------------------------------

def _handle_connection(conn, callback):
    """Read one message from *conn* and forward the parsed args to
    *callback*."""
    try:
        raw_len = conn.recv(4)
        if len(raw_len) < 4:
            return
        msg_len = struct.unpack("!I", raw_len)[0]

        data = b""
        while len(data) < msg_len:
            chunk = conn.recv(msg_len - len(data))
            if not chunk:
                return
            data += chunk

        if len(data) == msg_len:
            conn.sendall(b"\x00")
            args = json.loads(data.decode("utf-8"))
            callback(args)
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
