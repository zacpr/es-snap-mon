"""Custom UI widgets for the ES Snapshot Monitor."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser

import customtkinter as ctk

from .models import ClusterStatus, SnapshotState


def _clean_env() -> dict:
    """Return an env dict safe for spawning system GUI tools.

    PyInstaller injects LD_LIBRARY_PATH (Linux) and DYLD_LIBRARY_PATH
    (macOS) pointing at its bundled libs (libssl, libcrypto, etc.).
    Those break system commands like kde-open, xdg-open, gio open, etc.
    Strip those vars and restore the originals captured at startup.
    """
    env = os.environ.copy()
    for key in (
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
        "DYLD_LIBRARY_PATH",
        "DYLD_INSERT_LIBRARIES",
        "PYTHONPATH",
        "PYTHONHOME",
    ):
        orig = env.get(f"{key}_ORIG")
        if orig is not None:
            env[key] = orig
        else:
            env.pop(key, None)
    return env


def _open_url(url: str) -> bool:
    """Open a URL in the user's browser, robust to PyInstaller envs."""
    if sys.platform.startswith("linux"):
        env = _clean_env()
        for cmd in (["xdg-open", url], ["gio", "open", url], ["kde-open", url], ["kde-open5", url]):
            try:
                proc = subprocess.Popen(
                    cmd,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except FileNotFoundError:
                continue
            except Exception:
                continue
            # Give it a brief moment to fail (xdg-open exits 0 on success).
            try:
                rc = proc.wait(timeout=1.5)
                if rc == 0:
                    return True
                # Non-zero exit = try the next opener
            except subprocess.TimeoutExpired:
                # Still running = it almost certainly handed off to a browser
                return True
        # Fall through to webbrowser as a last resort
    try:
        return bool(webbrowser.open(url, new=2))
    except Exception:
        return False


class GradientProgressBar(ctk.CTkFrame):
    """A progress bar that renders a smooth multi-color horizontal gradient."""

    _GRADIENT_STOPS = [
        (0.0, "#e74c3c"),   # red
        (0.25, "#f39c12"),  # orange
        (0.5, "#f1c40f"),   # yellow
        (0.75, "#2ecc71"),  # green
        (1.0, "#3498db"),   # blue
    ]

    def __init__(self, master, height: int = 16, value: float = 0.0, **kwargs):
        super().__init__(master, height=height, **kwargs)
        self.value = max(0.0, min(1.0, value))
        self._bar_height = height
        self._canvas = tk.Canvas(
            self,
            height=height,
            highlightthickness=0,
            bg=self._get_bg_color(),
        )
        self._canvas.pack(fill="x", expand=True)
        self.bind("<Configure>", lambda e: self._draw())
        self.after(50, self._draw)

    def _get_bg_color(self):
        # Match dark card background
        return "#1e293b"

    def set(self, value: float):
        self.value = max(0.0, min(1.0, value))
        self._draw()

    def _hex_to_rgb(self, hex_color: str):
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))

    def _rgb_to_hex(self, r: int, g: int, b: int):
        return f"#{r:02x}{g:02x}{b:02x}"

    def _lerp_color(self, c1, c2, t: float):
        return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))

    def _color_at(self, pos: float):
        """Get interpolated color at position 0-1 across gradient stops."""
        stops = self._GRADIENT_STOPS
        if pos <= 0:
            return stops[0][1]
        if pos >= 1:
            return stops[-1][1]
        for i in range(len(stops) - 1):
            p1, c1 = stops[i]
            p2, c2 = stops[i + 1]
            if p1 <= pos <= p2:
                t = (pos - p1) / (p2 - p1) if p2 != p1 else 0
                rgb = self._lerp_color(self._hex_to_rgb(c1), self._hex_to_rgb(c2), t)
                return self._rgb_to_hex(*rgb)
        return stops[-1][1]

    def _draw(self, **kwargs):
        self._canvas.delete("all")
        width = self._canvas.winfo_width()
        if width < 2:
            self.after(50, self._draw)
            return

        h = self._bar_height
        r = h // 2

        # Background track (rounded)
        self._canvas.create_polygon(
            self._round_rect_points(0, 0, width, h, r),
            smooth=True, fill="#334155", outline="",
        )

        fill_width = int(width * self.value)
        if fill_width < 2:
            return

        # Smooth gradient: one vertical line per pixel
        for x in range(fill_width):
            color = self._color_at(x / max(fill_width - 1, 1))
            self._canvas.create_line(x, 0, x, h, fill=color, width=1)

        # Subtle top highlight for depth (stipple gives a nice translucent effect)
        try:
            hl_w = max(0, fill_width - r)
            if hl_w > 4:
                self._canvas.create_line(
                    r, 1, hl_w, 1,
                    fill="#ffffff", width=1, stipple="gray50",
                )
        except Exception:
            pass

    def _round_rect_points(self, x1, y1, x2, y2, r):
        """Return polygon points for a rounded rectangle."""
        return [
            x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
        ]


