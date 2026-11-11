"""Read-only: are all messages of a decrypted old Android `EnMicroMsg.db` present in current Windows WeChat 4.x?

Matches Android `msgSvrId` with 4.x `server_id`, per talker (`Msg_<md5(talker)>`). Prints counts only.
With --deep, every matched message is also checked for same talker, time, base type and content
(zstd content is decompressed). Expect some content differences for emoji: Android and PC store some
emoji with different code points, so "content_differs" is not a missing message.

Usage: python compare_android_vs_4x.py <android_plain.db> --account-dir <...> --wx4 <WeChatMsg-4x> [--deep]
"""
from __future__ import annotations

import argparse
import sys
import os
import collections
import sqlite3
from contextlib import closing
from datetime import datetime

import zstandard

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # also works with python -I
import common as c  # noqa: E402

ZD = zstandard.ZstdDecompressor()


def norm(v) -> bytes:
    if v is None:
        return b""
    if isinstance(v, str):
        v = v.encode("utf-8", "surrogatepass")
    if v[:4] == b"\x28\xb5\x2f\xfd":
        try:
            v = ZD.decompress(v, max_output_size=64 << 20)
        except zstandard.ZstdError:
            pass
    return v.strip()


def content_class(a: bytes, w: bytes) -> str:
    if a == w:
        return "content_identical"
    if not a and not w:
        return "both_empty"
    if not w:
        return "windows_empty"
    if not a:
        return "android_empty"
    if a in w or w in a:
        return "content_contained"
    return "content_differs"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("android_db")
    c.add_common_args(ap)
    ap.add_argument("--deep", action="store_true", help="also compare time, type and content of matched messages")
    args = ap.parse_args()
    c.init_wx4(args.wx4)

    android = {}  # svrid -> (talker, create_time_s, type, content)
    with closing(sqlite3.connect(f"file:{args.android_db}?mode=ro", uri=True)) as adb:
        for talker, svr, ct, typ, content in adb.execute("select talker,msgSvrId,createTime,type,content from message"):
            android[int(svr or 0)] = (talker, int(ct or 0) // 1000, int(typ or 0), norm(content) if args.deep else b"")
    talkers = {v[0] for v in android.values()}
    c.emit("ANDROID", {"messages": len(android), "talkers": len(talkers)})

    storage = args.account_dir / "db_storage"
    keys = c.scan_keys(storage)
    tables = {"Msg_" + c.md5(t): t for t in talkers}
    win = {}  # server_id -> (talker, create_time, base_type, content)
    win_times = collections.defaultdict(collections.Counter)
    with c.temp_dir(args.tmp_root) as tmp:
        for shard in c.shards(storage):
            with c.open_plain(shard, keys, tmp) as db:
                have = set(c.msg_tables(db))
                for tb, talker in tables.items():
                    if tb not in have:
                        continue
                    for sid, ct, lt, mc in db.execute(f"select server_id,create_time,local_type,message_content from [{tb}]"):
                        win[int(sid or 0)] = (talker, int(ct or 0), int(lt or 0) & 0xFFFFFFFF, norm(mc) if args.deep else b"")
                        win_times[talker][int(ct or 0)] += 1

    per = collections.defaultdict(collections.Counter)
    res = collections.Counter()
    for sid, (talker, ct, typ, content) in android.items():
        key = c.md5(talker)[:8]
        w = win.get(sid)
        if not w:
            per[key]["missing"] += 1
            per[key]["missing_but_same_time_exists"] += bool(win_times[talker].get(ct))
            per[key]["missing_" + datetime.fromtimestamp(ct).strftime("%Y-%m")] += 1
            res["missing"] += 1
            continue
        per[key]["found"] += 1
        res["found"] += 1
        if args.deep:
            res["same_talker" if w[0] == talker else "diff_talker"] += 1
            res["same_time" if w[1] == ct else "diff_time"] += 1
            res["same_type" if w[2] == (typ & 0xFFFFFFFF) else "diff_type"] += 1
            res[content_class(content, w[3])] += 1
    for key, cnt in sorted(per.items(), key=lambda kv: -sum(kv[1].values())):
        c.emit("TALKER", {"talker_md5_8": key, **dict(cnt)})
    c.emit("TOTAL", {"android_messages": len(android), **dict(res)})


if __name__ == "__main__":
    main()
