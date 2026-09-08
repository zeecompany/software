"""AURCO Inventory Manager - application configuration & storage layout.

The *bootstrap* config (which tells the app where the data folder lives) is kept
in the user profile:  %APPDATA%\\AURCO\\AurcoInventoryManager\\bootstrap.json
Everything else (company info, thresholds, SMTP, numbering...) lives in the
database in the selected storage folder, so a whole installation can be moved
by copying one directory.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "AURCO Inventory Manager"
APP_SHORT = "AurcoInventoryManager"
BRAND = "AURCO"
CREATED_BY = "Zain Shami"
APP_VERSION = "2.28.1"

# Sub-folders automatically created inside the storage root.
SUBFOLDERS = [
    "Database",
    "Inventory",
    "Reversed Inventory",
    "Delivery Notes",
    "Reversed Delivery Notes",
    "Returns",
    "Reversed Returns",
    "Stock Transfers",
    "Reversed Stock Transfers",
    "Stock Adjustments",
    "Reversed Stock Adjustments",
    "Stock Counts",
    "Reversed Stock Counts",
    "Reports",
    "Attachments",
    "Exports",
    "Backups",
    "Logs",
    "Admin Station",
    "Company Issuance",
    "Employee PPE Register",
    "Tools, Instruments & Devices",
    "Cable Records",
    "Labels",
]


def is_windows() -> bool:
    return os.name == "nt"


def appdata_dir() -> Path:
    if is_windows():
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    p = base / "AURCO" / APP_SHORT
    p.mkdir(parents=True, exist_ok=True)
    return p


BOOTSTRAP_FILE = appdata_dir() / "bootstrap.json"


def default_storage_root() -> Path:
    """D:\\AURCO Inventory when a D: drive exists, else Documents/Home."""
    if is_windows():
        for drive in ("D:", "E:"):
            if Path(drive + "\\").exists():
                return Path(drive + "\\") / "AURCO Inventory"
        return Path.home() / "Documents" / "AURCO Inventory"
    return Path.home() / "AURCO Inventory"


def read_bootstrap() -> dict:
    if BOOTSTRAP_FILE.exists():
        try:
            return json.loads(BOOTSTRAP_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def write_bootstrap(data: dict) -> None:
    BOOTSTRAP_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_storage_root() -> Path | None:
    data = read_bootstrap()
    root = data.get("storage_root")
    return Path(root) if root else None


def set_storage_root(path: str | os.PathLike) -> Path:
    root = Path(path)
    ensure_structure(root)
    data = read_bootstrap()
    data["storage_root"] = str(root)
    write_bootstrap(data)
    return root


def ensure_structure(root: str | os.PathLike) -> Path:
    """Create the AURCO folder tree. Raises OSError when not writable."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for sub in SUBFOLDERS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    probe = root / ".aurco_write_test"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()
    return root


def folder(name: str) -> Path:
    root = get_storage_root() or default_storage_root()
    p = Path(root) / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def bundled_logo() -> Path | None:
    """The AURCO brand logo shipped with the application, if present."""
    for name in ("aurco_brand_logo.png", "aurco_logo.png"):
        p = resource_path(f"assets/{name}")
        if p.exists():
            return p
    return None


def db_path() -> Path:
    return folder("Database") / "aurco_inventory.db"


def resource_path(rel: str) -> Path:
    """Works both from source and from a PyInstaller one-file bundle."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / rel
