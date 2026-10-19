---
id: matrix-and-keymap
title: "矩阵扫描与键位表 (YD-Y65S)"
category: reference
status: active
tags: [matrix, keymap, sh68f90, yd-y65s]
created: "2026-10-19T17:49:43"
updated: "2026-10-19T19:53:12"
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

### 记录格式

`record = [class, mod, hi, usage]`

| class | 含义 | 字段用法 |
|---|---|---|
| `0x00` | 键盘 | HID usage 在 `usage`，修饰位掩码在 `mod`；也可表示组合键，如 `00 10 00 52` = RCtrl+Up |
| `0x02` | consumer | 16 位 usage = `hi:usage`（`0x00EA` 音量减、`0x0192` 浏览器、`0x006F/0x0070` 亮度） |
| `0x07` | 厂商动作（**不止 Fn**） | 子码在 `usage`；全集见下 |
| `0x08` | LED/背光动作 | 子码在 `mod:hi:usage`；全集见下 |
| `0x0D` | 未分配 | 全零等效禁用 |

### class `0x07` 全集（已枚举，14 格）

| 子码 | 物理键 | 出现层 |
|---|---|---|
| `0x0D` | Fn（`c14r3`） | mac-base, win-base |
| `0x01` | Fn + 左下 Alt/Cmd（`c1r4`） | mac-fn, win-fn |
| `0x05` | Fn + Z | mac-fn, win-fn |
| `0x06` | Fn + X | mac-fn, win-fn |
| `0x07` | Fn + C | mac-fn, win-fn |
| `0x08` | Fn + V | mac-fn, win-fn |
| `0x0A` | Fn + G | mac-fn, win-fn |

**只有 `0x0D` 是 Fn（瞬时切层）**；其余 6 个是厂商私有动作（`0x01` 位置在左下 Alt/Cmd，
疑似 Win/Cmd 锁；`0x05..0x0A` 在 Z/X/C/V/G 上，疑似灯效选择）。移植时只有 `0x0D` 映射为
`MO(...)`，其余统一落成 `KC_NO /* vendor layer action 07:.. */`。

### class `0x08` LED 动作全集（已枚举，16 格，两个 Fn 层各 8）

| 记录 | 物理键 | 结构 |
|---|---|---|
| `08 FF 00 00` | Fn + Space | 单发 |
| `08 00 00 00` | Fn + Del | 单发 |
| `08 02 00 00` | Fn + PgUp | 单发 |
| `08 07 00 00` | Fn + PgDn | 单发 |
| `08 03 01 00` / `08 03 02 00` | Fn + Up / Fn + Down | 同轴 `0x03`，方向 `01`/`02` |
| `08 04 01 00` / `08 04 02 00` | Fn + Right / Fn + Left | 同轴 `0x04`，方向 `01`/`02` |

第二字节 `01`/`02` 成对出现在同一轴上（Up/Down、Left/Right），很像"同轴加/减"（亮度、速度或色相）；
`00`/`02`/`07`/`FF` 是单发动作（关灯、模式循环、总开关…）。**语义未证实**，见下。

### 层序与差异

层序与 SMK 的 `_MAC_BL/_WIN_BL/_MAC_FL/_WIN_FL` 一致。`keymap.py check` 可复现：

* mac-base vs win-base：3 格（`LGui`/`LAlt` 互换、`RAlt`/`RGui` 互换）。
* mac-fn vs win-fn：12 格（F1-F12 ↔ 亮度/媒体/组合键）。
* 基础层 vs Fn 层：66 格。

移植版把无法表达的东西落成 `KC_NO` + 原始字节注释：6 个 `0x07` 动作、8 个 `0x08` LED 动作、
1 个多修饰组合键（win-fn 的 Fn+6 = `00 A0 00 21` = RShift+RGui+4）、1 个未收录的 consumer
（Fn+O = `0x018A`，AL Email Reader）。这些注释即 TODO 锚点。

### 运行时表示

扫描/派发期间，按键同样以 4 字节记录出现在 XDATA `0x0ED7`（`R4,R5,R6,R7`），
字节 2（`R6`）的 bit7 被用作"按下/特殊"标志（`R6 |= 0x80`）。

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
```

## 运行时键处理（部分确证）

* `0x0ED7` 是 XDATA 中的当前按键 4 字节记录缓冲区（`R4..R7`）。
* `0x2CF0` 是通用辅助：把 `R4,R5,R6,R7` 依次写入 XDATA `@DPTR`（并自增 `DPTR`）——即"写回记录"原语；
  记录的第 3 字节（`R6`）的位 5/6/7（`0x20`/`0x40`/`0x80`）被用作标志位。
* 特殊键后处理例程约在 `0x1305-0x1402`，对 XDATA 运行时代码 `0x0CA0`（子码 `0x0CA1`）取值
  `2/4/6/7/8/9/0x0B` 分支，命中时把 `R6` 置位 `0x20`/`0x40`/`0x80` 并翻转 `BITS_30/31/39`。
* `0x294C-0x298E` 是围绕 `0x0CA0` 的递减状态机（`02→0B`、`01→0B`、`09→08`、`04→03`，
  小于 3 时从 `0x0F64` 重新装载），更像是背光/效果模式状态，而不是键位表 class 的直接比较。

## 尚未证实

* LED 子码的具体语义（哪个是亮度、哪个是速度、模式编号如何对应）未证实；
  class `0x07`/`0x08` 从 flash 键位表到运行时代码的转换点仍未找到。
* **每列 PWM 通道 ↔ 物理列的对应关系未证实**：`PWMxxDUTY` 初值全为 `0xB0`（均匀），
  效果引擎索引的是抽象缓冲（`0x9983` → XDATA `0x08F5`，128 B），静态无法反推走线。
  需要原理图或台架测量。
* "从左到右"的物理朝向未做按键核对；但**不影响正确性**：厂商与移植版使用同一
  `列序→引脚` 映射和同一按序号索引的键位表，同一物理按键在两者中解析为同一键位。
* 固件中**不存在** `MOV DPTR,#0xBC00` / `MOV DPH,#0xBC` 一类字面量访问，因此
  `0xBC00-0xCC00` 四层表**未被以字面地址 `MOVC` 读取**；它是运行时键表、还是仅供厂商
  配置工具/间接指针表使用，尚未确认。


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
