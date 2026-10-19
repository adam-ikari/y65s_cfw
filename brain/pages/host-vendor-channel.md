---
id: host-vendor-channel
title: "主机厂商通道 (HID report 9 / EP0)"
category: reference
status: active
tags: [hid vendor protocol probe]
created: "2026-10-19T22:56:12"
updated: "2026-10-19T23:09:22"
---

<!-- compiled_truth -->
主机侧厂商通道（HID report 9，usage page `0xff02`）—— 主机与键盘通信的那条链路，也是键盘作为「主机 ↔ 第二颗 SoC（模块）」桥的入口。
（模块链路本身的帧格式、命令全集、内容管道见 [[module-link]]。）

## 通道几何（实测 `tools/vendorhid.py list/desc` + 固件报告描述符 `0x4569`）

`258a:019d` 的 IF1 集合：

| # | usagePage/usage | Input | Feature | 用途 |
|---|---|---|---|---|
| col01 | `0x0001`/`0x0080` | 1 B (id 1) | – | 系统控制键 |
| col02 | `0x000c`/`0x0001` | 2 B (id 2) | – | 多媒体键 |
| col03 | **`0xff02`/`0x0001`** | 3 B (id 3) | – | 厂商输入（3 B） |
| col04 | `0x0001`/`0x0006` | 15 B (id 4) | – | **键盘（boot 风格 120 bit）** |
| col05 | `0xff00`/`0x0001` | – | 5 B (id 5) | **feature 5 = 进 ISP**（数据 `75 ..`） |
| col06 | `0xff00`/`0x0001` | – | 1031 B (id 6) | **feature 6 = ISP 页读取** |
| col07 | **`0xff02`/`0x0002`** | **7 B (id 9)** | **519 B (id 9)** | **主机 ↔ 设备厂商命令通道** |
| col08 | `0x0001`/`0x0002` | 7 B (id 7) | – | 鼠标 |

**IF1 没有任何 Output report** ⇒ 主机只能用 `SetFeature`/`GetFeature`（走 EP0 控制传输）跟固件讲话；
同类 ODM 上位机（driveall，需要 output report）从原理上就驱动不了本机。

## 固件侧 EP0 分发（基于 `build/fw_full.lst` 全线性反汇编）

- **SETUP 包暂存区 = `xdata 0x1147..0x114E`**（8 字节，字段顺序如下，可靠反证：描述符服务
  `0x1575..0x1889` 按 `xdata[0x114A]` 选择 flash 地址 —— 类型 1 → `0x4699`（设备描述符）、
  类型 2 → `0x46AB`（配置描述符）、类型 3 → 按 `xdata[0x1149]` 选字符串）：

  | 地址 | 字段 |
  |---|---|
  | `0x1147` | bmRequestType |
  | `0x1148` | bRequest |
  | `0x1149` | wValue 低 = **report ID** |
  | `0x114A` | wValue 高 = **报告类型**（`0x03` = Feature） |
  | `0x114B`/`0x114C` | wIndex 低/高（`0x0001` = IF1） |
  | `0x114D`/`0x114E` | wLength 低/高 |

- **EP0 OUT 数据缓冲 = `xdata 0x1100`，第 0 字节是 report ID**（`xdata[0x1100]==0x05`,
  `xdata[0x1101]==0x75` ⇒ ISP 桩，见下）。`xdata[0x0ECF:0x0ED0]` = 通用 16 位指针变量，
  分发器把它置成 `0x1100` 后按字段读。
- `xdata[0x1150]` = **EP0 状态**：SETUP 时先写入 bRequest，多包传输时被改写成子状态
  （已见 `2 / 4 / 6 / 9 / 0x0A / 0x0B`）；`xdata[0x1151]/[0x1152]` = 剩余长度。
- 分发器入口：`0x8293` / `0x82B7` / `0x8303` / `0x831D` / `0x8346` / `0x8363` / `0x83CD`
  - bRequest `9`（SET_REPORT）→ 指针置 `0x1100`，若 `xdata[0x1100]==0x05` 且 `xdata[0x1101]==0x75`
    就 `LJMP 0xB0ED` ⇒ **这就是 sinowisp 进 ISP 的真实触发路径**。
  - bRequest `0x0A` → `LCALL 0x7AB7` 后清 `0x1150`。
  - bRequest `0x0B` → 指针 = `0x1100`、`xdata[0x0F8A]=5`、`LCALL 0x6CA2`。
  - `0x8363` 处的判据其实是 SETUP 字段：`wValue 低=9` + `wValue 高=3` + `wIndex 低=1`
    ⇒ 就是 **`SetFeature(report 9)` on IF1**，置状态 `0x1150=0x0B`、清零偏移、把剩余长度 = wLength
    写入 `xdata[0x0B0A:0x0B0B]`（早先把它读成「3 字节命令记录 `09 03 01`」是误读）。
