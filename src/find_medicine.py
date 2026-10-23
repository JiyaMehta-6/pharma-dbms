"""Find medicine by name in v_medicines. Prompts user if no name given."""
from __future__ import annotations

import sys

from pharma_db import config
from pharma_db.db import Database

SQL = """
SELECT id, name, price_rs, manufacturer_name, type,
       pack_size_label, short_composition1, short_composition2,
       unit_rate
FROM v_medicines_dtl
WHERE name LIKE '%' || ? || '%' COLLATE NOCASE
ORDER BY name
LIMIT 20;
"""


def find(name: str):
    db = Database(config.resolve_db_path())
    return [tuple(r) for r in db.query(SQL, (name,))]


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        name = " ".join(argv).strip()
    else:
        name = input("Enter medicine name (part or full): ").strip()
    if not name:
        print("No name entered.")
        return
    try:
        rows = find(name)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}")
        return
    if not rows:
        print(f"No match for '{name}'.")
        return
    print(f"{len(rows)} match(es) for '{name}' (showing up to 20):")
    for row in rows:
        print(row)


if __name__ == "__main__":
    main()
