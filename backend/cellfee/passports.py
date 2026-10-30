"""Battery passports stored one row per battery (zlib-compressed JSON in SQLite), so opening a passport reads
only that battery. Loading the whole 58 MB fleet_details.json costs ~180 MB of memory, more than a small
cloud instance can spare.   python -m cellfee.passports   rebuilds artifacts/fleet_details.db from the JSON."""

from __future__ import annotations

import json
import sqlite3
import zlib

from . import config

DB = config.ARTIFACTS / "fleet_details.db"
JSON = config.ARTIFACTS / "fleet_details.json"


def write(detail: dict) -> None:
    tmp = DB.with_suffix(".db.tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.execute("CREATE TABLE passports (id TEXT PRIMARY KEY, doc BLOB NOT NULL)")
    con.executemany("INSERT INTO passports VALUES (?, ?)",
                    ((k, zlib.compress(json.dumps(v, default=float).encode(), 9)) for k, v in detail.items()))
    con.commit()
    con.execute("VACUUM")
    con.close()
    tmp.replace(DB)


def get(battery_id: str) -> dict:
    if not DB.exists():                       # older artifacts: build the database once from the JSON
        write(json.loads(JSON.read_text()))
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT doc FROM passports WHERE id = ?", (battery_id,)).fetchone()
    finally:
        con.close()
    return json.loads(zlib.decompress(row[0])) if row else {}


if __name__ == "__main__":
    write(json.loads(JSON.read_text()))
    print(f"{DB} written ({DB.stat().st_size / 2**20:.1f} MB)")
