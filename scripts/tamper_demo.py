"""Show that the audit hash chain notices edits made directly in the database.

Run it while the server is running (it edits one audit row, checks, then puts it back):

    python scripts\\tamper_demo.py --api-key <your STAFF_API_KEY>

This demonstrates DETECTION, not prevention: anyone with access to the database file can still
change it. See docs/security.md.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.config import Settings, sqlite_path  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", required=True)
    args = parser.parse_args()

    settings = Settings.load(ROOT / ".env")
    path = Path(sqlite_path(settings.database_url))
    path = path if path.is_absolute() else ROOT / path
    staff = {"X-API-Key": args.api_key}

    def verify() -> dict:
        return httpx.get(f"{args.base_url}/audit/verify", headers=staff, timeout=30).json()

    print("1. Verify the untouched log")
    before = verify()
    print("  ", before)
    if before["events_checked"] == 0:
        print("   The log is empty. Run scripts\\demo.py first.")
        return 1
    if not before["valid"]:
        print("   The log is already invalid; not touching it.")
        return 1

    conn = sqlite3.connect(path, timeout=10)
    row = conn.execute("SELECT seq, outcome FROM audit_events ORDER BY seq LIMIT 1 OFFSET 1").fetchone()
    if row is None:
        row = conn.execute("SELECT seq, outcome FROM audit_events ORDER BY seq LIMIT 1").fetchone()
    seq, original = row
    forged = "forged" if original != "forged" else "restored"

    print(f"\n2. Someone edits audit event #{seq} directly in SQLite (outcome '{original}' -> '{forged}')")
    conn.execute("UPDATE audit_events SET outcome = ? WHERE seq = ?", (forged, seq))
    conn.commit()
    try:
        print("3. Verify again")
        after = verify()
        print("  ", after)
        print("\n   -> tampering DETECTED" if not after["valid"] else "\n   -> NOT detected (unexpected!)")
    finally:
        conn.execute("UPDATE audit_events SET outcome = ? WHERE seq = ?", (original, seq))
        conn.commit()
        conn.close()

    print("\n4. Original value restored. Verify one more time")
    final = verify()
    print("  ", final)
    return 0 if (not after["valid"] and final["valid"]) else 1


if __name__ == "__main__":
    sys.exit(main())
