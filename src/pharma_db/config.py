"""Application paths and constants for the Pharma DBMS package."""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Pharma DBMS"
APP_ORG = "pharma-db"
APP_VERSION = "1.0.0"

DB_FILENAME = "indian_medicine.db"
CSV_FILENAME = "indian_medicine_data.csv"
SAMPLE_CSV_FILENAME = "sample_indian_medicines.csv"
DATA_DIRNAME = "Data"
BACKUP_DIRNAME = "Backups"

PAGE_SIZES = (50, 100, 250, 500, 1000)
DEFAULT_PAGE_SIZE = 100

MONEY_FORMAT = "\u20b9{:,.2f}"


def _has_project_marker(path: Path) -> bool:
    return (path / "pyproject.toml").is_file() or (
        (path / DATA_DIRNAME).is_dir()
        and (path / DATA_DIRNAME / CSV_FILENAME).is_file()
    )


def project_root() -> Path:
    """Locate the project root (folder holding Data/ and pyproject.toml).

    Walks up from this file (works for source/editable installs) and falls
    back to the current working directory chain.
    """
    candidates = []
    here = Path(__file__).resolve().parent
    candidates.extend(here.parents)
    cwd = Path.cwd().resolve()
    candidates.extend([cwd, *cwd.parents])
    for candidate in candidates:
        if _has_project_marker(candidate):
            return candidate
    return cwd


def data_dir() -> Path:
    return project_root() / DATA_DIRNAME


def csv_path() -> Path:
    return data_dir() / CSV_FILENAME


def sample_csv_path() -> Path:
    return data_dir() / SAMPLE_CSV_FILENAME


def source_csv() -> Path:
    """The CSV an import should read.

    Prefers the full catalogue when present; otherwise falls back to the
    bundled 500-row sample so a fresh clone still runs end to end.
    """
    primary = csv_path()
    if primary.is_file():
        return primary
    return sample_csv_path()


def default_db_path() -> Path:
    return data_dir() / DB_FILENAME


def backup_dir() -> Path:
    return data_dir() / BACKUP_DIRNAME


def env_db_path() -> Path | None:
    raw = os.environ.get("PHARMA_DB_PATH")
    if not raw:
        return None
    return Path(raw).expanduser()


def resolve_db_path() -> Path:
    """Best-effort location of the SQLite database file."""
    override = env_db_path()
    if override is not None:
        return override
    return default_db_path()


def format_money(value: float | None) -> str:
    if value is None:
        return ""
    return MONEY_FORMAT.format(value)
