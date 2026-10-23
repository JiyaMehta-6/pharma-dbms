"""Launch the Pharma DBMS GUI (alias of ``main.py``).

Run from the project root:

    python gui.py
"""
from __future__ import annotations

import sys

from pharma_db import main

if __name__ == "__main__":
    sys.exit(main())
