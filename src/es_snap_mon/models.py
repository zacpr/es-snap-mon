"""Data models for ES snapshot monitoring."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SnapshotState(Enum):
    """Possible states of a snapshot operation."""
    SUCCESS = "SUCCESS"
    IN_PROGRESS = "IN_PROGRESS"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    INCOMPATIBLE = "INCOMPATIBLE"
    MISSING = "MISSING"
    WAITING = "WAITING"
    UNKNOWN = "UNKNOWN"


@dataclass
class ClusterConfig:
    """User-configured cluster connection details."""
    name: str
    host: str
    snapshot_repo: str
    slm_policy: str
    username: str
    verify_ssl: bool = True
    # Optional CA bundle path. When set, used instead of `verify_ssl=True`
    # to validate the cluster's TLS certificate against a custom CA.
    # Special value "bundled" means "use the CA shipped inside this package".
    ca_cert: Optional[str] = None


@dataclass
class SnapshotInfo:
    """Parsed snapshot status from _snapshot/<repo>/_current."""
    name: str
    state: SnapshotState
    start_time_ms: int
    end_time_ms: Optional[int] = None
    duration_ms: int = 0
    indices_count: int = 0
    shards_total: int = 0
    shards_failed: int = 0
    shards_successful: int = 0


@dataclass
class SnapshotStats:
    """Human-readable stats derived from a snapshot response."""
    progress_pct: float = 0.0
    processed_bytes: int = 0
    total_bytes: int = 0
    processed_files: int = 0
    total_files: int = 0
    start_time: float = field(default_factory=time.time)
    current_speed_bps: float = 0.0
    avg_speed_bps: float = 0.0
    has_byte_stats: bool = False
    processed_shards: int = 0
    total_shards: int = 0
    current_shard_rate: float = 0.0  # shards per second
    avg_shard_rate: float = 0.0
    # Rolling-window stats (populated by the UI layer)
    window_avg_speed_bps: float = 0.0
    min_speed_bps: float = 0.0
    max_speed_bps: float = 0.0
    # Shard-rate rolling window (used when byte stats aren't available)
    window_avg_shard_rate: float = 0.0
    min_shard_rate: float = 0.0
    max_shard_rate: float = 0.0

    @property
    def processed_human(self) -> str:
        return _bytes_to_human(self.processed_bytes)

    @property
    def total_human(self) -> str:
        return _bytes_to_human(self.total_bytes)

    @property
    def eta_seconds(self) -> Optional[float]:
        if self.progress_pct >= 100:
            return None

        # Bytes-based ETA is the most accurate. Prefer the rolling-window
        # speed (smoother), fall back to lifetime average, then to wall-clock
        # extrapolation from progress %.
        remaining_bytes = self.total_bytes - self.processed_bytes
        if remaining_bytes > 0:
            speed = self.window_avg_speed_bps or self.avg_speed_bps
            if speed > 0:
                return remaining_bytes / speed

        # Shard-based ETA when no byte stats are available.
        remaining_shards = self.total_shards - self.processed_shards
        if remaining_shards > 0:
            sps = self.window_avg_shard_rate or self.avg_shard_rate
            if sps > 0:
                return remaining_shards / sps

        # Last resort: extrapolate from progress fraction
        if self.progress_pct > 0:
            elapsed = time.time() - self.start_time
            if elapsed > 0:
                total_est = elapsed / (self.progress_pct / 100)
                return max(0, total_est - elapsed)
        return None

    @property
    def eta_human(self) -> str:
        eta = self.eta_seconds
        if eta is None:
            return "—"
        return _seconds_to_human(int(eta))

    @property
    def completion_human(self) -> str:
        """Human-readable completion timestamp like 'Tue 7:30 AM' or 'Today 11:45 PM'."""
        eta = self.eta_seconds
        if eta is None:
            return ""
        from datetime import datetime, timedelta
        target = datetime.now().astimezone() + timedelta(seconds=eta)
        now = datetime.now().astimezone()
        days_ahead = (target.date() - now.date()).days
        time_str = target.strftime("%-I:%M %p")
        if days_ahead == 0:
            return f"~ Today {time_str}"
        if days_ahead == 1:
            return f"~ Tomorrow {time_str}"
        if days_ahead < 7:
            return f"~ {target.strftime('%A')} {time_str}"
        return f"~ {target.strftime('%a %b %d')} {time_str}"

    @property
    def current_speed_human(self) -> str:
        # Prefer live byte speed, fall back to average byte speed on first poll
        speed = self.current_speed_bps if self.current_speed_bps > 0 else self.avg_speed_bps
        if speed > 0:
            return _speed_to_human(speed)
        # Last resort: shard rate
        if self.current_shard_rate > 0:
            return _shard_rate_to_human(self.current_shard_rate)
        if self.avg_shard_rate > 0:
            return _shard_rate_to_human(self.avg_shard_rate)
        return "—"

    @property
    def avg_speed_human(self) -> str:
        if self.avg_speed_bps > 0:
            return _speed_to_human(self.avg_speed_bps)
        if self.avg_shard_rate > 0:
            return _shard_rate_to_human(self.avg_shard_rate)
        return "—"

    @property
    def window_avg_speed_human(self) -> str:
        if self.window_avg_speed_bps > 0:
            return _speed_to_human(self.window_avg_speed_bps)
        if self.window_avg_shard_rate > 0:
            return _shard_rate_to_human(self.window_avg_shard_rate)
        return "—"

    @property
    def min_speed_human(self) -> str:
        if self.min_speed_bps > 0:
            return _speed_to_human(self.min_speed_bps)
        if self.min_shard_rate > 0:
            return _shard_rate_to_human(self.min_shard_rate)
        return "—"

    @property
    def max_speed_human(self) -> str:
        if self.max_speed_bps > 0:
            return _speed_to_human(self.max_speed_bps)
        if self.max_shard_rate > 0:
            return _shard_rate_to_human(self.max_shard_rate)
        return "—"


@dataclass
class ClusterStatus:
    """Aggregated status for display on the dashboard."""
    config: ClusterConfig
    reachable: bool = False
    error_message: Optional[str] = None
    snapshot_info: Optional[SnapshotInfo] = None
    snapshot_stats: Optional[SnapshotStats] = None
    slm_last_run: Optional[str] = None
    slm_next_run: Optional[str] = None
    slm_in_progress: bool = False


def _bytes_to_human(value: int) -> str:
    """Convert bytes to human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if abs(value) < 1024.0:
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{value:.2f} EB"


def _speed_to_human(bps: float) -> str:
    """Convert bytes-per-second to human-readable speed."""
    if bps <= 0:
        return "—"
    return f"{_bytes_to_human(int(bps))}/s"


def _shard_rate_to_human(sps: float) -> str:
    """Convert shards-per-second to human-readable rate."""
    if sps <= 0:
        return "—"
    if sps < 1:
        return f"{sps * 60:.1f} shards/min"
    return f"{sps:.1f} shards/s"


def _seconds_to_human(seconds: int) -> str:
    """Convert seconds to human-readable duration."""
    if seconds < 60:
        return f"{seconds}s"
    mins, secs = divmod(seconds, 60)
    if mins < 60:
        return f"{mins}m {secs}s"
    hrs, mins = divmod(mins, 60)
    if hrs < 24:
        return f"{hrs}h {mins}m"
    days, hrs = divmod(hrs, 24)
    return f"{days}d {hrs}h"
