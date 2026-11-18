import json

from es_snap_mon.config_manager import load_clusters, save_clusters
from es_snap_mon.models import ClusterConfig


def test_cluster_jump_host_is_persisted(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cluster = ClusterConfig(
        name="APAC test",
        host="https://elastic.apac-test-2.sand.wtg.zone:443",
        snapshot_repo="repo",
        slm_policy="policy",
        username="elastic",
        ssh_jump_host="dante@10.2.0.31",
    )

    save_clusters([cluster])

    assert load_clusters()[0].ssh_jump_host == "dante@10.2.0.31"


def test_cluster_without_jump_defaults_to_direct(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = tmp_path / "es_snap_mon" / "clusters.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps([{
        "name": "direct",
        "host": "https://elastic.example",
        "snapshot_repo": "repo",
        "slm_policy": "policy",
        "username": "elastic",
    }]))

    assert load_clusters()[0].ssh_jump_host is None
