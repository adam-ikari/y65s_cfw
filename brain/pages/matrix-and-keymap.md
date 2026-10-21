---
id: matrix-and-keymap
title: "矩阵扫描与键位表 (YD-Y65S)"
category: reference
status: active
tags: [matrix, keymap, sh68f90, yd-y65s]
created: "2026-10-19T17:49:43"
updated: "2026-10-21T06:56:25"
---

<!-- compiled_truth -->
## 矩阵几何（已确认；三条独立证据）

列（15，扫描顺序 = 键位表列序）与行（5）**直接从厂商代码读出**，不是推断：

| 列序号 | 引脚 | 列序号 | 引脚 |
|---|---|---|---|
| 0-7 | `P6.0`…`P6.7` | 8-11 | `P5.0`, `P5.1`, `P5.2`, `P5.7` |
| 12-14 | `P4.0`, `P7.7`, `P4.5` | | |

行：`P7.1`, `P7.2`, `P7.3`, `P5.3`, `P5.4` = 物理行 0..4。

证据：

1. **扫描派发** `0x35E8`（10 项 `LJMP` 跳转表；索引 ≥ 10 直接跳过，`0x35D9`）。
   每个处理块按固定次序 `CLR Px.y` 驱动一列、`LCALL 0xB113`、结果存入 `RAM_2C + n`。
   这个次序就是列序，且与 `RAM_2C..RAM_3A` 一一对应：
   `P6.0→RAM_2C` `P6.1→RAM_2D` `P6.2→RAM_2E` `P6.3→RAM_2F`
   `P6.4→RAM_30` `P6.5→RAM_31` `P6.6→RAM_32` `P6.7→RAM_33`
   `P5.0→RAM_34` `P5.1→RAM_35` `P5.2→RAM_36` `P5.7→RAM_37`
   `P4.0→RAM_38` `P7.7→RAM_39` `P4.5→RAM_3A`。
   列 11/12 由压缩入口 `0xB108`（`CLR P5.7`）/`0xB10C` 承担，块尾 `SETB P5.7` 释放。
   索引 4..9 是同一 15 列的第二遍，结果写入 `RAM_41..RAM_4F`（上一状态）——`0x3606`
   首行即 `RAM_2C ^ RAM_41`（当前 ^ 上次），可交叉验证。
2. **行读取** `0xB130`：`MOV A,#0xFF; ACC.1..5 ← P7.1,P7.2,P7.3,P5.3,P5.4; CPL A`，
   因此 `R7` 的 bit0 恒为 0、bit(1+k) = 物理行 k。**这就是每列 slot0 空置的由来**。
3. **扫描序表** `0x0A90`（90 字节，`MOVC`，扫描序号 → 键码）：第 n 项 = `col*8 + slot`，
   `slot = row + 1`，未用槽为 `0xFF`（列 3/4/6/7 没有 slot5，即左下角少键）。
   编码范围 `0x00..0x75` 恰好覆盖 15×5，与上面两条完全一致。

端口方向：`P6CR=0xFF`、`P5CR=0x87`、`P7CR=0xF0`、`P4CR=0xB1`（`0x94A3-0x9535`）。

结论：`MATRIX_ROWS 5`、`MATRIX_COLS 15`；`analysis/keymap.py` 的 `COL_PINS/ROW_PINS`、
`src/keyboards/yd-y65s/kbdef.h` 与上述三处逐项一致。

## 键位表（已确认）

`0xBC00-0xCC00` 共 4 层 × `0x200` 字节，每层 90 条 4 字节记录，**列优先**，每列 slot0 空置
（对应不存在的行线），slot1..5 = 物理行 0..4。每层在 +`0x400` 处有一份**逐字节相同**的副本
（同一 2 KiB ISP 页内保留两拷）：

| 层 | 地址 | 副本 | 内容 |
|---|---|---|---|
| 0 | `0xBC00` | `0xC000` | mac 基础层 |
| 1 | `0xBE00` | `0xC200` | win 基础层 |
| 2 | `0xC400` | `0xC800` | mac Fn 层 |
| 3 | `0xC600` | `0xCA00` | win Fn 层 |

