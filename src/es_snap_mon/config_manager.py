"""Configuration and secure credential storage."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List

import keyring

from .models import ClusterConfig

_APP_NAME = "es_snap_mon"
_CONFIG_FILE = "clusters.json"

DEFAULT_PRESETS = [
    ClusterConfig(
        name="APAC Production",
        host="https://elastic.apac-prod-1.wtg.zone",
        snapshot_repo="au2s3-b1.wtg.ws-us2-production",
        slm_policy="slm_apac-prod-1-qid-full-backup-to-s3",
        username="elastic",
        verify_ssl=True,
    ),
    ClusterConfig(
        name="AMER Production",
        host="https://elastic.amer-prod-1.wtg.zone",
        snapshot_repo="us2s3-b1.wtg.ws-us2-production",
        slm_policy="slm_amer-prod-1-qid-full-backup-to-s3",
        username="elastic",
        verify_ssl=True,
    ),
    ClusterConfig(
        name="EMEA Production",
        host="https://elastic.emea-prod-1.wtg.zone",
        snapshot_repo="de1s3-b1.wtg.ws-us2-production",
        slm_policy="slm_emea-prod-1-qid-full-backup-to-s3",
        username="elastic",
        verify_ssl=True,
    ),
]


def _config_dir() -> Path:
    """Return platform-appropriate config directory."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif os.name == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    cfg = base / _APP_NAME
    cfg.mkdir(parents=True, exist_ok=True)
    return cfg


def _config_path() -> Path:
    return _config_dir() / _CONFIG_FILE


def _password_key(cluster_name: str) -> str:
    return f"{_APP_NAME}_cluster_{cluster_name}"


def load_clusters() -> List[ClusterConfig]:
    """Load all saved cluster configurations."""
    path = _config_path()
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    clusters = []
    for item in raw:
        try:
            clusters.append(
                ClusterConfig(
                    name=item["name"],
                    host=item["host"],
                    snapshot_repo=item["snapshot_repo"],
                    slm_policy=item["slm_policy"],
                    username=item["username"],
                    verify_ssl=bool(item.get("verify_ssl", True)),
                )
            )
        except KeyError:
            continue
    return clusters


def save_clusters(clusters: List[ClusterConfig]) -> None:
    """Persist cluster configurations (without passwords)."""
    data = [
        {
            "name": c.name,
            "host": c.host,
            "snapshot_repo": c.snapshot_repo,
            "slm_policy": c.slm_policy,
            "username": c.username,
            "verify_ssl": bool(c.verify_ssl),
        }
        for c in clusters
    ]
    with open(_config_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_password(cluster_name: str) -> str | None:
    """Retrieve password from OS keyring."""
    try:
        return keyring.get_password(_APP_NAME, _password_key(cluster_name))
    except Exception:
        return None


def set_password(cluster_name: str, password: str) -> None:
    """Store password in OS keyring."""
    keyring.set_password(_APP_NAME, _password_key(cluster_name), password)


def delete_password(cluster_name: str) -> None:
    """Remove password from OS keyring."""
    try:
        keyring.delete_password(_APP_NAME, _password_key(cluster_name))
    except Exception:
        pass


def save_cluster(cluster: ClusterConfig, password: str) -> None:
    """Save or update a cluster config + password."""
    clusters = {c.name: c for c in load_clusters()}
    clusters[cluster.name] = cluster
    save_clusters(list(clusters.values()))
    set_password(cluster.name, password)


def remove_cluster(name: str) -> None:
    """Delete a cluster config and its stored password."""
    clusters = [c for c in load_clusters() if c.name != name]
    save_clusters(clusters)
    delete_password(name)


def toggle_ssl_verify(name: str) -> bool:
    """Toggle SSL verification for a cluster. Returns new value."""
    clusters = load_clusters()
    for c in clusters:
        if c.name == name:
            c.verify_ssl = not c.verify_ssl
            save_clusters(clusters)
            return c.verify_ssl
    return True


def load_presets(password: str = "", verify_ssl: bool = True) -> None:
    """Load the default cluster presets."""
    for preset in DEFAULT_PRESETS:
        existing = load_clusters()
        if any(c.name == preset.name for c in existing):
            continue
        cfg = ClusterConfig(
            name=preset.name,
            host=preset.host,
            snapshot_repo=preset.snapshot_repo,
            slm_policy=preset.slm_policy,
            username=preset.username,
            verify_ssl=verify_ssl,
        )
        save_cluster(cfg, password)
