"""Read-only: how many voice messages in the chat list still have their audio? (WeChat 4.x, Windows)

In 4.x the message row (type 34) and the audio (`VoiceInfo.voice_data` in `message/media_*.db`) are stored apart.
A voice message without audio shows in the chat but cannot play, and official migration skips it entirely.
Run this before migrating to know which voice messages cannot move. Optional extra `db_storage` copies (older
backups of the same account) are checked for the missing audio too.

Usage: python check_voice_audio.py --account-dir <...> --wx4 <...> [--extra <old db_storage> ...]
"""
from __future__ import annotations

import argparse
import collections
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # also works with python -I
import common as c  # noqa: E402


def audio(storage, keys, tmp):
    have = set()
    for m in sorted((storage / "message").glob("media_*.db")):
        with c.open_plain(m, keys, tmp) as db:
            n2 = {r[0]: r[1] for r in db.execute("select rowid,user_name from Name2Id")}
            for cid, sid, ln in db.execute("select chat_name_id,svr_id,length(voice_data) from VoiceInfo"):
                if ln:
                    have.add(("Msg_" + c.md5(n2.get(cid, "")), int(sid)))
    return have


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    c.add_common_args(ap)
    ap.add_argument("--extra", type=Path, nargs="*", default=[], help="older db_storage copies to search")
    a = ap.parse_args()
    c.init_wx4(a.wx4)
    st = a.account_dir / "db_storage"
    keys = c.scan_keys(st, *a.extra)
    with c.temp_dir(a.tmp_root) as tmp:
        have = audio(st, keys, tmp)
        visible = {"Msg_" + c.md5(u) for u in c.session_usernames(st, keys, tmp)}
        missing = []
        by_year = collections.Counter()
        for sh in c.shards(st):
            with c.open_plain(sh, keys, tmp) as db:
                for tb in c.msg_tables(db):
                    if tb not in visible:
                        continue
                    for sid, ct in db.execute(f"select server_id,create_time from [{tb}] where (local_type & 4294967295)=34"):
                        ok = (tb, int(sid or 0)) in have
                        by_year[(datetime.fromtimestamp(ct).year, ok)] += 1
                        if not ok:
                            missing.append((tb, int(sid or 0)))
        for y in sorted({y for y, _ in by_year}):
            c.emit("YEAR", {"year": y, "with_audio": by_year[(y, True)], "without_audio": by_year[(y, False)]})
        for ex in a.extra:
            h = audio(ex, keys, tmp)
            c.emit("EXTRA", {"storage": ex.name, "audio_entries": len(h), "covers_missing": sum(m in h for m in missing)})
    c.emit("TOTAL_WITHOUT_AUDIO", len(missing))


if __name__ == "__main__":
    main()
