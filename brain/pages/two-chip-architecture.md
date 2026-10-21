---
id: two-chip-architecture
title: "两芯片架构 (主控 ↔ 模块 SoC)"
category: reference
status: active
tags: [architecture, module, sh68f90]
created: "2026-10-21T03:28:51"
updated: "2026-10-21T05:56:30"
---

<!-- compiled_truth -->
## 结论

YD-Y65S = **主控 SH68F90A（8051）+ 模块 SoC（ODM 屏/无线模组）**，分工干净：

* **主控 = 感知与转发**：扫键、USB HID、存配置、算灯效参数、当主机↔模块的桥。
* **模块 = 表达与连接**：TFT 渲染、每键 RGB、2.4G/BT 与电池、自己的 RTC。
* **音量旋钮在主控上**（2026-10-21 更正）：主控用 P4.2/P0.7 两个 GPIO 读机械编码器的正交信号，
  自己解码方向，再把结果同时送两路。

主控是主机与模块之间**唯一的桥**：主机侧一切（厂商 app、ODM web 驱动、我们的工具）都从主控的
USB 厂商通道（feature 9，519 B）进，再由主控转发。

完整取证报告：`docs/two-chip-architecture.md`（含地址速查表）。

## 为什么是这个分工（第一性依据）

主控外设全集（`analysis/fwdis.py sfr` 枚举全片 SFR/XSFR 访问）只有：USB、UART、
4 bank PWM、GPIO、定时器、flash、模块桥（XPAGE/IB_*）。
**没有**显示控制器、**没有** SPI/I²C、**没有** ADC/编码器、**没有**射频前端。
⇒ 主控不可能自己画屏、不可能做射频。
（「没有编码器外设」只说明要用 GPIO 软件解码，**不能**据此推断旋钮挂在模块 —— 2026-10-21 已推翻。）

## 主控职责（确认）

按键矩阵（15 列 × 5 行 = 90 键，`0x35E8`/`0x0A90`/键位表 `0xBC00`）· USB 键盘（IF0, EP 0x81 8 B）·
USB 厂商通道（IF1, EP 0x82 16 B + feature 9 = 519 B）· 配置存储（在用 profile `0xA400`，出厂 `0x9983`，
各 128 B，尾部 `5A A5` 标记）· 灯效**参数**计算（profile `0x0A` → 码表 `0x0C00`/`0x0C20`/`0x0C80`/`0x0CA0`）
· UART 桥（`0xB15A` 初始化 / `0x9BF9` 组帧 / `0xBADB` 字节流 / `0xB204` 大块帧）·
ISP bootloader（`0xB0ED` 跳转桩，`0x82EA` 分发）· 无线档位记账（`xdata[0x0F29]`：
1=USB，`0x25/0x35/0x45/0x55`=2.4G/BT1/BT2/BT3，切换 `0x116E/0x1265/0x127B`）· 少量状态灯 PWM。

## 模块职责（确认 / 推断分列）

* [确认] TFT 渲染 240×135 RGB565 大端；内容由主机经主控推入（记录 `0x0B/0x0C/0x0D` → cmd `0x81`）。
* [确认] 自己的 RTC（屏幕时间由 ODM `setTftDateTime` 设，会漂 ~1.5%）。
* [确认] 应答端是 ODM 兼容（首字节 `0x55`/`0xAA`）；还会发 `0x5A` 魔数私有短报文（≤14 B）。
* [推断-强] 每键 RGB 由模块执行——主控 PWM 只有 24 通道 × 2 duty，不够 68 键 × RGB；
  且实测"发记录 `0x04`（=推 profile 给模块）会让键盘 RGB 灭掉"。
* [推断-强] 2.4G/BT 射频与电池在模块（ODM 设备信息带 `batteryLevel`，由键盘转发给主机）。
* [确认] 音量旋钮在**主控**上：`0x2812` 采 `P4.2`/`P0.7`（一对正交相，两脚都开上拉），
  `0x283E` 用 6 位历史寄存器解码方向（`0x284C` `ADD A,#0xF9` 判 7、`0x2853` `ADD A,#0xFC` 判 11
  = 两个相反方向），方向写 `xdata[0x0CA0]=9` + `xdata[0x0CA1]=1|2`；派发表 `0x04A9` 索引 9 → `0x0594`。

