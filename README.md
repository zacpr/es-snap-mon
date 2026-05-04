# 📦 ES Snap Monitor

A sleek, dark-themed desktop GUI for monitoring Elasticsearch snapshot backups across multiple clusters.

![Python](https://img.shields.io/badge/python-3.9+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

## Features

- 🖥️ **Modern dark UI** built with [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)
- 🌐 **Multi-cluster dashboard** — track snapshots across all your ES clusters in one view
- 📊 **Human-readable progress** — bytes, files, ETA, shards all translated for humans
- 🔒 **Secure credential storage** — passwords stored in your OS keyring (Keychain / Windows Credential Manager / libsecret)
- 🔄 **Auto-refresh** — live updates every 15 seconds
- ⚡ **Test connection** — verify credentials before saving
- 📋 **One-click presets** — pre-loaded with APAC / AMER / EMEA production clusters

## Quick Start

```bash
# Install
pip install -e .

# Run
es-snap-mon
```

Or run directly:

```bash
python -m es_snap_mon
```

## Usage

1. Click **📋 Load Presets** to add the default clusters, or **➕ Add Cluster** for custom endpoints.
2. Enter credentials — passwords are stored securely in your OS keyring.
3. Watch the dashboard update with live snapshot progress.

## Development

```bash
# Install editable
pip install -e .

# Run
python -m es_snap_mon
```

## Tech Stack

- **Python 3.9+**
- **CustomTkinter** — modern tkinter alternative
- **Requests** — HTTP client for Elasticsearch APIs
- **Keyring** — cross-platform secret storage

## Security Notes

- Credentials are never written to disk in plain text.
- TLS certificate verification is enabled by default (can be disabled per cluster for testing).
- Use least-privilege ES users (`monitor` + `snapshot` roles recommended).
