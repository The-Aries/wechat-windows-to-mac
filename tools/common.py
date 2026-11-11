"""Shared read-only helpers for WeChat 4.x (Windows) databases.

Keys are scanned from the running Weixin process with WeChatMsg-4x (`wx4` package) and kept in memory only.
Every database is copied (with its -wal/-shm sidecars) into a temporary folder, decrypted there and deleted
after use. Source databases are never opened directly and never written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing, contextmanager
from pathlib import Path

_decrypt = None
_keymod = None


def add_common_args(parser: argparse.ArgumentParser, account: bool = True) -> None:
    if account:
        parser.add_argument("--account-dir", required=True, type=Path,
                            help="current account folder, e.g. ...\\xwechat_files\\wxid_xxx_1a2b")
    parser.add_argument("--wx4", type=Path, default=os.environ.get("WX4_DIR"),
                        help="path of a WeChatMsg-4x checkout (or set WX4_DIR)")
    parser.add_argument("--tmp-root", type=Path, default=None,
                        help="folder for temporary decrypted copies (default: system temp)")


def init_wx4(path) -> None:
    global _decrypt, _keymod
    if not path or not (Path(path) / "wx4").is_dir():
        raise SystemExit("--wx4 (or WX4_DIR) must point to a WeChatMsg-4x checkout that contains wx4/")
    sys.path.insert(0, str(Path(path)))
    from wx4 import decrypt, key  # noqa: E402
    _decrypt, _keymod = decrypt, key


def emit(tag: str, obj) -> None:
    # ASCII-escaped JSON is safe on any console code page.
    print(tag, json.dumps(obj, ensure_ascii=True, default=str), flush=True)


def md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def account_wxid(account_dir: Path) -> str:
    """`wxid_abc_1a2b` -> `wxid_abc` (4.x adds a 4-hex suffix to the folder name)."""
    return re.sub(r"_[0-9a-f]{4}$", "", account_dir.name)


def shards(storage: Path) -> list[Path]:
    return sorted(x for x in (storage / "message").glob("message_*.db")
                  if re.fullmatch(r"message_[0-9]+\.db", x.name))


def scan_keys(storage: Path, *extra_storages: Path) -> dict:
    """Return {salt_hex: key_hex} verified against `storage` (and older copies in `extra_storages`).

    Older copies of the same account usually share most salts with the live account, so their salts are
    added to the same scan. Salts that no key matches are simply absent from the result.
    """
    ex = _keymod.KeyExtractor(str(storage), progress=lambda _: None)
    ex.collect()
    for other in extra_storages:
        ex2 = _keymod.KeyExtractor(str(other), progress=lambda _: None)
        ex2.collect()
        for salt, items in ex2.salt_index.items():
            ex.salt_index.setdefault(salt, items)
    _keymod.enable_debug_privilege()
    procs = _keymod.find_weixin_processes()
    if not procs:
        raise SystemExit("Weixin is not running; log in to the account first")
    pid = max(procs, key=lambda p: p["mem_kb"])["pid"]
    stats = ex.scan_process(pid)
    emit("SCAN", {"verified_keys": len(ex.keys), "salts": len(ex.salt_index), "error": stats.get("error")})
    return ex.keys


@contextmanager
def temp_dir(root: Path | None):
    if root:
        root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wxtk_", dir=root) as folder:
        yield Path(folder)


def _decrypt_copy(source: Path, keys: dict, tmp: Path) -> Path:
    enc = tmp / ("enc_" + source.name)
    plain = tmp / ("plain_" + source.name)
    shutil.copy2(source, enc)
    for suffix in ("-wal", "-shm"):
        side = Path(str(source) + suffix)
        if side.is_file():
            shutil.copy2(side, Path(str(enc) + suffix))
    try:
        salt = enc.open("rb").read(16).hex()
        if salt not in keys:
            raise RuntimeError("no verified key for " + source.name)
        details = _decrypt.decrypt_file(str(enc), str(plain), bytes.fromhex(keys[salt]))
        if details.get("wal_error"):
            raise RuntimeError("WAL could not be merged for " + source.name)
        if not _decrypt.quick_check(str(plain)):
            raise RuntimeError("quick_check failed for " + source.name)
        return plain
    finally:
        enc.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(str(enc) + suffix).unlink(missing_ok=True)


@contextmanager
def open_plain(source: Path, keys: dict, tmp: Path):
    """Decrypt a copy of `source` and yield a read-only sqlite3 connection; the copy is deleted afterwards."""
    plain = _decrypt_copy(source, keys, tmp)
    try:
        with closing(sqlite3.connect(plain.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            yield db
    finally:
        plain.unlink(missing_ok=True)


def msg_tables(db) -> list[str]:
    return [r[0] for r in db.execute("select name from sqlite_master where type='table' and name like 'Msg_%'")
            if re.fullmatch(r"Msg_[0-9a-f]{32}", r[0])]


def session_usernames(storage: Path, keys: dict, tmp: Path) -> set[str]:
    with open_plain(storage / "session" / "session.db", keys, tmp) as db:
        return {r[0] for r in db.execute("select username from SessionTable") if r[0]}


def alive_chats(storage: Path, keys: dict, tmp: Path) -> set[str]:
    """md5(username) of every chat that still exists: in the session list or with message rows."""
    alive = {md5(u) for u in session_usernames(storage, keys, tmp)}
    for shard in shards(storage):
        with open_plain(shard, keys, tmp) as db:
            for tb in msg_tables(db):
                if db.execute(f"select 1 from [{tb}] limit 1").fetchone():
                    alive.add(tb[4:])
    return alive
