"""Main GUI application for ES Snapshot Monitor."""
from __future__ import annotations

import threading
import time
from typing import List

import customtkinter as ctk

from .config_manager import load_clusters, remove_cluster, get_password, load_presets, toggle_ssl_verify
from .es_client import fetch_cluster_status
from .models import ClusterStatus
from .widgets import ClusterCard, AddClusterDialog

class App(ctk.CTk):
    """Main application window."""

    REFRESH_INTERVAL = 15  # seconds

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

        self.cluster_statuses: List[ClusterStatus] = []
        self._refresh_timer = None
        self._auto_refresh = True
        self._refreshing = False
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

        self.auto_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(
            self.sidebar,
            text="Auto-refresh",
            variable=self.auto_var,
            command=self._toggle_auto_refresh,
        ).grid(row=5, column=0, padx=20, pady=(10, 0), sticky="nw")

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

        self.scroll = ctk.CTkFrame(self.content, fg_color="transparent")
        self.scroll.grid(row=1, column=0, sticky="nsew")
        self.scroll.grid_columnconfigure(0, weight=1)

        # Off-screen buffer used for flicker-free refreshes (double-buffering).
        # We build the next frame's cards in here, then swap it in.
        self._scroll_buffer = ctk.CTkFrame(self.content, fg_color="transparent")
        self._scroll_buffer.grid_columnconfigure(0, weight=1)

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
        for st in results:
            if st.snapshot_stats is None:
                continue
            name = st.config.name
            bytes_now = st.snapshot_stats.processed_bytes
            shards_now = st.snapshot_stats.processed_shards
            current_bps = 0.0
            current_sps = 0.0
            if name in self._last_poll:
                t_prev, bytes_prev, shards_prev = self._last_poll[name]
                dt = now - t_prev
                if dt > 0:
                    if bytes_now > bytes_prev:
                        current_bps = (bytes_now - bytes_prev) / dt
                        st.snapshot_stats.current_speed_bps = current_bps
                    if shards_now > shards_prev:
                        current_sps = (shards_now - shards_prev) / dt
                        st.snapshot_stats.current_shard_rate = current_sps
            self._last_poll[name] = (now, bytes_now, shards_now)

            # Update rolling speed history (keep last 10 min)
            history = self._speed_history.get(name, [])
            # On first poll we don't have a current_bps yet, so seed with avg_speed_bps
            speed_to_store = current_bps if current_bps > 0 else st.snapshot_stats.avg_speed_bps
            if speed_to_store > 0:
                history.append((now, speed_to_store))
            # Prune old samples (> 10 min)
            history = [(t, s) for t, s in history if now - t < 600]
            self._speed_history[name] = history

            if history:
                speeds = [s for _, s in history]
                st.snapshot_stats.window_avg_speed_bps = sum(speeds) / len(speeds)
                st.snapshot_stats.min_speed_bps = min(speeds)
                st.snapshot_stats.max_speed_bps = max(speeds)

            # Shard-rate history (used when byte stats aren't available)
            sr_history = self._shard_rate_history.get(name, [])
            sr_to_store = current_sps if current_sps > 0 else st.snapshot_stats.avg_shard_rate
            if sr_to_store > 0:
                sr_history.append((now, sr_to_store))
            sr_history = [(t, s) for t, s in sr_history if now - t < 600]
            self._shard_rate_history[name] = sr_history

            if sr_history:
                rates = [s for _, s in sr_history]
                st.snapshot_stats.window_avg_shard_rate = sum(rates) / len(rates)
                st.snapshot_stats.min_shard_rate = min(rates)
                st.snapshot_stats.max_shard_rate = max(rates)

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
        # Double-buffered render: build the new content in an off-screen frame,
        # then swap it in. This eliminates the flash where the old cards are
        # destroyed before the new ones appear.
        buf = self._scroll_buffer

        # Clear buffer (it should already be empty between renders, but be safe)
        for widget in buf.winfo_children():
            widget.destroy()

        if not self.cluster_statuses:
            empty = ctk.CTkLabel(
                buf,
                text="No clusters configured.\nClick 'Add Cluster' or 'Load Presets' to get started.",
                font=ctk.CTkFont(size=16),
                text_color=("#999999", "#64748b"),
                justify="center",
            )
            empty.grid(row=0, column=0, pady=80)
        else:
            for i, status in enumerate(self.cluster_statuses):
                history = self._speed_history.get(status.config.name, [])
                card = ClusterCard(
                    buf,
                    status=status,
                    speed_history=history,
                    on_remove=lambda n=status.config.name: self._confirm_remove(n),
                on_edit=lambda s=status: self._open_edit_dialog(s),

        # Swap: old visible frame becomes the new buffer, buffer becomes visible.
        old_visible = self.scroll
        old_visible.grid_forget()
        buf.grid(row=1, column=0, sticky="nsew")
        self.scroll = buf
        self._scroll_buffer = old_visible

        # Tear down the now-hidden old cards after the swap is on screen.
        # Using `after_idle` keeps the destruction off the critical render path.
        self.after_idle(lambda f=old_visible: [w.destroy() for w in f.winfo_children()])

    def _open_add_dialog(self):
        AddClusterDialog(self, on_save=self._trigger_refresh)

    def _open_edit_dialog(self, status: ClusterStatus):
        AddClusterDialog(self, on_save=self._trigger_refresh, existing=status)

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
