#!/usr/bin/env python
"""isp_flash.py -- write a firmware image into the YD-Y65S over the Sinowealth ISP.

This is the Python twin of `tool/crates/core/src/isp.rs`: same commands, same
page size, same order.  It exists for the Windows host, where the Tauri tool
is not built, and it talks to the raw Win32 HID API through `vendorhid.py`
(standard library only).

Sequence (identical to `sinowisp` and to our Rust implementation):

    enter ISP   SetFeature(report 5, 05 75 00 00 00 00) on 258a:019d
    wait        the board re-enumerates as 0603:1020 / 0603:1021
    0x55        enable flash access
    0x45        erase the application area
    0x57 + 0x77 init write at the address, then one 2048 byte page per transfer
    0x5a        reboot into the application

Only the application area (0x0000..0xEFFF) is written.  The bootloader at
0xF000..0xFFFF is left alone: the ISP erase does not cover it, and the
bootloader in the dump is byte identical to the one already on the board.

Usage
-----
    uv run tools/isp_flash.py firmware/YD-Y65S_full.bin
    uv run tools/isp_flash.py firmware/YD-Y65S_full.bin --read-back out.bin

`--read-back` re-reads the flash after the reboot and compares it with the
image that was written.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import vendorhid as vh  # noqa: E402

APP_VID, APP_PID = 0x258A, 0x019D
ISP_VID = 0x0603
ISP_PIDS = (0x1020, 0x1021)

PAGE_SIZE = 2048
FIRMWARE_SIZE = 0xF000          # application area; the bootloader is not touched
FLASH_SIZE = 0x10000

REPORT_CMD = 5
REPORT_XFER = 6
CMD_ENABLE_FIRMWARE = 0x55
CMD_INIT_READ = 0x52
CMD_ERASE = 0x45
CMD_INIT_WRITE = 0x57
CMD_REBOOT = 0x5A
XFER_READ_PAGE = 0x72
XFER_WRITE_PAGE = 0x77

ENTER_ISP = bytes([0x05, 0x75, 0x00, 0x00, 0x00, 0x00])


def collections(vid: int, pids: tuple[int, ...]):
    """Every HID collection of the given device, with its caps."""
    out = []
    for e in vh.enumerate_hid(overlapped=True):
        if e.get("vid") != vid or e.get("pid") not in pids:
            continue
        caps = e.get("caps")
        if caps is None:
            continue
        out.append(e)
    return out


def pick(entries, feature_len: int):
    """The 0xff00/0x0001 collection whose feature report is `feature_len` bytes."""
    hits = [
        e for e in entries
        if e["caps"].UsagePage == 0xFF00
        and e["caps"].Usage == 0x0001
        and e["caps"].FeatureReportByteLength == feature_len
    ]
    if not hits:
        raise SystemExit(
            f"没有 feature={feature_len} 的 0xff00/0x0001 集合"
            f"（现有: {[e['caps'].FeatureReportByteLength for e in entries]}）"
        )
    return hits[0]


def set_feature(entry, report: int, payload: bytes) -> bool:
    length = max(entry["caps"].FeatureReportByteLength, report + 1)
    buf = vh.ctypes.create_string_buffer(length)
    buf[0] = bytes([report])
    buf[1 : 1 + len(payload)] = payload
    return bool(vh.hid.HidD_SetFeature(entry["handle"], buf, length))


def get_feature(entry, report: int, length: int) -> bytes:
    buf = vh.ctypes.create_string_buffer(length)
    buf[0] = bytes([report])
    vh.hid.HidD_GetFeature(entry["handle"], buf, length)
    return buf.raw


def cmd(entry, code: int, arg0: int = 0, arg1: int = 0) -> bool:
    return set_feature(entry, REPORT_CMD, bytes([code, arg0, arg1, 0x00, 0x00]))


def enter_isp() -> None:
    """Make the board jump into its ISP bootloader."""
    if collections(ISP_VID, ISP_PIDS):
        print("[enter-isp] 设备已经在 ISP 里")
        return
    entries = [e for e in collections(APP_VID, (APP_PID,))
               if e["caps"].UsagePage == 0xFF00
               and e["caps"].Usage == 0x0001
               and e["caps"].FeatureReportByteLength == 6]
    if not entries:
        raise SystemExit("找不到应用模式下的 0xff00/0x0001 命令集合")
    # The device leaves the bus while the transfer is in flight, so the call
    # usually reports failure; that is the expected sign of a successful jump.
    ok = set_feature(entries[0], REPORT_CMD, ENTER_ISP[1:])
    print(f"[enter-isp] set_feature -> {ok}（失败反而是成功信号）")


def wait_for_isp(timeout: float = 30.0) -> list[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for e in collections(ISP_VID, ISP_PIDS):
            if e["caps"].UsagePage == 0xFF00 and e["caps"].Usage == 0x0001:
                print(f"[wait-isp] {e['vid']:04x}:{e['pid']:04x} "
                      f"feature={e['caps'].FeatureReportByteLength}")
                return collections(ISP_VID, ISP_PIDS)
        time.sleep(0.5)
    raise SystemExit("键盘没有重枚举为 0603:1020/1021")


def write_image(image: bytes) -> None:
    entries = collections(ISP_VID, ISP_PIDS)
    cmd_ch = pick(entries, 6)
    page_ch = pick(entries, PAGE_SIZE + 2)

    # The ISP payload keeps the application reset vector in two places: the
    # LJMP at 0x0000 and its canonical copy at 0xEFFC (firmware_size - 4).
    # The bootloader skips payload bytes 0..2 and writes payload[1..2] to
    # 0xEFFC itself, but it also stores the payload verbatim, so the copy is
    # mirrored here before writing -- exactly what the vendor tool does.
    payload = bytearray(image[:FIRMWARE_SIZE])
    payload[0xEFFC:0xEFFE] = payload[1:3]

    print("[erase] 0x45")
    cmd(cmd_ch, CMD_ERASE)
    time.sleep(2.0)

    print("[write] 0x57 addr=0x0000")
    cmd(cmd_ch, CMD_INIT_WRITE, 0x00, 0x00)
    time.sleep(0.2)

    total = len(payload)
    done = 0
    while done < total:
        take = min(PAGE_SIZE, total - done)
        buf = vh.ctypes.create_string_buffer(PAGE_SIZE + 2)
        buf[0] = bytes([REPORT_XFER])
        buf[1] = bytes([XFER_WRITE_PAGE])
        buf[2 : 2 + take] = payload[done : done + take]
        if not vh.hid.HidD_SetFeature(page_ch["handle"], buf, PAGE_SIZE + 2):
            raise SystemExit(f"写页失败 @0x{done:04X}")
        done += take
        if done % (PAGE_SIZE * 8) == 0 or done == total:
            print(f"  {done}/{total} 字节")
    print(f"[write] 完成 {done} 字节")

    # enable_firmware has to come *after* the pages: the bootloader uses the
    # vector it stored at 0xEFFC to build the LJMP at 0x0000 and sets the
    # 0xEFFB = 0x02 marker that tells it the firmware is enabled.
    print("[enable] 0x55")
    cmd(cmd_ch, CMD_ENABLE_FIRMWARE)
    time.sleep(0.5)


def read_flash(length: int = FLASH_SIZE) -> bytes:
    entries = collections(ISP_VID, ISP_PIDS)
    cmd_ch = pick(entries, 6)
    page_ch = pick(entries, PAGE_SIZE + 2)

    cmd(cmd_ch, CMD_ENABLE_FIRMWARE)
    time.sleep(0.2)
    cmd(cmd_ch, CMD_INIT_READ, 0x00, 0x00)
    time.sleep(0.2)

    out = bytearray()
    while len(out) < length:
        raw = get_feature(page_ch, REPORT_XFER, PAGE_SIZE + 2)
        if len(raw) < 2 or raw[1] != XFER_READ_PAGE:
            raise SystemExit(f"读页标记异常: {raw[:4].hex(' ')}")
        take = min(PAGE_SIZE, length - len(out))
        out += raw[2 : 2 + take]
    return bytes(out)


def reboot(entries) -> None:
    cmd_ch = pick(entries, 6)
    cmd(cmd_ch, CMD_REBOOT)


def app_present() -> bool:
    """True when the keyboard is back in application mode (258a:019d)."""
    return any(e.get("vid") == APP_VID for e in collections(APP_VID, (APP_PID,)))


def reboot_and_wait(entries, timeout: float = 30.0, tries: int = 3) -> None:
    """Ask the bootloader to boot the application and wait for the re-enumeration.

    The device leaves the bus while the command is in flight, so the
    SetFeature usually reports failure even though the reboot happens.
    """
    for attempt in range(tries):
        reboot(entries)
        deadline = time.time() + timeout / tries
        while time.time() < deadline:
            if app_present():
                print(f"[reboot] 已回到应用模式（第 {attempt + 1} 次）")
                return
            time.sleep(0.5)
    raise SystemExit("键盘没有回到应用模式（258a:019d）")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("image", help="固件镜像 (至少 0xF000 字节)")
    ap.add_argument("--read-back", metavar="PATH",
                    help="刷完后读回 flash 并保存到此文件")
    ap.add_argument("--read-only", metavar="PATH",
                    help="只读出整块 flash 保存到此文件，不做任何写入")
    ap.add_argument("--no-verify", action="store_true",
                    help="只写入，不读回校验")
    args = ap.parse_args(argv)

    if args.read_only:
        enter_isp()
        entries = wait_for_isp()
        flash = read_flash(FLASH_SIZE)
        reboot_and_wait(entries)
        pathlib.Path(args.read_only).write_bytes(flash)
        print(f"[read] {len(flash)} 字节 -> {args.read_only}  "
              f"md5={hashlib.md5(flash).hexdigest()}")
        return 0

    data = pathlib.Path(args.image).read_bytes()
    if len(data) < FIRMWARE_SIZE:
        raise SystemExit(f"镜像太小: {len(data)} 字节，至少需要 {FIRMWARE_SIZE}")
    print(f"[image] {args.image}  {len(data)} 字节  md5={hashlib.md5(data).hexdigest()}")

    enter_isp()
    entries = wait_for_isp()
    write_image(data)
    reboot_and_wait(entries)

    if args.read_back and not args.no_verify:
        enter_isp()
        entries = wait_for_isp()
        flash = read_flash(FLASH_SIZE)
        reboot_and_wait(entries)
        pathlib.Path(args.read_back).write_bytes(flash)
        want = hashlib.md5(data[:FLASH_SIZE]).hexdigest()
        got = hashlib.md5(flash).hexdigest()
        print(f"[verify] 期望 md5={want}  实得 md5={got}  "
              f"{'一致 ✓' if want == got else '不一致 ✗'}")
        return 0 if want == got else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
