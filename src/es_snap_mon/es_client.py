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
            # Fallback: if the configured repo has no current snapshot, ask
            # the cluster for ALL currently-running snapshots (any repo). This
            # handles cases where the active backup landed in a different
            # repository than the one configured here.
            if not snapshots:
                try:
                    all_resp = session.get(f"{base}/_snapshot/_status", timeout=20)
                    if all_resp.status_code == 200:
                        snapshots = all_resp.json().get("snapshots", []) or []
                        if snapshots:
                            # Use the running snapshot's actual repo for any
                            # follow-up _status call below.
                            running_repo = snapshots[0].get("repository")
                            if running_repo and running_repo != config.snapshot_repo:
                                # Stash so the rest of the code uses it.
                                config_repo_for_status = running_repo
                            else:
                                config_repo_for_status = config.snapshot_repo
                        else:
                            config_repo_for_status = config.snapshot_repo
                    else:
                        config_repo_for_status = config.snapshot_repo
                except Exception:
                    config_repo_for_status = config.snapshot_repo
            else:
                config_repo_for_status = config.snapshot_repo

            if snapshots:
                running = [s for s in snapshots if (s.get("state") or "").upper() in ("STARTED", "IN_PROGRESS")]
                status.active_snapshot_count = len(running)
                status.active_snapshot_names = [s.get("snapshot", "unknown") for s in running]
                snap = _select_snapshot(snapshots)
                if snap is None:
                    snap = snapshots[0]
                # /_status includes the actual repository per snapshot.
                running_repo = snap.get("repository")
                if running_repo:
                    config_repo_for_status = running_repo
                status.snapshot_info = _parse_snapshot(snap)
                status.snapshot_stats = _extract_stats(snap)

                # _current is light on stats; call _status for byte-level detail
                # while a snapshot is actually running.
                if status.snapshot_info.state == SnapshotState.IN_PROGRESS:
                    try:
                        snap_name = status.snapshot_info.name
                        s_resp = session.get(
                            f"{base}/_snapshot/{config_repo_for_status}/{snap_name}/_status",
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


def _select_snapshot(snapshots: list[dict]) -> Optional[dict]:
    """Pick the best snapshot candidate from a payload.

    Preference:
    1) running snapshots (STARTED/IN_PROGRESS),
    2) newest start time.
    """
    if not snapshots:
        return None

    def _is_running(s: dict) -> bool:
        return (s.get("state") or "").upper() in ("STARTED", "IN_PROGRESS")

    def _start_ms(s: dict) -> int:
        stats = s.get("stats") or {}
        v = stats.get("start_time_in_millis") or s.get("start_time_in_millis") or 0
        try:
            return int(v)
        except Exception:
            return 0

    running = [s for s in snapshots if _is_running(s)]
    pool = running if running else snapshots
    return max(pool, key=_start_ms)


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


def fetch_diagnostics(config: ClusterConfig, password: str, sections: set[str] | None = None) -> dict:
    """Collect compact cluster + node stats useful for performance diagnosis.

    `sections` filters which sub-sections to include. Recognized keys:
    'health', 'pending_tasks', 'nodes', 'repository', 'recoveries', 'shards'.
    None = all of them.
    """
    sec = sections if sections is not None else {
        "health", "pending_tasks", "nodes", "repository", "recoveries", "shards",
    }
    out: dict = {"host": config.host, "name": config.name}
    session = requests.Session()
    session.auth = HTTPBasicAuth(config.username, password)
    session.verify = _resolve_verify(config)
    base = config.host.rstrip("/")

    def _get(path: str, timeout: int = 15):
        try:
            r = session.get(f"{base}{path}", timeout=timeout)
            if r.status_code != 200:
                return {"_status": r.status_code, "_body": r.text[:300]}
            return r.json()
        except Exception as e:
            return {"_error": str(e)[:300]}

    # 1. Cluster health
    if "health" in sec:
        health = _get("/_cluster/health")
        if isinstance(health, dict) and "_error" not in health and "_status" not in health:
            out["health"] = {
            k: health.get(k)
            for k in (
                "status",
                "number_of_nodes",
                "number_of_data_nodes",
                "active_primary_shards",
                "active_shards",
                "relocating_shards",
                "initializing_shards",
                "unassigned_shards",
                "delayed_unassigned_shards",
                "active_shards_percent_as_number",
                "task_max_waiting_in_queue_millis",
            )
        }
        else:
            out["health"] = health

    # 2. Pending tasks (top of the queue, if any)
    if "pending_tasks" in sec:
        pending = _get("/_cluster/pending_tasks")
        if isinstance(pending, dict):
            tasks = pending.get("tasks", [])
            out["pending_tasks_count"] = len(tasks)
            out["pending_tasks_top"] = [
                {k: t.get(k) for k in ("priority", "source", "time_in_queue_millis")}
                for t in tasks[:5]
            ]

    # 3. Per-node stats (jvm + fs + os.load + indices.store), trimmed
    if "nodes" in sec:
        nstats = _get("/_nodes/stats/jvm,fs,os,indices,thread_pool?human=false", timeout=20)
        if isinstance(nstats, dict) and "nodes" in nstats:
            nodes_out = []
            for nid, n in (nstats.get("nodes") or {}).items():
                jvm_mem = (n.get("jvm") or {}).get("mem", {})
                jvm_gc = ((n.get("jvm") or {}).get("gc") or {}).get("collectors", {})
                old_gc = jvm_gc.get("old", {})
                young_gc = jvm_gc.get("young", {})
                fs_total = (n.get("fs") or {}).get("total", {})
                os_info = n.get("os") or {}
                cpu = (os_info.get("cpu") or {})
                indices = n.get("indices") or {}
                store = indices.get("store") or {}
                tps = n.get("thread_pool") or {}
                tp_summary = {}
                for pool in ("snapshot", "snapshot_meta", "write", "search", "generic"):
                    p = tps.get(pool) or {}
                    tp_summary[pool] = {
                        "active": p.get("active"),
                        "queue": p.get("queue"),
                        "rejected": p.get("rejected"),
                    }
                nodes_out.append({
                    "name": n.get("name"),
                    "roles": n.get("roles"),
                    "host": n.get("host") or n.get("ip"),
                    "jvm_heap_used_pct": jvm_mem.get("heap_used_percent"),
                    "jvm_heap_used_bytes": jvm_mem.get("heap_used_in_bytes"),
                    "jvm_heap_max_bytes": jvm_mem.get("heap_max_in_bytes"),
                    "gc_old_count": old_gc.get("collection_count"),
                    "gc_old_ms": old_gc.get("collection_time_in_millis"),
                    "gc_young_count": young_gc.get("collection_count"),
                    "gc_young_ms": young_gc.get("collection_time_in_millis"),
                    "fs_total_bytes": fs_total.get("total_in_bytes"),
                    "fs_free_bytes": fs_total.get("free_in_bytes"),
                    "fs_available_bytes": fs_total.get("available_in_bytes"),
                    "cpu_pct": cpu.get("percent"),
                    "load_avg": (os_info.get("cpu") or {}).get("load_average"),
                    "indices_store_bytes": store.get("size_in_bytes"),
                    "thread_pools": tp_summary,
                })
            out["nodes"] = nodes_out
        else:
            out["nodes"] = nstats

    # 4. Snapshot repository details + verification
    if "repository" in sec:
        repo = _get(f"/_snapshot/{config.snapshot_repo}")
        if isinstance(repo, dict):
            rd = (repo.get(config.snapshot_repo) or {})
            out["repository"] = {
                "type": rd.get("type"),
                "settings": rd.get("settings"),
            }

    # 5. Recovery state for any moving shards
    if "recoveries" in sec:
        rec = _get("/_recovery?active_only=true")
        if isinstance(rec, dict):
            active = []
            for idx, payload in rec.items():
                shards = payload.get("shards") or []
                for s in shards:
                    if s.get("stage") in ("DONE", None):
                        continue
                    src = (s.get("source") or {}).get("host")
                    tgt = (s.get("target") or {}).get("host")
                    idx_stats = (s.get("index") or {}).get("size") or {}
                    active.append({
                        "index": idx,
                        "shard": s.get("id"),
                        "type": s.get("type"),
                        "stage": s.get("stage"),
                        "source": src,
                        "target": tgt,
                        "total_bytes": idx_stats.get("total_in_bytes"),
                        "recovered_bytes": idx_stats.get("recovered_in_bytes"),
                        "percent": idx_stats.get("percent"),
                    })
            out["active_recoveries"] = active[:25]
            out["active_recovery_count"] = len(active)

    # 6. Shard allocation summary (counts only — full output is huge)
    if "shards" in sec:
        cat_shards = _get("/_cat/shards?format=json&h=index,shard,prirep,state,node&bytes=b")
        if isinstance(cat_shards, list):
            by_state: dict[str, int] = {}
            unassigned = []
            for sh in cat_shards:
                st = sh.get("state") or "UNKNOWN"
                by_state[st] = by_state.get(st, 0) + 1
                if st == "UNASSIGNED" and len(unassigned) < 10:
                    unassigned.append({k: sh.get(k) for k in ("index", "shard", "prirep")})
            out["shard_state_counts"] = by_state
            out["unassigned_examples"] = unassigned

    return out
