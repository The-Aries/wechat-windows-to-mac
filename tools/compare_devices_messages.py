"""Read-only: compare every message of the live Windows account with a copy of another device's `db_storage`
(for example the Mac after migration). Prints counts per chat (md5[:8], or names with --show-names).

The other device's databases must be copied while its WeChat is not running (`message/`, `session/`, `contact/`),
and its keys given as JSON {salt_hex: key_hex} (see mac_capture_keys.py). Keys are only read, never printed.
Messages after --cutoff are ignored, because the two devices were online at different times.
Missing messages are split into chats that are in the Windows chat list (what you can see) and chats that are not.

Usage: python compare_devices_messages.py <other_db_storage_copy> <other_keys.json> --account-dir <...> --wx4 <...>
       [--cutoff 2026-11-10] [--show-names] [--tsv out.tsv]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # also works with python -I
import common as c  # noqa: E402

TYPES = {1: "text", 3: "image", 34: "voice", 43: "video", 47: "emoji", 49: "app/file/link",
         10000: "system", 42: "card", 48: "location", 50: "call"}


def rows(storage, keys, tmp):
    out = collections.defaultdict(list)
    for sh in c.shards(storage):
        with c.open_plain(sh, keys, tmp) as db:
            for tb in c.msg_tables(db):
                out[tb] += [(int(s or 0), int(t or 0) & 0xFFFFFFFF, int(ct or 0))
                            for s, t, ct in db.execute(f"select server_id,local_type,create_time from [{tb}]")]
    return out


def names(storage, keys, tmp):
    with c.open_plain(storage / "contact" / "contact.db", keys, tmp) as db:
        return {"Msg_" + c.md5(u): (r or n or u) for u, n, r in db.execute("select username,nick_name,remark from contact")}


def diff(a, b):
    ids = {s for s, _, _ in b if s}
    loc = collections.Counter((ct, t) for s, t, ct in b if not s)
    out = []
    for s, t, ct in a:
        if s:
            if s not in ids:
                out.append((t, ct))
        elif loc[(ct, t)] > 0:
            loc[(ct, t)] -= 1
        else:
            out.append((t, ct))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("other_storage", type=Path)
    ap.add_argument("other_keys", type=Path)
    c.add_common_args(ap)
    ap.add_argument("--cutoff", default=None, help="YYYY-MM-DD; ignore messages from this day on")
    ap.add_argument("--show-names", action="store_true")
    ap.add_argument("--tsv", type=Path, help="write per-chat details (contains names if --show-names)")
    a = ap.parse_args()
    c.init_wx4(a.wx4)
    cut = int(datetime.strptime(a.cutoff, "%Y-%m-%d").timestamp()) if a.cutoff else 1 << 62
    win_st = a.account_dir / "db_storage"
    win_keys = c.scan_keys(win_st)
    other_keys = json.loads(a.other_keys.read_text())
    with c.temp_dir(a.tmp_root) as tmp:
        W, O = rows(win_st, win_keys, tmp), rows(a.other_storage, other_keys, tmp)
        ws = {"Msg_" + c.md5(u) for u in c.session_usernames(win_st, win_keys, tmp)}
        os_ = {"Msg_" + c.md5(u) for u in c.session_usernames(a.other_storage, other_keys, tmp)}
        nm = {}
        if a.show_names:
            nm = {**names(a.other_storage, other_keys, tmp), **names(win_st, win_keys, tmp)}
    label = lambda tb: nm.get(tb, tb[4:12])  # noqa: E731
    c.emit("TOTALS", {"windows_rows": sum(map(len, W.values())), "other_rows": sum(map(len, O.values())),
                      "windows_sessions": len(ws), "other_sessions": len(os_)})
    missing = []
    summary = collections.Counter()
    for tb, r in W.items():
        m = diff([x for x in r if x[2] < cut], O.get(tb, []))
        if m:
            vis = "visible" if tb in ws else "not_in_chat_list"
            summary[vis + "_rows"] += len(m)
            summary[vis + "_chats"] += 1
            missing.append((tb, vis, m))
    extra = sum(len(diff([x for x in r if x[2] < cut], W.get(tb, []))) for tb, r in O.items())
    summary["other_rows_not_on_windows"] = extra
    c.emit("MISSING_ON_OTHER", dict(summary))
    vt = collections.Counter(TYPES.get(t, str(t)) for _, v, m in missing if v == "visible" for t, _ in m)
    c.emit("VISIBLE_MISSING_BY_TYPE", dict(vt.most_common()))
    missing.sort(key=lambda x: -len(x[2]))
    for tb, vis, m in missing[:30]:
        c.emit("CHAT", {"chat": label(tb), "visible": vis == "visible", "missing": len(m), "other_has_chat": tb in O,
                        "types": dict(collections.Counter(TYPES.get(t, str(t)) for t, _ in m).most_common(4))})
    if a.tsv:
        with open(a.tsv, "w", encoding="utf-8-sig", newline="\n") as f:
            f.write("chat\tvisible\tmissing\ttypes\tmonths\n")
            for tb, vis, m in missing:
                ty = dict(collections.Counter(TYPES.get(t, str(t)) for t, _ in m))
                mo = dict(sorted(collections.Counter(datetime.fromtimestamp(ct).strftime("%Y-%m") for _, ct in m if ct).items()))
                f.write(f"{label(tb)}\t{vis == 'visible'}\t{len(m)}\t{json.dumps(ty, ensure_ascii=False)}\t{json.dumps(mo)}\n")


if __name__ == "__main__":
    main()
