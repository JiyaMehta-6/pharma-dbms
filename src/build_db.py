"""Build SQLite RDBMS from Data/indian_medicine_data.csv (CLI wrapper).

The import logic lives in :mod:`pharma_db.services` so the GUI and this
command share one implementation.
"""
from __future__ import annotations

from pharma_db import config
from pharma_db.db import Database
from pharma_db.services import rebuild_database


def _progress(stage: str, done: int, total: int) -> None:
    if total:
        print(f"[{stage}] {done:,} / {total:,}")
    else:
        print(f"[{stage}] {done:,}")


def main() -> None:
    csv_path = config.source_csv()
    if not csv_path.exists():
        raise FileNotFoundError(
            f"CSV not found: {config.csv_path()} (and no sample at {config.sample_csv_path()})"
        )
    print(f"Source CSV: {csv_path}")
    db = Database(config.resolve_db_path())
    stats = rebuild_database(db, csv_path=csv_path, progress=_progress)
    size_mb = db.path.stat().st_size / 1024 / 1024
    print(
        "manufacturers={manufacturers}, compositions={compositions}, "
        "medicines={medicines}, orphan_man={orphan_manufacturers} "
        "orphan_comp={orphan_compositions}".format(**stats)
    )
    print(f"Done -> {db.path} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
