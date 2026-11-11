"""Decrypt a copy of an old Android WeChat `EnMicroMsg.db` (SQLCipher 1 parameters) into a new plain file.

Key: md5(IMEI + uin)[:7], PBKDF2-SHA1 4000 rounds, page 1024, 16-byte IV reserve. IMEI candidates come from
`CompatibleInfo.cfg` when given, plus the fixed value `1234567890ABCDEF` used by newer Android versions.
uin is in `shared_prefs/system_config_prefs.xml` (`default_uin`) or `auth_info_key_prefs.xml`.
If `<src>-wal` exists, its valid committed frames are applied (cumulative checksums are verified).
The source is only read. No key and no message content is printed.

Usage: python decrypt_android_enmicromsg.py <EnMicroMsg.db> <out.db> --uin <uin> [--cfg CompatibleInfo.cfg]
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import struct
import sys

from Cryptodome.Cipher import AES

PAGE, RES = 1024, 16
DEFAULT_IMEI = "1234567890ABCDEF"


def dec_page(key: bytes, page: bytes, pgno: int) -> bytes:
    body = page[16:] if pgno == 1 else page
    plain = AES.new(key, AES.MODE_CBC, body[-RES:]).decrypt(body[:-RES])
    return (b"SQLite format 3\x00" if pgno == 1 else b"") + plain + b"\x00" * RES


def find_key(data: bytes, uin: str, cfg: str | None):
    raw = open(cfg, "rb").read() if cfg and os.path.exists(cfg) else b""
    cands = {m.decode() for m in re.findall(rb"(?<![0-9A-Za-z])([0-9A-Za-z]{14,17})(?![0-9A-Za-z])", raw)}
    for imei in sorted(cands) + [DEFAULT_IMEI]:
        pw = hashlib.md5((imei + uin).encode()).hexdigest()[:7]
        key = hashlib.pbkdf2_hmac("sha1", pw.encode(), data[:16], 4000, 32)
        d = dec_page(key, data[:PAGE], 1)
        if d[16:18] == b"\x04\x00" and d[21:24] == b"\x40\x20\x20":
            return imei, key
    sys.exit("NO_KEY candidates=%d" % (len(cands) + 1))


def apply_wal(wal: bytes, pages: dict, npages: int) -> int:
    magic, _ver, psz, _ckpt, s1, s2 = struct.unpack(">IIIIII", wal[:24])
    endian = ">" if magic & 1 else "<"

    def cks(buf, a, b):
        for x0, x1 in struct.iter_unpack(endian + "II", buf):
            a = (a + x0 + b) & 0xFFFFFFFF
            b = (b + x1 + a) & 0xFFFFFFFF
        return a, b

    a, b = cks(wal[:24], 0, 0)
    header_ok = (a, b) == struct.unpack(">II", wal[24:32]) and psz == PAGE
    pending, applied, frames, commits, off = {}, 0, 0, 0, 32
    while header_ok and off + 24 + PAGE <= len(wal):
        pg, dbsize, fs1, fs2, c1, c2 = struct.unpack(">IIIIII", wal[off:off + 24])
        if (fs1, fs2) != (s1, s2):
            break
        a, b = cks(wal[off:off + 8] + wal[off + 24:off + 24 + PAGE], a, b)
        if (a, b) != (c1, c2):
            break
        frames += 1
        pending[pg] = wal[off + 24:off + 24 + PAGE]
        if dbsize:  # commit frame
            commits += 1
            pages.update(pending)
            applied += len(pending)
            npages = dbsize
            pending = {}
        off += 24 + PAGE
    print("WAL header_ok=%s valid_frames=%d commits=%d pages_applied=%d" % (header_ok, frames, commits, applied))
    return npages


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--uin", required=True)
    ap.add_argument("--cfg", help="CompatibleInfo.cfg from the same backup (optional)")
    args = ap.parse_args()
    if os.path.exists(args.out):
        sys.exit("output exists; choose a new file")
    data = open(args.src, "rb").read()
    imei, key = find_key(data, args.uin, args.cfg)
    print("KEY_OK imei_source=%s" % ("default" if imei == DEFAULT_IMEI else "cfg"))
    pages = {i // PAGE + 1: data[i:i + PAGE] for i in range(0, len(data) - PAGE + 1, PAGE)}
    npages = len(pages)
    wal_path = args.src + "-wal"
    if os.path.exists(wal_path) and os.path.getsize(wal_path) >= 32:
        npages = apply_wal(open(wal_path, "rb").read(), pages, npages)
    with open(args.out, "wb") as f:
        for pg in range(1, npages + 1):
            f.write(dec_page(key, pages[pg], pg) if pg in pages else b"\x00" * PAGE)
    print("PAGES", npages)


if __name__ == "__main__":
    main()
