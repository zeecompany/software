"""Offline license keys for the packaged Windows application.

Practical design goals:
- the Windows EXE can require activation before use;
- the developer can generate a key for a customer's installation id;
- the activation key can be stored locally on each PC (not in the shared DB);
- source/dev runs stay convenient unless license enforcement is explicitly on.

This is a business-control feature, not military-grade DRM. For stronger secrecy,
set a private AURCO_LICENSE_SECRET before building your own Windows release.
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import hmac
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

from . import config

FORMAT_PREFIX = "AURCO1"
DEFAULT_SECRET = "AURCO-Inventory-License-2026-Private-Seed"
BOOT_LICENSE_KEY = "license_key"
BOOT_LICENSE_AT = "license_activated_at"
BOOT_CUSTOMER = "license_customer"
BOOT_INSTALLATION = "license_installation_id"


def _secret() -> str:
    return os.environ.get("AURCO_LICENSE_SECRET", DEFAULT_SECRET)


def should_enforce() -> bool:
    """Only the packaged EXE is locked by default; source runs stay developer-friendly."""
    return bool(getattr(sys, "frozen", False) or os.environ.get("AURCO_ENFORCE_LICENSE") == "1")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    text = str(text or "")
    return base64.urlsafe_b64decode(text + "=" * ((4 - len(text) % 4) % 4))


def today() -> str:
    return _dt.date.today().isoformat()


def machine_name() -> str:
    return (os.environ.get("COMPUTERNAME") or platform.node() or "UNKNOWN-PC").strip()


def installation_parts() -> dict[str, str]:
    appdata = config.appdata_dir()
    return {
        "brand": config.BRAND,
        "app": config.APP_SHORT,
        "machine": machine_name(),
        "platform": platform.system(),
        "release": platform.release(),
        "home": str(Path.home()),
        "appdata": str(appdata),
    }


def installation_id() -> str:
    raw = json.dumps(installation_parts(), sort_keys=True, separators=(",", ":"))
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()
    return f"AUR-{h[:6]}-{h[6:12]}-{h[12:18]}-{h[18:24]}"


def build_payload(installation: str, customer: str = "", expires_on: str = "",
                  seats: int = 1, note: str = "") -> dict[str, Any]:
    return {
        "v": 1,
        "app": config.APP_SHORT,
        "iid": str(installation or "").strip().upper(),
        "cust": str(customer or "").strip(),
        "exp": str(expires_on or "").strip(),
        "seats": max(1, int(seats or 1)),
        "note": str(note or "").strip(),
        "iat": today(),
    }


def generate_license_key(installation: str, customer: str = "", expires_on: str = "",
                         seats: int = 1, note: str = "") -> str:
    payload = build_payload(installation, customer, expires_on, seats, note)
    blob = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(_secret().encode("utf-8"), blob.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{FORMAT_PREFIX}.{blob}.{sig[:24].upper()}"


def parse_key(key: str) -> tuple[dict[str, Any] | None, str]:
    text = str(key or "").strip()
    try:
        prefix, blob, sig = text.split(".", 2)
    except ValueError:
        return None, "Invalid key format."
    if prefix != FORMAT_PREFIX:
        return None, "Unknown key prefix."
    exp = hmac.new(_secret().encode("utf-8"), blob.encode("ascii"), hashlib.sha256).hexdigest()[:24].upper()
    if not hmac.compare_digest(exp, sig.upper()):
        return None, "Signature check failed."
    try:
        payload = json.loads(_unb64(blob).decode("utf-8"))
    except Exception:
        return None, "The key payload could not be decoded."
    return payload, "ok"


def validate_license_key(key: str, installation: str | None = None) -> dict[str, Any]:
    payload, msg = parse_key(key)
    if not payload:
        return {"valid": False, "reason": msg, "payload": {}}
    if payload.get("app") != config.APP_SHORT:
        return {"valid": False, "reason": "This key was not issued for this application.",
                "payload": payload}
    cur = str(installation or installation_id()).strip().upper()
    if str(payload.get("iid") or "").upper() != cur:
        return {"valid": False, "reason": "This key belongs to a different installation.",
                "payload": payload}
    exp = str(payload.get("exp") or "").strip()
    if exp:
        try:
            if _dt.date.fromisoformat(exp) < _dt.date.today():
                return {"valid": False, "reason": f"This license expired on {exp}.",
                        "payload": payload}
        except ValueError:
            return {"valid": False, "reason": "The expiry date stored in this key is invalid.",
                    "payload": payload}
    return {"valid": True, "reason": "ok", "payload": payload}


def _read_boot() -> dict[str, Any]:
    return config.read_bootstrap()


def _write_boot(data: dict[str, Any]) -> None:
    config.write_bootstrap(data)


def apply_license_key(key: str) -> dict[str, Any]:
    res = validate_license_key(key)
    if not res["valid"]:
        return res
    boot = _read_boot()
    boot[BOOT_LICENSE_KEY] = str(key).strip()
    boot[BOOT_LICENSE_AT] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    boot[BOOT_CUSTOMER] = str(res["payload"].get("cust") or "")
    boot[BOOT_INSTALLATION] = installation_id()
    _write_boot(boot)
    return res


def clear_license_key() -> None:
    boot = _read_boot()
    for k in (BOOT_LICENSE_KEY, BOOT_LICENSE_AT, BOOT_CUSTOMER, BOOT_INSTALLATION):
        boot.pop(k, None)
    _write_boot(boot)


def current_status() -> dict[str, Any]:
    key = str(_read_boot().get(BOOT_LICENSE_KEY) or "").strip()
    if not key:
        return {
            "valid": False,
            "reason": "No license key has been activated on this PC yet.",
            "payload": {},
            "installation_id": installation_id(),
            "machine": machine_name(),
            "activated_at": "",
        }
    res = validate_license_key(key)
    boot = _read_boot()
    res["installation_id"] = installation_id()
    res["machine"] = machine_name()
    res["activated_at"] = str(boot.get(BOOT_LICENSE_AT) or "")
    res["key"] = key
    return res


def customer_label(payload: dict[str, Any] | None) -> str:
    p = payload or {}
    cust = str(p.get("cust") or "").strip() or "Licensed user"
    exp = str(p.get("exp") or "").strip()
    return cust + (f" · expires {exp}" if exp else " · perpetual")