记录格式 `record = [class, mod, hi, usage]`（即运行时 `xdata 0x0B91..0x0B94` 的 4 字节）。

> **重要**：键位表还有两张**全零**表在 `0xCC00/0xCE00`（选择子 2）与 `0xD400/0xD600`
> （选择子 3）。它们不是"未使用"，而是运行时可被写入的槽位（见"消费链"与 `0x2530`）。

## 键位表消费链（已确认）

### 读取器 `0x748F`

输入全部经 XDATA 传递：

| 变量 | 含义 |
|---|---|
| `xdata[0x0EC2]` | 键序号 `idx`（0..89） |
| `xdata[0x0F25]` | 模式 `mode`：0 = Mac，1 = Win |
| `xdata[0x0EC8]` | 选择子 `S`（0..3） |
| `xdata[0x0EC4..0x0EC6]` | 目标 4 字节 XDATA 指针（`R3:R2:R1`，即 memtype/xaddr） |
| `xdata[0x0EC7]` | 同 `idx`（写入时用） |

地址 = `base(S) + 0x200*mode + 4*idx`，其中 `base`：`S=0→0xBC`、`1→0xC4`、`2→0xCC`、`3→0xD4`。
读 4 个 code 字节进 `R4-R7`，再通过目标指针写进 XDATA。
`S=1` 与 `S=2` 分支带**回退**：若读出的 4 字节全零，则改用 `S=0`（基础层）重读；
`S>=4` 直接返回、不写。

标准调用点用 `R3:R2:R1 = 0x01:0x0B:0x91`，因此记录副本固定落在 **`xdata 0x0B91..0x0B94`**。

### 两个 class 派发器

派发不是 `CJNE A,#07`，而是 `DEC A` 链：

| 进入点 | 用途 | 先做的准备 |
|---|---|---|
| `0x27B4` | 主派发（按键事件） | `0x2773` 先读 `xdata[0x0B0F + 21*row + col]` 作为 `S` 写进 `xdata[0x0EC8]` |
| `0x25D5` | 副派发（键位改写/宏录制路径 `0x2530`） | 强制 `S=3`，并把 `21*row+col` 格的 `S` 写成 3 |

`xdata[0x0B0F + 21*row + col]`（21 = 每列槽数）是**逐键选择子数组**：主派发读它，
副派发写它。这就是 Fn 层"逐键生效"的机制所在（不是全局开关）。

| class | 主派发 `0x27B4` | 副派发 `0x25D5` |
|---|---|---|
| `0x00` | `0x64AA`（普通键：mod + usage；读 `xdata[0x0C28]`） | `0x5108` |
| `0x01` | `0x27D9`：`RAM_0x78=0`，`SETB BITS_0C` | `0x2605`：`RAM_0x78 = byte1`（`03→04`、`04→08`、`05→10`），`SETB BITS_0C` |
| `0x02` | `0x27E0`：`RAM_0x57=RAM_0x58=0`，`SETB BITS_0B` | `0x2638`：`RAM_0x57=byte3`、`RAM_0x58=byte2`，`SETB BITS_0B` |
| `0x03` | `0x27E9`：仅当 `xdata[0x0B97]==4` → `xdata[0x0B96]=0` | `0x264A` |
| `0x07` | `0x9538` | `0x6A07` |
| `0x08` | `0xB90D` | `0x55CF` |
| `0x0D` | `0x2808`：`xdata[0x0BAB]=0`，`CLR BITS_32/37` | `0x2741`：`xdata[0x0BAB] = (byte1==0) ? 1 : 2` |
| 其他 | 返回 | 返回 |

### class `0x07` 语义（厂商组合键 / 模式动作）

字段在 **`byte3` = 子码**。主派发 `0x9538`：

