"""Custom UI widgets for the ES Snapshot Monitor."""
from __future__ import annotations

import threading
import tkinter as tk

import customtkinter as ctk

from .models import ClusterStatus, SnapshotState


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

            name_text = snap.name
            if len(name_text) > 50:
                name_text = name_text[:47] + "…"
            ctk.CTkLabel(
                snap_frame,
                text=name_text,
                font=ctk.CTkFont(size=12, weight="bold"),
            ).pack(side="left", padx=(8, 0))

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
