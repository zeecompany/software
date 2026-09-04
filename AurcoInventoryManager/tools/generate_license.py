from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aurco.core import licensing as L  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate an AURCO offline license key.")
    ap.add_argument("installation_id", help="Customer installation id shown by the activation dialog")
    ap.add_argument("--customer", default="", help="Customer/company name")
    ap.add_argument("--expires", default="", help="Expiry date YYYY-MM-DD (blank = perpetual)")
    ap.add_argument("--seats", type=int, default=1, help="Seat count metadata")
    ap.add_argument("--note", default="", help="Optional note")
    args = ap.parse_args()
    print(L.generate_license_key(args.installation_id, args.customer, args.expires,
                                 args.seats, args.note))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
