---
id: module-link
title: "模块链路：主控 ↔ 屏幕/无线 SoC"
category: reference
status: active
tags: [module, uart, screen, protocol]
created: "2026-10-19T23:09:10"
updated: "2026-10-19T23:09:10"
---

<!-- compiled_truth -->
主控（SH68F90A）↔ 模块（第二颗 SoC：无线 + 彩色小屏）之间那条私有 UART 链路的完整现状。相关页：[[screen-customization]]（目标）、[[host-vendor-channel]]（主机入口）、[[driveall-protocol]]（同族 ODM 主机协议）。

## 物理层

- 硬件 EUART：`SBUF=0xAA`、`SCON=0xD8`；初始化在 **`0xB15A..0xB187`**：`SCON=0x50`（模式 1，REN=1）、
  `SBRTH=0xFF`、`SBRTL=0xFB`、`SFINE=0x0C`、清 TI/RI、置 `PCON` bit6、开 `IEN1` bit6（UART 中断）。
  （`SADDR/SADEN` 在本固件未用；接收器固件用了 → 两边不同构建。）
- 发送是**中断驱动的分包发送**：帧缓冲 `xdata 0x11C1`，流描述符 `xdata[0x0F5C]`=空间选择（1=xdata）、
  `0x0F5D:0x0F5E`=指针、`0x0F5F:0x0F60`=剩余字节数；单字节出口 `0xA3D3` / `0xAEF7`（写 `SBUF`），
  每次出口把指针 +1、计数 −1。

## 帧格式

- 主控 → 模块：`50 <cmd> <len> <payload...> <sum>`，组帧 `0x9BF9`，`<sum>` = `0xB607`（8 位累加和，
  覆盖 cmd+len+payload）。payload 源用「空间选择 + 16 位指针」描述（`0x2BC0`/`0x2BD9` 读）。
- 大块帧：`50 81 <size_hi> <size_lo>` + payload，组帧 `0xB204`（唯一调用点 `0x063A`）。
  帧头写在 `xdata 0x08F1..0x08F4`，payload 缓冲 `xdata 0x08F5..0x0AFC`（恰好 520 B），
  size 常量 = `0x0208` = 520。
- 模块 → 主控：首字节 `0x5A`（`0xAF26` 处判 `xdata[0x1130]==0x5A`）；`0x6761` 与 `0xA2E9` 也会把
  `0x5A` 开头的帧组成到 `0x11C1`（例：`5A D1 05 <x>` + 和校验，共 5 字节），说明这条链上
  两个方向都用同一套 `0x50`/`0x5A` 前缀区分。

## 命令全集（`0x9BF9` 全部 12 个调用点）

| cmd | len | 发送点 | 备注 |
|---|---|---|---|
| `0x0A` | 14 | `0x009B` | payload 最大的一帧 |
| `0x1B` | 1 | `0x00E1` | |
| `0x08` | 1 | `0x011E` | |
| `0x02` | 1 | `0x01DE` | payload 先 `ORL A,#0x80` |
| `0x03` | 0 | `0x021A` | |
| `0x04` | 4 | `0x02A2` | |
| `0x13` | 1 | `0x0300` | payload 先 `ORL A,#0x08` |
| `0x15` | 2 | `0x035D`、`0x05F1` | |
| `0x17` | 1 | `0x044F` | payload 先 `ORL A,#0x80` |
| `0x18` | 1 | `0x0691` | |
| `0x1A` | 1 | `0x06D2` | |
| `0x81` | **520** | `0xB204`（唯一调用 `0x063A`） | 大块数据帧 |

这些调用点集中在 `0x008B..0x06EE`（模块事件/状态处理区），由主控状态变化（连接态、模式、灯效、电量、
HID 报告等）驱动 ⇒ **主控对模块说的是"状态"，不是"内容"**。唯一的内容通道就是 `0x81` 大块帧。

## 主机 → 模块 内容管道（关键结论）

1. 主机对 IF1 写 `SetFeature(feature report 9)`（`wLength=519`）⇒ 固件在 `0x8363` 判 SETUP：
   `wValue 低=9`（report ID）、`wValue 高=3`（Feature）、`wIndex 低=1`（IF1）⇒ 置 EP0 状态 `0x1150=0x0B`、
   偏移 `xdata[0x0B08:0x0B09]=0`、剩余长度 `xdata[0x0B0A:0x0B0B]` = wLength。
