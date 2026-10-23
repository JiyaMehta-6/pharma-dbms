"""Entry point: launch the Pharma DBMS GUI.

Run from the project root:

    python main.py

Equivalent to ``python -m pharma_db`` / the ``pharma-db`` console script.
"""
from __future__ import annotations

import sys

from pharma_db import main

if __name__ == "__main__":
    sys.exit(main())
