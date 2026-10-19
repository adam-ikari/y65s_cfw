---
id: matrix-and-keymap
title: "矩阵扫描与键位表 (YD-Y65S)"
category: reference
status: active
tags: [matrix, keymap, sh68f90, yd-y65s]
created: "2026-10-19T17:49:43"
updated: "2026-10-19T17:54:30"
---

<!-- compiled_truth -->
## 矩阵几何（已确认）

从厂商固件的矩阵扫描跳转表 `0x35E8` + 端口方向初始化 `0x94A3-0x9535` 推出，并与 SMK 同芯片
板级定义 `src/keyboards/nuphy-air60/kbdef.h` 交叉验证：

| | 引脚 | 说明 |
|---|---|---|
| 列（15） | `P6.0-P6.7`, `P5.0-P5.2`, `P5.7`, `P4.0`, `P7.7`, `P4.5` | 扫描时逐列推挽输出拉低 |
| 行（5） | `P7.1`, `P7.2`, `P7.3`, `P5.3`, `P5.4` | 输入，读取时被打包 |

* 端口方向：`P6CR=0xFF`、`P5CR=0x87`、`P7CR=0xF0`、`P4CR=0xB1`（`0x94A3-0x9535`）。
* 行读取例程 `0xB130`：`R7 = ~(0xFF 的 ACC 位 1..5 = P7.1,P7.2,P7.3,P5.3,P5.4)`。
* `0xB113` 把传入的增量写入 XDATA `0x0ECD` 后落入 `0xB130`；`0xB108/0xB10C` 是列 11/12 的
  共享入口（代码压缩）。
* 结论：`MATRIX_ROWS 5`、`MATRIX_COLS 15`。

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
| `0x07` | 层/厂商动作 | 子码在 `usage`；基础层 `0x07 00 00 0D` 即 Fn 键 |
| `0x08` | LED/背光控制 | 子码在 `mod:hi:usage`（`08 FF 00 00`、`08 03 01 00` …） |
| `0x0D` | 未分配 | 全零等效禁用 |

### 层序与差异

层序与 SMK 的 `_MAC_BL/_WIN_BL/_MAC_FL/_WIN_FL` 一致。`keymap.py check` 可复现：

* mac-base vs win-base：3 格（`LGui`/`LAlt` 互换、`RAlt`/`RGui` 互换）。
* mac-fn vs win-fn：12 格（F1-F12 ↔ 亮度/媒体/组合键）。
* 基础层 vs Fn 层：66 格。

### 运行时表示

扫描/派发期间，按键同样以 4 字节记录出现在 XDATA `0x0ED7`（`R4,R5,R6,R7`），
字节 2（`R6`）的 bit7 被用作"按下/特殊"标志（`R6 |= 0x80`）。

## LED 驱动（已确认）

LED 由**芯片内置 PWM bank 直驱**，没有外置驱动 IC：

* `0x48BE-0x48FD` 写 `PWM00CON..PWM30CON`；
* `0x46F9-0x48AB` 把 `PWMxxDUTY1L/H` / `DUTY2L/H` 设为 `0xB0`、`PERD=0xB0`；
* 共 15-16 通道（约每列一路亮度），对应 SMK 的 `LED_PWM_C0..C15`；
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
* 实际扫描期键映射读的是 flash 表：`0x0A90`（90 B，扫描序号 → `col*8+row` 代码，未用槽为 `0xFF`）、
  以及 `0x0C15`/`0x0C93`（步长 `0x15`=21 的间接表），均用 `MOVC`（code 空间）。

## 尚未证实（推断 / 待解）

* 列顺序按扫描跳转表存储顺序（`RAM_2C..RAM_3A`）解释为"从左到右"，未做物理按键核对。
* 每列 PWM 通道与物理列的对应关系为推断（通道数 15-16 与列数一致）。
* 固件中**不存在** `MOV DPTR,#0xBC00` / `MOV DPH,#0xBC` 一类字面量访问，因此
  `0xBC00-0xCC00` 四层表**未被以字面地址 `MOVC` 读取**；它是运行时键表、还是仅供厂商
  配置工具/间接指针表使用，尚未确认。
* class `0x07`/`0x08` 从 flash 键位表到运行时代码 `0x0CA0` 的转换点未找到。


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
