"""Read-only file inventory of a WeChat 4.x account folder (Windows or macOS). No decryption, no hashing.

Prints file counts and bytes per section, the top extensions, and the largest `msg/attach/<md5(username)>`
chat folders. Run it on the source before migration and on the destination afterwards, then compare.

Usage: python inventory_account.py <account_dir> [--top 35]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
from pathlib import Path


def summarize(root: Path, depth: int = 1) -> dict:
    sections = collections.defaultdict(lambda: [0, 0])
    exts = collections.Counter()
    files = total = errors = 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            size = entry.stat(follow_symlinks=False).st_size
                            parts = Path(entry.path).relative_to(root).parts
                            label = "/".join(parts[:depth]) if len(parts) > depth else "(root)"
                            sections[label][0] += 1
                            sections[label][1] += size
                            exts[Path(entry.name).suffix.lower() or "(none)"] += 1
                            files += 1
                            total += size
                    except OSError:
                        errors += 1
        except OSError:
            errors += 1
    return {"files": files, "bytes": total, "errors": errors,
            "sections": dict(sorted(sections.items(), key=lambda kv: -kv[1][1])),
            "extensions_top": dict(exts.most_common(12))}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("account_dir", type=Path)
    ap.add_argument("--top", type=int, default=35, help="number of largest attach chat folders to show")
    args = ap.parse_args()
    acc = args.account_dir
    if not acc.is_dir():
        raise SystemExit("account folder not found")
    out = lambda tag, obj: print(tag, json.dumps(obj, ensure_ascii=True), flush=True)  # noqa: E731
    out("ACCOUNT", acc.name)
    out("OVERALL", summarize(acc))
    for name in ("msg", "db_storage"):
        if (acc / name).is_dir():
            out(name.upper(), summarize(acc / name))
    if (acc / "msg" / "attach").is_dir():
        attach = summarize(acc / "msg" / "attach")
        attach["total_chat_folders"] = len(attach["sections"])
        attach["sections"] = dict(list(attach["sections"].items())[:args.top])
        out("ATTACH_BY_CHAT", attach)


if __name__ == "__main__":
    main()
