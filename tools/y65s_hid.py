#!/usr/bin/env -S uv run python
"""y65s_hid.py -- cross platform HID access to the YD-Y65S vendor channel.

The keyboard exposes a lot of HID collections (keyboard, mouse, vendor
collections ...).  We need the one with usage page 0xff02 / usage 0x0002,
which carries feature report 9 (519 bytes) and an 8 byte input report.

Windows: hidapi (which talks to hid.dll).
Linux:   hidapi -> /dev/hidrawN; the collection is picked by usage page/usage
         from the report descriptor, and we may need the kernel `hid` driver
         detached for input reports (feature reports work regardless).
macOS:   hidapi -> IOHIDManager.

The Windows build of this project also has tools/vendorhid.py, which can open
collections the hidapi listing does not expose; it is used as a fallback
when the hidapi enumeration comes up empty.
"""

from __future__ import annotations

import ctypes
import time

VID, PID = 0x258A, 0x019D
USAGE_PAGE, USAGE = 0xFF02, 0x0002
REPORT = 9
FEATURE_LEN = 520        # report id + 519 bytes
INPUT_LEN = 8            # report id + 7 bytes


class HidError(RuntimeError):
    pass


def _import_hid():
    try:
        import hid  # type: ignore
        return hid
    except Exception:
        return None


def _import_vendorhid():
    import pathlib
    import sys
    here = pathlib.Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    try:
        import vendorhid  # type: ignore
        return vendorhid
    except Exception:
        return None


def enumerate_collections(vid: int = VID, pid: int = PID) -> list[dict]:
    """Every collection of the device we can see, with its usage page/usage."""
    out: list[dict] = []
    hid = _import_hid()
    if hid is not None:
        try:
            for dev in hid.enumerate(vid, pid):
                out.append({
                    "path": dev.get("path"),
                    "serial": dev.get("serial_number"),
                    "product": dev.get("product_string"),
                    "usage_page": dev.get("usage_page", 0),
                    "usage": dev.get("usage", 0),
                    "backend": "hidapi",
                })
        except Exception as exc:
            out.append({"error": f"hidapi enumerate failed: {exc}"})
    if not out:
        vh = _import_vendorhid()
        if vh is not None:
            try:
                for e in vh.enumerate_hid():
                    if e.get("vid") == vid and e.get("pid") == pid:
                        caps = e.get("caps")
                        out.append({
                            "path": e.get("path"),
                            "usage_page": caps.UsagePage if caps else 0,
                            "usage": caps.Usage if caps else 0,
                            "backend": "vendorhid(win32)",
                        })
            except Exception as exc:
                out.append({"error": f"vendorhid enumerate failed: {exc}"})
    return out


def find_collection(vid: int = VID, pid: int = PID,
                    usage_page: int = USAGE_PAGE, usage: int = USAGE) -> dict | None:
    cols = enumerate_collections(vid, pid)
    for c in cols:
        if c.get("usage_page") == usage_page and c.get("usage") == usage:
            return c
    # some backends do not report usage pages; fall back to the only device
    cands = [c for c in cols if "path" in c]
    if len(cands) == 1:
        return cands[0]
    return None