- `xdata[0x0F83:0x0F84]` = **代码空间(flash)读指针**；`0xA78E` 从 flash 拷 8 B 到 `xdata[0x1108]`
  （EP0 暂存），`0xA783` 写该指针。描述符服务 `0x1575..0x1889` 与 EP0 数据泵 `0x9771..0x97F8`
  都用它 ⇒ 主机可以经这条通道读 flash/描述符。
- `xdata[0x0B08:0x0B09]` = 520 B 暂存缓冲的**写偏移**，`xdata[0x0B0A:0x0B0B]` = **剩余字节数**，
  缓冲 `xdata 0x08F5..0x0AFC`（恰好 520 B）；`0x6CA2` → `0xA650` = 把一批字节追加进去
  （源指针存 `0x0ED1:0x0ED2`）。**不是**早先记的 520 B 环形缓冲。
- `0xA3D3` / `0xAEF7` = 单字节发送（写 `SBUF`，由 UART TX 中断续发），被 `0x9BF9`（`50` 帧组帧）
  与 `0xB204`（`50 81` 大块帧）共用。

## 主机 → 模块 的内容管道（重要）

`SetFeature(report 9, IF1, wLength=519)` 会启动一次搬运：50 个左右 8 字节 EP0 OUT 包被追加进上面的
520 B 缓冲，搬完后固件把它作为 `50 81 02 08` + 520 B 大块帧发给模块。详见 [[module-link]]。

## 实测（只读，安全）

- `get_feature(9)` 返回 519 B，内容是 **USB 描述符暂存区**（`18 03` 开头的字符串描述符
  `YD-Y65S`/`SINO WEALTH`/`0001`/`BY Tech`、配置描述符、HID 报告描述符片段）
  ⇒ feature 9 与描述符服务共用 `xdata 0x1100` 起同一块内存；空闲时读到的是描述符残留，
  不是「模块回包」。
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

- time: 2026-10-19T23:09:22
  kind: decision
  summary: "修正版：IF1 无 output report；SETUP 字段在 0x1147-0x114E(wValue低=report ID)；EP0 OUT 缓冲=xdata 0x1100(第0字节=report ID)；0x0B08-0x0B0B 是 520B 暂存缓冲的偏移/剩余;新增主机->模块内容管道入口说明"
  source: "build/fw_full.lst + tools/vendorhid.py"
  affects: [host-vendor-channel]

- time: 2026-10-19T23:09:22
  kind: reversal
  summary: "作废两条旧解读：(1) EP0 数据缓冲不是 xdata 0x0011/0x0012 而是 xdata 0x1100/0x1101(第0字节=report ID)，ISP 判据 0x1100==05 && 0x1101==75；(2) 0x1149/0x114A/0x114B 不是'3字节命令记录 09 03 01'而是 SETUP 包的 wValue低(report ID)/wValue高(报告类型)/wIndex低(接口)。另 0x0B08-0x0B0B 不是环形缓冲，是 0x08F5 起 520B 暂存缓冲的偏移/剩余计数"
  source: "0x8293-0x8460 全线性反汇编 + 0x1575 描述符服务(按 xdata[0x114A] 选 flash 地址)"
  affects: [host-vendor-channel, firmware-layout, module-link]

- time: 2026-10-19T23:09:22
  kind: evidence
  summary: "IF1 报告描述符(0x4569)复核: col01 系统控制1B/col02 多媒体2B/col03 ff02-01输入3B/col04 键盘15B/col05 feature5B(ISP入口)/col06 feature1031B(ISP页)/col07 ff02-02 输入7B+feature519B/col08 鼠标7B —— 无任何 output report"
  source: analysis/usbdesc.py --dev 0x4699 --hid 0x4569 --len 304
  affects: [host-vendor-channel]
