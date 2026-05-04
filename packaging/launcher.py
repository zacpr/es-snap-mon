"""Launcher for PyInstaller — keeps package-relative imports working."""
# Explicit imports so PyInstaller's static analyzer bundles every module.
import es_snap_mon  # noqa: F401
import es_snap_mon.models  # noqa: F401
import es_snap_mon.config_manager  # noqa: F401
import es_snap_mon.es_client  # noqa: F401
import es_snap_mon.widgets  # noqa: F401
import es_snap_mon.app  # noqa: F401
from es_snap_mon.app import App


def main():
    App().run()


if __name__ == "__main__":
    main()