class Device:
    """The vendor collection, opened for feature report 9."""

    def __init__(self, path: str | None = None, vid: int = VID, pid: int = PID,
                 usage_page: int = USAGE_PAGE, usage: int = USAGE) -> None:
        self.backend = "hidapi"
        self.handle = None
        self._vh = None
        self._vh_entry = None
        self._event = None
        if path is None:
            col = find_collection(vid, pid, usage_page, usage)
            if col is None:
                raise HidError(
                    "vendor collection (usage page 0x%04x / usage 0x%04x) not found"
                    % (usage_page, usage))
            path = col["path"]
        self.path = path
        hid = _import_hid()
        if hid is not None:
            try:
                self.handle = hid.device()
                self.handle.open_path(path)
                self.backend = "hidapi"
                return
            except Exception:
                self.handle = None
        vh = _import_vendorhid()
        if vh is not None:
            import types as _t
            args = _t.SimpleNamespace(vid=vid, pid=pid, page=usage_page, usage=usage)
            try:
                entry = vh.pick(vh.enumerate_hid(overlapped=True), args)
                vh.guard(entry, REPORT)
                self._vh = vh
                self._vh_entry = entry
                self._event = vh.kernel32.CreateEventW(None, True, False, None)
                self.backend = "vendorhid(win32)"
                return
            except Exception:
                self._vh = None
        raise HidError(f"cannot open {path}")

    # -- feature reports --------------------------------------------------
    def send_feature(self, data: bytes) -> bool:
        """data must contain the report id in byte 0."""
        if self.handle is not None:
            try:
                n = self.handle.send_feature_report(bytes(data))
                return n == len(data) or n > 0
            except Exception as exc:
                raise HidError(f"send_feature_report failed: {exc}") from exc
        vh = self._vh
        entry = self._vh_entry
        length = max(entry["caps"].FeatureReportByteLength, len(data))
        buf = vh.ctypes.create_string_buffer(length)
        vh.ctypes.memmove(buf, bytes(data), len(data))
        return bool(vh.hid.HidD_SetFeature(entry["handle"], buf, length))

    def get_feature(self, length: int = FEATURE_LEN) -> bytes:
        if self.handle is not None:
            try:
                return bytes(self.handle.get_feature_report(REPORT, length))
            except Exception:
                return b""
        vh = self._vh
        entry = self._vh_entry
        length = max(entry["caps"].FeatureReportByteLength, length)
        buf = vh.ctypes.create_string_buffer(length)
        buf[0] = bytes([REPORT])
        if not vh.hid.HidD_GetFeature(entry["handle"], buf, length):
            return b""
        return bytes(buf.raw[:length])

    # -- input reports ----------------------------------------------------
    def read_input(self, seconds: float = 1.0) -> bytes:
        """The device's 8 byte answer frame.

        Best effort: on Linux the kernel hid driver may swallow the
        interrupt endpoint, and hidraw may not deliver it at all.  Feature
        reports (what we actually need) always work.
        """
        if self.handle is not None:
            try:
                self.handle.set_nonblocking(True)
            except Exception:
                pass
            deadline = time.time() + seconds
            try:
                while time.time() < deadline:
                    data = self.handle.read(INPUT_LEN)
                    if data:
                        return bytes(data)
                    time.sleep(0.02)
            except Exception:
                return b""
            finally:
                try:
                    self.handle.set_nonblocking(False)
                except Exception:
                    pass
            return b""
        vh = self._vh
        entry = self._vh_entry
        in_len = max(entry["caps"].InputReportByteLength if entry["caps"] else 64, 64)
        deadline = time.time() + seconds
        while time.time() < deadline:
            buf = vh.ctypes.create_string_buffer(in_len)
            read = vh.wintypes.DWORD()
            vh.kernel32.ResetEvent(self._event)
            ov = vh.OVERLAPPED()
            ov.hEvent = self._event
            ok = vh.kernel32.ReadFile(entry["handle"], buf, in_len,
                                     vh.ctypes.byref(read), vh.ctypes.byref(ov))
            if not ok:
                if vh.ctypes.get_last_error() != 997:
                    time.sleep(0.02)
                    continue
                if vh.kernel32.WaitForSingleObject(self._event, 200) != 0:
                    vh.kernel32.CancelIo(entry["handle"])
                    continue
                vh.kernel32.GetOverlappedResult(entry["handle"], vh.ctypes.byref(ov),
                                                vh.ctypes.byref(read), False)
            if read.value:
                return bytes(buf.raw[:read.value])
        return b""

    def close(self) -> None:
        if self.handle is not None:
            try:
                self.handle.close()
            except Exception:
                pass


if __name__ == "__main__":  # pragma: no cover
    for c in enumerate_collections():
        print(c)
