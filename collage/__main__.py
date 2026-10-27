"""python -m collage  (or the frozen exe via run_collage.py). All input is through the Tk UI."""
from __future__ import annotations

import logging
import logging.handlers
import sys

from .storage import Store, legacy_template_dirs


def _setup_logging(store: Store) -> None:
    handler = logging.handlers.RotatingFileHandler(
        store.log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # --noconsole / pythonw: sys.stdout and sys.stderr are None, so any print() or warning would crash.
    if sys.stdout is None or sys.stderr is None:
        stream = open(store.log_file, "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = stream
        if sys.stderr is None:
            sys.stderr = stream


def main() -> int:
    store = Store()
    _setup_logging(store)
    try:
        store.migrate_legacy(legacy_template_dirs())
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("legacy template migration failed")

    from .ui.app import App

    App(store).mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
