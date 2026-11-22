[中文](README.md) | English

# Moving WeChat chat history from Windows to Mac: a full record of cleanup, migration and verification

This document records a real WeChat migration: why, the problems, the method, the tools, what worked and the pitfalls.
It comes with a set of **read-only** check scripts ([`tools/`](tools/)) that answer one question:
**after migration, what exactly is missing?**

All deletions and migrations were done by the account owner in the **official WeChat client**. The scripts only read
**copies** of the databases and never modify any WeChat data.

## 1. Summary

- **Official migration (Windows → phone → Mac) carries text, images, videos, files and voice messages**, provided the
  files really exist on the source device.
- For an account with about 1.9 million messages and 45 GiB, the final message-by-message check showed: in chats visible
  in the chat list, the Mac lacks 1,948 messages; about 80% are call records and **voice messages that had no audio in the
  first place**, and more than half date from 2019–2020.
- The hardest part is not the migration but **deciding what is missing**. Comparing by file name marks many renamed
  images as missing. Check against the message records.

## 2. Goal

Three WeChat accounts, all on one Windows PC; the largest has history since 2019. I wanted to move to a MacBook Air:

1. **Clean up first**: remove friends and chats I no longer need.
2. **Move the real files too**: original images, videos, voice messages and files, not only text.
3. **Lose nothing**: there were several old backups on an external drive. Confirm that nothing I wanted existed only there.
4. **Keep the originals intact** until success is confirmed.

## 3. Problems

| Problem | Why it was hard |
| --- | --- |
| Account folders not recognizable | Folder names are internal IDs (`wxid_…`) |
| Encrypted databases | Without decryption you cannot count or verify messages |
| Scattered old data | Older 4.x snapshot, 3.x folders, a 2020 Android backup, a pre-migration backup |
| Migration merges | It does not carry deletions; old chats still on a phone come back |
| Mac decryption is hard | SIP and code signing block a normal memory scan on macOS |

## 4. Method

### 4.1 What "read-only" means

**No WeChat database was ever modified.** The only write into a WeChat folder was a test that copied 6 image files to
the Mac; they were removed afterwards.

- To look at data, the database files (with `-wal`, `-shm`) were **copied** to a temporary folder, decrypted there,
  opened read-only, counted, and deleted.
- Deleting friends and chats, and migrating, were done in the **official UI** by the owner.
- After each step, a new database copy was checked.

Reading a database does not mean changing it. Writing into WeChat's databases can cause client errors, corruption or a
mismatch with the server, and cannot be undone. So even when messages were found missing on the Mac, **nothing** was written into its database.

### 4.2 Steps

1. **Identify the account** from the decrypted contact database ("self" entry).
2. **Take a baseline** before cleanup: sessions, messages per year and type, attachments per chat.
3. **Clean up**: no-remark friends sorted by message count, decided one by one; a 10-per-page checklist page for
   non-friend chats (default keep). Deletion in the official UI.
4. **Pilot with the small accounts** (Windows → phone → Mac), compared file by file.
5. **Find every old copy** on the drive by WeChat file patterns.
6. **Compare each copy** (6.2): apart from 4 documents, everything in old backups but not on the PC belonged to chats the owner deleted.
7. **Migrate the main account**: Windows → new phone → Mac, plus one import from the old phone.
8. **Verify**: file-level comparison first (mostly false alarms, see 6.3), then the Mac database key and a
   **message-by-message comparison** for a reliable answer.

## 5. Results

| Item | Result |
| --- | --- |
| Smaller account (the second one) | Videos 313/313 identical; files 35/36 identical (the last differs only by a duplicate-name suffix); attachments nearly identical |
| Main account (~1.94 M messages) | In visible chats the Mac lacks 1,948: 917 call records, 622 voice, 295 links/files, 71 text, the rest emoji/system/image |
| The missing voice messages | On Windows they have a message row but **no audio**, and none of the checked backups holds the audio, so migration skipped them |
| Leftover chats not in the chat list | 32 chats / ~58,000 messages were not migrated; they were invisible on Windows too |
| Messages on the Mac but not on Windows | 16 (probably from the old phone) |
| Deleted chats | Came back on the Mac and on Windows, probably because of the old-phone import (accepted by the owner) |
| Old backups | All 83,538 messages of the 2020 Android backup are on the PC; messages in the old 4.x snapshot but not on the PC all belonged to deleted or cleared chats; 4 documents exist only in the snapshot |

## 6. Pitfalls

### 6.1 Migration
- **Migration merges; it does not sync.** Chats deleted on Windows return if a phone still has them. Importing the old
  phone brings back the deleted chats it still holds.
- **A second import can fill gaps.** Migration merges, so re-importing does not remove anything.
- **Do not wipe the old phone for a "clean" result.** It can hold unique messages.
- One account can be logged in on one computer at a time (Windows or Mac).
- Keep all devices on power, stop the Mac from sleeping, turn off phone auto-lock.

### 6.2 Old data
- **Archives can hide an older version**: an Android backup folder had an extracted `EnMicroMsg.db` and an earlier one in
  `com.tencent.mm.tar.gz` with a `-wal` (3 commits). Check both; apply the WAL.
