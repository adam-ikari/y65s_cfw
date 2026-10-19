"""Send arbitrary feature-9 payloads while listening for HID input reports."""

from __future__ import annotations

import ctypes
import pathlib
import sys
import time
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import vendorhid as vh  # noqa: E402

REPORT = 9


def main(argv: list[str]) -> int:
    entries = vh.enumerate_hid(overlapped=True)
    args = types.SimpleNamespace(vid=0x258A, pid=0x019D, page=0xFF02, usage=2)
    e = vh.pick(entries, args)
    handle, caps = e["handle"], e["caps"]
    length = max(caps.FeatureReportByteLength, REPORT + 1)
    in_len = max(caps.InputReportByteLength if caps else 64, 64)
    event = vh.kernel32.CreateEventW(None, True, False, None)

    sends = []
    for spec in argv:
        name, _, hexs = spec.partition("=")
        if hexs.startswith("@"):
            with open(hexs[1:], "rb") as fh:
                data = fh.read()
        elif hexs:
            data = bytes(int(t, 16) for t in hexs.split())
        else:
            with open(name, "rb") as fh:
                data = fh.read()
        sends.append((name, data))

    t0 = time.time()
    idx = 0
    next_send = 0.8
    seen = 0
    while time.time() - t0 < 1.0 + 1.7 * len(sends):
        if idx < len(sends) and time.time() - t0 >= next_send:
            name, data = sends[idx]
            p = bytearray(519)
            p[:len(data)] = data
            buf = ctypes.create_string_buffer(length)
            buf[0] = bytes([REPORT])
            buf[1:1 + 519] = bytes(p)
            ok = vh.hid.HidD_SetFeature(handle, buf, length)
            print(f"[{time.time() - t0:5.2f}] -> {name} rec=0x{p[0]:02x} "
                  f"ok={bool(ok)}", flush=True)
            idx += 1
            next_send += 1.7
        buf = ctypes.create_string_buffer(in_len)
        read = vh.wintypes.DWORD()
        vh.kernel32.ResetEvent(event)
        ov = vh.OVERLAPPED()
        ov.hEvent = event
        ok = vh.kernel32.ReadFile(handle, buf, in_len,
                                  ctypes.byref(read), ctypes.byref(ov))
        if not ok:
            if ctypes.get_last_error() != 997:
                time.sleep(0.01)
                continue
            if vh.kernel32.WaitForSingleObject(event, 120) != 0:
                vh.kernel32.CancelIo(handle)
                continue
            vh.kernel32.GetOverlappedResult(handle, ctypes.byref(ov),
                                            ctypes.byref(read), False)
        if read.value:
            seen += 1
            print(f"[{time.time() - t0:5.2f}] IN: "
                  + " ".join(f"{b:02x}" for b in buf.raw[:read.value]), flush=True)
    print(f"input reports: {seen}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
