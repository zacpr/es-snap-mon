# AGENTS.md — Elasticsearch Snapshot Monitor

## Project Overview

**Status:** Planning phase — no source code or build system exists yet.  
**Goal:** Build a pleasant GUI application that tracks the progress of ongoing Elasticsearch snapshot backups across multiple clusters and translates the stats into human-readable form.

The project directory currently contains only `thePLAN.md`, which describes the intended clusters and credentials for testing.

## Target Clusters (for dev / testing)

| Cluster | Snapshot Repository | SLM Policy |
|---------|---------------------|------------|
| `elastic.apac-prod-1.wtg.zone` | `au2s3-b1.wtg.ws-us2-production` | `slm_apac-prod-1-qid-full-backup-to-s3` |
| `elastic.amer-prod-1.wtg.zone` | `us2s3-b1.wtg.ws-us2-production` | `slm_amer-prod-1-qid-full-backup-to-s3` |
| `elastic.emea-prod-1.wtg.zone` | `de1s3-b1.wtg.ws-us2-production` | `slm_emea-prod-1-qid-full-backup-to-s3` |

**Test credentials:** `zac` / `mayhem`

## Technology Stack (to be decided)

Nothing has been chosen yet. Common options for a small cross-platform GUI of this type include:

- **Python** + PyQt / PySide / Tkinter / Tauri (via `pywebview`)
- **Node.js / TypeScript** + Electron / Tauri
- **Rust** + Tauri / egui / iced

The app will need to:
1. Query Elasticsearch `_snapshot` and SLM APIs.
2. Parse JSON responses and render progress / status visually.
3. Store user-configurable cluster endpoints and credentials securely.

## Project Layout (proposed)

Until a stack is chosen, no directory structure exists. A typical layout once development starts might look like:

```
├── src/               # Application source
├── tests/             # Unit / integration tests
├── docs/              # Additional documentation
├── config/            # Example configuration files
├── pyproject.toml     # or package.json, Cargo.toml, etc.
└── README.md          # Human-facing documentation
```

## Build and Test Commands

**Not applicable yet.** Once a stack is selected, add the standard commands here (e.g., `pip install -e .`, `npm run build`, `cargo test`).

## Code Style Guidelines

**Not defined yet.** Decide and document formatting rules (e.g., Black/Ruff for Python, Prettier/ESLint for JS, rustfmt/clippy for Rust).

## Testing Instructions

**Not defined yet.** Plan to include:
- Unit tests for JSON parsing / translation logic.
- Integration tests against a local Elasticsearch instance or mock server.
- UI tests if using a framework that supports them.

## Security Considerations

- **Do not commit credentials.** The test credentials (`zac/mayhem`) listed in `thePLAN.md` must never be hard-coded in source.
- Use OS-native secret storage (e.g., keyring, Keychain, Windows Credential Manager) or environment variables for cluster passwords/API keys.
- Validate TLS certificates when connecting to production clusters.
- Consider least-privilege Elasticsearch users (e.g., `monitor` + `snapshot` roles only).

## Next Steps for Agents

1. Choose a technology stack with the user.
2. Initialize the project with the appropriate package manager and build tool.
3. Implement a minimal proof-of-life: query one cluster’s `_snapshot/<repo>/_current` endpoint and print the response.
4. Add configuration persistence and secure credential storage.
5. Build the GUI layer on top of the core monitoring logic.
