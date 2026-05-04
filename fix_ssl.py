#!/usr/bin/env python3
"""One-shot script to disable SSL verification for all saved clusters."""
from es_snap_mon.config_manager import load_clusters, save_clusters

clusters = load_clusters()
for c in clusters:
    c.verify_ssl = False
save_clusters(clusters)
print(f"SSL verification disabled for {len(clusters)} cluster(s).")
