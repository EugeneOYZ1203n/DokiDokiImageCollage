"""PyInstaller entry point (absolute imports; collage/__main__.py uses relative ones)."""
import multiprocessing

from collage.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
