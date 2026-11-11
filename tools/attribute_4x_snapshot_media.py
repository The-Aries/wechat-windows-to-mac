"""Read-only: find which chat references each month-folder media file of an older 4.x snapshot,
and whether that chat still exists in the live account.

`msg/file/<YYYY-MM>/...` and `msg/video/<YYYY-MM>/...` folders are not keyed by chat, so a missing file there
cannot be classified by its path. This script searches each file's base name (and, for videos, the name
without extension and `_thumb`) in the decompressed message_content and packed_info_data of every snapshot
message. Use it on the `file/...` and `video/...` paths that compare_4x_snapshot_media.py reports missing.

Usage: python attribute_4x_snapshot_media.py <snapshot_db_storage> <paths.txt> --account-dir <...> --wx4 <...> [--show-names]
"""
from __future__ import annotations

import argparse
import sys
import os
import collections
from pathlib import Path

import zstandard

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # also works with python -I
import common as c  # noqa: E402

ZD = zstandard.ZstdDecompressor()


def text(v) -> bytes:
    if v is None:
        return b""
    b = v if isinstance(v, bytes) else str(v).encode("utf-8")
    if b[:4] == b"\x28\xb5\x2f\xfd":
        try:
            return ZD.decompress(b, max_output_size=64 << 20)
        except zstandard.ZstdError:
            return b
    return b


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("snapshot", type=Path)
    ap.add_argument("paths", type=Path, help="text file, one relative media path per line (e.g. file/2023-04/a.docx)")
    c.add_common_args(ap)
    ap.add_argument("--show-names", action="store_true", help="print file paths of items in chats that still exist")
    args = ap.parse_args()
    c.init_wx4(args.wx4)
    paths = [p.strip() for p in open(args.paths, encoding="utf-8") if p.strip()]
    needles = collections.defaultdict(set)
    for p in paths:
        name = p.rsplit("/", 1)[-1]
        needles[name.encode("utf-8")].add(p)
        stem = name.split(".", 1)[0].removesuffix("_thumb")
        if p.startswith("video/") and len(stem) >= 16:
            needles[stem.encode("utf-8")].add(p)

    cur = args.account_dir / "db_storage"
    keys = c.scan_keys(cur, args.snapshot)
    owner = collections.defaultdict(set)  # path -> {md5(username)}
    with c.temp_dir(args.tmp_root) as tmp:
        for shard in c.shards(args.snapshot):
            with c.open_plain(shard, keys, tmp) as db:
                for tb in c.msg_tables(db):
                    for mc, pk in db.execute(f"select message_content,packed_info_data from [{tb}] where local_type not in (1,10000)"):
                        blob = text(mc) + b"\x00" + text(pk)
                        for n, ps in needles.items():
                            if n in blob:
                                for p in ps:
                                    owner[p].add(tb[4:])
        alive = c.alive_chats(cur, keys, tmp)

    res = collections.Counter()
    for p in paths:
        top = p.split("/", 1)[0]
        o = owner.get(p, set())
        present = o & alive
        res[top + ("_unattributed" if not o else "_a_chat_present" if present else "_b_chat_removed")] += 1
        if present:
            item = {"month": p.split("/")[1] if "/" in p else None, "ext": Path(p).suffix,
                    "chats": sorted(t[:8] for t in present)}
            if args.show_names:
                item["path"] = p
            c.emit("A_ITEM", item)
    c.emit("ATTRIBUTION", dict(sorted(res.items())))


if __name__ == "__main__":
    main()
