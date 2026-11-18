import socket
from unittest.mock import Mock, patch

import pytest

from es_snap_mon.ssh_tunnel import (
    SSHTunnel,
    SSHTunnelError,
    build_ssh_command,
    close_tunnel,
    configure_tunnel,
)


def test_dynamic_tunnel_uses_openssh_without_a_remote_shell():
    command = build_ssh_command("dante@10.2.0.31", 19080)

    assert command[:2] == ["ssh", "-N"]
    assert "-D" in command
    assert "127.0.0.1:19080" in command
    assert command[-1] == "dante@10.2.0.31"
    assert "BatchMode=yes" in command
    assert "ExitOnForwardFailure=yes" in command


def test_jump_host_can_include_a_nonstandard_ssh_port():
    command = build_ssh_command("dante@jump.example:2222", 19080)

    assert command[-3:] == ["-p", "2222", "dante@jump.example"]


def test_tunnel_waits_until_socks_port_is_listening():
    process = Mock()
    process.poll.return_value = None
    checks = iter([False, False, True])

    tunnel = SSHTunnel("jump.example", local_port=19080)
    tunnel._process = process
    tunnel._is_listening = lambda: next(checks)
    tunnel._sleep = lambda _: None

    tunnel._wait_until_ready(timeout=2)

    assert tunnel.proxy_url == "socks5h://127.0.0.1:19080"


def test_tunnel_reports_ssh_failure_instead_of_timing_out():
    process = Mock()
    process.poll.return_value = 255
    process.stderr.read.return_value = "ssh: connect to host jump.example: Connection timed out"

    tunnel = SSHTunnel("jump.example", local_port=19080)
    tunnel._process = process

    with pytest.raises(SSHTunnelError, match="Connection timed out"):
        tunnel._wait_until_ready(timeout=2)


def test_stop_terminates_owned_ssh_process():
    process = Mock()
    process.poll.return_value = None
    tunnel = SSHTunnel("jump.example", local_port=19080)
    tunnel._process = process

    tunnel.stop()

    process.terminate.assert_called_once_with()
    process.wait.assert_called_once_with(timeout=5)
    assert tunnel._process is None


def test_different_jump_hosts_keep_independent_tunnels():
    tunnels = {}

    class FakeTunnel:
        def __init__(self, host):
            self.jump_host = host
            tunnels[host] = self
            self.proxy_url = f"socks5h://127.0.0.1:{19080 + len(tunnels)}"

        def start(self):
            return self.proxy_url

        def stop(self):
            pass

    with patch("es_snap_mon.ssh_tunnel.SSHTunnel", FakeTunnel):
        first = configure_tunnel("first.example")
        second = configure_tunnel("second.example")
        assert configure_tunnel("first.example") == first

    assert first != second
    assert set(tunnels) == {"first.example", "second.example"}
    close_tunnel()


def test_free_local_port_returns_a_bindable_port():
    tunnel = SSHTunnel("jump.example")
    port = tunnel._find_free_port()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))
