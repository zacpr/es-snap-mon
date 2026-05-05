"""Main GUI application for ES Snapshot Monitor."""
from __future__ import annotations

import threading
import time
from dataclasses import replace
from typing import List

import customtkinter as ctk

from .config_manager import load_clusters, remove_cluster, get_password, load_presets, toggle_ssl_verify
from .es_client import fetch_cluster_status, fetch_diagnostics
from .models import ClusterStatus, SnapshotState
from .widgets import ClusterCard, AddClusterDialog, AISettingsDialog, AnalysisDialog, AnalysisScopeDialog


def _icon_path() -> str | None:
    """Return absolute path to the bundled app icon, or None if missing."""
    import os, sys
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidate = os.path.join(base, "es_snap_mon", "data", "icon.png")
    else:
        candidate = os.path.join(os.path.dirname(__file__), "data", "icon.png")
    return candidate if os.path.exists(candidate) else None

class App(ctk.CTk):
    """Main application window."""

    REFRESH_INTERVAL = 15  # seconds

    @staticmethod
    def _job_key(cluster_name: str, snapshot_name: str | None) -> str:
        if snapshot_name:
            return f"{cluster_name}::{snapshot_name}"
        return cluster_name

    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        # Fix Linux blank-window / scaling issues
        self.tk.call("tk", "scaling", 1.0)
        try:
            self.attributes("-alpha", 1.0)
        except Exception:
            pass

        self.title("Elasticsearch Snapshot Monitor")
        self.geometry("1100x750")

        # Set window / taskbar icon if available
        try:
            import tkinter as tk
            ipath = _icon_path()
            if ipath:
                self._app_icon = tk.PhotoImage(file=ipath)
                self.iconphoto(True, self._app_icon)
        except Exception:
            pass

        self.cluster_statuses: List[ClusterStatus] = []
        self._refresh_timer = None
        self._auto_refresh = True
        self._refreshing = False
        self._scenic_mode = False
        self._parallax_test_mode = "auto"  # auto | normal | stampede
        self._parallax_intensity = 1.0  # 0.75 calm | 1.0 normal | 1.35 wild
        self._last_poll: dict[str, tuple[float, int, int]] = {}  # (time, bytes, shards)
        self._speed_history: dict[str, list[tuple[float, float]]] = {}  # name -> [(time, bps), ...]
        self._shard_rate_history: dict[str, list[tuple[float, float]]] = {}  # name -> [(time, shards/sec), ...]

        # Build UI while hidden to avoid blank-window flicker on Linux
        self.withdraw()
        self._build_ui()
        self.update_idletasks()
        self.deiconify()
        self.update()
        self.minsize(900, 600)
        # Secret test hotkey: Ctrl+Shift+P cycles auto/normal/stampede.
        self.bind_all("<Control-Shift-P>", self._cycle_parallax_test_mode)
        # Secret hotkey: Ctrl+Shift+I cycles cinematic intensity.
        self.bind_all("<Control-Shift-I>", self._cycle_parallax_intensity)
        self.lift()
        # Trigger first refresh shortly after window shows
        self.after(800, self._trigger_refresh)

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(5, weight=1)

        ctk.CTkLabel(
            self.sidebar,
            text="ES Snap",
            font=ctk.CTkFont(size=24, weight="bold"),
        ).grid(row=0, column=0, padx=20, pady=(20, 4), sticky="w")

        ctk.CTkLabel(
            self.sidebar,
            text="Snapshot Monitor",
            font=ctk.CTkFont(size=12),
            text_color=("#666666", "#94a3b8"),
        ).grid(row=1, column=0, padx=20, pady=(0, 20), sticky="w")

        self.refresh_btn = ctk.CTkButton(
            self.sidebar,
            text="Refresh Now",
            command=self._trigger_refresh,
        )
        self.refresh_btn.grid(row=2, column=0, padx=20, pady=(0, 10), sticky="ew")

        self.add_btn = ctk.CTkButton(
            self.sidebar,
            text="Add Cluster",
            command=self._open_add_dialog,
        )
        self.add_btn.grid(row=3, column=0, padx=20, pady=(0, 10), sticky="ew")

        self.presets_btn = ctk.CTkButton(
            self.sidebar,
            text="Load Presets",
            fg_color="transparent",
            border_width=2,
            command=self._load_presets_dialog,
        )
        self.presets_btn.grid(row=4, column=0, padx=20, pady=(0, 10), sticky="ew")

        self.analyze_btn = ctk.CTkButton(
            self.sidebar,
            text="Analyze Performance",
            fg_color="#7c3aed",
            hover_color="#6d28d9",
            command=self._analyze_performance,
        )
        self.analyze_btn.grid(row=7, column=0, padx=20, pady=(20, 6), sticky="ew")

        self.ai_settings_btn = ctk.CTkButton(
            self.sidebar,
            text="AI Settings",
            fg_color="transparent",
            border_width=1,
            text_color=("#666", "#94a3b8"),
            command=self._open_ai_settings,
        )
        self.ai_settings_btn.grid(row=8, column=0, padx=20, pady=(0, 10), sticky="ew")

        self.auto_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(
            self.sidebar,
            text="Auto-refresh",
            variable=self.auto_var,
            command=self._toggle_auto_refresh,
        ).grid(row=5, column=0, padx=20, pady=(10, 0), sticky="nw")

        self.scenic_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(
            self.sidebar,
            text="Scenic Motion",
            variable=self.scenic_var,
            command=self._toggle_scenic_mode,
        ).grid(row=6, column=0, padx=20, pady=(8, 0), sticky="nw")

        # Main content
        self.content = ctk.CTkFrame(self, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew", padx=24, pady=(20, 0))
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(1, weight=1)

        self.header = ctk.CTkLabel(
            self.content,
            text="Dashboard",
            font=ctk.CTkFont(size=28, weight="bold"),
        )
        self.header.grid(row=0, column=0, sticky="w", pady=(0, 14))

        self.scroll = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        self.scroll.grid(row=1, column=0, sticky="nsew")
        self.scroll.grid_columnconfigure(0, weight=1)
        # Mouse-wheel scrolling on the whole content area
        try:
            self.scroll._parent_canvas.configure(yscrollincrement=20)
        except Exception:
            pass

        # Cards reused across refreshes — keyed by cluster name so we only
        # rebuild a card's contents when its data changes, instead of tearing
        # down and rebuilding every card frame on every refresh.
        self._card_widgets: dict[str, ClusterCard] = {}
        self._card_fingerprints: dict[str, tuple] = {}
        self._empty_label: ctk.CTkLabel | None = None

        self.spinner = ctk.CTkLabel(
            self.content,
            text="Loading…",
            font=ctk.CTkFont(size=16),
            text_color=("#888888", "#64748b"),
        )

        # Bottom status bar
        self.status_bar = ctk.CTkFrame(self, height=32, corner_radius=0)
        self.status_bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.status_bar.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            self.status_bar,
            text="Ready",
            font=ctk.CTkFont(size=11),
            text_color=("#888888", "#64748b"),
        )
        self.status_label.grid(row=0, column=0, padx=20, pady=6, sticky="w")

    def _toggle_auto_refresh(self):
        self._auto_refresh = self.auto_var.get()
        if self._auto_refresh:
            self._schedule_refresh(self.REFRESH_INTERVAL)
        else:
            self._cancel_refresh()

    def _toggle_scenic_mode(self):
        self._scenic_mode = self.scenic_var.get()
        self._render_cards()

    def _cycle_parallax_test_mode(self, _event=None):
        modes = ["auto", "normal", "stampede"]
        idx = modes.index(self._parallax_test_mode)
        self._parallax_test_mode = modes[(idx + 1) % len(modes)]
        label = {
            "auto": "Parallax test: AUTO",
            "normal": "Parallax test: FORCED NORMAL",
            "stampede": "Parallax test: FORCED STAMPEDE",
        }[self._parallax_test_mode]
        self.status_label.configure(text=label)
        self._render_cards()

    def _cycle_parallax_intensity(self, _event=None):
        levels = [(0.75, "CALM"), (1.0, "NORMAL"), (1.35, "WILD")]
        current = next((i for i, (v, _) in enumerate(levels) if abs(v - self._parallax_intensity) < 1e-6), 1)
        self._parallax_intensity, name = levels[(current + 1) % len(levels)]
        self.status_label.configure(text=f"Parallax intensity: {name}")
        self._render_cards()

    def _schedule_refresh(self, delay: float):
        self._cancel_refresh()
        if self._auto_refresh or delay < 1:
            self._refresh_timer = self.after(int(delay * 1000), self._trigger_refresh)

    def _cancel_refresh(self):
        if self._refresh_timer:
            self.after_cancel(self._refresh_timer)
            self._refresh_timer = None

    def _trigger_refresh(self):
        if self._refreshing:
            return
        self._refreshing = True
        self.status_label.configure(text="Refreshing…")
        self.refresh_btn.configure(state="disabled")

        if not self.cluster_statuses:
            self.spinner.grid(row=2, column=0, pady=40)

        thread = threading.Thread(target=self._fetch_all, daemon=True)
        thread.start()

    def _fetch_all(self):
        configs = load_clusters()
        results = []
        for cfg in configs:
            pwd = get_password(cfg.name)
            if not pwd:
                st = ClusterStatus(config=cfg, reachable=False, error_message="No password stored")
            else:
                st = fetch_cluster_status(cfg, pwd)
            results.append(st)

        self.after(0, lambda: _safe_call(self._on_refresh_done, results))

    def _on_refresh_done(self, results: List[ClusterStatus]):
        now = time.time()

        def _update_rate_windows(key: str, stats) -> None:
            bytes_now = stats.processed_bytes
            shards_now = stats.processed_shards
            current_bps = 0.0
            current_sps = 0.0
            if key in self._last_poll:
                t_prev, bytes_prev, shards_prev = self._last_poll[key]
                dt = now - t_prev
                if dt > 0:
                    if bytes_now > bytes_prev:
                        current_bps = (bytes_now - bytes_prev) / dt
                        stats.current_speed_bps = current_bps
                    if shards_now > shards_prev:
                        current_sps = (shards_now - shards_prev) / dt
                        stats.current_shard_rate = current_sps
            self._last_poll[key] = (now, bytes_now, shards_now)

            # Update rolling speed history (keep last 10 min)
            history = self._speed_history.get(key, [])
            speed_to_store = current_bps if current_bps > 0 else stats.avg_speed_bps
            if speed_to_store > 0:
                history.append((now, speed_to_store))
            history = [(t, s) for t, s in history if now - t < 600]
            self._speed_history[key] = history

            if history:
                speeds = [s for _, s in history]
                stats.window_avg_speed_bps = sum(speeds) / len(speeds)
                stats.min_speed_bps = min(speeds)
                stats.max_speed_bps = max(speeds)

            # Shard-rate history (used when byte stats aren't available)
            sr_history = self._shard_rate_history.get(key, [])
            sr_to_store = current_sps if current_sps > 0 else stats.avg_shard_rate
            if sr_to_store > 0:
                sr_history.append((now, sr_to_store))
            sr_history = [(t, s) for t, s in sr_history if now - t < 600]
            self._shard_rate_history[key] = sr_history

            if sr_history:
                rates = [s for _, s in sr_history]
                stats.window_avg_shard_rate = sum(rates) / len(rates)
                stats.min_shard_rate = min(rates)
                stats.max_shard_rate = max(rates)

        for st in results:
            if st.snapshot_jobs:
                for job in st.snapshot_jobs:
                    if job.stats is None:
                        continue
                    k = self._job_key(st.config.name, job.info.name)
                    _update_rate_windows(k, job.stats)
                # Keep primary stats in sync with the corresponding job stats
                # so non-split render paths stay consistent.
                if st.snapshot_info is not None and st.snapshot_stats is not None:
                    for job in st.snapshot_jobs:
                        if job.info.name == st.snapshot_info.name and job.stats is not None:
                            st.snapshot_stats = job.stats
                            break
            elif st.snapshot_stats is not None:
                k = self._job_key(st.config.name, st.snapshot_info.name if st.snapshot_info else None)
                _update_rate_windows(k, st.snapshot_stats)

        self.cluster_statuses = results
        self._refreshing = False
        self.spinner.grid_forget()
        self.refresh_btn.configure(state="normal")
        self._render_cards()

        reachable = sum(1 for s in results if s.reachable)
        self.status_label.configure(
            text=f"{reachable}/{len(results)} clusters reachable  •  {time.strftime('%H:%M:%S')}"
        )

        if self._auto_refresh:
            self._schedule_refresh(self.REFRESH_INTERVAL)

    def _render_cards(self):
        # Reuse existing card widgets; only refresh content for clusters whose
        # data actually changed. Add cards for new clusters, remove stale ones.

        all_active = bool(self.cluster_statuses) and all(
            s.snapshot_info is not None and s.snapshot_info.state == SnapshotState.IN_PROGRESS
            for s in self.cluster_statuses
        )
        if self._parallax_test_mode == "normal":
            all_active = False
        elif self._parallax_test_mode == "stampede":
            all_active = True

        # Empty state
        if not self.cluster_statuses:
            for card in self._card_widgets.values():
                card.destroy()
            self._card_widgets.clear()
            self._card_fingerprints.clear()
            if self._empty_label is None:
                self._empty_label = ctk.CTkLabel(
                    self.scroll,
                    text="No clusters configured.\nClick 'Add Cluster' or 'Load Presets' to get started.",
                    font=ctk.CTkFont(size=16),
                    text_color=("#999999", "#64748b"),
                    justify="center",
                )
                self._empty_label.grid(row=0, column=0, pady=80)
            return

        # Drop empty-state label if it was showing
        if self._empty_label is not None:
            self._empty_label.destroy()
            self._empty_label = None

        rows: list[tuple[str, ClusterStatus, str, str]] = []
        for status in self.cluster_statuses:
            name = status.config.name
            if status.snapshot_jobs and len(status.snapshot_jobs) > 1:
                for job in status.snapshot_jobs:
                    row_key = f"{name}::{job.info.name}"
                    row_status = replace(status, snapshot_info=job.info, snapshot_stats=job.stats)
                    rows.append((row_key, row_status, name, row_key))
            else:
                hist_key = self._job_key(name, status.snapshot_info.name if status.snapshot_info else None)
                rows.append((name, status, name, hist_key))

        seen: set[str] = set()
        for i, (row_key, status, base_name, hist_key) in enumerate(rows):
            seen.add(row_key)
            history = self._speed_history.get(hist_key, [])
            fp = self._card_fingerprint(
                status,
                history,
                self._scenic_mode,
                all_active,
                self._parallax_intensity,
            )
            card = self._card_widgets.get(row_key)
            if card is None:
                card = ClusterCard(
                    self.scroll,
                    status=status,
                    speed_history=history,
                    scenic_mode=self._scenic_mode,
                    frenzy_mode=all_active,
                    parallax_intensity=self._parallax_intensity,
                    on_remove=lambda n=base_name: self._confirm_remove(n),
                    on_edit=lambda s=status: self._open_edit_dialog(s),
                )
                self._card_widgets[row_key] = card
                self._card_fingerprints[row_key] = fp
            else:
                # Keep callbacks bound to the latest status object
                card.on_edit = lambda s=status: self._open_edit_dialog(s)
                card.on_remove = lambda n=base_name: self._confirm_remove(n)
                if self._card_fingerprints.get(row_key) != fp:
                    card.refresh(
                        status,
                        history,
                        scenic_mode=self._scenic_mode,
                        frenzy_mode=all_active,
                        parallax_intensity=self._parallax_intensity,
                    )
                    self._card_fingerprints[row_key] = fp
            card.grid(row=i, column=0, sticky="ew", padx=8, pady=6)

        # Remove cards for clusters that no longer exist
        for stale in [n for n in self._card_widgets if n not in seen]:
            self._card_widgets[stale].destroy()
            del self._card_widgets[stale]
            self._card_fingerprints.pop(stale, None)

    @staticmethod
    def _card_fingerprint(
        status: ClusterStatus,
        history: list[tuple[float, float]],
        scenic: bool,
        frenzy: bool,
        parallax_intensity: float,
    ) -> tuple:
        """Compact signature of fields that materially affect rendered card UI."""
        s = status.snapshot_info
        st = status.snapshot_stats
        hist_tail = tuple(int(v) for _, v in history[-10:])
        return (
            status.reachable,
            status.error_message or "",
            s.name if s else None,
            s.state.value if s else None,
            s.shards_successful if s else None,
            s.shards_total if s else None,
            s.shards_failed if s else None,
            status.active_snapshot_count,
            tuple(status.active_snapshot_names[:4]),
            round(st.progress_pct, 2) if st else None,
            st.processed_files if st else None,
            st.total_files if st else None,
            int(st.processed_bytes) if st else None,
            int(st.total_bytes) if st else None,
            int(st.current_speed_bps) if st else None,
            int(st.avg_speed_bps) if st else None,
            status.slm_last_run or "",
            status.slm_next_run or "",
            scenic,
            frenzy,
            round(parallax_intensity, 2),
            hist_tail,
        )

    def _open_add_dialog(self):
        AddClusterDialog(self, on_save=self._trigger_refresh)

    def _open_edit_dialog(self, status: ClusterStatus):
        AddClusterDialog(self, on_save=self._trigger_refresh, existing=status)

    def _open_ai_settings(self):
        AISettingsDialog(self)

    def _analyze_performance(self):
        from .ai_client import get_ai_token

        if not get_ai_token():
            # No token yet — open settings first.
            AISettingsDialog(self, on_save=self._analyze_performance)
            return

        if not self.cluster_statuses:
            self.status_label.configure(text="Nothing to analyze — refresh clusters first.")
            return

        # Let the user choose which clusters + which diagnostic sections to send.
        AnalysisScopeDialog(
            self,
            cluster_statuses=self.cluster_statuses,
            on_confirm=self._begin_analysis,
        )

    def _begin_analysis(self, selected_clusters: set[str], selected_sections: set[str]):
        dlg = AnalysisDialog(self, title="Performance Analysis")
        dlg.set_text(
            f"Collecting diagnostics from {len(selected_clusters)} cluster(s) — "
            f"sections: {', '.join(sorted(selected_sections)) or '(none)'}\n"
            "This usually takes a few seconds.",
            header="Gathering diagnostics",
        )
        threading.Thread(
            target=self._run_analysis,
            args=(dlg, selected_clusters, selected_sections),
            daemon=True,
        ).start()

    def _run_analysis(self, dlg, selected_clusters: set[str], selected_sections: set[str]):
        import json
        import sys
        import traceback
        from .ai_client import analyze, load_ai_settings

        # 1. Collect diagnostics for every selected reachable cluster (in parallel).
        diagnostics: dict[str, dict] = {}
        threads = []
        results: dict[str, dict] = {}
        lock = threading.Lock()

        def worker(status: ClusterStatus):
            if not status.reachable:
                with lock:
                    results[status.config.name] = {
                        "skipped": True,
                        "reason": status.error_message or "unreachable",
                    }
                return
            pwd = get_password(status.config.name) or ""
            try:
                diag = fetch_diagnostics(status.config, pwd, sections=selected_sections)
            except Exception as e:
                print(f"[es-snap-mon] diagnostics error for {status.config.name}: {e}", file=sys.stderr)
                traceback.print_exc()
                diag = {"_error": str(e)}
            with lock:
                results[status.config.name] = diag

        targets = [s for s in self.cluster_statuses if s.config.name in selected_clusters]
        for st in targets:
            t = threading.Thread(target=worker, args=(st,), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout=30)
        diagnostics = results

        # 2. Update dialog so the user knows we're now talking to the model.
        self.after(0, lambda: dlg.set_text(
            "Diagnostics collected. Sending to model — this can take a few seconds…",
            header="Analyzing",
        ))

        # 3. Build prompt (snapshot stats + diagnostics) and send.
        try:
            prompt = self._build_analysis_prompt(diagnostics, selected_clusters)
        except Exception as e:
            print("[es-snap-mon] failed to build analysis prompt:", e, file=sys.stderr)
            traceback.print_exc()
            self.after(0, lambda: dlg.set_error(
                f"Failed to build analysis prompt: {e}\n\n"
                "Diagnostics collected:\n"
                + json.dumps(diagnostics, indent=2, default=str)[:2000]
            ))
            return

        # Rough token estimate: GPT-family tokenizers average ~4 chars/token.
        approx_tokens = max(1, len(prompt) // 4)
        print(
            f"[es-snap-mon] prompt: {len(prompt):,} chars  ~{approx_tokens:,} tokens",
            file=sys.stderr,
        )
        self.after(0, lambda t=approx_tokens, c=len(prompt): dlg.set_text(
            f"Diagnostics collected. Sending to model…\n\n"
            f"Prompt size: {c:,} chars  (~{t:,} tokens)",
            header="Analyzing",
        ))

        # Cap prompt size — GitHub Models has token limits.
        if len(prompt) > 60000:
            print(f"[es-snap-mon] truncating prompt {len(prompt)} -> 60000", file=sys.stderr)
            prompt = prompt[:60000] + "\n\n... (truncated)"
        try:
            reply = analyze(
                prompt,
                system=(
                    "You are an Elasticsearch snapshot + cluster performance analyst. "
                    "You will receive live snapshot stats AND deeper cluster/node "
                    "diagnostics (heap, GC, FS, CPU, thread pools, recoveries, "
                    "shard state) for one or more clusters. Identify bottlenecks "
                    "(saturated thread pools, high heap pressure, slow disks, hot "
                    "nodes, repository/network throttling, unassigned shards), "
                    "rank findings by impact, and propose concrete tuning steps "
                    "(max_snapshot_bytes_per_sec, repository chunk size, "
                    "concurrent_streams, snapshot/snapshot_meta pool sizing, "
                    "indices.recovery.max_bytes_per_sec, instance/disk class, "
                    "network MTU). Use short headings + bullet lists. Be concise."
                ),
            )
        except Exception as e:
            print("[es-snap-mon] AI request failed:", e, file=sys.stderr)
            traceback.print_exc()
            err_msg = (
                f"{e}\n\n"
                f"Endpoint: {load_ai_settings().base_url}\n"
                f"Model: {load_ai_settings().model}\n"
                f"Prompt size: {len(prompt):,} chars\n\n"
                "Tips:\n"
                " • 401/403 — token missing the 'Models' permission, or expired.\n"
                " • 404 model_not_found — try a different model in AI Settings (e.g. openai/gpt-4o-mini).\n"
                " • 413/context length — prompt too large; fewer clusters or shorter run.\n"
                " • Connection errors — check network / proxy."
            )
            self.after(0, lambda m=err_msg: dlg.set_error(m))
            return

        model = load_ai_settings().model
        self.after(0, lambda: dlg.set_text(
            reply
            + f"\n\n—\nPrompt size: {len(prompt):,} chars  (~{approx_tokens:,} tokens)",
            header=f"Analysis ({model})",
        ))

    def _build_analysis_prompt(self, diagnostics: dict | None = None, selected_clusters: set[str] | None = None) -> str:
        import json
        diagnostics = diagnostics or {}
        lines = [
            "Analyze the following Elasticsearch snapshot stats and cluster diagnostics. "
            "Highlight slow clusters, stalled shards, throughput issues, heap/GC "
            "pressure, saturated thread pools, and suggest concrete tuning. "
            "Be concise — short headings + bullets.",
            "",
        ]
        for s in self.cluster_statuses:
            cfg = s.config
            if selected_clusters is not None and cfg.name not in selected_clusters:
                continue
            lines.append(f"## Cluster: {cfg.name}")
            lines.append(f"- host: {cfg.host}")
            lines.append(f"- repo: {cfg.snapshot_repo}")
            lines.append(f"- reachable: {s.reachable}")
            if s.error_message:
                lines.append(f"- error: {s.error_message}")
            snap = s.snapshot_info
            if snap:
                lines.append(
                    f"- snapshot: {snap.name}  state={snap.state.value}  "
                    f"shards={snap.shards_successful}/{snap.shards_total} failed={snap.shards_failed}"
                )
                lines.append(f"- duration_ms: {snap.duration_ms}")
            stats = s.snapshot_stats
            if stats:
                lines.append(
                    f"- progress: {stats.progress_pct:.2f}%  "
                    f"data: {stats.processed_human}/{stats.total_human}  "
                    f"files: {stats.processed_files}/{stats.total_files}"
                )
                lines.append(
                    f"- speed: cur={stats.current_speed_human} avg={stats.avg_speed_human} "
                    f"window_avg_bps={stats.window_avg_speed_bps:.0f} "
                    f"min_bps={stats.min_speed_bps:.0f} max_bps={stats.max_speed_bps:.0f}"
                )
                lines.append(
                    f"- shard_rate: cur={stats.current_shard_rate:.3f}/s "
                    f"avg={stats.avg_shard_rate:.3f}/s "
                    f"window_avg={stats.window_avg_shard_rate:.3f}/s"
                )
                if stats.eta_human and stats.eta_human != "—":
                    lines.append(f"- eta: {stats.eta_human}  completion: {stats.completion_human or '—'}")
            if s.slm_last_run:
                lines.append(f"- slm_last: {s.slm_last_run}")
            if s.slm_next_run:
                lines.append(f"- slm_next: {s.slm_next_run}")

            diag = diagnostics.get(cfg.name)
            if diag:
                lines.append("- diagnostics:")
                # Compact JSON keeps token count down vs. pretty-printed.
                lines.append("```json")
                lines.append(json.dumps(diag, separators=(",", ":"), default=str))
                lines.append("```")
            lines.append("")
        return "\n".join(lines)

    def _do_toggle_ssl(self, name: str):
        new_val = toggle_ssl_verify(name)
        self.status_label.configure(text=f"SSL verify = {new_val} for {name}")
        self._trigger_refresh()

    def _load_presets_dialog(self):
        import tkinter as tk
        dialog = tk.Toplevel(self)
        dialog.title("Load Presets")
        dialog.geometry("400x260")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.configure(bg="#2b2b2b")

        frame = ctk.CTkFrame(dialog, corner_radius=0)
        frame.pack(fill="both", expand=True)

        ctk.CTkLabel(
            frame,
            text="Load Default Clusters",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(pady=(20, 8))

        ctk.CTkLabel(
            frame,
            text="This will add APAC, AMER, and EMEA production clusters.\nEnter the shared password to store it securely.",
            font=ctk.CTkFont(size=12),
            text_color=("#666666", "#94a3b8"),
            justify="center",
        ).pack(pady=(0, 12))

        pwd_entry = ctk.CTkEntry(frame, placeholder_text="Password", show="•")
        pwd_entry.pack(fill="x", padx=40, pady=(0, 8))

        ssl_var = tk.IntVar(value=1)
        ctk.CTkCheckBox(
            frame,
            text="Verify SSL certificates",
            variable=ssl_var,
            onvalue=1,
            offvalue=0,
        ).pack(anchor="w", padx=40, pady=(0, 12))

        btn_frame = ctk.CTkFrame(frame)
        btn_frame.pack(pady=(0, 16))

        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            width=80,
            fg_color="#555555",
            command=dialog.destroy,
        ).pack(side="left", padx=4)

        def do_load():
            load_presets(password=pwd_entry.get(), verify_ssl=bool(ssl_var.get()))
            dialog.destroy()
            self._trigger_refresh()

        ctk.CTkButton(
            btn_frame,
            text="Load",
            width=80,
            command=do_load,
        ).pack(side="left", padx=4)

        dialog.lift()
        dialog.focus_force()
        dialog.grab_set()

    def _confirm_remove(self, name: str):
        import tkinter as tk
        dialog = tk.Toplevel(self)
        dialog.title("Remove Cluster")
        dialog.geometry("360x160")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.configure(bg="#2b2b2b")

        frame = ctk.CTkFrame(dialog, corner_radius=0)
        frame.pack(fill="both", expand=True)

        ctk.CTkLabel(
            frame,
            text=f'Remove "{name}"?',
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(pady=(20, 8))

        ctk.CTkLabel(
            frame,
            text="This will delete the saved configuration and password.",
            font=ctk.CTkFont(size=12),
            text_color=("#666666", "#94a3b8"),
        ).pack(pady=(0, 16))

        btn_frame = ctk.CTkFrame(frame)
        btn_frame.pack(pady=(0, 16))

        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            width=80,
            fg_color="#555555",
            command=dialog.destroy,
        ).pack(side="left", padx=4)

        def do_remove():
            remove_cluster(name)
            dialog.destroy()
            self._trigger_refresh()

        ctk.CTkButton(
            btn_frame,
            text="Remove",
            width=80,
            fg_color="#e74c3c",
            hover_color="#c0392b",
            command=do_remove,
        ).pack(side="left", padx=4)

        dialog.lift()
        dialog.focus_force()
        dialog.grab_set()

    def run(self):
        self.mainloop()


def _safe_call(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        print(f"UI error: {exc}")
