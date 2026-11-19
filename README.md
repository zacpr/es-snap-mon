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

### SSH jump host

Choose **SSH Jump Settings** and enter an OpenSSH destination such as `dante@10.2.0.31`, `dante@jump.example:2222`, or an alias from `~/.ssh/config`. Leave it blank for direct connections.

Drastic Smurf starts dynamic SOCKS tunnels and uses them for Elasticsearch monitoring, repository discovery, diagnostics, and Kibana-compatible API requests. Cluster URLs remain unchanged, including HTTPS hostnames and certificate verification. DNS is resolved through the selected SSH host. Authentication uses your existing OpenSSH keys, agent, and `ProxyJump` rules; interactive password prompts are not supported.

Each cluster can override the global destination in its **Edit Cluster** dialog. Enter an SSH destination to route only that cluster through SSH, leave the field blank to inherit the global setting, or enter `-` to force a direct connection. Different SSH destinations can remain connected at the same time. For node-local services, use the node itself as the SSH destination (for example `10.2.60.11`) and a loopback service URL such as `http://127.0.0.1:5601`.

### ECE deployments

Choose **ECE Deployments** to open the separate Elastic Cloud Enterprise deployment browser. Enter the ECE coordinator URL (typically port `12443`), an ECE username and password, and an optional SSH destination. The password is stored in the OS keyring.

The browser authenticates with the ECE GUI login endpoint and uses its bearer token for `/api/v1/deployments`. It supports both current and older ECE response formats, retrieving deployment details when needed. The summary includes deployment health, Elasticsearch versions, running instance counts, memory, storage capacity, and memory pressure. Each Elasticsearch instance lists its health, running state, roles, memory, storage, and pressure. SSH destinations use the same OpenSSH configuration and `ProxyJump` support as cluster monitoring.

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