class MiniSparkline(ctk.CTkFrame):
    """A tiny filled line chart for speed history."""

    def __init__(self, master, data: list[tuple[float, float]], height: int = 50, **kwargs):
        super().__init__(master, height=height, **kwargs)
        self.data = data  # [(timestamp, value), ...]
        self._chart_h = height
        self._canvas = tk.Canvas(
            self,
            height=height,
            highlightthickness=0,
            bg=self._get_bg_color(),
        )
        self._canvas.pack(fill="x", expand=True)
        self.bind("<Configure>", lambda e: self._draw())
        self.after(50, self._draw)

    def _get_bg_color(self):
        return "#1e293b"

    def set_data(self, data: list[tuple[float, float]]):
        self.data = data
        self._draw()

    def _draw(self, **kwargs):
        self._canvas.delete("all")
        w = self._canvas.winfo_width()
        if w < 2 or len(self.data) < 1:
            self.after(50, self._draw)
            return

        h = self._chart_h
        pad = 4

        # Duplicate single point so we have something to draw
        data = self.data if len(self.data) > 1 else [self.data[0], self.data[0]]

        values = [v for _, v in data]
        vmin = min(values) * 0.95 if min(values) > 0 else 0
        vmax = max(values) * 1.05 if max(values) > 0 else 1
        if vmax == vmin:
            vmax = vmin + 1

        times = [t for t, _ in data]
        tmin = times[0]
        tmax = times[-1]
        if tmax == tmin:
            tmax = tmin + 1

        def tx(t):
            return pad + (t - tmin) / (tmax - tmin) * (w - pad * 2)

        def ty(v):
            return h - pad - (v - vmin) / (vmax - vmin) * (h - pad * 2)

        # Subtle grid lines
        for frac in (0.25, 0.5, 0.75):
            gy = h - pad - frac * (h - pad * 2)
            self._canvas.create_line(pad, gy, w - pad, gy, fill="#334155", width=1)

        # Build polygon for filled area
        points = []
        for t, v in data:
            points.extend([tx(t), ty(v)])
        # Close the polygon at the bottom
        points.extend([tx(data[-1][0]), h - pad, tx(data[0][0]), h - pad])

        self._canvas.create_polygon(points, fill="#1e3a5f", outline="", smooth=True)

        # Line on top
        line_points = []
        for t, v in data:
            line_points.extend([tx(t), ty(v)])
        self._canvas.create_line(line_points, fill="#3498db", width=2, smooth=True)

        # Dot at the latest point (use original data so it sits on the right edge when duplicated)
        self._canvas.create_oval(
            tx(self.data[-1][0]) - 3, ty(self.data[-1][1]) - 3,
            tx(self.data[-1][0]) + 3, ty(self.data[-1][1]) + 3,
            fill="#3498db", outline="#ffffff", width=1,
        )

        # Min / max labels
        self._canvas.create_text(
            w - pad, pad + 6, text=f"{self._fmt(vmax)}",
            anchor="ne", fill="#94a3b8", font=("Helvetica", 8),
        )
        self._canvas.create_text(
            w - pad, h - pad - 6, text=f"{self._fmt(vmin)}",
            anchor="se", fill="#94a3b8", font=("Helvetica", 8),
        )

    @staticmethod
    def _fmt(bps: float) -> str:
        if bps >= 1024 * 1024 * 1024:
            return f"{bps / (1024 ** 3):.1f} GB/s"
        if bps >= 1024 * 1024:
            return f"{bps / (1024 ** 2):.1f} MB/s"
        if bps >= 1024:
            return f"{bps / 1024:.1f} KB/s"
        return f"{bps:.0f} B/s"


