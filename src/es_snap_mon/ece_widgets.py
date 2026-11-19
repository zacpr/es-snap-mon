"""Elastic Cloud Enterprise deployment browser."""
from __future__ import annotations

import threading
import tkinter as tk

import customtkinter as ctk

from .config_manager import (
    get_ece_password,
    get_ece_settings,
    save_ece_settings,
    set_ece_password,
)
from .ece_client import fetch_ece_deployments
from .models import _bytes_to_human


class EceDeploymentsDialog:
    def __init__(self, master):
        self.dialog = tk.Toplevel(master)
        self.dialog.title("ECE Deployments")
        self.dialog.geometry("1100x700")
        self.dialog.minsize(850, 550)
        self.dialog.configure(bg="#1f1f1f")
        self.dialog.transient(master)
        self.dialog.grid_columnconfigure(0, weight=1)
        self.dialog.grid_rowconfigure(2, weight=1)
        self._build_settings()
        self.status = ctk.CTkLabel(self.dialog, text="Ready", anchor="w")
        self.status.grid(row=1, column=0, sticky="ew", padx=18, pady=(8, 0))
        self.scroll = ctk.CTkScrollableFrame(self.dialog)
        self.scroll.grid(row=2, column=0, sticky="nsew", padx=18, pady=12)
        self.scroll.grid_columnconfigure(0, weight=1)
        if self.url_entry.get().strip():
            self.refresh()

    def _build_settings(self):
        settings = get_ece_settings()
        frame = ctk.CTkFrame(self.dialog)
        frame.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 0))
        for column in (1, 3):
            frame.grid_columnconfigure(column, weight=1)
        ctk.CTkLabel(frame, text="ECE coordinator URL").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 0))
        self.url_entry = ctk.CTkEntry(frame, placeholder_text="https://ece.example:12443")
        self.url_entry.grid(row=0, column=1, sticky="ew", padx=10, pady=(10, 0))
        self.url_entry.insert(0, settings.get("url", ""))
        ctk.CTkLabel(frame, text="Username").grid(row=0, column=2, sticky="w", padx=10, pady=(10, 0))
        self.user_entry = ctk.CTkEntry(frame)
        self.user_entry.grid(row=0, column=3, sticky="ew", padx=10, pady=(10, 0))
        self.user_entry.insert(0, settings.get("username", "admin"))
        ctk.CTkLabel(frame, text="Password").grid(row=1, column=0, sticky="w", padx=10, pady=(10, 0))
        self.pass_entry = ctk.CTkEntry(frame, show="•")
        self.pass_entry.grid(row=1, column=1, sticky="ew", padx=10, pady=(10, 0))
        self.pass_entry.insert(0, get_ece_password() or "")
        ctk.CTkLabel(frame, text="SSH destination (optional)").grid(row=1, column=2, sticky="w", padx=10, pady=(10, 0))
        self.ssh_entry = ctk.CTkEntry(frame)
        self.ssh_entry.grid(row=1, column=3, sticky="ew", padx=10, pady=(10, 0))
        self.ssh_entry.insert(0, settings.get("ssh_jump_host", ""))
        self.ssl_var = tk.IntVar(value=1 if settings.get("verify_ssl", True) else 0)
        ctk.CTkCheckBox(frame, text="Verify SSL", variable=self.ssl_var).grid(row=2, column=0, sticky="w", padx=10, pady=10)
        ctk.CTkButton(frame, text="Save", command=self.save).grid(row=2, column=2, sticky="e", padx=10, pady=10)
        ctk.CTkButton(frame, text="Refresh deployments", command=self.refresh).grid(row=2, column=3, sticky="e", padx=10, pady=10)

    def save(self):
        try:
            save_ece_settings(
                self.url_entry.get(), self.user_entry.get(), bool(self.ssl_var.get()), self.ssh_entry.get()
            )
            set_ece_password(self.pass_entry.get())
            self.status.configure(text="ECE settings saved", text_color="#2ecc71")
        except Exception as exc:
            self.status.configure(text=f"Save failed: {exc}", text_color="#e74c3c")

    def refresh(self):
        self.status.configure(text="Loading ECE deployments…", text_color="#94a3b8")
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            deployments = fetch_ece_deployments(
                self.url_entry.get().strip(),
                self.user_entry.get().strip(),
                self.pass_entry.get(),
                verify_ssl=bool(self.ssl_var.get()),
                ssh_jump_host=self.ssh_entry.get().strip() or None,
            )
        except Exception as exc:
            self.dialog.after(0, lambda: self.status.configure(text=str(exc), text_color="#e74c3c"))
            return
        self.dialog.after(0, lambda: self._render(deployments))

    def _render(self, deployments):
        for child in self.scroll.winfo_children():
            child.destroy()
        healthy = sum(item.healthy is True for item in deployments)
        memory = sum(item.memory_mb for item in deployments)
        storage = sum(item.storage_mb for item in deployments)
        self.status.configure(
            text=f"{len(deployments)} deployments · {healthy} healthy · {_bytes_to_human(memory * 1024 ** 2)} RAM · {_bytes_to_human(storage * 1024 ** 2)} storage",
            text_color="#94a3b8",
        )
        for deployment in deployments:
            color = "#2ecc71" if deployment.healthy else "#e74c3c" if deployment.healthy is False else "#f39c12"
            card = ctk.CTkFrame(self.scroll)
            card.pack(fill="x", pady=6)
            ctk.CTkLabel(
                card,
                text=f"{deployment.name}   {'Healthy' if deployment.healthy else 'Degraded' if deployment.healthy is False else 'Unknown'}",
                font=ctk.CTkFont(size=16, weight="bold"),
                text_color=color,
            ).pack(anchor="w", padx=14, pady=(12, 2))
            ctk.CTkLabel(
                card,
                text=f"ID {deployment.id} · Elasticsearch {deployment.elasticsearch_version or 'unknown'} · {deployment.running_instances}/{deployment.instance_count} instances running · {_bytes_to_human(deployment.memory_mb * 1024 ** 2)} RAM · {_bytes_to_human(deployment.storage_mb * 1024 ** 2)} storage",
            ).pack(anchor="w", padx=14, pady=(0, 8))
            for instance in deployment.instances:
                state = "running" if instance.running else "stopped" if instance.running is False else "unknown"
                ctk.CTkLabel(
                    card,
                    text=f"• {instance.name}: {state}; {_bytes_to_human(instance.memory_mb * 1024 ** 2)} RAM; {_bytes_to_human(instance.storage_mb * 1024 ** 2)} storage; memory pressure {instance.memory_pressure if instance.memory_pressure is not None else 'unknown'}; native pressure {instance.native_memory_pressure if instance.native_memory_pressure is not None else 'unknown'}; roles {', '.join(instance.roles) or 'none'}",
                    font=ctk.CTkFont(size=11),
                    text_color="#cbd5e1",
                ).pack(anchor="w", padx=26, pady=1)
            ctk.CTkLabel(card, text="").pack(pady=2)
