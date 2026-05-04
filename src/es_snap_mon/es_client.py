"""Elasticsearch API client for snapshot monitoring."""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

import requests
from requests.auth import HTTPBasicAuth

from .models import (
    ClusterConfig,
    ClusterStatus,
    SnapshotInfo,
    SnapshotState,
    SnapshotStats,
)


def _resolve_verify(config: ClusterConfig):
    """Resolve the `verify` parameter for requests.

    Returns:
        - `False` if SSL verification is disabled.
        - A path string when a custom CA bundle is configured (or the
          bundled cert is requested via `ca_cert == "bundled"`).
        - `True` for default system CA verification.
    """
    if not config.verify_ssl:
        return False
    ca = config.ca_cert
    if ca:
        if ca == "bundled":
            bundled = _bundled_ca_path()
            if bundled and bundled.exists():
                return str(bundled)
        elif Path(ca).exists():
            return ca
    return True


def _bundled_ca_path() -> Optional[Path]:
    """Locate the bundled ca.pem in both source and PyInstaller-frozen runs."""
    # PyInstaller extracts data files to sys._MEIPASS at runtime
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "es_snap_mon" / "data" / "ca.pem"
    return Path(__file__).parent / "data" / "ca.pem"


def fetch_cluster_status(config: ClusterConfig, password: str) -> ClusterStatus:
    """Fetch full status for a single cluster."""
    status = ClusterStatus(config=config)
    session = requests.Session()
    session.auth = HTTPBasicAuth(config.username, password)
    session.verify = _resolve_verify(config)
    base = config.host.rstrip("/")

    # 1. Health check
    try:
        resp = session.get(f"{base}/_cluster/health", timeout=10)
        resp.raise_for_status()
        status.reachable = True
    except requests.exceptions.SSLError as exc:
        status.error_message = f"SSL error: {exc}"
        return status
    except requests.exceptions.ConnectionError as exc:
        status.error_message = f"Connection error: {exc}"
        return status
    except requests.exceptions.Timeout:
        status.error_message = "Connection timed out"
        return status
    except requests.exceptions.RequestException as exc:
        status.error_message = f"Request failed: {exc}"
        return status

    # 2. Current snapshot
    try:
        resp = session.get(
            f"{base}/_snapshot/{config.snapshot_repo}/_current",
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            snapshots = data.get("snapshots", [])
            if snapshots:
                snap = snapshots[0]
                status.snapshot_info = _parse_snapshot(snap)
                status.snapshot_stats = _extract_stats(snap)

                # _current is light on stats; call _status for byte-level detail
                # while a snapshot is actually running.
                if status.snapshot_info.state == SnapshotState.IN_PROGRESS:
                    try:
                        snap_name = status.snapshot_info.name
                        s_resp = session.get(
                            f"{base}/_snapshot/{config.snapshot_repo}/{snap_name}/_status",
                            timeout=20,
                        )
                        if s_resp.status_code == 200:
                            s_data = s_resp.json().get("snapshots", [])
                            if s_data:
                                status.snapshot_stats = _extract_stats(s_data[0])
                                # Refresh shard counts from the richer status payload
                                status.snapshot_info = _merge_shard_stats(
                                    status.snapshot_info, s_data[0]
                                )
                    except Exception:
                        pass  # Fall back to whatever _current gave us
    except Exception as exc:
        status.error_message = f"Snapshot query failed: {exc}"

    # 3. SLM policy status
    try:
        resp = session.get(
            f"{base}/_slm/policy/{config.slm_policy}",
            timeout=10,
        )
        if resp.status_code == 200:
            policy_data = resp.json().get(config.slm_policy, {})
            raw_last = policy_data.get("last_success", {}).get("time")
            raw_next = policy_data.get("next_execution")
            status.slm_last_run = _format_es_time(raw_last)
            status.slm_next_run = _format_es_time(raw_next)
            status.slm_in_progress = policy_data.get("in_progress", {}).get("name") is not None
    except Exception:
        pass  # SLM is optional info

    return status


def _parse_snapshot(raw: dict) -> SnapshotInfo:
    """Parse snapshot JSON into SnapshotInfo."""
    state_str = raw.get("state", "UNKNOWN")
    # The /_status endpoint uses "STARTED" instead of "IN_PROGRESS"
    if state_str == "STARTED":
        state = SnapshotState.IN_PROGRESS
    else:
        try:
            state = SnapshotState(state_str)
        except ValueError:
            state = SnapshotState.UNKNOWN

    start = raw.get("start_time_in_millis", 0)
    end = raw.get("end_time_in_millis")
    duration = raw.get("duration_in_millis", 0)
    if end is None and duration and start:
        end = start + duration

    shards_block = raw.get("shards_stats") or raw.get("shards", {})
    return SnapshotInfo(
        name=raw.get("snapshot", "unknown"),
        state=state,
        start_time_ms=start,
        end_time_ms=end,
        duration_ms=duration,
        indices_count=len(raw.get("indices", [])),
        shards_total=shards_block.get("total", 0),
        shards_failed=shards_block.get("failed", 0),
        shards_successful=shards_block.get("done", shards_block.get("successful", 0)),
    )


def _merge_shard_stats(info: SnapshotInfo, status_raw: dict) -> SnapshotInfo:
    """Update shard counts on an existing SnapshotInfo from a /_status payload."""
    shards_block = status_raw.get("shards_stats") or status_raw.get("shards", {})
    info.shards_total = shards_block.get("total", info.shards_total)
    info.shards_failed = shards_block.get("failed", info.shards_failed)
    info.shards_successful = shards_block.get(
        "done", shards_block.get("successful", info.shards_successful)
    )
    return info


def _extract_stats(raw: dict) -> SnapshotStats:
    """Extract progress stats from snapshot JSON.

    Handles both the lightweight `_current` response and the richer
    `_status` response (which has `shards_stats` and nested `stats`).

    IMPORTANT: For incremental snapshots, the meaningful denominator is
    `stats.incremental.size_in_bytes` — the bytes this snapshot run actually
    has to upload. `stats.total.size_in_bytes` is the entire live cluster
    footprint (including segments already present in the repo from prior
    snapshots) and would dramatically understate progress.
    """
    stats = raw.get("stats", {})
    processed = stats.get("processed", {})
    incremental = stats.get("incremental", {})
    total = stats.get("total", {})

    processed_bytes = processed.get("size_in_bytes", 0)
    processed_files = processed.get("file_count", 0)

    # Prefer incremental (the work this snapshot is actually doing).
    # Fall back to total only if incremental isn't reported.
    incr_bytes = incremental.get("size_in_bytes", 0)
    incr_files = incremental.get("file_count", 0)
    if incr_bytes > 0:
        denom_bytes = incr_bytes
        denom_files = incr_files or total.get("file_count", 0)
    else:
        denom_bytes = total.get("size_in_bytes", 0)
        denom_files = total.get("file_count", 0)

    has_byte_stats = denom_bytes > 0 or processed_bytes > 0

    # Shard counts: `_status` uses `shards_stats`, `_current` uses `shards`.
    shards_block = raw.get("shards_stats") or raw.get("shards", {})
    shards_total = shards_block.get("total", 0)
    shards_successful = shards_block.get("done", shards_block.get("successful", 0))

    pct = 0.0
    if denom_bytes > 0:
        pct = min(100.0, (processed_bytes / denom_bytes) * 100)
    elif raw.get("state") == "SUCCESS":
        pct = 100.0

    # Fallback: shard-based progress when ES doesn't give byte stats
    if pct == 0.0 and shards_total > 0:
        pct = min(100.0, (shards_successful / shards_total) * 100)

    # Prefer server-reported elapsed time; fall back to client-side calculation
    time_ms = stats.get("time_in_millis")
    if time_ms:
        elapsed = time_ms / 1000.0
    else:
        start_ms = raw.get("start_time_in_millis") or stats.get("start_time_in_millis", int(time.time() * 1000))
        elapsed = max(0, time.time() - (start_ms / 1000.0))

    avg_speed = (processed_bytes / elapsed) if elapsed > 0 and processed_bytes > 0 else 0.0
    avg_shard_rate = (shards_successful / elapsed) if elapsed > 0 and shards_successful > 0 else 0.0

    # Use server start time if available (inside stats or at snapshot root)
    start_ms = raw.get("start_time_in_millis") or stats.get("start_time_in_millis", int(time.time() * 1000))

    return SnapshotStats(
        progress_pct=pct,
        processed_bytes=processed_bytes,
        total_bytes=denom_bytes,
        processed_files=processed_files,
        total_files=denom_files,
        start_time=start_ms / 1000.0,
        avg_speed_bps=avg_speed,
        has_byte_stats=has_byte_stats,
        processed_shards=shards_successful,
        total_shards=shards_total,
        avg_shard_rate=avg_shard_rate,
    )


def _format_es_time(value: Union[str, int, None]) -> Optional[str]:
    """Convert ES epoch millis or ISO string to human-readable local time."""
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
        else:
            # ISO 8601 string — try with/without Z
            s = str(value).replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
        return dt.astimezone().strftime("%b %d, %Y %I:%M %p")  # e.g. "Jan 15, 2024 10:30 AM"
    except Exception:
        return str(value)