class ClusterCard(ctk.CTkFrame):
    """A dashboard card showing status for a single cluster."""

    _STATE_COLORS = {
        SnapshotState.SUCCESS: ("#2ecc71", "#27ae60"),
        SnapshotState.IN_PROGRESS: ("#3498db", "#2980b9"),
        SnapshotState.FAILED: ("#e74c3c", "#c0392b"),
        SnapshotState.PARTIAL: ("#f39c12", "#d68910"),
        SnapshotState.UNKNOWN: ("#95a5a6", "#7f8c8d"),
        SnapshotState.WAITING: ("#9b59b6", "#8e44ad"),
    }

    def __init__(self, master, status: ClusterStatus, speed_history=None, on_remove=None, on_edit=None, on_toggle_ssl=None):
        super().__init__(master, corner_radius=12, fg_color=("#f0f0f0", "#1e293b"))
        self.status = status
        self.speed_history = speed_history or []
        self.on_remove = on_remove
        self.on_edit = on_edit
        self.on_toggle_ssl = on_toggle_ssl
        self._build()

    def refresh(self, status: ClusterStatus, speed_history=None):
        """Update this card in-place with new data, no card-frame churn."""
        self.status = status
        self.speed_history = speed_history or []
        for child in self.winfo_children():
            child.destroy()
        self._build()

    def _build(self):
        cfg = self.status.config

        # Header row
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=18, pady=(14, 6))
        header.grid_columnconfigure(1, weight=1)

        conn_color = "#2ecc71" if self.status.reachable else "#e74c3c"
        self.indicator = ctk.CTkLabel(
            header,
            text="●",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=conn_color,
        )
        self.indicator.grid(row=0, column=0, padx=(0, 6))

        title_frame = ctk.CTkFrame(header, fg_color="transparent")
        title_frame.grid(row=0, column=1, sticky="w")

        ctk.CTkLabel(
            title_frame,
            text=cfg.name,
            font=ctk.CTkFont(size=17, weight="bold"),
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_frame,
            text=cfg.host.replace("https://", "").replace("http://", ""),
            font=ctk.CTkFont(size=10),
            text_color=("#666666", "#8899aa"),
        ).pack(anchor="w")

        btn_frame = ctk.CTkFrame(header, fg_color="transparent")
        btn_frame.grid(row=0, column=2, sticky="e")

        if self.on_edit:
            ctk.CTkButton(
                btn_frame,
                text="Edit",
                width=40,
                height=26,
                corner_radius=13,
                font=ctk.CTkFont(size=10),
                fg_color="transparent",
                hover_color=("#e0e0e0", "#334155"),
                text_color=("#666666", "#94a3b8"),
                command=self.on_edit,
            ).pack(side="left", padx=(0, 4))

        if self.on_remove:
            ctk.CTkButton(
                btn_frame,
                text="Del",
                width=40,
                height=26,
                corner_radius=13,
                font=ctk.CTkFont(size=10),
                fg_color="transparent",
                hover_color=("#e0e0e0", "#334155"),
                text_color=("#666666", "#94a3b8"),
                command=self.on_remove,
            ).pack(side="left")

        # Error display
        if self.status.error_message:
            err = ctk.CTkLabel(
                self,
                text=f"⚠ {self.status.error_message}",
                font=ctk.CTkFont(size=11),
                text_color="#e74c3c",
                wraplength=520,
                justify="left",
            )
            err.pack(fill="x", padx=18, pady=(0, 6))

            if self.on_toggle_ssl and ("SSL" in self.status.error_message or "CERT" in self.status.error_message.upper()):
                ctk.CTkButton(
                    self,
                    text="Disable SSL verification",
                    width=200,
                    height=28,
                    fg_color="#e74c3c",
                    hover_color="#c0392b",
                    font=ctk.CTkFont(size=11),
                    command=self.on_toggle_ssl,
                ).pack(anchor="w", padx=18, pady=(0, 10))
            return

        # Snapshot info
        if self.status.snapshot_info:
            snap = self.status.snapshot_info
            stats = self.status.snapshot_stats

            snap_frame = ctk.CTkFrame(self, fg_color="transparent")
            snap_frame.pack(fill="x", padx=18, pady=(4, 2))

            state_colors = self._STATE_COLORS.get(snap.state, self._STATE_COLORS[SnapshotState.UNKNOWN])
            state_color = state_colors[1] if ctk.get_appearance_mode() == "Dark" else state_colors[0]

            badge = ctk.CTkFrame(snap_frame, fg_color=state_color, corner_radius=4)
            badge.pack(side="left")
            ctk.CTkLabel(
                badge,
                text=snap.state.value,
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color="white",
            ).pack(padx=7, pady=2)

            # Selectable, wrapping snapshot name (so users can copy it)
            import tkinter as _tk

            name_text = snap.name
            _is_dark = ctk.get_appearance_mode() == "Dark"
            # Match the card's background so the Text widget blends in
            try:
                _card_bg = self._apply_appearance_mode(self.cget("fg_color"))
            except Exception:
                _card_bg = "#2b2b2b" if _is_dark else "#dbdbdb"
            name_widget = _tk.Text(
                snap_frame,
                wrap="word",
                height=1,
                borderwidth=0,
                highlightthickness=0,
                background=_card_bg,
                foreground="#ffffff" if _is_dark else "#000000",
                selectbackground="#3498db",
                selectforeground="#ffffff",
                font=("", 12, "bold"),
                cursor="xterm",
            )
            name_widget.insert("1.0", name_text)
            name_widget.update_idletasks()
            try:
                line_count = int(name_widget.index("end-1c").split(".")[0])
                name_widget.configure(height=max(1, min(line_count, 3)))
            except Exception:
                pass
            name_widget.configure(state="disabled")
            # Keep selection enabled while disabled
            name_widget.bind("<1>", lambda e: name_widget.focus_set())
            name_widget.pack(side="left", fill="x", expand=True, padx=(8, 6))

            def _copy_snap_name(t=name_text):
                try:
                    self.clipboard_clear()
                    self.clipboard_append(t)
                except Exception:
                    pass

            ctk.CTkButton(
                snap_frame,
                text="Copy",
                width=52,
                height=22,
                font=ctk.CTkFont(size=10),
                command=_copy_snap_name,
            ).pack(side="right")

            # Progress bar
            if stats:
                prog_frame = ctk.CTkFrame(self, fg_color="transparent")
                prog_frame.pack(fill="x", padx=18, pady=(4, 2))

                self.progress = GradientProgressBar(
                    prog_frame,
                    height=16,
                    value=stats.progress_pct / 100.0,
                )
                self.progress.pack(fill="x")

                pct_text = f"{stats.progress_pct:.1f}%"
                self.pct_label = ctk.CTkLabel(
                    prog_frame,
                    text=pct_text,
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color="#3498db",
                )
                self.pct_label.pack(anchor="e", pady=(2, 0))

            # Speed sparkline (if we have history)
            if self.speed_history and len(self.speed_history) >= 1:
                graph_frame = ctk.CTkFrame(self, fg_color="transparent")
                graph_frame.pack(fill="x", padx=18, pady=(2, 4))
                MiniSparkline(graph_frame, data=self.speed_history, height=50).pack(fill="x")

            # Stats grid
            stats_frame = ctk.CTkFrame(self, fg_color="transparent")
            stats_frame.pack(fill="x", padx=18, pady=(2, 6))
            stats_frame.grid_columnconfigure((0, 1), weight=1)

            if stats:
                row = 0
                col = 0
                if stats.has_byte_stats:
                    self._stat_item(stats_frame, "Data", f"{stats.processed_human} / {stats.total_human}", row, col)
                    col += 1
                    if col > 1:
                        col = 0
                        row += 1
                    self._stat_item(stats_frame, "Files", f"{stats.processed_files:,} / {stats.total_files:,}", row, col)
                    col += 1
                    if col > 1:
                        col = 0
                        row += 1

                self._stat_item(stats_frame, "Shards", f"{snap.shards_successful}/{snap.shards_total}", row, col)
                col += 1
                if col > 1:
                    col = 0
                    row += 1

                eta_label = "ETA" if stats.has_byte_stats else "ETA (est.)"
                eta_text = stats.eta_human
                completion = stats.completion_human
                if completion:
                    eta_text = f"{eta_text}   {completion}"
                self._stat_item(stats_frame, eta_label, eta_text, row, col)
                col += 1
                if col > 1:
                    col = 0
                    row += 1

                self._stat_item(stats_frame, "Speed", stats.current_speed_human, row, col)
                col += 1
                if col > 1:
                    col = 0
                    row += 1

                self._stat_item(stats_frame, "Avg", stats.avg_speed_human, row, col)
                col += 1
                if col > 1:
                    col = 0
                    row += 1

                if snap.shards_failed:
                    self._stat_item(stats_frame, "Failed", str(snap.shards_failed), row, col, color="#e74c3c")

        elif self.status.reachable:
            ctk.CTkLabel(
                self,
                text="No snapshot in progress",
                font=ctk.CTkFont(size=13),
                text_color=("#888888", "#64748b"),
            ).pack(pady=16)

        # SLM section
        if self.status.slm_last_run or self.status.slm_next_run:
            slm_frame = ctk.CTkFrame(self, fg_color=("#e8e8e8", "#0f172a"), corner_radius=8)
            slm_frame.pack(fill="x", padx=14, pady=(2, 10))

            if self.status.slm_in_progress:
                ctk.CTkLabel(
                    slm_frame,
                    text="SLM policy running",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color="#3498db",
                ).pack(anchor="w", padx=10, pady=(6, 2))

            if self.status.slm_last_run:
                ctk.CTkLabel(
                    slm_frame,
                    text=f"Last run: {self.status.slm_last_run}",
                    font=ctk.CTkFont(size=11),
                    text_color=("#555555", "#94a3b8"),
                ).pack(anchor="w", padx=10, pady=(4, 2))

            if self.status.slm_next_run:
                ctk.CTkLabel(
                    slm_frame,
                    text=f"Next run: {self.status.slm_next_run}",
                    font=ctk.CTkFont(size=11),
                    text_color=("#555555", "#94a3b8"),
                ).pack(anchor="w", padx=10, pady=(2, 6))

    def _stat_item(self, parent, label: str, value: str, row: int, col: int, color=None):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=col, sticky="w", padx=(0, 12), pady=2)
        ctk.CTkLabel(
            frame,
            text=f"{label}: ",
            font=ctk.CTkFont(size=11),
            text_color=("#777777", "#64748b"),
        ).pack(side="left")
        ctk.CTkLabel(
            frame,
            text=value,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=color or ("#333333", "#e2e8f0"),
        ).pack(side="left")


