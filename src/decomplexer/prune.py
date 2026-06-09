from __future__ import annotations

import argparse
import shutil
import sqlite3
from pathlib import Path

def act_dir(data_dir: Path, signature: str) -> Path:
    letters, number, year = signature.split("/")
    return data_dir / "files" / letters / year / f"{letters}-{number}-{year}"

def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())

def not_in_force(db_path: Path) -> list[str]:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT signature FROM acts WHERE obowiazuje = 0 ORDER BY signature"
        )
        return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()

def _clear_file_markers(db_path: Path, signature: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE acts SET content_local_path = NULL WHERE signature = ?", (signature,)
        )
        conn.execute(
            "UPDATE attachments SET downloaded = 0, local_path = NULL "
            "WHERE act_signature = ?",
            (signature,),
        )
        conn.commit()
    finally:
        conn.close()

def prune(data_dir: Path, *, apply: bool) -> tuple[int, int]:
    db_path = data_dir / "acts.sqlite"
    if not db_path.exists():
        raise SystemExit(f"no acts.sqlite found in {data_dir}")

    signatures = not_in_force(db_path)
    verb = "Deleting" if apply else "Would delete"
    acts = freed = 0
    for sig in signatures:
        d = act_dir(data_dir, sig)
        if not d.exists():
            continue
        size = _dir_size(d)
        print(f"{verb} {sig}: {d}  ({size:,} bytes)")
        if apply:
            shutil.rmtree(d)
            _clear_file_markers(db_path, sig)
        acts += 1
        freed += size

    head = "Pruned" if apply else "Dry run — nothing deleted."
    print(f"\n{head} {acts} not-in-force act(s), {freed:,} bytes"
          f"{'' if apply else ' would be freed (re-run with --apply)'}.")
    if not signatures:
        print("(No acts are flagged obowiazuje=0. Run `decomplexer update` first.)")
    return acts, freed

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parent,
                    help="Directory holding acts.sqlite + files/ (default: this script's dir)")
    ap.add_argument("--apply", action="store_true",
                    help="Actually delete (default is a safe dry run)")
    args = ap.parse_args(argv)
    prune(args.data_dir, apply=args.apply)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
