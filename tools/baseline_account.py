"""Read-only message baseline of the logged-in WeChat 4.x account on Windows.

Prints: self-contact check, session count, per-shard rows, totals by year and message type, and the largest
chats. Chats are shown as md5(username)[:8] unless --show-names is given. No message bodies are printed.
Take a baseline before cleanup or migration so the result can be checked against numbers later.

Usage: python baseline_account.py --account-dir <xwechat_files\\wxid_xxx_1a2b> --wx4 <WeChatMsg-4x> [--show-names]
"""
from __future__ import annotations

import argparse
import sys
import os
import collections
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # also works with python -I
import common as c  # noqa: E402


def dt(ts):
    try:
        return datetime.fromtimestamp(int(ts)).isoformat(timespec="seconds") if ts else None
    except (OSError, ValueError, OverflowError):
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    c.add_common_args(ap)
    ap.add_argument("--show-names", action="store_true", help="print contact names instead of hashes")
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()
    c.init_wx4(args.wx4)
    storage = args.account_dir / "db_storage"
    if not storage.is_dir():
        raise SystemExit("db_storage not found under --account-dir")
    wxid = c.account_wxid(args.account_dir)
    keys = c.scan_keys(storage)

    names, sessions = {}, {}
    rows_by_chat = collections.Counter()
    years, types = collections.Counter(), collections.Counter()
    total = 0
    lo_hi = []
    errors = []
    with c.temp_dir(args.tmp_root) as tmp:
        with c.open_plain(storage / "contact" / "contact.db", keys, tmp) as db:
            rows = db.execute("select username,nick_name,remark,alias from contact").fetchall()
            names = {u: remark or nick or alias or u for u, nick, remark, alias in rows}
            c.emit("PROFILE", {"wxid": wxid, "self_contact_found": wxid in names, "contacts": len(rows),
                               "group_contacts": sum(u.endswith("@chatroom") for u in names)})
        with c.open_plain(storage / "session" / "session.db", keys, tmp) as db:
            cols = {r[1] for r in db.execute("pragma table_info(SessionTable)")}
            ts_col = "last_timestamp" if "last_timestamp" in cols else "0"
            sessions = {u: t for u, t in db.execute(f"select username,{ts_col} from SessionTable") if u}
            c.emit("SESSIONS", {"rows": len(sessions), "groups": sum(u.endswith("@chatroom") for u in sessions)})
        lookup = {"Msg_" + c.md5(u): u for u in set(names) | set(sessions)}
        for shard in c.shards(storage):
            start = time.monotonic()
            try:
                with c.open_plain(shard, keys, tmp) as db:
                    shard_rows = 0
                    for tb in c.msg_tables(db):
                        n, lo, hi = db.execute(f"select count(*),min(create_time),max(create_time) from [{tb}]").fetchone()
                        shard_rows += n
                        total += n
                        rows_by_chat[tb] += n
                        lo_hi += [x for x in (lo, hi) if x]
                        for y, k in db.execute(f"select strftime('%Y',create_time,'unixepoch'),count(*) from [{tb}] group by 1"):
                            years[str(y)] += k
                        for t, k in db.execute(f"select local_type & 4294967295,count(*) from [{tb}] group by 1"):
                            types[str(t)] += k
                    c.emit("SHARD", {"db": shard.name, "rows": shard_rows, "elapsed_s": round(time.monotonic() - start, 1)})
            except RuntimeError as exc:
                errors.append({"db": shard.name, "error": str(exc)})
                c.emit("ERROR", errors[-1])

    def label(tb):
        u = lookup.get(tb)
        return names.get(u, u) if (args.show_names and u) else tb[4:12]

    c.emit("MESSAGE_SUMMARY", {
        "errors": errors, "message_rows": total, "message_tables": len(rows_by_chat),
        "tables_without_known_user": sum(tb not in lookup for tb in rows_by_chat),
        "oldest": dt(min(lo_hi)) if lo_hi else None, "newest": dt(max(lo_hi)) if lo_hi else None,
        "by_year": dict(sorted(years.items())), "base_types_top": dict(types.most_common(15)),
    })
    c.emit("TOP_CHATS", [{"chat": label(tb), "is_group": (lookup.get(tb) or "").endswith("@chatroom"),
                          "rows": n, "in_session_list": lookup.get(tb) in sessions}
                         for tb, n in rows_by_chat.most_common(args.top)])


if __name__ == "__main__":
    main()
