---
id: firmware-layout
title: "固件布局 (Firmware Layout)"
category: reference
status: active
created: "2026-10-19T16:46:15"
updated: "2026-10-19T22:56:13"
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

## 第二颗 SoC：主控 ↔ 模块的私有串口（屏幕 / 无线）

**主控只做三件事**：扫矩阵、USB HID、驱动 LED。**小屏上的内容是模块自己画的，不是 8051 画的。**

主控没有任何显示外设（`fwdis.py sfr` 与 `xdata` 全量枚举，均无遗漏）：

* 实际访问到的外设只有 4 组 PWM bank（`PWM00CON..PWM33DUTY2H`，各 6 通道）、UART、USB 和 GPIO。
* **不存在** LCD 控制器、SPI、I2C 寄存器（`SFR_NAMES`/`XSFR_NAMES` 全表已枚举）。
* flash 内没有字模/点阵/位图数据（`0x0700-0x0BFF` 是 PWM/曲线查表数据，`0x7D82` 是版本串）。
* 除 UART 外没有任何"软件翻转引脚"的串行总线（点屏用的 SPI 必然要软件翻转 SCL/SDA）。

固件里唯一的外设间串口：

| 项 | 位置 |
|---|---|
| 初始化 | `0xB169-0xB17F`：`SBRTH=0xFF`、`SBRTL=0xFB`、`SFINE=0x0C`、`SCON=0x50`（mode1 + REN） |
| 接收中断 | `0x8EF2`（`SCON.0`/RI 分支；`0x9E6C` `LCALL 0x8EF2`），取 `SBUF` → `xdata[0x0ECE]` |
| 发送 | `0xA3FC` / `0xAF18`：`MOV SBUF,A`，字节从 `xdata 0x0F57..` 环形区取 |
| 发送帧头 | `01 11 xx`（`0xA30D` 写 `0xC1`；`0xB1E7` 写 `0xE0`） |
| 接收缓冲 | `xdata 0x1130..0x113D`（≤14 B），魔数 `xdata[0x1130]==0x5A`，`xdata[0x0F61]=1` 表示收齐 |
| 收包处理 | `0xAF1B` → `0xB4FC`：只认 `xdata[0x1131]` = `0xAC`（写 `xdata[0x0F18]`）/ `0xFE`（写 `xdata[0x1155]`） |
| 状态变量 | `0x0F55`/`0x0F56`/`0x0F57..0x0F61`（收发指针与计数/标志） |
| 硬件连线 | `P4.1` 反复 `ORL P4CR,#02` + `CLR P4.1` 再 `ANL P4CR,#FD`（切输出拉低再切回输入）= 链路唤醒/握手脚；`P0.5` 是使能该链路的跳线（`JB P0.5`，`0x8EF8`/`0xAF40`） |

链路状态 `xdata[0x0F29]`：

* `1` = USB 有线；`0x25`/`0x35`/`0x45`/`0x55` = 2.4G / BT1 / BT2 / BT3（4 个无线档，写于 `0x1283`/`0x128F`/`0x129B`/`0x12A7`）。
* `xdata[0x0B8E]` = 上一档；`xdata[0x0BA7]` = 切换标志；切换入口 `0x116E`/`0x1265`/`0x127B`。
* 与 SMK 的 `src/peripherals/bk3632/rf_controller.h`（`RF_MODE_2_4G/BT1/BT2/BT3`）**四档一一对应**，
  但帧格式不同：SMK 用 `0xAA` 魔数，本机是 `0x5A` 魔数 + `01 11 xx` 帧头。故 SMK 的 BK3632
  驱动不能直接套用，需要按本机协议改写。

**结论（后两条为推断）**：YD-Y65S = 主控 SH68F90A + 第二颗 SoC（无线 + 彩色小屏 + 旋钮），两者只靠这条
UART 交换短报文（连接状态、HID 报告、灯效、模式切换）。因此 **屏幕不是 8051 驱动的**；自制固件若不说
这条私有串口协议，屏幕不会有主机侧内容、旋钮与 2.4G/BT 也不能用。

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

- time: 2026-10-19T17:50:04
  kind: decision
  summary: "确认矩阵引脚(15列/5行)与 0xBC00-0xCC00 四层键位表格式，LED 为内置 PWM bank 直驱；细节见 matrix-and-keymap"
  source: "analysis/keymap.py + fwdis.py"
  affects: [firmware-layout, matrix-and-keymap]

- time: 2026-10-19T22:19:43
  kind: decision
  summary: Rewrote compiled_truth to the new best understanding
  source: brain update-truth
  affects: [firmware-layout]

- time: 2026-10-19T22:31:27
  kind: evidence
  summary: "解码主控->模块命令帧：50 cmd len payload chk（组帧 0x9BF9，求和 0xB607）；命令码 02/03/04/08/0A/13/15/17/18/1A/1B，大 payload 通道 50 81 取自 xdata 0x08F4"
  source: "build/fw_full.lst (0x9BF9, 0xB204, 0xB607, call sites 0x009B-0x06D2)"
  affects: [screen-customization]

- time: 2026-10-19T22:46:33
  kind: evidence
  summary: "Sinowealth ISP bootloader 只走 USB: 反汇编内无 SBUF/SCON 引用 => 第二颗 SoC(模块)的固件无法经 8051 的 UART 读出; 8051<->模块链路是硬件 EUART(SBUF=0xAA/SCON=0xD8, TX 0xAF18/0xA3FC, RX 0x8EF5)。另: 接收器 258a:0150 已 dump 64KiB(sh68f90,MD5 38EFE2AA9E91B9A9B8A82C69E3C52DDB), 键盘两次读取逐字节一致(MD5 3F7EE6AE...), 与存档 dump 仅差 1 字节(0xA44F: 0x57 vs 0x05, 位于 0xA400..0xA47F 数据表内)"
  source: "build/fw_full.lst + firmware/backups/"
  affects: [firmware-layout]

- time: 2026-10-19T22:56:13
  kind: reversal
  summary: "早先『xdata 0x1130 = 模块 RX 帧 / 0x11C1 = 模块 TX 缓冲』的解读作废: get_feature(9) 返回的 519 B 描述符暂存内容说明 0x1100 起是主机厂商命令/EP0 暂存区, 0x1130/0x11C1 落在其中, 需按主机通道重解"
  source: "tools/vendorhid.py get --report 9 实测"
  affects: [firmware-layout]
