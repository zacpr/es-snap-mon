"""Application-managed OpenSSH dynamic tunnel."""
from __future__ import annotations

import socket
import subprocess
import time
from threading import RLock


class SSHTunnelError(RuntimeError):
    pass


def build_ssh_command(jump_host: str, local_port: int) -> list[str]:
    port_args: list[str] = []
    destination = jump_host
    if ":" in jump_host:
        candidate, port = jump_host.rsplit(":", 1)
        if port.isdigit():
            destination = candidate
            port_args = ["-p", port]
    return [
        "ssh",
        "-N",
        "-D", f"127.0.0.1:{local_port}",
        "-o", "BatchMode=yes",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ConnectTimeout=10",
        "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=3",
        *port_args,
        destination,
    ]


class SSHTunnel:
    def __init__(self, jump_host: str, local_port: int | None = None):
        self.jump_host = jump_host
        self.local_port = local_port
        self._process: subprocess.Popen | None = None
        self._lock = RLock()
        self._sleep = time.sleep

    @property
    def proxy_url(self) -> str:
        if self.local_port is None:
            raise SSHTunnelError("SSH tunnel has not been started")
        return f"socks5h://127.0.0.1:{self.local_port}"

    def start(self) -> str:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return self.proxy_url
            self.local_port = self.local_port or self._find_free_port()
            try:
                self._process = subprocess.Popen(
                    build_ssh_command(self.jump_host, self.local_port),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            except OSError as exc:
                self._process = None
                raise SSHTunnelError(f"Could not start OpenSSH: {exc}") from exc
            self._wait_until_ready(timeout=15)
            return self.proxy_url

    def stop(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    def _wait_until_ready(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._process is None:
                raise SSHTunnelError("SSH tunnel is not running")
            if self._process.poll() is not None:
                detail = (self._process.stderr.read() if self._process.stderr else "").strip()
                self._process = None
                raise SSHTunnelError(detail or "OpenSSH could not establish the tunnel")
            if self._is_listening():
                return
            self._sleep(0.1)
        self.stop()
        raise SSHTunnelError(f"SSH tunnel to {self.jump_host} did not become ready")

    def _is_listening(self) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", self.local_port), timeout=0.2):
                return True
        except OSError:
            return False

    @staticmethod
    def _find_free_port() -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]


_tunnels: dict[str, SSHTunnel] = {}
_tunnel_lock = RLock()


def configure_tunnel(jump_host: str | None) -> str | None:
    jump_host = (jump_host or "").strip() or None
    with _tunnel_lock:
        if jump_host is None:
            return None
        tunnel = _tunnels.get(jump_host)
        if tunnel is None:
            tunnel = SSHTunnel(jump_host)
            _tunnels[jump_host] = tunnel
        try:
            return tunnel.start()
        except Exception:
            _tunnels.pop(jump_host, None)
            raise


def close_tunnel() -> None:
    with _tunnel_lock:
        tunnels = list(_tunnels.values())
        _tunnels.clear()
        for tunnel in tunnels:
            tunnel.stop()