class AddClusterDialog:
    """Modal dialog for adding or editing a cluster — uses plain tk.Toplevel to avoid CTkToplevel blank-window bugs."""

    def __init__(self, master, on_save, existing: ClusterStatus | None = None):
        self.on_save = on_save
        self.existing = existing
        self.result = None

        self.dialog = tk.Toplevel(master)
        self.dialog.title("Edit Cluster" if existing else "Add Cluster")
        self.dialog.geometry("520x680")
        self.dialog.minsize(520, 600)
        self.dialog.transient(master)
        self.dialog.configure(bg="#2b2b2b")

        self.frame = ctk.CTkFrame(self.dialog, corner_radius=0)
        self.frame.pack(fill="both", expand=True)

        self._build_form()
        if existing:
            self._prefill()

        self.dialog.lift()
        self.dialog.focus_force()
        self.dialog.grab_set()

    def _build_form(self):
        pad = {"padx": 20, "pady": (12, 0)}

        ctk.CTkLabel(self.frame, text="Cluster Name", font=ctk.CTkFont(weight="bold")).pack(anchor="w", **pad)
        self.name_entry = ctk.CTkEntry(self.frame, placeholder_text="e.g. APAC Production")
        self.name_entry.pack(fill="x", padx=20, pady=(4, 0))

        ctk.CTkLabel(self.frame, text="Host URL", font=ctk.CTkFont(weight="bold")).pack(anchor="w", **pad)
        self.host_entry = ctk.CTkEntry(self.frame, placeholder_text="https://elastic.example.com:9200")
        self.host_entry.pack(fill="x", padx=20, pady=(4, 0))

        ctk.CTkLabel(self.frame, text="Snapshot Repository", font=ctk.CTkFont(weight="bold")).pack(anchor="w", **pad)
        self.repo_entry = ctk.CTkEntry(self.frame, placeholder_text="e.g. my-s3-repo")
        self.repo_entry.pack(fill="x", padx=20, pady=(4, 0))

        ctk.CTkLabel(self.frame, text="SLM Policy Name", font=ctk.CTkFont(weight="bold")).pack(anchor="w", **pad)
        self.slm_entry = ctk.CTkEntry(self.frame, placeholder_text="e.g. daily-snapshot-policy")
        self.slm_entry.pack(fill="x", padx=20, pady=(4, 0))

        ctk.CTkLabel(self.frame, text="Username", font=ctk.CTkFont(weight="bold")).pack(anchor="w", **pad)
        self.user_entry = ctk.CTkEntry(self.frame, placeholder_text="elastic")
        self.user_entry.pack(fill="x", padx=20, pady=(4, 0))

        ctk.CTkLabel(self.frame, text="Password", font=ctk.CTkFont(weight="bold")).pack(anchor="w", **pad)
        self.pass_entry = ctk.CTkEntry(self.frame, placeholder_text="••••••", show="•")
        self.pass_entry.pack(fill="x", padx=20, pady=(4, 0))

        self.ssl_var = tk.IntVar(value=1)
        ctk.CTkCheckBox(
            self.frame,
            text="Verify SSL certificates",
            variable=self.ssl_var,
            onvalue=1,
            offvalue=0,
        ).pack(anchor="w", padx=20, pady=(16, 0))

        self.test_label = ctk.CTkLabel(self.frame, text="", font=ctk.CTkFont(size=12))
        self.test_label.pack(anchor="w", padx=20, pady=(8, 0))

        btn_frame = ctk.CTkFrame(self.frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(16, 16))

        ctk.CTkButton(
            btn_frame,
            text="Test",
            width=80,
            command=self._test_connection,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            width=80,
            fg_color="#555555",
            command=self.dialog.destroy,
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_frame,
            text="Save",
            width=80,
            command=self._save,
        ).pack(side="right")

    def _prefill(self):
        from .config_manager import get_password
        cfg = self.existing.config
        self.name_entry.insert(0, cfg.name)
        self.host_entry.insert(0, cfg.host)
        self.repo_entry.insert(0, cfg.snapshot_repo)
        self.slm_entry.insert(0, cfg.slm_policy)
        self.user_entry.insert(0, cfg.username)
        self.ssl_var.set(1 if cfg.verify_ssl else 0)
        self.name_entry.configure(state="disabled")

        pwd = get_password(cfg.name)
        if pwd:
            self.pass_entry.insert(0, pwd)

    def _test_connection(self):
        self.test_label.configure(text="Testing…", text_color="#3498db")
        thread = threading.Thread(target=self._run_test, daemon=True)
        thread.start()

    def _run_test(self):
        from .es_client import fetch_cluster_status
        from .models import ClusterConfig

        ca_cert = self.existing.config.ca_cert if self.existing else None
        cfg = ClusterConfig(
            name="test",
            host=self.host_entry.get().strip(),
            snapshot_repo="test",
            slm_policy="test",
            username=self.user_entry.get().strip(),
            verify_ssl=bool(self.ssl_var.get()),
            ca_cert=ca_cert,
        )
        pwd = self.pass_entry.get()
        result = fetch_cluster_status(cfg, pwd)

        def update():
            if result.reachable:
                self.test_label.configure(text="Connection OK", text_color="#2ecc71")
            else:
                self.test_label.configure(text=f"{result.error_message}", text_color="#e74c3c")

        self.dialog.after(0, update)

    def _save(self):
        from .models import ClusterConfig
        from .config_manager import save_cluster

        # When editing, the name field is disabled — read from existing config.
        if self.existing:
            name = self.existing.config.name
            ca_cert = self.existing.config.ca_cert
        else:
            name = self.name_entry.get().strip()
            ca_cert = None
        host = self.host_entry.get().strip()
        repo = self.repo_entry.get().strip()
        slm = self.slm_entry.get().strip()
        user = self.user_entry.get().strip()
        pwd = self.pass_entry.get()

        if not all([name, host, repo, slm, user]):
            self.test_label.configure(text="Please fill in all fields", text_color="#e74c3c")
            return

        cfg = ClusterConfig(
            name=name,
            host=host,
            snapshot_repo=repo,
            slm_policy=slm,
            username=user,
            verify_ssl=bool(self.ssl_var.get()),
            ca_cert=ca_cert,
        )
        try:
            save_cluster(cfg, pwd)
        except Exception as e:
            self.test_label.configure(text=f"Save failed: {e}", text_color="#e74c3c")
            return
        self.test_label.configure(text="Saved", text_color="#2ecc71")
        try:
            self.on_save()
        finally:
            self.dialog.after(250, self.dialog.destroy)


