#!/usr/bin/env -S uv run python
"""vendorhid.py -- probe the YD-Y65S (258a:019d) vendor HID channel by hand.

Only the Python standard library is used: SetupAPI / hid.dll are reached through
ctypes.  The tool is *read-only by default* and refuses, in code, to touch the
two reports that can change device state:

    interface 1, usage page 0xff00, feature report 5 -> magic [05 75 00 00 00 00]
        = "enter ISP": the MCU reboots into the Sinowealth ISP bootloader.
    interface 1, usage page 0xff00, feature report 6 -> ISP page read/write.
    usage page 0x0007/0x0001 keyboard collections, and any output report with a
        keyboard/mouse usage, are never written at all.

Everything else (`get`, `set` on the 0xff02 vendor collection, feature report 9)
is allowed, but `set` only sends what the caller spells out on the command line.

Usage
-----
  uv run tools/vendorhid.py list
  uv run tools/vendorhid.py desc --vid 258a --pid 019d
  uv run tools/vendorhid.py get  --vid 258a --pid 019d --report 9
  uv run tools/vendorhid.py get  --vid 258a --pid 019d --report 9 --repeat 20 --interval 0.2
  uv run tools/vendorhid.py set  --vid 258a --pid 019d --report 9 --data "00 00"
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import time
from ctypes import wintypes

# --------------------------------------------------------------------------
# win32 plumbing
# --------------------------------------------------------------------------

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
hid = ctypes.WinDLL("hid", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 1
FILE_SHARE_WRITE = 2
OPEN_EXISTING = 3
IOCTL_HID_GET_REPORT_DESCRIPTOR = 0x000B0192

# reports we must never touch (state changing / ISP)
FORBIDDEN = {
    (0xFF00, 5): "feature report 5 = enter ISP bootloader",
    (0xFF00, 6): "feature report 6 = ISP page read/write",
}


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("InterfaceClassGuid", GUID),
        ("Flags", wintypes.DWORD),
        ("Reserved", ctypes.POINTER(wintypes.ULONG)),
    ]


class SP_DEVICE_INTERFACE_DETAIL_DATA_W(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("DevicePath", ctypes.c_wchar * 1)]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Size", wintypes.ULONG),
        ("VendorID", wintypes.USHORT),
        ("ProductID", wintypes.USHORT),
        ("VersionNumber", wintypes.USHORT),
    ]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", wintypes.USHORT),
        ("UsagePage", wintypes.USHORT),
        ("InputReportByteLength", wintypes.USHORT),
        ("OutputReportByteLength", wintypes.USHORT),
        ("FeatureReportByteLength", wintypes.USHORT),
        ("Reserved", wintypes.USHORT * 17),
        ("NumberLinkCollectionNodes", wintypes.USHORT),
        ("NumberInputButtonCaps", wintypes.USHORT),
        ("NumberInputValueCaps", wintypes.USHORT),
        ("NumberInputDataIndices", wintypes.USHORT),
        ("NumberOutputButtonCaps", wintypes.USHORT),
        ("NumberOutputValueCaps", wintypes.USHORT),
        ("NumberOutputDataIndices", wintypes.USHORT),
        ("NumberFeatureButtonCaps", wintypes.USHORT),
        ("NumberFeatureValueCaps", wintypes.USHORT),
        ("NumberFeatureDataIndices", wintypes.USHORT),
    ]


setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
setupapi.SetupDiGetClassDevsW.argtypes = [
    ctypes.POINTER(GUID), wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD,
]
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
]
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
    ctypes.POINTER(SP_DEVICE_INTERFACE_DETAIL_DATA_W), wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
]
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]

hid.HidD_GetAttributes.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDD_ATTRIBUTES)]
hid.HidD_GetPreparsedData.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid.HidD_GetFeature.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_SetFeature.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.ULONG]
hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
hid.HidD_GetManufacturerString.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetProductString.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.ULONG]

class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_void_p),
        ("InternalHigh", ctypes.c_void_p),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", ctypes.c_void_p),
    ]


FILE_FLAG_OVERLAPPED = 0x40000000
ERROR_IO_PENDING = 997
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258

kernel32.CreateFileW.restype = ctypes.c_void_p
kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
]
kernel32.CreateEventW.restype = ctypes.c_void_p
kernel32.CreateEventW.argtypes = [
    ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR,
]
kernel32.ResetEvent.argtypes = [ctypes.c_void_p]
kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.ReadFile.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED),
]
kernel32.GetOverlappedResult.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(OVERLAPPED),
    ctypes.POINTER(wintypes.DWORD), wintypes.BOOL,
]
kernel32.CancelIo.argtypes = [ctypes.c_void_p]
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
kernel32.DeviceIoControl.argtypes = [
    ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
    ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
]


def parse_hex(text: str) -> int:
    return int(text, 16)


def enumerate_hid(overlapped: bool = False) -> list[dict]:
    """Return one dict per HID interface with its caps and device path."""
    guid = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(guid))
    hdev = setupapi.SetupDiGetClassDevsW(
        ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
    )
    if hdev == INVALID_HANDLE_VALUE:
        raise OSError("SetupDiGetClassDevs failed")

    out: list[dict] = []
    detail_size = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
    try:
        index = 0
        while True:
            iface = SP_DEVICE_INTERFACE_DATA()
            iface.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            if not setupapi.SetupDiEnumDeviceInterfaces(
                hdev, None, ctypes.byref(guid), index, ctypes.byref(iface)
            ):
                break
            index += 1
            buf = ctypes.create_string_buffer(2048)
            detail = ctypes.cast(buf, ctypes.POINTER(SP_DEVICE_INTERFACE_DETAIL_DATA_W))
            detail.contents.cbSize = detail_size
            needed = wintypes.DWORD()
            if not setupapi.SetupDiGetDeviceInterfaceDetailW(
                hdev, ctypes.byref(iface), detail, len(buf), ctypes.byref(needed), None
            ):
                continue
            path = ctypes.wstring_at(ctypes.addressof(buf) + ctypes.sizeof(wintypes.DWORD))
            handle = kernel32.CreateFileW(
                path, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                None, OPEN_EXISTING, FILE_FLAG_OVERLAPPED if overlapped else 0, None,
            )
            if handle == INVALID_HANDLE_VALUE or handle is None:
                continue
            entry = {"path": path, "handle": handle}
            try:
                attrs = HIDD_ATTRIBUTES()
                attrs.Size = ctypes.sizeof(HIDD_ATTRIBUTES)
                hid.HidD_GetAttributes(handle, ctypes.byref(attrs))
                entry["vid"] = attrs.VendorID
                entry["pid"] = attrs.ProductID
                entry["version"] = attrs.VersionNumber
                for key, fn in (("manufacturer", hid.HidD_GetManufacturerString),
                                ("product", hid.HidD_GetProductString)):
                    sbuf = ctypes.create_unicode_buffer(126)
                    if fn(handle, sbuf, ctypes.sizeof(sbuf)):
                        entry[key] = sbuf.value
                pp = ctypes.c_void_p()
                if hid.HidD_GetPreparsedData(handle, ctypes.byref(pp)):
                    caps = HIDP_CAPS()
                    # HidP_GetCaps returns HIDP_STATUS_SUCCESS = 0x00110000
                    status = hid.HidP_GetCaps(pp, ctypes.byref(caps))
                    if status in (0, 0x110000):
                        entry["caps"] = caps
                    else:
                        entry["caps_status"] = status
                    hid.HidD_FreePreparsedData(pp)
                out.append(entry)
            except Exception:
                kernel32.CloseHandle(handle)
                raise
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return out


def report_descriptor(handle: int) -> bytes:
    buf = ctypes.create_string_buffer(4096)
    returned = wintypes.DWORD()
    ok = kernel32.DeviceIoControl(
        handle, IOCTL_HID_GET_REPORT_DESCRIPTOR, None, 0,
        buf, len(buf), ctypes.byref(returned), None,
    )
    if not ok:
        raise OSError(f"IOCTL_HID_GET_REPORT_DESCRIPTOR failed ({ctypes.get_last_error()})")
    return buf.raw[: returned.value]


def parse_report_descriptor(desc: bytes) -> list[str]:
    """Very small HID item walker: enough to list the report IDs and sizes."""
    lines: list[str] = []
    usage_page = report_id = 0
    report_size = report_count = 0
    i = 0
    while i < len(desc):
        prefix = desc[i]
        i += 1
        if prefix == 0xFE:  # long item
            if i + 2 > len(desc):
                break
            size = desc[i]
            i += 2 + size
            continue
        size = {0: 0, 1: 1, 2: 2, 3: 4}[prefix & 0x03]
        tag = prefix >> 4
        typ = (prefix >> 2) & 0x03
        value = int.from_bytes(desc[i : i + size], "little")
        i += size
        bits = size * 8
        if typ == 1:  # global
            if tag == 0 and size == 1:
                usage_page = value
            elif tag == 4 and size == 1:
                report_size = value
            elif tag == 5 and size in (1, 2):
                report_count = value
            elif tag == 7 and size == 1:
                report_id = value
                lines.append(f"  Report ID {report_id}")
            elif tag == 8:
                pass  # push
            elif tag == 9:
                pass  # pop
        elif typ == 0:  # main
            if tag in (8, 9, 11):  # Input / Output / Feature
                kind = {8: "Input", 9: "Output", 11: "Feature"}[tag]
                total = (report_size * report_count + 7) // 8
                lines.append(
                    f"    {kind:<7} id={report_id:<3} {report_count} x {report_size} bit"
                    f" = {total} B  (flags {value:#04x})"
                )
            elif tag == 10:  # collection
                lines.append(f"  Collection (usage page {usage_page:#06x}, usage {value:#06x})")
            elif tag == 12:  # end collection
                lines.append("  End collection")
    return lines


def match(entry: dict, vid: int | None, pid: int | None, page: int | None,
          usage: int | None) -> bool:
    if vid is not None and entry.get("vid") != vid:
        return False
    if pid is not None and entry.get("pid") != pid:
        return False
    caps = entry.get("caps")
    if page is not None and (caps is None or caps.UsagePage != page):
        return False
    if usage is not None and (caps is None or caps.Usage != usage):
        return False
    return True


def caps_line(e: dict) -> str:
    caps = e.get("caps")
    if not caps:
        return "caps: <none>"
    return (
        f"usagePage={caps.UsagePage:#06x} usage={caps.Usage:#06x} "
        f"in={caps.InputReportByteLength} out={caps.OutputReportByteLength} "
        f"feature={caps.FeatureReportByteLength}"
    )


def guard(entry: dict, report: int):
    caps = entry.get("caps")
    page = caps.UsagePage if caps else None
    reason = FORBIDDEN.get((page, report))
    if reason:
        raise SystemExit(f"拒绝: {reason} (usage page {page:#06x}, report {report})")


def cmd_list(args) -> int:
    for e in enumerate_hid():
        if args.vid is not None and e.get("vid") != args.vid:
            continue
        if args.pid is not None and e.get("pid") != args.pid:
            continue
        print(f"{e.get('vid', 0):04x}:{e.get('pid', 0):04x} "
              f"v{e.get('version', 0):04x}  {caps_line(e)}")
        print(f"    {e.get('manufacturer', '?')} / {e.get('product', '?')}")
        print(f"    {e['path']}")
    return 0


def pick(entries: list[dict], args) -> dict:
    hits = [e for e in entries if match(e, args.vid, args.pid, args.page, args.usage)]
    if not hits:
        raise SystemExit("没有匹配的 HID 集合（检查 --vid/--pid/--page/--usage）")
    if len(hits) > 1 and args.page is None:
        for e in hits:
            print(f"candidate: {caps_line(e)}")
        raise SystemExit("有多个集合匹配，请用 --page/--usage 指定")
    return hits[0]


def cmd_desc(args) -> int:
    e = pick(enumerate_hid(), args)
    print(f"{caps_line(e)}\n{e['path']}")
    desc = report_descriptor(e["handle"])
    print(f"\n-- report descriptor ({len(desc)} B) --")
    print(" ".join(f"{b:02x}" for b in desc))
    print("\n-- walk --")
    print("\n".join(parse_report_descriptor(desc)))
    return 0


def cmd_get(args) -> int:
    e = pick(enumerate_hid(), args)
    guard(e, args.report)
    caps = e["caps"]
    length = max(caps.FeatureReportByteLength, args.report + 1)
    for n in range(args.repeat):
        buf = ctypes.create_string_buffer(length)
        buf[0] = bytes([args.report])
        ok = hid.HidD_GetFeature(e["handle"], buf, length)
        raw = buf.raw
        err = ctypes.get_last_error()
        print(f"[{n:3d}] get_feature id={args.report} ok={bool(ok)} err={err} "
              f"len={length}")
        print("      " + " ".join(f"{b:02x}" for b in raw))
        if not ok:
            break
        if n + 1 < args.repeat:
            time.sleep(args.interval)
    return 0


def cmd_set(args) -> int:
    e = pick(enumerate_hid(), args)
    guard(e, args.report)
    payload = bytes(int(t, 16) for t in args.data.split())
    caps = e["caps"]
    length = max(caps.FeatureReportByteLength, args.report + 1)
    if len(payload) + 1 > length:
        raise SystemExit(f"数据太长: {len(payload)} B + id > {length}")
    buf = ctypes.create_string_buffer(length)
    buf[0] = bytes([args.report])
    buf[1 : 1 + len(payload)] = payload
    ok = hid.HidD_SetFeature(e["handle"], buf, length)
    print(f"set_feature id={args.report} ok={bool(ok)} err={ctypes.get_last_error()}")
    print("      " + " ".join(f"{b:02x}" for b in buf.raw))
    return 0


def cmd_watch(args) -> int:
    """Listen for input reports (pure read, nothing is written to the device)."""
    e = pick(enumerate_hid(overlapped=True), args)
    caps = e.get("caps")
    length = max(caps.InputReportByteLength if caps else 64, 64)
    event = kernel32.CreateEventW(None, True, False, None)
    deadline = time.time() + args.seconds
    print(f"监听 input report（{args.seconds:.0f} s，纯读取，不写设备）...")
    while time.time() < deadline:
        buf = ctypes.create_string_buffer(length)
        read = wintypes.DWORD()
        kernel32.ResetEvent(event)
        ol = OVERLAPPED()
        ol.hEvent = event
        ok = kernel32.ReadFile(e["handle"], buf, length, ctypes.byref(read), ctypes.byref(ol))
        if not ok:
            err = ctypes.get_last_error()
            if err != ERROR_IO_PENDING:
                print(f"ReadFile 失败: {err}")
                break
            if kernel32.WaitForSingleObject(event, 500) == WAIT_TIMEOUT:
                continue
            if not kernel32.GetOverlappedResult(
                e["handle"], ctypes.byref(ol), ctypes.byref(read), False
            ):
                continue
        if read.value == 0:
            continue
        raw = buf.raw[: read.value]
        print(f"[{time.strftime('%H:%M:%S')}] id={raw[0]} len={len(raw)}: "
              + " ".join(f"{b:02x}" for b in raw))
    kernel32.CancelIo(e["handle"])
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--vid", type=parse_hex, default=None)
        p.add_argument("--pid", type=parse_hex, default=None)
        p.add_argument("--page", type=parse_hex, default=None,
                       help="HID usage page of the collection, e.g. ff02")
        p.add_argument("--usage", type=parse_hex, default=None)

    p = sub.add_parser("list", help="列出 HID 集合")
    common(p)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("desc", help="打印集合的报告描述符并解析")
    common(p)
    p.set_defaults(func=cmd_desc)

    p = sub.add_parser("get", help="读 feature report（只读）")
    common(p)
    p.add_argument("--report", type=parse_hex, required=True)
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--interval", type=float, default=0.2)
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("set", help="写 feature report（危险，已挡住 ISP 报告）")
    common(p)
    p.add_argument("--report", type=parse_hex, required=True)
    p.add_argument("--data", required=True, help='十六进制字节，如 "00 00"')
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("watch", help="监听 input report（纯读取）")
    common(p)
    p.add_argument("--seconds", type=float, default=10.0)
    p.set_defaults(func=cmd_watch)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