## 数据流一句话版

主控**永远**是搬运工 + 记账员，模块**永远**是执行者。
按键/灯效参数/屏幕内容/音量/时钟/无线档位六条流全部过主控；
其中"音量"与"时钟"的内容由主机给；"旋钮"由**主控**解码后分两路发：HID consumer 用量
`0xE9/0x0EA` 给主机（系统音量），状态字节 `0x81/0x82` 经 cmd `0x15` 给模块（屏幕音量条）。

## 主控 → 模块命令语义（新增）

* 状态/事件类（调用点集中在 `0x008B..0x06EE`，载荷来自 `xdata 0x0EE4`）：
  `0x0A`(14 B 完整状态) `0x04`(4 B) `0x15`(2 B = **灯效模式/序号**) `0x02` `0x08` `0x13` `0x17`(`|0x80`,
  与事件码 `0x22` 联动) `0x18`(来自 `0x0F6A`) `0x1A`(来自 `0x0C2C`) `0x1B` `0x03`(0 B)。
* 数据类：模块 cmd = **ODM cmd + 0x1E**。`0x52`=ODM `0x34`(profile 128 B) `0x54`=`0x36` `0x56`=`0x38`
  (TFT 代码表 126 B) `0x5E/0x5F`=`0x40/0x41` `0x62/0x63`=`0x44/0x45` `0x66/0x67` `0x6A/0x6B`
  `0x6E..0x75`=`0x50..0x57` `0x81`=大块帧 520 B。
* 模块 → 主控私有短报文（`0xB4FC`）：类型 `0x00` → 载荷写 `xdata[0x0F18]`（**事件码**：`0x12`=链路档位变化、
  `0x22`=另一类事件）；类型 `0x02` → 写 `xdata[0x1155]`；其它类型 → 置 `xdata[0x0F16] |= 0x20`。


## Timeline

- time: 2026-10-21T03:28:51
  kind: decision
  summary: "Created this page: 两芯片架构 (主控 ↔ 模块 SoC)"
  source: "2026-10-21 反汇编 + 描述符 + ODM 驱动"
  affects: [two-chip-architecture]

- time: 2026-10-21T03:28:51
  kind: decision
  summary: "YD-Y65S 双芯分工与数据流的取证结论（主控=搬运工+记账员，模块=执行者），详见 docs/two-chip-architecture.md"
  source: "2026-10-21 分析报告"
  affects: [two-chip-architecture]

- time: 2026-10-21T05:56:23
  kind: decision
  summary: "更正：音量旋钮在主控上（8051 用 P4.2/P0.7 正交解码），模块不负责旋钮；旋钮事件同时产生 HID consumer 用量（给主机）与 cmd 0x15 状态字节（给屏幕）"
  source: "2026-10-21 反汇编复核 0x2812/0x283E/0x0594/0x04A9"
  affects: [two-chip-architecture]

- time: 2026-10-21T05:56:30
  kind: reversal
  summary: "推翻原结论「音量旋钮挂在模块（推断-强）」：旋钮其实在主控 SH68F90A 上。0x2812 采样 P4.2/P0.7 作为一对正交相（两脚均开上拉，均不在 15×5 键矩阵内），0x283E 用 6 位历史寄存器（(hist<<2|新样)）解码，0x284C ADD A,#0xF9 判 7、0x2853 ADD A,#0xFC 判 11，即两个相反的旋转方向；方向写 xdata[0x0CA0]=9 与 [0x0CA1]=1|2，0x04A9 派发表索引 9 → 0x0594。原推理错在把「没有编码器外设」当成「读不了旋钮」——机械编码器只需两个 GPIO 软件解码。原 compiled_truth 的相关句子（模块负责音量旋钮、主控不可能直接读旋钮、数据流里旋钮由模块给）已同步更正。"
  source: "2026-10-21 反汇编复核 0x2812/0x2833/0x283E/0x284C/0x2853/0x2874/0x29AE/0x0594/0x04A9"
  affects: [two-chip-architecture, firmware-layout, screen-customization, no-write-policy]
