"""Read-only: which messages of an older WeChat 4.x snapshot of the same account are missing from the live account?

The snapshot folder is a copy of an older `db_storage` (at least `message/message_N.db` and `session/session.db`,
with -wal/-shm). Keys are scanned from the running Weixin process; old salts that no key matches are reported.
Messages are matched per `Msg_<md5(username)>` table by server_id, or by (create_time, local_type) when
server_id is 0 (local-only rows). Missing rows are split into:
  (a) chat still exists now (in the session list or with rows) - a real gap or a cleared chat;
  (b) chat no longer exists - the chat was deleted.
Prints counts only.

Usage: python compare_4x_snapshot_messages.py <snapshot_db_storage> --account-dir <...> --wx4 <WeChatMsg-4x>
"""
from __future__ import annotations

import argparse
import sys
import os
import collections
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # also works with python -I
import common as c  # noqa: E402


def read_rows(storage: Path, keys: dict, tmp: Path, failed: list) -> dict:
    rows = collections.defaultdict(list)  # table -> [(server_id, base_type, create_time)]
    for shard in c.shards(storage):
        try:
            with c.open_plain(shard, keys, tmp) as db:
                for tb in c.msg_tables(db):
                    rows[tb] += [(int(s or 0), int(t or 0) & 0xFFFFFFFF, int(ct or 0))
                                 for s, t, ct in db.execute(f"select server_id,local_type,create_time from [{tb}]")]
        except RuntimeError as exc:
            failed.append({"db": str(shard.relative_to(storage)), "error": str(exc)})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("snapshot", type=Path)
    c.add_common_args(ap)
    args = ap.parse_args()
    c.init_wx4(args.wx4)
    cur = args.account_dir / "db_storage"
    keys = c.scan_keys(cur, args.snapshot)
    failed = []
    with c.temp_dir(args.tmp_root) as tmp:
        snap_rows = read_rows(args.snapshot, keys, tmp, failed)
        cur_rows = read_rows(cur, keys, tmp, failed)
        snap_sess = c.session_usernames(args.snapshot, keys, tmp)
        cur_sess = c.session_usernames(cur, keys, tmp)
    c.emit("UNDECRYPTABLE", failed)
    cur_sess_tables = {"Msg_" + c.md5(u) for u in cur_sess}
    groups = {"Msg_" + c.md5(u) for u in snap_sess | cur_sess if u.endswith("@chatroom")}
    c.emit("TOTALS", {"snapshot_tables": len(snap_rows), "snapshot_rows": sum(map(len, snap_rows.values())),
                      "current_tables": len(cur_rows), "current_rows": sum(map(len, cur_rows.values())),
                      "snapshot_sessions": len(snap_sess), "current_sessions": len(cur_sess)})

    summary = collections.Counter()
    gaps = []
    for tb, rows in snap_rows.items():
        have = cur_rows.get(tb, [])
        ids = {s for s, _, _ in have if s}
        local = collections.Counter((ct, t) for s, t, ct in have if not s)
        missing = []
        for s, t, ct in rows:
            if s:
                if s not in ids:
                    missing.append((t, ct))
            elif local[(ct, t)] > 0:
                local[(ct, t)] -= 1
            else:
                missing.append((t, ct))
        summary["snapshot_rows"] += len(rows)
        summary["found"] += len(rows) - len(missing)
        if not missing:
            continue
        present = tb in cur_sess_tables or bool(have)
        cls = "a_chat_present" if present else "b_chat_removed"
        summary[cls + "_rows"] += len(missing)
        summary[cls + "_chats"] += 1
        if present:
            months = collections.Counter(datetime.fromtimestamp(ct).strftime("%Y-%m") for _, ct in missing if ct)
            gaps.append({"table_md5_8": tb[4:12], "is_group": tb in groups, "snapshot_rows": len(rows),
                         "current_rows": len(have), "in_session_list": tb in cur_sess_tables,
                         "missing": len(missing),
                         "missing_types": dict(collections.Counter(t for t, _ in missing).most_common(6)),
                         "first_month": min(months) if months else None,
                         "last_month": max(months) if months else None})
    c.emit("SUMMARY", dict(summary))
    for g in sorted(gaps, key=lambda g: -g["missing"]):
        c.emit("GAP_A", g)


if __name__ == "__main__":
    main()
