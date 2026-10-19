---
id: firmware-layout
title: "\""
category: reference
status: active
created: "2026-10-19T16:46:15"
updated: "2026-10-19T16:46:41"
---

<!-- compiled_truth -->
## 芯片与 flash 划分

Sinowealth **SH68F90/A**，8051 内核，24 MHz 系统时钟，64 KiB flash：

| 区间 | 用途 |
|---|---|
| `0x0000-0xEFFF` | 应用固件（61440 B） |
| `0xF000-0xFFFF` | ISP bootloader（4096 B） |

`sinowisp` 的 `platform_spec.rs` 记录：`SH68F90: 61440 + 4096, page 2048`。

## dump 文件

| 文件 | 大小 | MD5 |
|---|---|---|
| `firmware/YD-Y65S_full.bin` | 65536 | `c94234578ba69c566576b6e2569dbb34` |
| `firmware/YD-Y65S_firmware.bin` | 61440 | `b27db05404ff3de42d4de92b419a8891` |
| `firmware/YD-Y65S_bootloader.bin` | 4096 | `3e0ebd0c440af5236d7ff8872343f85d` |

bootloader 的 MD5 与社区已知的 `3e0ebd0c` 完全一致，说明平台判断与 dump 结构正确。

## 中断向量表

| 向量 | 目标 | 说明 |
|---|---|---|
| `0x0000` | `LJMP 0x89D7` | reset / main |
| `0x0003` | `LJMP 0xA114` | INT0 |
| `0x000B` | `LJMP 0xD1FE` | Timer0 |
| `0x0013` | `LJMP 0xD0F0` | INT1 |
| `0x001B` | `LJMP 0x0006` | 共享清标志 RETI 桩 |
| `0x0033` | `LJMP 0x900F` | — |
| `0x003B` | `LJMP 0x9EAA` | USB（SH68F90 的第 7 号向量） |
| `0x0043` | `LJMP 0x61DA` | — |
| `0x004B` | `LJMP 0xD042` | — |
| `0x0053` | `LJMP 0xD056` | — |
| `0x005B` | `LJMP 0xD06A` | — |
| `0x0063` | `LJMP 0x1F22` | — |
| `0x006B` | `LJMP 0x9E41` | — |

`0x0023` / `0x002B` 处不是 `LJMP`，而是内联处理代码。

## 已定位的关键结构

| 位置 | 内容 |
|---|---|
| `0x4526` | IF0 HID 报告描述符（67 B，标准 6KRO 键盘 + 5 个 LED） |
| `0x4569` | IF1 HID 报告描述符（304 B，8 个 collection：System / Consumer / 0xFF02 / NKRO / 0xFF00 cmd / 0xFF00 data / 0xFF02 / Mouse） |
| `0x4699` | USB 设备描述符（`258A:019D`，bcdDevice `3003`） |
| `0x46AB` | 配置描述符（2 interface，EP1 IN 8 B + EP2 IN 16 B） |
| `0x44DE/44EE/4507/4511` | 字符串：`YD-Y65S` / `SINO WEALTH` / `0001` / `BY Tech` |
| `0x7D82` | 固件版本串 `YD-Y65S-5.0 A` |
| `0xB0ED` | ISP 跳转桩（`CLR IEN0.7` / `MOV B,#A5` / `MOV A,#5A` / `LJMP 0xFF00`） |
| `0x82EA` | ISP 命令分发（`05 75` → 跳转桩） |
| `0x35E8` | 矩阵扫描跳转表（10 个 `LJMP`，按 bank 分批扫 P6/P5/P4/P7） |
| `0xB108/0xB10C/0xB113` | 扫描结果写入 XDATA `0x0ECD` 的辅助例程 |
| `0xBC00-0xCC00` | 键位/配置表（4 字节记录，列优先，含 `00 00 00 29`=Esc 之类） |

## 熵与空区

* `0xD222-0xEFFF` 共 7646 字节全 `0x00`（未使用）。
* `0xA480-0xA5FF` 384 字节全 `0x00`。
* 低熵区 `0xA800`(1.07)、`0xBC00-0xCBFF`(~1.35)、`0xCC00`(0.02) 是配置/键位/映射表。
* `0x0700-0x0BFF` 是查表数据（正弦/GAMMA/字模一类的曲线表）。

## 注意

`0x88-0x8F` 是 `MOV direct,Rn` 而非 `MOV Rn,direct`；早期 JS 版反汇编器在这一点上渲染反了，
Python 版（`analysis/mcs51.py`）已修正。


## Timeline

- time: 2026-10-19T16:46:15
  kind: decision
  summary: "Created this page: \""
  source: created via brain create-page
  affects: [firmware-layout]

- time: 2026-10-19T16:46:41
  kind: decision
  summary: "\""
  source: brain update-truth
  affects: [firmware-layout]
