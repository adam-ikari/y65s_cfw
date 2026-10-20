#!/usr/bin/env -S uv run python
"""y65s_tool.py -- YD-Y65S 小彩屏 / 灯光 控制工具（图形界面）

驱动的是逆向所得的厂商通道：258a:019d, IF1 usage page 0xff02, feature report 9。
不提供 console 输出，一切在窗口内完成；绝不触碰 ISP 报告（5/6）。

功能（已验证）：
  * 屏幕校时（发给模块 ODM 0x34 时间包，固件会自动打 0x13 补丁）
  * 切换内置图片索引（ODM 0x51 / SET_TFT_BUILT_IN_INDEX）
  * 灯效模式 2 / 恢复命令（记录 0x0D / 0x0C，只写 RAM）
  * 监听键盘回传（纯读取）
实验性（需要显式确认，可能覆盖模块用户动画槽且无法恢复）：
  * 上传自定义图片（ODM 0x50 / SET_TFT_USER_ANIMATION，BMP 24bit 输入）

用法：  uv run tools/y65s_tool.py
"""

from __future__ import annotations

import ctypes
import datetime as dt
import pathlib
import struct
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import vendorhid as vh  # noqa: E402

VID, PID, PAGE, USAGE, REPORT = 0x258A, 0x019D, 0xFF02, 0x0002, 9
FEATURE_LEN = 520      # report 9 的 feature 长度（1 id + 519 payload）
WINDOW = 128           # 记录 0x04 每次转发的字节数 payload[7..134]
BLOCK = 512            # 记录 0x05 每次转发的字节数 payload[7..518]
BLOCK_DATA = BLOCK - 8 # 块头 AA 50 idx cnt 50 06 之后的净数据
CHUNK_DELAY = 1.8      # 记录 0x05 之间必须留够中继时间，否则固件会丢弃（TFT 忙）

