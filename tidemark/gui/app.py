"""``tidemark-gui`` entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from tidemark import __version__
from tidemark.gui.main_window import MainWindow
from tidemark.gui.theme import apply_theme
from tidemark.store.db import Database, migrate
from tidemark.store.git_repo import ConfigRepo
from tidemark.store.paths import default_paths


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)

    # --version / --help without booting Qt
    if "--version" in argv[1:]:
        print(f"tidemark-gui {__version__}")
        return 0

    demo = "--demo" in argv

    if demo:
        from tidemark.gui import demo as demo_mod
        db, _repo, runner = demo_mod.make_context()
        paths = default_paths()
    else:
        paths = default_paths()
        paths.ensure_dirs()
        db = Database(paths.db_path)
        migrate(db)
        ConfigRepo(paths.configs_git_dir)  # ensure the configs repo exists on first boot

        from tidemark.core.credentials import read_credentials
        from tidemark.core.engine import DirectBackupRunner
        from tidemark.core.profiles import ProfileRegistry
        from tidemark.store.repositories import DeviceRepo

        devices = DeviceRepo(db).list(enabled_only=True)
        profiles = ProfileRegistry(user_profiles_dir=paths.user_profiles_dir)
        creds = read_credentials(prompt_device="tidemark-gui")
        runner = DirectBackupRunner(devices, profiles, creds, max_workers=5)

    app = QApplication(argv)
    app.setApplicationName("Tidemark")
    app.setApplicationVersion(__version__)
    apply_theme(app)

    window = MainWindow(db, paths, runner, demo=demo)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
