"""Read-only, no key needed: does a WeChat 4.x account folder cover the chats and months of an old 3.x folder?

3.x stores chat attachments in `FileStorage/MsgAttach/<md5(username)>/<Image|Thumb|File|...>/<YYYY-MM>/` and
4.x in `msg/attach/<md5(username)>/<YYYY-MM>/`. Both use the same md5, so (chat, month) pairs can be compared
without decrypting anything. A full match supports, but does not prove, that the 4.x data holds the 3.x
history: it says nothing about text messages. A message-level check needs the 3.x key, which can only be
read from a 3.x client logged in to that account.

Pure standard library; runs on Windows or macOS (for example directly against a mounted backup drive).
Usage: python compare_3x_4x_attach_coverage.py <3x WeChat Files/wxid_xxx> <4x xwechat_files/wxid_xxx_1a2b>
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

MONTH = re.compile(r"20\d\d-\d\d")


def pairs_3x(root: Path) -> collections.Counter:
    out = collections.Counter()
    base = root / "FileStorage" / "MsgAttach"
    for month_dir in base.glob("*/*/*"):
        if month_dir.is_dir() and MONTH.fullmatch(month_dir.name):
            out[(month_dir.parent.parent.name, month_dir.name)] += sum(1 for f in month_dir.iterdir() if f.is_file())
    return out


def pairs_4x(root: Path) -> collections.Counter:
    out = collections.Counter()
    for month_dir in (root / "msg" / "attach").glob("*/*"):
        if month_dir.is_dir() and MONTH.fullmatch(month_dir.name):
            out[(month_dir.parent.name, month_dir.name)] += sum(1 for f in month_dir.rglob("*") if f.is_file())
    return out


def months_3x(root: Path) -> collections.Counter:
    out = collections.Counter()
    for f in (root / "FileStorage").rglob("*"):
        if f.is_file() and not f.name.startswith("."):
            m = next((p for p in f.parts if MONTH.fullmatch(p)), None)
            if m:
                out[m] += 1
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dir_3x", type=Path)
    ap.add_argument("dir_4x", type=Path)
    args = ap.parse_args()
    p3, p4 = pairs_3x(args.dir_3x), pairs_4x(args.dir_4x)
    db3 = sorted((f.relative_to(args.dir_3x).as_posix(), f.stat().st_size)
                 for f in (args.dir_3x / "Msg" / "Multi").glob("MSG*.db"))
    out = lambda tag, obj: print(tag, json.dumps(obj, ensure_ascii=True), flush=True)  # noqa: E731
    out("3X_MSG_DBS", db3)
    out("3X_FILESTORAGE_MONTHS", dict(sorted(months_3x(args.dir_3x).items())))
    out("COUNTS", {"3x_chats": len({t for t, _ in p3}), "4x_chats": len({t for t, _ in p4}),
                   "3x_chat_months": len(p3), "4x_chat_months": len(p4)})
    missing = sorted(set(p3) - set(p4))
    out("3X_CHAT_MONTHS_NOT_IN_4X", [{"chat_md5_8": t[:8], "month": m, "3x_files": p3[(t, m)]} for t, m in missing])
    out("VERDICT", "all 3.x (chat, month) pairs exist in 4.x" if not missing else f"{len(missing)} pairs missing in 4.x")


if __name__ == "__main__":
    main()