| 子码 | 主派发动作 |
|---|---|
| `0x01`, `0x05`…`0x08` | → `0x9580`：`xdata[0x0F18]=0x12`、`xdata[0x0BB0]=2`、`xdata[0x0F16] |= 0x01`；并给运行时记录 `0x0ED7` 打标（byte3 `|= 2`、byte2 `|= 0x80`），`SETB BITS_31` |
| `0x0A` | → `0x955A`：若长按计数 `xdata[0x0C29] >= 0xC8` 则 `xdata[0x0F17] |= 0x02`；计数清零 |
| `0x0B`, `0x0C` | → `0x9575`：`CLR BITS_3E`；`xdata[0x0F34]=0` |
| `0x0D` | → `0x9572`：`CLR BITS_3C`（**这是 Fn 键**：基础层 `07 00 00 0D`） |
| `0x0F`, `0x12` | → `0x957D`：`CLR BITS_3A` |

副派发 `0x6A07` 才是**真·跳转表**：SDCC switch helper `0x2D08` 弹出返回地址做表基址，
表在 `0x6A2C`，3 字节条目 `[addr_hi, addr_lo, case]`（case 比对条目第 3 字节），
末项 `00 00 6B`。解析结果：

| 子码 | 目标 | 动作 |
|---|---|---|
| `0x01` | `0x6A4B` | `xdata[0x0BAC]` 在 `0x00`/`0xFF` 间翻转；`SETB BITS_17` |
| `0x05` | `0x6AA5` | 需 `xdata[0x0F29] ∈ {0x35,0x45,0x55}`；`xdata[0x0F7F]=1`；`xdata[0x0B8E]=[0x0F29]`；`xdata[0x0F29]=0x35`；`SETB BITS_35` |
| `0x06` | `0x6AD8` | 同上，`xdata[0x0F7F]=2`、`xdata[0x0F29]=0x45` |
| `0x07` | `0x6B08` | 同上，`xdata[0x0F7F]=3`、`xdata[0x0F29]=0x55` |
| `0x08` | `0x6B38` | 需 `xdata[0x0F29]==0x25`；`xdata[0x0F29]=0x25` |
| `0x0A` | `0x6A98` | 若 `xdata[0x0F29]==1` 则直接清 `xdata[0x0C29]`，否则 `SETB BITS_37`；随后清 `xdata[0x0C29]` |
| `0x0D` | `0x6A5E` | `SETB BITS_3C`（Fn 按下侧） |
| `0x20` | `0x6A61` | 仅 Win（`xdata[0x0F25]!=0`）时 `xdata[0x0B8F]=0` |
| `0x21` | `0x6A70` | 仅 Mac（`xdata[0x0F25]!=1`）时 `xdata[0x0B8F]=1`；并把运行时记录 byte3 `|= 2` 回写 |
| 其他 | `0x0000` | 无 |

