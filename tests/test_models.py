"""Unit tests for data models and utilities."""
import pytest
from es_snap_mon.models import _bytes_to_human, _seconds_to_human, SnapshotState, SnapshotStats


def test_bytes_to_human():
    assert _bytes_to_human(512) == "512.00 B"
    assert _bytes_to_human(1536) == "1.50 KB"
    assert _bytes_to_human(1024 * 1024 * 2.5) == "2.50 MB"
    assert _bytes_to_human(1024 ** 4 * 3) == "3.00 TB"


def test_seconds_to_human():
    assert _seconds_to_human(45) == "45s"
    assert _seconds_to_human(125) == "2m 5s"
    assert _seconds_to_human(3665) == "1h 1m"
    assert _seconds_to_human(90061) == "1d 1h"


def test_snapshot_stats_progress():
    stats = SnapshotStats(
        progress_pct=50.0,
        processed_bytes=536870912,
        total_bytes=1073741824,
        processed_files=100,
        total_files=200,
    )
    assert stats.processed_human == "512.00 MB"
    assert stats.total_human == "1.00 GB"
    assert stats.progress_pct == 50.0


def test_snapshot_state_values():
    assert SnapshotState.SUCCESS.value == "SUCCESS"
    assert SnapshotState.IN_PROGRESS.value == "IN_PROGRESS"