SIZES = {  # 模块家族已知的屏幕规格（竖向）
    "96x160": (96, 160),
    "135x240": (135, 240),
    "240x240": (240, 240),
}


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("YD-Y65S 小屏工具（逆向协议版）")
        root.geometry("640x560")

        self.handle = None
        self.path = None
        self.cancel = threading.Event()

        top = ttk.Frame(root, padding=8)
        top.pack(fill="x")
        ttk.Button(top, text="连接键盘", command=self.connect).pack(side="left")
        self.status = ttk.Label(top, text="未连接", foreground="#b00")
        self.status.pack(side="left", padx=12)

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=8, pady=4)

        # ---- 屏幕 ----
        f1 = ttk.Frame(nb, padding=12)
        nb.add(f1, text="屏幕")
        row = ttk.Frame(f1); row.pack(fill="x", pady=4)
        ttk.Button(row, text="校时（同步电脑时间到屏幕）",
                   command=self.sync_time).pack(side="left")
        row = ttk.Frame(f1); row.pack(fill="x", pady=4)
        ttk.Label(row, text="内置图片编号(0-255):").pack(side="left")
        self.idx = tk.IntVar(value=0)
        ttk.Spinbox(row, from_=0, to=255, width=6, textvariable=self.idx).pack(side="left", padx=6)
        ttk.Button(row, text="切换", command=self.set_builtin).pack(side="left")

        row = ttk.Frame(f1); row.pack(fill="x", pady=4)
        ttk.Label(row, text="分辨率:").pack(side="left")
        self.size = tk.StringVar(value="96x160")
        ttk.Combobox(row, textvariable=self.size, values=list(SIZES),
                     width=9, state="readonly").pack(side="left", padx=6)
        ttk.Button(row, text="上传自定义图片(BMP)...",
                   command=self.ask_upload_bmp).pack(side="left", padx=6)
        self.prog = ttk.Progressbar(f1, length=400)
        self.prog.pack(pady=6)
        ttk.Button(f1, text="停止上传", command=self.cancel.set).pack()

        tip = ("提示：\n"
               "· 校时 / 内置图 / 灯效 = 不写闪存，可随意尝试（内置图编号在不同页面下可能看不出效果）。\n"
               "· 上传图片会写模块自己的「用户动画槽」（相当于厂商工具的自定义图片功能），\n"
               "  会覆盖现有图片且没有厂商工具时可能无法恢复——采用前请三思。")
        ttk.Label(f1, text=tip, foreground="#555", justify="left").pack(pady=8)

        # ---- 灯光 ----
        f2 = ttk.Frame(nb, padding=12)
        nb.add(f2, text="灯光/救援")
        ttk.Button(f2, text="灯效模式 2（实验发现：会切换屏幕背景）",
                   command=self.light_mode2).pack(fill="x", pady=4)
        ttk.Button(f2, text="发送恢复命令 0x0C",
                   command=lambda: self.send_simple(0x0C)).pack(fill="x", pady=4)
        ttk.Button(f2, text="发送 0x0B",
                   command=lambda: self.send_simple(0x0B)).pack(fill="x", pady=4)

        # ---- 日志 ----
        f3 = ttk.Frame(nb, padding=12)
        nb.add(f3, text="日志")
        self.log = tk.Text(f3, height=20)
        self.log.pack(fill="both", expand=True)

        # ---- 监听 ----
        f4 = ttk.Frame(nb, padding=12)
        nb.add(f4, text="监听")
        row = ttk.Frame(f4); row.pack(fill="x")
        ttk.Button(row, text="监听 5 秒（纯读取）", command=self.watch5).pack(side="left")
        self.watch_out = tk.Text(f4, height=20)
        self.watch_out.pack(fill="both", expand=True, pady=6)

        self.log_write("工具就绪。先点「连接键盘」。")

    # ------------------------------------------------------------------
    def log_write(self, msg: str) -> None:
        self.log.insert("end", time_hint() + " " + msg + "\n")
        self.log.see("end")

    def connect(self) -> None:
        try:
            hits = [
                e for e in vh.enumerate_hid()
                if e.get("vid") == VID and e.get("pid") == PID
                and e.get("caps") and e["caps"].UsagePage == PAGE
                and e["caps"].Usage == USAGE
            ]
        except Exception as exc:
            messagebox.showerror("连接失败", str(exc))
            return
        if not hits:
            self.status.config(text="未找到（检查键盘是否插好/是否在 ISP 模式）", foreground="#b00")
            self.log_write("未找到 258a:019d 的 0xff02 vendor 集合")
            return
        self.handle = hits[0]["handle"]
        self.path = hits[0]["path"]
        caps = hits[0]["caps"]
        self.status.config(text=f"已连接  feature={caps.FeatureReportByteLength}", foreground="#070")
        self.log_write(f"已连接: {self.path}")

    def send_main(self, payload: bytes) -> bool:
        """写 feature report 9，payload = 519 B（report id 由工具补到 buf[0]）。"""
        if self.handle is None:
            messagebox.showinfo("未连接", "先点「连接键盘」")
            return False
        buf = ctypes.create_string_buffer(FEATURE_LEN)
        buf[0] = bytes([REPORT])
        buf[1:1 + len(payload)] = payload
        ok = vh.hid.HidD_SetFeature(self.handle, buf, FEATURE_LEN)
        return bool(ok)

    # ------------------------------------------------------------------
    # 记录协议封装
    def rec_with_window(self, window: bytes) -> bool:
        p = bytearray(519)
        p[0] = 0x04
        p[7:7 + len(window)] = window[:WINDOW]
        return self.send_main(bytes(p))

    def rec_block(self, sub: int, block: bytes) -> bool:
        """记录 0x05：payload[4] 选模块命令（0x6E+sub），payload[7..518] 共 512 B。"""
        p = bytearray(519)
        p[0] = 0x05
        p[4] = sub & 0x07
        p[7:7 + len(block)] = block[:BLOCK]
        return self.send_main(bytes(p))

    def send_simple(self, cmd: int) -> None:
        ok = self.send_main(bytes([cmd]) + bytearray(518))
        self.log_write(f"记录 0x{cmd:02X} 发送 {'成功' if ok else '失败'}")

    def light_mode2(self) -> None:
        self.send_simple(0x0D)

    def sync_time(self) -> None:
        now = dt.datetime.now()
        wd = (now.weekday() + 1) % 7  # 厂商 Hu 的星期参数 0-6
        ts = bytes([0x5A, 0x01, 0x5A, now.year % 100, now.month, now.day,
                    now.hour, now.minute, now.second, wd])
        # 厂商 contentSize=24：10 字节时间 + 14 字节 0
        payload = ts + bytes(24 - len(ts))
        # 厂商 xn() 组包：AA 34 <contentSize=0x18> 00 00 00 01 00
        packet = bytes([0xAA, 0x34, 0x18, 0x00, 0x00, 0x00, 0x01, 0x00]) + payload
        ok = self.rec_with_window(packet)
        self.log_write(f"校时 {now:%Y-%m-%d %H:%M:%S} wd={wd} {'成功' if ok else '失败'}"
                       f"（注意：屏幕只在时钟页才看得出来；"
                       f"若时钟没跳，用 tools/tft_probe.py clock 扫窗口布局）")

    def set_builtin(self) -> None:
        idx = self.idx.get() & 0xFF
        # ODM 0x51 / 模块 0x6F：contentSize=1，数据首字节 = 索引
        p = bytearray(519)
        p[0] = 0x05
        p[4] = 0x01
        p[7] = idx
        ok = self.send_main(bytes(p))
        self.log_write(f"切换内置图 #{idx} {'成功' if ok else '失败'}")

    # ------------------------------------------------------------------
    # BMP -> RGB565 -> 上传（实验性）
    def ask_upload_bmp(self) -> None:
        if not messagebox.askyesno(
            "确认风险",
            "上传会写入模块自身的「用户动画槽」（厂商工具的自定义图片功能）。\n\n"
            "· 可能覆盖键盘现有的自定义图片\n"
            "· 没有厂商工具时可能无法恢复\n\n确定继续吗？",
        ):
            return
        fn = filedialog.askopenfilename(filetypes=[("BMP 图片", "*.bmp")])
        if not fn:
            return
        w, h = SIZES[self.size.get()]
        try:
            rgb565 = bmp_to_rgb565(fn, w, h)
        except Exception as exc:
            messagebox.showerror("转换失败", str(exc))
            return
        frames = 1
        header = bytearray([0xFF] * 256)
        header[0] = frames
        header[frames] = 0            # 1 帧：header = 01 00 FF FF ...
        data = bytes(header) + rgb565
        total = (len(data) + BLOCK_DATA - 1) // BLOCK_DATA
        blocks = []
        for b in range(total):
            piece = data[b * BLOCK_DATA:(b + 1) * BLOCK_DATA]
            piece = piece + bytes(BLOCK_DATA - len(piece))
            blocks.append(bytes([0xAA, 0x50, b & 0xFF, (b >> 8) & 0xFF,
                                 total & 0xFF, (total >> 8) & 0xFF, 0x50, 0x06]) + piece)
        self.log_write(f"开始上传: {w}x{h}, RGB565 {len(rgb565)} B, "
                       f"总流 {len(data)} B, {total} 块 x {BLOCK} B "
                       f"(约 {total * CHUNK_DELAY / 60:.1f} 分钟)")
        self.cancel.clear()
        threading.Thread(target=self._upload_worker, args=(blocks,), daemon=True).start()

    def _upload_worker(self, blocks: list[bytes]) -> None:
        total = len(blocks)
        for j, block in enumerate(blocks):
            if self.cancel.is_set():
                self.log_write(f"已停止 @ {j}/{total}")
                return
            if not self.rec_block(0x00, block):
                self.log_write(f"块 {j} 写入失败，已中止")
                return
            if j % 10 == 0 or j == total - 1:
                self.log_write(f"进度 {j + 1}/{total}")
            self.root.after(0, lambda j=j: self.prog.config(value=100 * (j + 1) / total))
            if j != total - 1:
                time.sleep(CHUNK_DELAY)
        self.root.after(0, lambda: self.log_write(
            "上传结束，看屏幕是否出现测试图案（四色 + 十字线）。"))

    # ------------------------------------------------------------------
    def watch5(self) -> None:
        def work() -> None:
            e = None
            for x in vh.enumerate_hid(overlapped=True):
                if x.get("vid") == VID and x.get("pid") == PID and x.get("caps") \
                        and x["caps"].UsagePage == PAGE and x["caps"].Usage == USAGE:
                    e = x
                    break
            if e is None:
                self.root.after(0, lambda: self.watch_out.insert("end", "设备未找到\n"))
                return
            caps = e["caps"]
            length = max(caps.InputReportByteLength if caps else 64, 64)
            event = vh.kernel32.CreateEventW(None, True, False, None)
            deadline = time.time() + 5
            out = []
            while time.time() < deadline and not self.cancel.is_set():
                buf = ctypes.create_string_buffer(length)
                read = vh.wintypes.DWORD()
                vh.kernel32.ResetEvent(event)
                ol = vh.OVERLAPPED()
                ol.hEvent = event
                ok = vh.kernel32.ReadFile(e["handle"], buf, length, ctypes.byref(read),
                                          ctypes.byref(ol))
                if not ok:
                    if ctypes.get_last_error() != vh.ERROR_IO_PENDING:
                        break
                    if vh.kernel32.WaitForSingleObject(event, 400) == vh.WAIT_TIMEOUT:
                        continue
                    if not vh.kernel32.GetOverlappedResult(e["handle"], ctypes.byref(ol),
                                                           ctypes.byref(read), False):
                        continue
                if read.value:
                    raw = buf.raw[:read.value]
                    out.append(time.strftime("%H:%M:%S") + " " +
                               " ".join(f"{b:02x}" for b in raw))
            vh.kernel32.CancelIo(e["handle"])
            self.root.after(0, lambda: self.watch_out.insert(
                "end", "\n".join(out) + ("\n" if out else "（5 秒内无回传）\n")))

        threading.Thread(target=work, daemon=True).start()