class AISettingsDialog:
    """Configure the AI provider used by Performance Analysis."""

    # Fine-grained personal access tokens (new style). The GitHub Models API
    # accepts these and they're scoped/expiring by default.
    GITHUB_TOKEN_URL = "https://github.com/settings/personal-access-tokens/new"

    def __init__(self, master, on_save=None):
        from .ai_client import load_ai_settings, get_ai_token

        self.on_save = on_save
        settings = load_ai_settings()

        self.dialog = tk.Toplevel(master)
        self.dialog.title("AI Settings")
        self.dialog.geometry("600x600")
        self.dialog.transient(master)
        self.dialog.configure(bg="#2b2b2b")

        frame = ctk.CTkFrame(self.dialog, corner_radius=0)
        frame.pack(fill="both", expand=True)

        # Sign-in panel for GitHub Models
        signin = ctk.CTkFrame(frame, fg_color=("#e8f0ff", "#0f1f3a"), corner_radius=8)
        signin.pack(fill="x", padx=20, pady=(16, 4))
        ctk.CTkLabel(
            signin,
            text="Use GitHub Models (free, recommended)",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=14, pady=(10, 2))
        ctk.CTkLabel(
            signin,
            text=(
                "1. Click ‘Get a Token’ — opens GitHub's fine-grained token page.\n"
                "2. Token name: ‘ES Snap Mon — AI Analysis’.  Resource owner: your account.\n"
                "3. Permissions → Account permissions → ‘Models’ = Read-only.\n"
                "4. Generate, copy, paste below, click Verify, then Save."
            ),
            font=ctk.CTkFont(size=11),
            text_color=("#444", "#94a3b8"),
            justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 6))
        signin_btns = ctk.CTkFrame(signin, fg_color="transparent")
        signin_btns.pack(fill="x", padx=10, pady=(0, 6))
        ctk.CTkButton(
            signin_btns,
            text="Get a Token  ↗",
            width=130,
            command=self._open_github_tokens,
        ).pack(side="left", padx=(4, 6))
        ctk.CTkButton(
            signin_btns,
            text="Copy URL",
            width=110,
            fg_color="transparent",
            border_width=1,
            command=self._copy_token_url,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            signin_btns,
            text="Paste from Clipboard",
            width=160,
            fg_color="transparent",
            border_width=1,
            command=self._paste_clipboard,
        ).pack(side="left")

        # Always-visible, selectable URL so the user can see + copy it manually.
        url_row = ctk.CTkFrame(signin, fg_color="transparent")
        url_row.pack(fill="x", padx=10, pady=(0, 10))
        url_entry = ctk.CTkEntry(url_row, font=ctk.CTkFont(size=10))
        url_entry.insert(0, self.GITHUB_TOKEN_URL)
        url_entry.configure(state="readonly")
        url_entry.pack(fill="x")

        ctk.CTkLabel(
            frame,
            text="API Token",
            font=ctk.CTkFont(weight="bold"),
        ).pack(anchor="w", padx=20, pady=(14, 0))
        token_row = ctk.CTkFrame(frame, fg_color="transparent")
        token_row.pack(fill="x", padx=20, pady=(4, 0))
        self.token_entry = ctk.CTkEntry(token_row, show="•", placeholder_text="ghp_… / sk-…")
        self.token_entry.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            token_row,
            text="Verify",
            width=80,
            command=self._verify_token,
        ).pack(side="left", padx=(8, 0))
        existing = get_ai_token()
        if existing:
            self.token_entry.insert(0, existing)

        # Advanced overrides — collapsed visually with a small label
        ctk.CTkLabel(
            frame,
            text="Advanced (override provider / model)",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("#666", "#94a3b8"),
        ).pack(anchor="w", padx=20, pady=(18, 0))

        adv = ctk.CTkFrame(frame, fg_color="transparent")
        adv.pack(fill="x", padx=20, pady=(4, 0))
        adv.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(adv, text="Base URL", font=ctk.CTkFont(size=11)).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        self.base_entry = ctk.CTkEntry(adv)
        self.base_entry.grid(row=0, column=1, sticky="ew", pady=2)
        self.base_entry.insert(0, settings.base_url)
        ctk.CTkLabel(adv, text="Model", font=ctk.CTkFont(size=11)).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
        # Editable combobox: pick from common GitHub Models or type any other id.
        # Larger context windows help when many clusters are analyzed at once.
        model_values = [
            "openai/gpt-4.1",            # 1M ctx — best for big diagnostics
            "openai/gpt-4.1-mini",
            "openai/gpt-4.1-nano",
            "openai/gpt-4o",
            "openai/gpt-4o-mini",
            "openai/gpt-5",
            "openai/gpt-5-mini",
            "openai/o1",
            "openai/o1-mini",
            "openai/o3-mini",
            "meta/Llama-3.3-70B-Instruct",
            "mistral-ai/Mistral-Large-2411",
        ]
        self.model_entry = ctk.CTkComboBox(adv, values=model_values)
        self.model_entry.grid(row=1, column=1, sticky="ew", pady=2)
        self.model_entry.set(settings.model)
        ctk.CTkLabel(
            adv,
            text="Tip: ‘openai/gpt-4.1’ has the largest context — best when analyzing many clusters.",
            font=ctk.CTkFont(size=10),
            text_color=("#666", "#94a3b8"),
            wraplength=480,
            justify="left",
        ).grid(row=2, column=1, sticky="w", pady=(2, 0))

        self.status_label = ctk.CTkLabel(frame, text="", font=ctk.CTkFont(size=11))
        self.status_label.pack(anchor="w", padx=20, pady=(10, 0))

        btns = ctk.CTkFrame(frame, fg_color="transparent")
        btns.pack(fill="x", padx=20, pady=(12, 16))
        ctk.CTkButton(btns, text="Cancel", width=80, fg_color="#555555", command=self.dialog.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btns, text="Save", width=80, command=self._save).pack(side="right")

        self.dialog.lift()
        self.dialog.focus_force()
        self.dialog.grab_set()

    def _open_github_tokens(self):
        # Always print the URL too so the user has a fallback in the terminal.
        print(f"[es-snap-mon] GitHub token URL: {self.GITHUB_TOKEN_URL}", file=sys.stderr)
        if _open_url(self.GITHUB_TOKEN_URL):
            self.status_label.configure(
                text="Opened browser. Generate a token, copy it, then paste it below.",
                text_color="#3498db",
            )
        else:
            # Fallback: copy URL so the user can paste into a browser manually.
            try:
                self.dialog.clipboard_clear()
                self.dialog.clipboard_append(self.GITHUB_TOKEN_URL)
                self.status_label.configure(
                    text="Could not open browser. URL copied to clipboard — paste it into your browser.",
                    text_color="#f39c12",
                )
            except Exception as e:
                self.status_label.configure(text=f"Could not open browser: {e}", text_color="#e74c3c")

    def _copy_token_url(self):
        try:
            self.dialog.clipboard_clear()
            self.dialog.clipboard_append(self.GITHUB_TOKEN_URL)
            self.status_label.configure(
                text="URL copied to clipboard — paste into your browser.",
                text_color="#3498db",
            )
        except Exception as e:
            self.status_label.configure(text=f"Copy failed: {e}", text_color="#e74c3c")

    def _paste_clipboard(self):
        try:
            text = self.dialog.clipboard_get().strip()
        except tk.TclError:
            self.status_label.configure(text="Clipboard is empty.", text_color="#e74c3c")
            return
        if not text:
            self.status_label.configure(text="Clipboard is empty.", text_color="#e74c3c")
            return
        self.token_entry.delete(0, "end")
        self.token_entry.insert(0, text)
        self.status_label.configure(text="Token pasted from clipboard.", text_color="#3498db")

    def _verify_token(self):
        token = self.token_entry.get().strip()
        base = self.base_entry.get().strip()
        model = self.model_entry.get().strip()
        if not token:
            self.status_label.configure(text="Enter a token first.", text_color="#e74c3c")
            return
        self.status_label.configure(text="Verifying…", text_color="#3498db")
        threading.Thread(
            target=self._do_verify, args=(token, base, model), daemon=True
        ).start()

    def _do_verify(self, token: str, base: str, model: str):
        from .ai_client import AISettings, save_ai_settings, set_ai_token, analyze, get_ai_token, load_ai_settings

        # Stash existing values, set candidates temporarily, restore on failure.
        prev_token = get_ai_token()
        prev_settings = load_ai_settings()
        try:
            set_ai_token(token)
            save_ai_settings(AISettings(base_url=base, model=model))
            reply = analyze(
                "Reply with the single word OK.",
                system="You are a connectivity test. Reply with only: OK",
                timeout=20,
            )
        except Exception as e:
            # Restore previous
            try:
                if prev_token:
                    set_ai_token(prev_token)
                save_ai_settings(prev_settings)
            except Exception:
                pass
            self.dialog.after(0, lambda: self.status_label.configure(
                text=f"Verify failed: {e}", text_color="#e74c3c"
            ))
            return

        ok_msg = f"Verified — {model} responded ({reply.strip()[:40]})"
        self.dialog.after(0, lambda: self.status_label.configure(text=ok_msg, text_color="#2ecc71"))

    def _save(self):
        from .ai_client import AISettings, save_ai_settings, set_ai_token

        token = self.token_entry.get().strip()
        base = self.base_entry.get().strip()
        model = self.model_entry.get().strip()
        if not token:
            self.status_label.configure(text="Token is required.", text_color="#e74c3c")
            return
        try:
            set_ai_token(token)
            save_ai_settings(AISettings(base_url=base, model=model))
        except Exception as e:
            self.status_label.configure(text=f"Save failed: {e}", text_color="#e74c3c")
            return
        if self.on_save:
            self.on_save()
        self.dialog.destroy()