`xdata[0x0F29]` 是厂商"组合键状态寄存器"（值 `0x25`/`0x35`/`0x45`/`0x55`），
`xdata[0x0B8E]` 保存旧值，`xdata[0x0F7F]` 是 `1..3` 的模式号。
`xdata[0x0F18]` 是按键状态机（`0x11`=Fn 单键、`0x12`=组合待续、`0x22`=组合完成），
`xdata[0x0BB0]` 是 `1`（单键）/`2`（组合）模式；`xdata[0x0F16`]`/`[0x0F17`]` 是动作请求位域。

### class `0x08` 语义（LED / 背光控制）

字段在 **`byte1` = 动作号**，`byte2` = 参数（`byte3` 仅 `0x00` 分支用到）。
副派发 `0x55CF` 是真·跳转表（表在 `0x55F4`，10 项 3 字节 `LJMP`，索引 = `byte1`；
另有 `0xFF` 特判）。前置门：`xdata[0x0F2D] != 0` 直接返回；各分支还要求
`xdata[0x0C28] ∉ {0x00?, 0xFF, 0x69}` 且 `RAM_0x22`（BITS_10..17）为 0（一次性闩锁）。

| byte1 | 键 | 目标 | 动作 |
|---|---|---|---|
| `0x00` | Fn+Del | `0x5612` | `SETB BITS_10`；`xdata[0x0BA6] = (byte3 != 0) ? 4 : byte2` |
| `0x01` | — | — | 无 |
| `0x02` | Fn+PgUp | `0x567C` | `SETB BITS_13`；`xdata[0x0B8D] = byte2` |
| `0x03` | Fn+Up / Fn+Down | `0x56A5` | `byte2==1` → `SETB BITS_11`；否则 `SETB BITS_12` |
| `0x04` | Fn+Right / Fn+Left | `0x56D0` | `byte2==1` → `SETB BITS_15`；否则 `SETB BITS_16` |
| `0x05` | — | `0x56F5` | 仅 `xdata[0x0F65]==0x13`；`xdata[0x0C28]` 0→`0x69`、`0xFF`→`0x96` |
| `0x06`,`0x08` | — | — | 无 |
| `0x07` | Fn+PgDn | `0x5719` | 仅 `xdata[0x0F65]==0x13`；0→`0x69` 且 `LCALL 0xB580` + `SETB BITS_08/09/0B`；`0xFF`→`0x96` |
| `0x09` | — | `0x564A` | `xdata[0x0F65] = byte2`（**直接设灯效**）；`xdata[0x0BAD]=0`；`xdata[0x0BAE]=0xAA`；`SETB BITS_51` |
| `0xFF` | Fn+Space | `0x5747` | `SETB BITS_32`；`xdata[0x0C29]=0` |

主派发 `0xB90D` 只处理 `byte1 == 0xFF`：`CLR BITS_32`；若 `xdata[0x0C29] >= 0x96`
则 `xdata[0x0F17] |= 0x01`；`xdata[0x0C29]=0`。其余 8 个 LED 记录在主派发里是 **no-op**，
真正的语义全在副派发 `0x55CF`。

**结论**：`class 0x08` 不是"未知的灯效 id"，而是**灯效/亮度控制指令**，
`byte1` = 动作（Del 预设、PgUp 速度、Up/Down 与 Left/Right 是同轴 ±、PgDn 复位、
Space 开关），`byte2` = 参数/方向。

### LED 子系统变量（已确认到变量与表一级）

* `xdata[0x0F65]` = **灯效索引**（`0..0x13`），由 `0x95EE` 的 20 项 3 字节 `LJMP` 表派发。
* `xdata[0x0CA1]` = **灯效预设号**（`0..0x0F`），经 code 表 **`0xD119`**（16 字节
  `01 02 03 04 05 07 08 09 0A 0B 0C 0D 0F 10 11 13`）映射到 `xdata[0x0F65]`。
* `xdata[0x0CA0]` = **LED 状态机状态**（`0..0x0A`），由 `0x2899` 的 11 项 3 字节表派发；
  该状态机 `0x2812` 由 **4 分频的定时中断**（`0x62E0`，`xdata[0x0F32]` 计数到 4）调用，
  不是按键路径。
* 动作请求位：`RAM_0x21` 的 `BITS_08..BITS_0F`、`RAM_0x22` 的 `BITS_10..BITS_17`。
* `xdata[0x0C28]` = 灯效开/关/模式闩锁，取值 `0x00`/`0x69`/`0x96`/`0xFF`；`0x2812` 在
  `xdata[0x0C28] == 0xFF` 时跳过刷新。
* `xdata[0x0C29]` = 长按计数器（阈值 `0x96`=150、`0xC8`=200，配合 [0x0F17] 位）。

## LED 驱动（部分确认）

LED 由**芯片内置 PWM bank 直驱**，没有外置驱动 IC：

* `0x48BE-0x48FD` 写 `PWM00CON..PWM30CON`（4 个 bank × 6 通道 = 24 路；`PWM4x` 另有配置）；
* `0x46F9-0x48AB` 把 `PWMxxDUTY1L/H` / `DUTY2L/H` 设为 `0xB0`、`PERD=0xB0`（**初值均匀**）；
* 效果渲染在 `0xD11` 起：从 code `0x9983` 拷 128 字节进 XDATA `0x08F5`，随后以
  `LCALL 0xB970`（`R7` = 命令）与 `LCALL 0xBAF6`（`R3` = 命令、`R5` = 值）驱动，
  并维护 XDATA `0x0EB2/0x0EB3` 的 16 位计数器与 `0x0F8A/0x0F8B`（`05`/`0A`）；
* `DRVCON` 解锁码 `0x05/0x45/0x85/0xC5` 出现在 `0xA270-0xA284`。

## 复现

```
uv run analysis/keymap.py dump  firmware/YD-Y65S_firmware.bin --layer 0
uv run analysis/keymap.py list  firmware/YD-Y65S_firmware.bin --layer 2
uv run analysis/keymap.py check firmware/YD-Y65S_firmware.bin
# 全量线性反汇编（reachable-only 的 build/fw_code.lst 有缺洞，必须用全量）
uv run analysis/fwdis.py dis firmware/YD-Y65S_firmware.bin --start 0 --len 0xF000
```

## 静态分析陷阱（重要）

`analysis/fwdis.py` 的"可达性"输出（`build/fw_code.lst`）**存在大片 gap**
（例如 `0x27B4..0x2AED`、`0x9355..0x9A02`），原因是个别 `LCALL` 返回后未继续跟踪。
早期的"固件里不存在 `#07`/`#08` 比较"结论就是这些 gap 造成的假象。
**任何"全固件范围内找不到 X"的结论都必须用 `--start 0 --len 0xF000` 的全量线性反汇编复核。**

## 本机「，」键（已定性为硬件问题；固件侧排查终止）

2026-10-21 结论。用户判断为硬件问题并决定放弃调查，固件侧到此为止。

* **固件侧已证明是正常的**：base 层 `(col9 × row3 = P5.1 × P5.3)` 的记录是
  `00 00 00 36`（class 0x00 普通键，usage 0x36 = ISO 逗号）—— **是打开的**；
  同一列下面一格 `(col9 × row4 = P5.1 × P5.4)` 才是 `0D 00 00 00`（class 0x0D = 禁用）。
* **固件确实扫到了这颗键**：按下时 RGB 有反应，但主机收不到任何字符；加按 Fn 时
  主机收到 `左Ctrl + 左Alt + 右Alt`。而 row4 (`P5.4`) 一行里恰好只有四个纯修饰键
  `(col0 LCtrl / col1 LGui / col2 LAlt / col8 RAlt)`；本机 `profile[0x36]=0` →
  `xdata[0x0F25]=0` → base 层取 `0xBC00`（mac 基础层，修饰键组合正是 Ctrl/Gui/Alt/Alt），
  与现象逐项吻合。
* ⇒ **这颗键被解析到了 row4，而不是它应该在的 row3** —— 属硬件（轴体/走线）层面的错位，
  不是固件改坏了。刷机也无关：刷机前后代码区与键位表逐字节相同，8051 可见的配置字节
  全部还原后现象不变。
* 诊断探针镜像（**未写入设备**）：`build/YD-Y65S_comma_probe.bin`
  （md5 `42bac627d23241d13594ede5c96b4a29`，相对当时已刷镜像只改 23 字节、全在键位表区、
  代码区 0 改动）：把 base 层 9 个空/禁用槽填成互不相同的字母 (q/w/e/r/t/y/u/i)，
  `(col9 × row4)` 填「，」。若日后要继续查：刷进去按「，」，出来哪个字母就是它被解析到的位置。


## 尚未证实

* **每列 PWM 通道 ↔ 物理列的对应关系未证实**：`PWMxxDUTY` 初值全为 `0xB0`（均匀），
  效果引擎索引的是抽象缓冲（`0x9983` → XDATA `0x08F5`，128 B），静态无法反推走线。
  需要原理图或台架测量。
* `xdata[0x0BA6]`（Fn+Del 装入的预设号）、`xdata[0x0B8D]`（Fn+PgUp 装入值）的最终消费者未定位。
* `class 0x01`（`RAM_0x78`）与 `class 0x02`（`RAM_0x57`/`RAM_0x58`）的目标语义未证实
  （疑似亮度/颜色通道，因为它们与 LED 状态机共享 `BITS_0B`/`BITS_0C` 标志）。
* `xdata[0x0B8F]`（class `0x07` 子码 `0x20`/`0x21` 写入）的含义未证实，疑似 Mac/Win 或
  协议模式切换标志。
* `0x2530`（键位改写/宏录制）与 `xdata[0x0BAA]`、`xdata[0x0BB1+R3]` 的完整语义未证实。
* "从左到右"的物理朝向未做按键核对；但**不影响正确性**：厂商与移植版使用同一
  `列序→引脚` 映射和同一按序号索引的键位表，同一物理按键在两者中解析为同一键位。


## Timeline

- time: 2026-10-19T17:49:43
  kind: decision
  summary: "Created this page: 矩阵扫描与键位表 (YD-Y65S)"
  source: README.md / analysis/keymap.py
  affects: [matrix-and-keymap]

- time: 2026-10-19T17:49:59
  kind: decision
  summary: "矩阵引脚(15列/5行)、4层键位表格式与地址、内置PWM bank LED驱动均已确认"
  source: "analysis/keymap.py + fwdis.py + SMK nuphy-air60 交叉验证"
  affects: [matrix-and-keymap]

- time: 2026-10-19T17:54:30
  kind: decision
  summary: "补充运行时键处理事实：0x0ED7 记录缓冲、0x2CF0 写回原语、0x0CA0 状态机；并记录 0xBC00 未被字面地址 MOVC 读取的开放问题"
  source: "fwdis.py dis/find 静态分析"
  affects: [matrix-and-keymap]

- time: 2026-10-19T19:08:25
  kind: evidence
  summary: "SMK 板级目录按本页的 COL_PINS/ROW_PINS 实现；P6CR=0xFF、P5CR=0x87 与列掩码完全一致，P7CR/P4CR 多出的 P7.4-P7.6、P4.4/P4.7 不当作列（疑似 RGB），留待 LED 逆向"
  source: "src/keyboards/yd-y65s/user_matrix.c + user_init.c"
  affects: [matrix-and-keymap, smk-port]

- time: 2026-10-19T19:50:40
  kind: decision
  summary: "矩阵几何改为已确认：扫描派发 0x35E8 的引脚次序 + 行读取 0xB130 位打包 + 扫描序表 0x0A90(col*8+slot) 三处独立互证，与移植版 kbdef.h 逐项一致"
  source: "fwdis.py dis 0x3590-0x37E0 / 0xB108-0xB148 + 0x0A90 表"
  affects: [matrix-and-keymap]

- time: 2026-10-19T19:53:12
  kind: evidence
  summary: "枚举 key-map 类全集：class 0x07 共 7 个子码（只有 0x0D 是 Fn；0x01 在左下 Alt/Cmd、0x05-0x0A 在 Z/X/C/V/G），class 0x08 共 8 个 LED 动作（Space/Del/PgUp/PgDn/方向键，b2 的 01/02 成对同轴）；类 0x00/0x02/0x0D 亦已全量列出"
  source: "build/class_probe.py + build/gap_probe.py（临时探针）"
  affects: [matrix-and-keymap]

- time: 2026-10-19T20:47:24
  kind: decision
  summary: "确认键位表消费链与 class 0x07/0x08 语义"
  source: "fwdis 全量线性反汇编 + SDCC switch helper 0x2D08 解析"
  affects: [matrix-and-keymap]

- time: 2026-10-19T20:47:50
  kind: evidence
  summary: "找到键位表真正的消费链：读取器 0x748F（地址 = base(S)+0x200*mode+4*idx，S=0..3 → 0xBC/0xC4/0xCC/0xD4，S=1/2 全零时回退 S=0）→ 记录副本 xdata 0x0B91..0x0B94 → class 派发 0x27B4（主）与 0x25D5（副）；逐键选择子数组为 xdata 0x0B0F+21*row+col（主派发读、副派发写 3）"
  source: "fw_full.lst 全量线性反汇编 0x25xx/0x27xx/0x748F-0x75A0"
  affects: [matrix-and-keymap]

- time: 2026-10-19T20:47:51
  kind: evidence
  summary: "class 0x08 语义确认 = LED/背光控制指令（byte1=动作号，byte2=参数）：副派发 0x55CF 的真跳转表在 0x55F4（10 项），与键位表 8 条记录逐条对上（00=Fn+Del 预设, 02=Fn+PgUp, 03=Fn+Up/Down 同轴±, 04=Fn+Right/Left 同轴±, 07=Fn+PgDn 复位, FF=Fn+Space 开关, 09=直设 0x0F65）；主派发 0xB90D 只处理 byte1==0xFF"
  source: "fwdis dis 0x55CF-0x575B + 0x5612/0x564A/0x567C/0x56A5/0x56D0/0x56F5/0x5719/0x5747"
  affects: [matrix-and-keymap]

- time: 2026-10-19T20:47:51
  kind: evidence
  summary: "class 0x07 语义确认（byte3=子码）：副派发 0x6A07 的真跳转表在 0x6A2C，3 字节条目 [addr_hi,addr_lo,case]，由 SDCC switch helper 0x2D08 派发；0x0D=Fn（SETB BITS_3C）、0x01=翻转 xdata 0x0BAC、0x05/0x06/0x07 写 xdata 0x0F29/0x0F7F/0x0B8E、0x08=0x0F29、0x0A=长按/BITS_37、0x20/0x21=Mac/Win 标志 0x0B8F"
  source: "fw_full.lst 0x6A07-0x6B56 + 0x2D08-0x2D2C"
  affects: [matrix-and-keymap]

- time: 2026-10-19T20:47:51
  kind: evidence
  summary: "LED 子系统确认到变量/表一级：xdata 0x0F65=灯效索引（0x95EE 20 项表派发）、xdata 0x0CA1=预设号经 code 表 0xD119（01 02 03 04 05 07 08 09 0A 0B 0C 0D 0F 10 11 13）映射、xdata 0x0CA0=LED 状态机状态（0x2899 11 项表）、状态机 0x2812 由 4 分频定时中断 0x62E0 调用、xdata 0x0C28 为 00/69/96/FF 闩锁、xdata 0x0C29 为长按计数"
  source: fwdis dis 0x2812-0x2AE0 / 0x62E0 / 0x95EE / 0xD119
  affects: [matrix-and-keymap]

- time: 2026-10-19T20:47:51
  kind: reversal
  summary: "反转两条旧结论：① class 0x08 其余 7 条记录不是 no-op，而是 LED 控制指令（真语义在副派发 0x55CF，主派发 0xB90D 只看 0xFF）；② 早期"
  affects: [matrix-and-keymap]

- time: 2026-10-21T06:24:22
  kind: evidence
  summary: "2026-10-21 刷机事故排查结论：键盘 flash 的『键行为』与刷机前逐字节等价，刷机不是，键失灵的原因。依据三条：① 8051 对在用 profile(0xA400) 只读 14 个偏移(0x03/0x0A/0x16/0x18/0x1F/0x31/0x33/0x35/0x36/0x37/0x7E/0x7F)，整块 profile 与 0xA800-0xA95F 都不读；② 键位表在 flash 0xBC00(4 层)，「，」用 usage 0x36 位于 col9×row3(P5.1×P5.3)，记录 00 00 00 36 = 启用(不是 0x0D 禁用)；③ 刷机前后 0x0000-0xA448 代码区逐字节相同，唯一固件可见的配置字节 flash[0xA403](profile 偏移 0x03，经 0xD021 变成 xdata[0x0C2A]=值+2，是键记录表 0x04F5/0x0473(21B 一项)的索引)。刷机把该字节从 0x01 还原成出厂的 0x00(键表切回另一套)，已按 0x01 刷回仍然无效 ⇒ 该键在刷机前就已经是不灵的，或与固件无关(硬件/键帽/主机端)。同次刷机顺带验证旋钮仍然好用(主机音量 50%→48%)。"
  source: "2026-10-21 真机刷机前后 64KiB 逐字节比对 + build/fw_full.lst 复核 0xD021/0x748F/0x04F5"
  affects: [matrix-and-keymap, isp-protocol, no-write-policy]

- time: 2026-10-21T06:27:37
  kind: evidence
  summary: "2026-10-21 补正上一条：唯一还差的固件可见字节是 flash[0xA418]（profile 偏移 0x18），不是 0xA417（那个固件根本不读）。0xA418 经 0x78B2/0x7CF8 进入 xdata[0x0F2B]，0x1F83 处非零才走 0x1F8D 的分支并把该值经 0x2C18（24 位乘法器）参与表索引计算 ⇒ 数值不同会算出不同的表项。刷机前本机是 0x02，出厂 dump 是 0x0A。键位区 0xBC00-0xCBFF 刷机前后只差 5 字节：0xBDFE/0xBDFF 与 0xC5FE/0xC5FF 是 0x5AA5 标记（固件不读，落在层块尾部填充区），0xC4EC 是 layer2 col9 row4 的 0x0D↔0x00（两者都是空/禁用，无功能差别）。最终镜像 = 出厂代码区(0x0000-0xA3FF 与出厂 dump 逐字节相同) + 本机自己的配置区 + 补丁 no-volume-send(0x5557) + no-volume-ods(0x059C)，MD5 48cc703280ae668539cba81a30c1ae7e，读回校验一致。"
  source: "2026-10-21 真机三轮刷机 + 逐字节比对 + 0x2C18/0x1F83 复核"
  affects: [matrix-and-keymap, isp-protocol, custom-firmware-path]

- time: 2026-10-21T06:44:01
  kind: evidence
  summary: "2026-10-21 「，」键诊断（旋钮已确认修好：主机音量 50%→48%）：固件侧「，」是打开的 —— base 层 (col9 × row3 = P5.1×P5.3) 记录 00 00 00 36；同一列下一格 (col9 × row4 = P5.1×P5.4) 是 0D 00 00 00（禁用）。用户实测：单按「，」完全没反应但 RGB 会有反应（说明固件确实扫到了这颗键），「，」+Fn 会冒出 左Ctrl+左Alt+右Alt —— 而 row4 (P5.4) 恰好只有四个纯修饰键 (col0 LCtrl / col1 LGui / col2 LAlt / col8 RAlt)，且本机 profile[0x36]=0 → xdata[0x0F25]=0 → base 层取 0xBC00（mac-base，修饰键组合正是 Ctrl/Gui/Alt/Alt），与现象完全吻合 ⇒ 推测这颗键被解析到了 row4 而非 row3。已构建诊断探针镜像 build/YD-Y65S_comma_probe.bin（md5 42bac627d23241d13594ede5c96b4a29，相对当时已刷镜像只改 23 字节、全在键位表区）：把 base 层 9 个空/禁用槽各填一个不同字母 (q/w/e/r/t/y/u/i) 作探针，col9×row4 填「，」。按下去出现哪个字母 = 固件把这颗键解析成了哪个矩阵位置；出现「，」= 位置确认且直接可用。设备尚未写入该镜像（需用户明确授权）。"
  source: "2026-10-21 真机复测 + fw_full.lst 复核 0x27B4 类派发/0xB130 行读取/0x748F 键位读取器"
  affects: [matrix-and-keymap, no-write-policy]

- time: 2026-10-21T06:56:25
  kind: decision
  summary: "加入「，」键硬件问题结论；固件侧排查终止"
  source: "2026-10-21 真机复测 + 用户判断"
  affects: [matrix-and-keymap]
