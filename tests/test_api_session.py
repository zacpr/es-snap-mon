from unittest.mock import patch

import requests

from es_snap_mon.es_client import create_api_session
from es_snap_mon.models import ClusterConfig


def config() -> ClusterConfig:
    return ClusterConfig(
        name="test",
        host="https://elastic.cluster.example:443",
        snapshot_repo="repo",
        slm_policy="policy",
        username="elastic",
    )


def test_direct_session_does_not_set_a_proxy():
    with patch("es_snap_mon.es_client.configure_tunnel", return_value=None):
        session = create_api_session(config(), "secret")

    assert isinstance(session, requests.Session)
    assert session.proxies == {}


def test_tunnel_session_routes_http_and_https_through_remote_dns_socks():
    with patch(
        "es_snap_mon.es_client.configure_tunnel",
        return_value="socks5h://127.0.0.1:19080",
    ) as configure:
        session = create_api_session(config(), "secret", ssh_jump_host="jump.example")

    configure.assert_called_once_with("jump.example")
    assert session.proxies == {
        "http": "socks5h://127.0.0.1:19080",
        "https": "socks5h://127.0.0.1:19080",
    }
