---
id: host-vendor-channel
title: "主机厂商通道 (HID report 9 / EP0)"
category: reference
status: active
tags: [hid vendor protocol probe]
created: "2026-10-19T22:56:12"
updated: "2026-10-19T22:56:13"
---

<!-- compiled_truth -->
主机侧厂商通道（HID report 9，usage page `0xff02`）——主机与键盘通信、以及键盘作为「主机↔第二颗 SoC」桥的那条链路。

## 通道几何（实测：`uv run tools/vendorhid.py list/desc`）
`258a:019d` 的 IF1 有多个集合：

| 集合 | usagePage/usage | Input | Feature | 用途 |
|---|---|---|---|---|
| col01 | `0x0001`/`0x0080` | 2 B | – | 系统控制键 |
| col02 | `0x000c`/`0x0001` | 3 B | – | 多媒体键 |
| col03 | **`0xff02`/`0x0001`** | 4 B | – | 厂商输入（4 B） |
| col04 | `0x0001`/`0x0002` | 12 B | – | 鼠标 |
| col05 | `0xff00`/`0x0001` | – | 6 B | **feature report 5 = 进 ISP**（`75 00 00 00 00`） |
| col06 | `0xff00`/`0x0001` | – | 1032 B | **feature report 6 = ISP 页** |
| col07 | **`0xff02`/`0x0002`** | **8 B**（ID 9 + 7 B） | **520 B**（ID 9 + 519 B） | **主机↔设备厂商命令通道** |

固件里的报告描述符（`0x4569`，304 B）确认同一 collection（0xFF02/0x02）内：
`Feature 4152bit (519x8) id=9` + `Input 56bit (7x8) id=9`。

## 固件侧 EP0 分发（基于 `build/fw_full.lst` 全线性反汇编）
- `xdata[0x1150]` = 当前 **bRequest**；`xdata[0x1151]/[0x1152]` = 剩余长度；`xdata[0x115C]` = 标志。
- `xdata[0x0ECF:0x0ED0]` = 通用 16 位指针变量，多处被置为 **0x0011** 再读取 EP0 数据：
  `xdata[0x0011]` = report ID，`xdata[0x0012..]` = payload。
- 分发器：`0x8293` / `0x82B7` / `0x8303` / `0x831D` / `0x8346` / `0x8363` / `0x83CD`
  - bRequest `9`（SET_REPORT）→ 取 `[0x0011]`，若 `==5` 且 `[0x0012]==0x75` 则 `LJMP 0xB0ED`
    （ISP 跳转桩）。这就是 sinowisp 进入 ISP 的真实触发路径。
  - bRequest `0x0A` → `LCALL 0x7AB7` 后清 `0x1150`；`0x0B` → 指针=0x0011、`xdata[0x0F8A]=5`、`LCALL 0x6CA2`。
  - `xdata[0x1149/0x114A/0x114B]` = 另一组 3 字节命令（例：`09 03 01` ⇒ 置 `xdata[0x1150]=0x0B`、清 `xdata[0x0B08:0x0B09]`）。
- `xdata[0x0F83:0x0F84]` = **代码空间(flash)读指针**；`0xA78E` 从 flash 拷 8 B 到 `xdata[0x1108]`
  （EP0 暂存），`0xA783` 写该指针。描述符服务代码 `0x1575..0x1889` 与 EP0 数据泵 `0x9771..0x97F8`
  都用它 ⇒ 主机可以经这条通道读 flash/描述符。
- `xdata[0x0B08..0x0B0B]` = 两个 16 位计数器，比较界限 **0x0208 = 520** ⇒ 一个 520 字节环形缓冲；
  `BITS_54` = 有数据待发；`0x6CA2` = 入队（源指针存 `0x0ED1:0x0ED2`）。
- `0x6B67..0x6CA1` = 收包组装器：凑满 15 字节后把 `xdata[0x0E0B]` 置 **0x5A**（0x5A 帧就绪标志）。

## 实测（只读，安全）
- `get_feature(9)` 返回 519 B，内容是 **USB 描述符暂存区**（`18 03` 字符串描述符
  `YD-Y65S`/`SINO WEALTH`/`0001`/`BY Tech`、配置描述符、HID 报告描述符片段）。
  ⇒ feature 9 的缓冲与 EP0 暂存区共用同一块 xdata（约 `0x1100` 起）。
  这推翻了早先「`xdata 0x1130` = 模块 RX 帧、`0x11C1` = 模块 TX」的解读 —— 它们落在这块
  519 B 缓冲区内，语义需要重新核对（见 [[firmware-layout]]）。
- 空闲 12 s 内 **input report 9 一帧都没有** ⇒ 7 B IN 不是周期上报，只在有事件/数据时出现。

## 工具
`tools/vendorhid.py`（纯 stdlib + ctypes；代码里硬性拒绝触碰 report 5/6 与键鼠集合）：

    uv run tools/vendorhid.py list  --vid 258a --pid 019d
    uv run tools/vendorhid.py desc  --vid 258a --pid 019d --page ff02 --usage 2
    uv run tools/vendorhid.py get   --vid 258a --pid 019d --page ff02 --usage 2 --report 9
    uv run tools/vendorhid.py set   --vid 258a --pid 019d --page ff02 --usage 2 --report 9 --data ".."
    uv run tools/vendorhid.py watch --vid 258a --pid 019d --page ff02 --usage 2 --seconds 10

写操作仍受 [[no-write-policy]] 约束：**未经逐次许可不得刷写 flash**；`set` 只发命令行里明写的字节。


## Timeline

- time: 2026-10-19T22:56:12
  kind: decision
  summary: "Created this page: 主机厂商通道 (HID report 9 / EP0)"
  source: "tools/vendorhid.py + build/fw_full.lst"
  affects: [host-vendor-channel]

- time: 2026-10-19T22:56:13
  kind: decision
  summary: "主机↔设备厂商通道 = usage 0xff02/0x0002 的 report 9(7B IN + 519B feature)；固件 EP0 分发按 bRequest 分派，SET_REPORT 数据里 [0x0011]==5 && [0x0012]==0x75 即 ISP 桩；0x0F83/84 是 flash 读指针；0x0B08-0x0B0B 是 520B 环缓"
  source: "build/fw_full.lst + tools/vendorhid.py"
  affects: [host-vendor-channel]

- time: 2026-10-19T22:56:13
  kind: evidence
  summary: "实测: get_feature(9) 空闲时返回 USB 描述符暂存内容(字符串表+配置/HID描述符); 空闲 12s 内 input report 9 无任何帧"
  source: tools/vendorhid.py get/watch
  affects: [host-vendor-channel]