# All diagnostic sections that fetch_diagnostics() can produce.
# Order here is the order shown in the AnalysisScopeDialog.
DIAGNOSTIC_SECTIONS: list[tuple[str, str, bool]] = [
    ("health",        "Cluster health (status, shard counts)",      True),
    ("pending_tasks", "Pending cluster tasks",                       True),
    ("nodes",         "Per-node JVM / GC / FS / CPU / thread pools", True),
    ("repository",    "Snapshot repository settings",                True),
    ("recoveries",    "Active shard recoveries",                     True),
    ("shards",        "Shard allocation summary (large)",            False),
]


class AnalysisScopeDialog:
    """Pick which clusters and which diagnostic sections to include."""

    def __init__(self, master, cluster_statuses, on_confirm):
        from .ai_client import load_analysis_scope

        self.cluster_statuses = cluster_statuses
        self.on_confirm = on_confirm
        self._estimate_after_id: str | None = None

        saved = load_analysis_scope()
        saved_clusters = set(saved.get("clusters") or [])
        saved_sections = set(saved.get("sections") or [])
        self._has_saved = bool(saved)

        self.dialog = tk.Toplevel(master)
        self.dialog.title("Analyze Performance — Scope")
        self.dialog.geometry("620x680")
        self.dialog.minsize(520, 520)
        self.dialog.transient(master)

        outer = ctk.CTkFrame(self.dialog)
        outer.pack(fill="both", expand=True, padx=14, pady=14)

        # Pack the action bar FIRST at the bottom so it's never clipped
        # by long cluster/section lists.
        btns = ctk.CTkFrame(outer, fg_color="transparent")
        btns.pack(side="bottom", fill="x", padx=12, pady=(8, 6))

        # Scrollable content above the action bar.
        frame = ctk.CTkScrollableFrame(outer, fg_color="transparent")
        frame.pack(side="top", fill="both", expand=True)

        ctk.CTkLabel(
            frame,
            text="What should we send to the model?",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(
            frame,
            text="Smaller selections fit better in models with limited context.",
            font=ctk.CTkFont(size=11),
            text_color=("#666", "#94a3b8"),
        ).pack(anchor="w", padx=12, pady=(0, 8))

        # --- Clusters ---
        ctk.CTkLabel(
            frame, text="Clusters", font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=12, pady=(6, 2))

        cluster_box = ctk.CTkFrame(frame, fg_color=("#f3f4f6", "#1f2937"))
        cluster_box.pack(fill="x", padx=12, pady=(0, 4))
        self.cluster_vars: dict[str, ctk.BooleanVar] = {}
        for st in cluster_statuses:
            name = st.config.name
            if self._has_saved:
                default = name in saved_clusters
            else:
                default = st.reachable
            var = ctk.BooleanVar(value=default)
            self.cluster_vars[name] = var
            label = name
            if not st.reachable:
                label += "  (unreachable)"
            ctk.CTkCheckBox(cluster_box, text=label, variable=var).pack(anchor="w", padx=6, pady=2)

        cluster_btns = ctk.CTkFrame(frame, fg_color="transparent")
        cluster_btns.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkButton(
            cluster_btns, text="All", width=60, height=24,
            fg_color="transparent", border_width=1,
            command=lambda: [v.set(True) for v in self.cluster_vars.values()],
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            cluster_btns, text="None", width=60, height=24,
            fg_color="transparent", border_width=1,
            command=lambda: [v.set(False) for v in self.cluster_vars.values()],
        ).pack(side="left")

        # --- Sections ---
        ctk.CTkLabel(
            frame, text="Diagnostic sections", font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=12, pady=(6, 2))

        section_box = ctk.CTkFrame(frame, fg_color=("#f3f4f6", "#1f2937"))
        section_box.pack(fill="x", padx=12, pady=(0, 4))
        self.section_vars: dict[str, ctk.BooleanVar] = {}
        for key, label, default in DIAGNOSTIC_SECTIONS:
            if self._has_saved:
                default = key in saved_sections
            var = ctk.BooleanVar(value=default)
            self.section_vars[key] = var
            ctk.CTkCheckBox(section_box, text=label, variable=var).pack(anchor="w", padx=6, pady=2)

        section_btns = ctk.CTkFrame(frame, fg_color="transparent")
        section_btns.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkButton(
            section_btns, text="All", width=60, height=24,
            fg_color="transparent", border_width=1,
            command=lambda: [v.set(True) for v in self.section_vars.values()],
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            section_btns, text="None", width=60, height=24,
            fg_color="transparent", border_width=1,
            command=lambda: [v.set(False) for v in self.section_vars.values()],
        ).pack(side="left")

        # --- Action buttons (already-packed at the bottom) ---

        # Live, coarse token estimate. Real size depends on cluster shape;
        # this is a heuristic so users can see relative impact while toggling.
        # Numbers are approx tokens contributed per (cluster x section).
        self._SECTION_WEIGHTS = {
            "health": 60,
            "pending_tasks": 40,
            "nodes": 350,        # scales with nodes; dominant chunk
            "repository": 60,
            "recoveries": 200,
            "shards": 250,
        }
        self._BASE_PER_CLUSTER = 120  # snapshot stats + headers
        self._BASE_PROMPT = 200

        self.estimate_label = ctk.CTkLabel(
            btns, text="Estimating…", font=ctk.CTkFont(size=11),
            text_color=("#666", "#94a3b8"),
        )
        self.estimate_label.pack(side="left")

        ctk.CTkButton(
            btns, text="Cancel", width=80, fg_color="#555555",
            command=self.dialog.destroy,
        ).pack(side="right", padx=(6, 0))
        ctk.CTkButton(
            btns, text="Analyze", width=100, command=self._confirm,
        ).pack(side="right", padx=(6, 0))
        ctk.CTkButton(
            btns, text="Save", width=80,
            fg_color="transparent", border_width=1,
            command=self._save_selection,
        ).pack(side="right")

        # Hook all checkboxes to schedule a debounced estimate refresh.
        for v in list(self.cluster_vars.values()) + list(self.section_vars.values()):
            v.trace_add("write", lambda *_: self._schedule_estimate())
        # Compute the first estimate immediately so the user isn't staring at
        # "Estimating…" while idle.
        self._update_estimate()

        self.dialog.lift()
        self.dialog.focus_force()

    def _schedule_estimate(self):
        # Show that an update is pending and recompute 2s after the user stops
        # toggling checkboxes (debounce).
        try:
            self.estimate_label.configure(text="Estimating…")
        except Exception:
            pass
        if self._estimate_after_id is not None:
            try:
                self.dialog.after_cancel(self._estimate_after_id)
            except Exception:
                pass
        self._estimate_after_id = self.dialog.after(2000, self._update_estimate)

    def _update_estimate(self):
        self._estimate_after_id = None
        n_clusters = sum(1 for v in self.cluster_vars.values() if v.get())
        sec_tokens = sum(
            self._SECTION_WEIGHTS.get(k, 0)
            for k, v in self.section_vars.items() if v.get()
        )
        per_cluster = self._BASE_PER_CLUSTER + sec_tokens
        total = self._BASE_PROMPT + n_clusters * per_cluster
        self.estimate_label.configure(
            text=f"Estimate: ~{total:,} tokens  ({n_clusters} cluster(s))"
        )

    def _save_selection(self):
        from .ai_client import save_analysis_scope
        clusters = sorted(n for n, v in self.cluster_vars.items() if v.get())
        sections = sorted(k for k, v in self.section_vars.items() if v.get())
        try:
            save_analysis_scope(clusters, sections)
            self.estimate_label.configure(text="✓ Saved")
            self.dialog.after(1500, self._update_estimate)
        except Exception as e:
            self.estimate_label.configure(text=f"Save failed: {e}")

    def _confirm(self):
        clusters = {n for n, v in self.cluster_vars.items() if v.get()}
        sections = {k for k, v in self.section_vars.items() if v.get()}
        if not clusters:
            return  # silently no-op; user can flip a checkbox
        self.dialog.destroy()
        self.on_confirm(clusters, sections)


class AnalysisDialog:
    """Display AI analysis output in a scrollable window."""

    def __init__(self, master, title: str = "Performance Analysis"):
        self.dialog = tk.Toplevel(master)
        self.dialog.title(title)
        self.dialog.geometry("780x600")
        self.dialog.transient(master)
        self.dialog.configure(bg="#2b2b2b")

        outer = ctk.CTkFrame(self.dialog, corner_radius=0)
        outer.pack(fill="both", expand=True)

        self.header = ctk.CTkLabel(
            outer,
            text="Analyzing snapshot performance…",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.header.pack(anchor="w", padx=18, pady=(14, 6))

        self.textbox = ctk.CTkTextbox(outer, wrap="word", font=ctk.CTkFont(size=12))
        self.textbox.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        self.textbox.insert("1.0", "Contacting model — this can take a few seconds…\n")
        self.textbox.configure(state="disabled")

        btns = ctk.CTkFrame(outer, fg_color="transparent")
        btns.pack(fill="x", padx=14, pady=(0, 12))
        self.copy_btn = ctk.CTkButton(btns, text="Copy", width=80, command=self._copy, state="disabled")
        self.copy_btn.pack(side="left")
        ctk.CTkButton(btns, text="Close", width=80, fg_color="#555555", command=self.dialog.destroy).pack(side="right")

        self.dialog.lift()
        self.dialog.focus_force()

    def set_text(self, text: str, header: str | None = None):
        if header is not None:
            self.header.configure(text=header)
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        self.textbox.insert("1.0", text)
        self.textbox.configure(state="disabled")
        self.copy_btn.configure(state="normal")

    def set_error(self, msg: str):
        self.set_text(msg, header="Analysis failed")

    def _copy(self):
        try:
            text = self.textbox.get("1.0", "end")
            self.dialog.clipboard_clear()
            self.dialog.clipboard_append(text)
        except Exception:
            pass
