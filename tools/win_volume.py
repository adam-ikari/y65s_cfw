#!/usr/bin/env python
"""win_volume.py -- read (or set) the Windows master output volume.

This is how we check the knob end to end: the knob makes the keyboard send a
HID consumer usage (Volume Increment / Volume Decrement), so the Windows
master volume must move when the knob is turned.  If the volume moves, the
host-facing half of the knob still works; if it does not, the knob path is
broken on the keyboard side.

    uv run --with pycaw --with comtypes tools/win_volume.py
    uv run --with pycaw --with comtypes tools/win_volume.py --set 40
    uv run --with pycaw --with comtypes tools/win_volume.py --watch 30
"""

from __future__ import annotations

import argparse
import sys
import time


def endpoint_volume():
    """Return (volume_object, scalar_volume, mute_state)."""
    from pycaw.pycaw import AudioUtilities

    device = AudioUtilities.GetSpeakers()
    volume = device.EndpointVolume
    return volume, volume.GetMasterVolumeLevelScalar(), bool(volume.GetMute())


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--set", type=float, metavar="V",
                    help="set the master volume to 0..1 (e.g. 0.4)")
    ap.add_argument("--watch", type=float, metavar="SECONDS",
                    help="poll the volume every 0.5 s and print changes")
    args = ap.parse_args(argv)

    try:
        volume, scalar, mute = endpoint_volume()
    except Exception as exc:  # noqa: BLE001 - report whatever went wrong
        print(f"读不到音频端点: {exc}")
        return 1

    if args.set is not None:
        value = max(0.0, min(1.0, args.set))
        volume.SetMasterVolumeLevelScalar(value, None)
        print(f"master volume -> {value:.4f} ({value * 100:.0f}%)")
        return 0

    if args.watch:
        deadline = time.time() + args.watch
        last = None
        while time.time() < deadline:
            _, scalar, mute = endpoint_volume()
            if scalar != last:
                print(f"[{time.strftime('%H:%M:%S')}] volume {scalar * 100:.1f}%"
                      f"{' (muted)' if mute else ''}", flush=True)
                last = scalar
            time.sleep(0.5)
        return 0

    print(f"master volume {scalar * 100:.1f}%{' (muted)' if mute else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