- **File size says little**: several 3.x accounts that were used for one day each have a `MSG0.db` of exactly 50 MiB, apparently preallocated.
- **3.x keys** generally come only from a 3.x client logged in to that account. Without a key, compare attachment folders:
  3.x `FileStorage/MsgAttach/<md5>` and 4.x `msg/attach/<md5>` use the same md5.
- **Android `EnMicroMsg.db`** key = first 7 chars of `md5(IMEI + uin)`; our backup used the fixed IMEI `1234567890ABCDEF` (common on newer Android).

### 6.3 Checking
- **Comparing images by file name gives false alarms.** Windows keeps `_W` image files; after going through the phone,
  the Mac apparently stores the same image under another name and format. By name, and even by content, 12,000 images
  looked missing; every image spot-checked opened at full size on the Mac.
- **Spot checks need a before-and-after.** A "copy then it displays" test without checking the state before copying
  proves nothing.
- **A message row is not its content.** 4.x stores voice rows in `message_*.db` and audio in `media_*.db` (`VoiceInfo`).
  A row without audio is skipped by migration and does not appear on the Mac.
- **Match messages by server ID, not by content** (Android and PC encode some emoji differently); local messages have no
  server ID, so match them by time + type.
- Message content may be zstd-compressed (`28 b5 2f fd`); base type is `local_type & 0xFFFFFFFF`.
- **Windows and Mac database keys differ.**

### 6.4 Getting the key on the Mac
macOS protection blocks debugging the signed WeChat. What works:
1. Quit WeChat and **copy** `WeChat.app`.
2. Ad-hoc sign the copy (`codesign --force --deep --sign -`).
3. Launch the copy under LLDB with a breakpoint on `CCKeyDerivationPBKDF` and read each database key.
4. Verify each key with the page-1 HMAC.
5. Delete the copy and start the original.

The original app is untouched, SIP stays on, and no root is needed. The copy needs one phone-confirmed login.
Script: [`tools/mac_capture_keys.py`](tools/mac_capture_keys.py); idea from
[acmerfight's gist](https://gist.github.com/acmerfight/0a01249ef72970d07a2603dbb629e80f).

### 6.5 Other
- **Script deletion is permanent** (no Recycle Bin). Use the Recycle Bin / Trash when you may want files back.
- On a Mac, Finder writes `._*` and `.DS_Store` onto exFAT drives; use only non-writing commands for read-only checks.

## 7. Tools

### 7.1 Recommended third-party tools

| Tool | Use | Our result |
| --- | --- | --- |
| Official WeChat client | Deletion, migration | The only way data was changed |
| [WeChatMsg-4x](https://github.com/chenanhan230-del/WeChatMsg-4x) (GPL-3.0) | 4.x keys from the running Windows client; decryption | All 35 databases; the scripts here depend on it |
| [acmerfight's gist](https://gist.github.com/acmerfight/0a01249ef72970d07a2603dbb629e80f) | Method for 4.x keys on macOS | Own script along its idea; 28 of 29 databases (including the message, session and contact databases) |
| [WeFlow](https://github.com/334456777/WeFlow) | Find account folders | Found accounts; key step failed because WeChat was not running |

### 7.2 Scripts in this repository (`tools/`, all read-only)

Python 3.10+, `pip install -r tools/requirements.txt`, and a WeChatMsg-4x checkout (`--wx4`).

| Script | Question |
| --- | --- |
| `inventory_account.py` | Files and bytes per section; run before and after migration |
| `baseline_account.py` | Sessions, messages per year and type; take before cleanup and migration |
| `check_voice_audio.py` | Which voice messages have no audio (migration skips them)? Is it in an old backup? |
| `compare_devices_messages.py` | What does another device (e.g. the Mac) lack compared with Windows, per chat? |
| `mac_capture_keys.py` | Get the 4.x database keys on the Mac (re-signed copy + LLDB) |
| `compare_4x_snapshot_messages.py` | Messages in an old 4.x snapshot but not now: chat still there (real gap) or deleted? |
| `compare_4x_snapshot_media.py`, `attribute_4x_snapshot_media.py` | Are old snapshot files still there? Which chat owns a month-folder file? |
| `decrypt_android_enmicromsg.py`, `compare_android_vs_4x.py` | Decrypt an old Android database (with `-wal`) and compare it with the PC |
| `compare_3x_4x_attach_coverage.py` | No key: does 4.x cover every 3.x chat and month with attachments? |

Output is counts, dates and md5[:8] chat IDs; names only with `--show-names`; never message bodies or keys.

## 8. Not done yet

- **Voice on the old phone.** 624 voice messages have no audio on the PC or in any backup. Only the old phone was not
  checked. If they play there, migrate **only those chats**, never the whole phone (deleted chats would return).
- 86 leftover chats not in the chat list (~220,000 messages, 0.5 GB) remain in the Windows database. They are not in the chat
  list and no official way to delete them was found; the database was not edited.

## 9. Notes

- Use these methods and scripts only on your own account and devices.
- Keys and decryption are for checking your own data. Never upload or share keys, databases or chat content.
- WeChat versions and formats change. This is based on Windows WeChat 4.2.0.12 (cleanup and old-data checks) and 4.2.0.13 (the actual migration; auto-updated on 2026-11-10), Mac WeChat 4.1.15 and macOS 27.2.1, November 2026.

## License

[GPL-3.0](LICENSE). The scripts in `tools/` depend on WeChatMsg-4x (GPL-3.0).
