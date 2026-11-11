"""Run on the Mac. Capture the SQLCipher keys of WeChat 4.x for macOS (Apple Silicon) from an ad-hoc re-signed
copy of WeChat launched under LLDB. Only 32-byte keys that pass the SQLCipher 4 page-1 HMAC check against a
database in <db_storage> are kept. Keys go to a new 0600 JSON file ({salt_hex: key_hex}); nothing secret is printed.

Prepare first (quit WeChat normally; do NOT touch /Applications/WeChat.app itself):
    mkdir -m 700 ~/wxkey && cd ~/wxkey
    /usr/bin/ditto /Applications/WeChat.app WeChat-trial.app
    codesign --force --deep --sign - WeChat-trial.app
Run (log in with "Enter WeChat" + phone confirmation in the window that appears; do not chat in it):
    PYTHONPATH="$(/usr/bin/lldb -P)" /usr/bin/python3 mac_capture_keys.py \
        ~/wxkey/WeChat-trial.app/Contents/MacOS/WeChat \
        ~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/<wxid_xxx_1a2b>/db_storage \
        ~/wxkey/keys.json --timeout 300
The script kills the copy at the end. Afterwards: move WeChat-trial.app to the Trash, start the original WeChat,
and delete keys.json when you are done. Tested: macOS 27.2, WeChat 4.1.15, arm64.
Method follows the CCKeyDerivationPBKDF breakpoint idea from https://gist.github.com/acmerfight/0a01249ef72970d07a2603dbb629e80f
"""
import argparse
import hashlib
import hmac
import json
import os
import sys
import time

import lldb


def page1s(root):
    pages = {}
    for base, _, files in os.walk(root):
        for f in files:
            if f.endswith(".db"):
                try:
                    with open(os.path.join(base, f), "rb") as fh:
                        pg = fh.read(4096)
                except OSError:
                    continue
                if len(pg) == 4096:
                    pages.setdefault(pg[:16], pg)
    return pages


def verified(key, pg):
    mk = hashlib.pbkdf2_hmac("sha512", key, bytes(x ^ 0x3A for x in pg[:16]), 2, 32)
    mac = hmac.new(mk, pg[16:4032] + b"\x01\x00\x00\x00", hashlib.sha512).digest()
    return hmac.compare_digest(mac, pg[4032:4096])


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("exe")
    ap.add_argument("db_storage")
    ap.add_argument("out")
    ap.add_argument("--timeout", type=int, default=300)
    a = ap.parse_args()
    if os.path.exists(a.out):
        sys.exit("output exists; choose a new file")
    pages = page1s(a.db_storage)
    print("databases (distinct salts):", len(pages), flush=True)
    keys = {}
    dbg = lldb.SBDebugger.Create()
    dbg.SetAsync(True)
    dbg.SkipLLDBInitFiles(True)
    target = dbg.CreateTarget(a.exe)
    bp = target.BreakpointCreateByName("CCKeyDerivationPBKDF")
    li = lldb.SBLaunchInfo([])
    li.SetWorkingDirectory(os.path.dirname(a.exe))
    err = lldb.SBError()
    proc = target.Launch(li, err)
    if not err.Success():
        sys.exit("launch failed: %s" % err.GetCString())
    ev = lldb.SBEvent()
    listener = dbg.GetListener()
    t0 = time.time()
    try:
        while time.time() - t0 < a.timeout and len(keys) < len(pages):
            if not listener.WaitForEvent(1, ev):
                continue
            st = proc.GetState()
            if st in (lldb.eStateExited, lldb.eStateCrashed, lldb.eStateDetached):
                break
            if st != lldb.eStateStopped:
                continue
            for th in proc:
                if th.GetStopReason() != lldb.eStopReasonBreakpoint or th.GetStopReasonDataAtIndex(0) != bp.GetID():
                    continue
                fr = th.GetFrameAtIndex(0)
                # CCKeyDerivationPBKDF(alg, password, passwordLen, salt, saltLen, prf, rounds, derivedKey, len)
                pp, pl, sp, sl, prf, rounds = [fr.FindRegister("x%d" % i).GetValueAsUnsigned() for i in range(1, 7)]
                if not (0 < pl <= 256 and sl == 16 and prf == 5 and rounds in (2, 256000)):
                    continue
                e = lldb.SBError()
                secret, salt = proc.ReadMemory(pp, pl, e), proc.ReadMemory(sp, sl, e)
                if not secret or not salt:
                    continue
                if rounds == 256000:          # passphrase -> derive the page key
                    dbsalt, key = salt, hashlib.pbkdf2_hmac("sha512", secret, salt, 256000, 32)
                else:                          # HMAC-key derivation: secret is already the page key
                    dbsalt, key = bytes(x ^ 0x3A for x in salt), secret
                if len(key) == 32 and dbsalt in pages and dbsalt.hex() not in keys and verified(key, pages[dbsalt]):
                    keys[dbsalt.hex()] = key.hex()
                    print("verified %d of %d" % (len(keys), len(pages)), flush=True)
            proc.Continue()
    finally:
        fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(keys, f)
        print("done: %d of %d keys verified" % (len(keys), len(pages)), flush=True)
        proc.Kill()


if __name__ == "__main__":
    main()
