#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# Ensure the package is installed
if ! python3 -c "import es_snap_mon" 2>/dev/null; then
    echo "Installing es-snap-mon..."
    pip install -e . --quiet
fi

# Launch
exec python3 -m es_snap_mon "$@"