def time_hint() -> str:
    return dt.datetime.now().strftime("%H:%M:%S")


def bmp_to_rgb565(path: str, w: int, h: int) -> bytes:
    """最小 BMP 读取器：1/4/8/16/24/32bpp 调色板或直接像素 -> 缩放到 w x h -> RGB565。"""
    raw = pathlib.Path(path).read_bytes()
    if raw[:2] != b"BM":
        raise ValueError("不是 BMP 文件")
    off, = struct.unpack_from("<I", raw, 10)
    hdr, = struct.unpack_from("<I", raw, 14)
    if hdr < 40:
        raise ValueError("仅支持 BITMAPINFOHEADER(40) 及以上")
    bw, bh, bpp = struct.unpack_from("<iih", raw, 18)
    if bpp not in (1, 4, 8, 16, 24, 32):
        raise ValueError(f"不支持 {bpp}bpp")
    flip = bh > 0
    rows = abs(bh)
    row_bytes = ((bw * bpp + 31) // 32) * 4
    pal_n = 0
    if bpp in (1, 4, 8):
        pal_n = struct.unpack_from("<I", raw, 46)[0] or (1 << bpp)
    pal = []
    for i in range(min(pal_n, 256)):
        b, g, r = raw[54 + 4 * i: 54 + 4 * i + 3]
        pal.append((r, g, b))

    def get(i: int) -> tuple[int, int, int]:
        if bpp >= 16:
            b0 = raw[off + i * bpp // 8: off + (i + 1) * bpp // 8]
            if bpp == 24:
                return b0[2], b0[1], b0[0]
            if bpp == 32:
                return b0[2], b0[1], b0[0]
            words, = struct.unpack("<H", bytes(b0))
            r = (words >> 10) & 0x1F
            g = (words >> 5) & 0x1F
            b = words & 0x1F
            return r << 3, g << 3, b << 3
        bit = 8 // bpp
        idx = (raw[off + i // bit] >> ((bit - 1 - i % bit) * bpp)) & ((1 << bpp) - 1)
        return pal[idx] if idx < len(pal) else (0, 0, 0)

    grid = [[get(y * bw + x) for x in range(bw)] for y in range(rows)]
    if flip:
        grid.reverse()

    def clamp(v, m):
        return 0 if v < 0 else m if v > m else v

    data = bytearray()
    for ty in range(h):
        sy = ty * rows / h
        r0 = int(sy)
        for tx in range(w):
            sx = tx * bw / w
            c0 = grid[clamp(r0, rows - 1)][clamp(int(sx), bw - 1)]
            r, g, b = c0
            v = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
            data += bytes([(v >> 8) & 0xFF, v & 0xFF])
    return bytes(data)


def main() -> int:
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
