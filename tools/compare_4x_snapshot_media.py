"""Read-only: which media files of an older WeChat 4.x `msg/` folder are missing from the live account?

Input is either the snapshot `msg/` folder itself or a TSV listing of it, one line per file:
`<bytes>\\t./<relative path>`. On macOS, for a drive mounted there, a listing can be made with:
    cd "<snapshot>/msg" && find . -type f ! -name '._*' -exec stat -f '%z%t%N' {} +
Compares relative path + byte size (no hashing). `attach/<md5(username)>/...` files are split into chats
that still exist now (a) and chats that were removed (b). Prints counts only.

Usage: python compare_4x_snapshot_media.py <snapshot_msg_dir_or_listing.tsv> --account-dir <...> --wx4 <WeChatMsg-4x>
"""
from __future__ import annotations

import argparse
import sys
import collections
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # also works with python -I
import common as c  # noqa: E402


def walk(root: Path) -> dict:
    out = {}
    for base, _, files in os.walk(root):
        for f in files:
            if f.startswith("._") or f == ".DS_Store":
                continue
            p = os.path.join(base, f)
            out[os.path.relpath(p, root).replace("\\", "/")] = os.path.getsize(p)
    return out


def read_listing(path: Path) -> dict:
    out = {}
    for line in open(path, encoding="utf-8"):
        size, _, rel = line.rstrip("\n").partition("\t")
        if rel:
            out[rel[2:] if rel.startswith("./") else rel] = int(size)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("snapshot", type=Path)
    c.add_common_args(ap)
    args = ap.parse_args()
    c.init_wx4(args.wx4)
    snap = walk(args.snapshot) if args.snapshot.is_dir() else read_listing(args.snapshot)
    local = walk(args.account_dir / "msg")
    storage = args.account_dir / "db_storage"
    keys = c.scan_keys(storage)
    with c.temp_dir(args.tmp_root) as tmp:
        alive = c.alive_chats(storage, keys, tmp)

    stat = collections.Counter()
    gaps = collections.defaultdict(collections.Counter)
    for rel, size in snap.items():
        parts = rel.split("/")
        top = parts[0]
        if local.get(rel) == size:
            stat[top + "_same"] += 1
            continue
        kind = "size_differs" if rel in local else "missing"
        if top == "attach" and len(parts) > 1:
            cls = "a_chat_present" if parts[1] in alive else "b_chat_removed"
            stat[f"attach_{kind}_{cls}"] += 1
            stat[f"attach_{kind}_{cls}_bytes"] += size
            if cls == "a_chat_present":
                gaps["attach:" + parts[1][:8]][kind] += 1
                gaps["attach:" + parts[1][:8]]["bytes"] += size
        else:
            stat[f"{top}_{kind}"] += 1
            stat[f"{top}_{kind}_bytes"] += size
            if top in ("file", "video") and len(parts) > 2:
                gaps[top + ":" + parts[1]][kind] += 1
    c.emit("SNAPSHOT_FILES", len(snap))
    c.emit("LOCAL_FILES", len(local))
    c.emit("STATS", dict(sorted(stat.items())))
    for key, g in sorted(gaps.items(), key=lambda kv: -(kv[1]["missing"] + kv[1]["size_differs"])):
        c.emit("GAP", {"key": key, **dict(g)})


if __name__ == "__main__":
    main()
