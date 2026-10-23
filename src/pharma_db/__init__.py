"""Pharma DBMS - desktop database management system for the medicine catalogue."""
from __future__ import annotations

from typing import Sequence

__version__ = "1.0.0"


def main(argv: Sequence[str] | None = None) -> int:
    """Console-script entry point: launch the GUI."""
    from .app import main as _main

    return _main(argv)


__all__ = ["__version__", "main"]