2. 之后每个 **8 字节 EP0 OUT 包**（EP0 `mps=8`，见设备描述符）从 `xdata 0x1100` 起，
   由 `0x6CA2` → `0xA650` 追加到 `xdata 0x08F5 + 偏移`，同时剩余 −8、偏移 +8；
   缓冲写满（偏移 ≥ `0x208`）或剩余归零时收尾（`xdata[0x0F8A]=0`、状态清零）。
3. 收尾后由模块链路状态机（`xdata[0x0D85]++` + `SETB T2CON.2` 启动 timer 2）把整块以
   `50 81 02 08` + 520 B 发给模块。
   ⇒ **一次 519 B 的 feature 9 写入 ≈ 一个 520 B 的模块数据块，一一对应，且不需要改任何固件。**
   待实测确认的细节：EP0 缓冲第 0 字节是 report ID，所以 519 B 报告 ↔ 520 B 块（含 ID 字节）；
   偏移/尾巴分包的对齐（`0x6CA2` 每次固定追加 8 B，尾包取剩余长度）只从静态解码得出。

## 模块固件：读不到、也写不了

- 8051 侧无任何「读模块 flash 回传」的路径；`0xF000` 附近那颗 Sinowealth ISP bootloader **只走 USB**
  （反汇编中 `SBUF`/`SCON` 引用为 0）⇒ ISP 命令无法经 UART 转给模块。
- 模块命令集里**没有**擦除/写入/进 bootloader 之类的命令 ⇒ 模块 flash 只能硬件接线（拆机 + 接 ISP/SWD 焊盘）才能碰。
- 模块芯片型号依旧未知（用户无法拆机）。目前最接近的样本是它的 RF 伙伴：接收器 `258a:0150` 的 64 KiB
  dump（`firmware/backups/dongle_258a-0150_full_20261019.bin`，MD5 `38EFE2AA9E91B9A9B8A82C69E3C52DDB`，
  同族 Sinowealth 8051、含 UTF-16LE `Gaming KB`），但那只是 RF 对端，不等于模块 SoC。

## 未解 / 待验证

- 520 B 块在模块端被当成什么（屏幕图像？灯效参数？字库？）—— 需要一次受控写入探测。
- 模块事件/状态处理区里各命令的语义（`0x0A` 14 B 那帧尤其可疑），以及 `0x0ED7`/`0x0ED8` 标志字的驱动者。
- `0x6B67` 那段的性质：它把 **flash 表 `0x0377`**（12 B/行 × 15 行）展开进 xdata（经 `0x0EBE/0x0EC0-0x0EC2`），
  末尾写 `xdata[0x0E0B]=0x5A` ⇒ 更像「按表生成一帧数据 + 置就绪标志」，不是早先记的「15 字节收包组装器」。


## Timeline

- time: 2026-10-19T23:09:10
  kind: decision
  summary: "Created this page: 模块链路：主控 ↔ 屏幕/无线 SoC"
  source: "build/fw_full.lst + README 2026-10-19"
  affects: [module-link]

- time: 2026-10-19T23:09:10
  kind: decision
  summary: "主控↔模块 UART 链路全貌：0x50/0x5A 帧、命令全集、50 81 大块帧、以及 feature 9 → 520B → 模块 的内容管道；模块固件不可读不可写"
  source: "build/fw_full.lst + analysis/lst.py"
  affects: [module-link]

- time: 2026-10-19T23:09:10
  kind: evidence
  summary: "解出模块链路发送引擎(流描述符 0x0F5C-0x0F60 + SBUF 中断发包, UART 初始化 0xB15A)、0x9BF9 全部 12 个命令调用点(cmd 02/03/04/08/0A/13/15/17/18/1A/1B)、大块帧 50 81 0208(0xB204, 缓冲 0x08F5..0x0AFC=520B)"
  source: build/fw_full.lst
  affects: [module-link, host-vendor-channel, screen-customization]

- time: 2026-10-19T23:09:10
  kind: evidence
  summary: "主机->模块内容管道闭环: SetFeature(feature 9,IF1,wLength=519) 在 0x8363 判 SETUP(wValue低=9/wValue高=3/wIndex低=1) -> 偏移/剩余清零 -> 每个 8 字节 EP0 OUT 包(源 xdata 0x1100) 经 0x6CA2/0xA650 追加进 0x08F5+偏移 -> 收尾后由 timer2 状态机以 50 81 02 08 + 520B 发给模块; 即 519B feature 写入 == 一个 520B 模块数据块"
  source: "build/fw_full.lst + 报告描述符 0x4569"
  affects: [module-link, host-vendor-channel, screen-customization]
