---
id: smk-port
title: "SMK 移植细节 (YD-Y65S)"
category: reference
status: active
tags: [smk, port, build, sdcc]
created: "2026-10-19T19:07:35"
updated: "2026-10-19T19:07:53"
---

<!-- compiled_truth -->
## 结论

YD-Y65S 的 SMK 移植已经从"计划"变成**可编译的板级目录 + 可复现的构建链路**，产物为
`build/smk-yd-y65s/yd-y65s_default_smk.hex`。尚未写入设备。

## 仓库布局

* `src/keyboards/yd-y65s/` — 版本化的板级目录（SMK 的 `tools/smk` 不入库）：
  `kbdef.h`、`user_matrix.c`、`user_init.c`、`kb.c`、`user_sleep.c`、
  `layouts/default/layout.c`、`meson.build`。
* `tools/sync-port.ps1` — 镜像 `src/keyboards/yd-y65s` 到
  `tools/smk/src/keyboards/yd-y65s`，并把 `subdir('yd-y65s')` 追加到 SMK 的
  `src/keyboards/meson.build`（幂等）。
* `analysis/gen_smk_layout.py` — 从 `firmware/YD-Y65S_firmware.bin` 生成 `layout.c`，
  避免手抄键位。改板级目录后应重新生成再构建。
* `tools/build-port.ps1` — sync + patch + `meson setup` + 只编译
  `yd-y65s_default_smk.hex`。

## 板级映射

* `MATRIX_ROWS 5` / `MATRIX_COLS 15`，列顺序严格采用 `keymap.py` 的 `COL_PINS`：
  `P6.0-P6.7, P5.0-P5.2, P5.7, P4.0, P7.7, P4.5`。
* 行：`P7.1, P7.2, P7.3, P5.3, P5.4`。`user_matrix_read_rows()` 打包为
  bit0=P7.1 … bit2=P7.3、bit3=P5.3、bit4=P5.4；bit 0 永远为 0，对应键位表的 slot0。
* 列掩码：P6=`0xFF`、P5=`0x87`、P4=`0x21`、P7=`0x80`。`user_matrix_scan_post()`
  只关闭这些列的 pull-up/输出，因此 P5.3/P5.4 与 P7.1-P7.3 的行 pull-up 不会被破坏。
* `user_init()`：行输入 + pull-up，列输出且默认拉高（扫描为低有效）。
* 厂商 `P4CR=0xB1` / `P7CR=0xF0` 中多出的 P4.4/P4.7、P7.4-P7.6 疑似 RGB/其他功能，
  当前不驱动，留作后续 LED 逆向。

## 键位层

`gen_smk_layout.py` 把厂商四层映射为：

| SMK 层 | 名称 | 厂商地址 |
|---|---|---|
| 0 | `_WIN_BL` | `0xBE00` |
| 1 | `_MAC_BL` | `0xBC00` |
| 2 | `_WIN_FL` | `0xC600` |
| 3 | `_MAC_FL` | `0xC400` |

把 Windows 基础层放在 0，是为了让 SMK 的 `default_layer=0` 直接符合本机默认行为。
Fn 键在 win 基础层是 `MO(_WIN_FL)`，在 mac 基础层是 `MO(_MAC_FL)`。
`layout_os_base_layer(bool is_mac)` 返回 `_MAC_BL/_WIN_BL`，但当前通用 `kb.c` 不调用它；
将来接 OS 切换开关时再用。

映射规则：class `0x00` 键盘（单修饰键→`KC_*`，单修饰组合→`LCTL(kc)` 等）、
class `0x02` consumer（音量/媒体/亮度等）、class `0x07` → `MO(...)`、
class `0x08`（LED 动作）与多修饰组合键 → `KC_NO /* 原始字节 */`。
这些注释是有意保留的 TODO 锚点。

## 构建环境（Windows）

* `scoop install sdcc meson ninja gcc`；sinowisp 用 `tools/fetch-tools.ps1`
  下载官方 v2.1.0（资产名必须带三元组：
  `sinowisp-x86_64-pc-windows-msvc-v2.1.0.tar.gz`，旧的 `sinowisp-win.tar.gz` 已 404）。
* scoop 的 sdcc 只创建 `sdcc` shim；`sdar`/`packihx` 在
  `%USERPROFILE%\scoop\apps\sdcc\current\bin`，构建脚本显式加入 PATH。
* gcc 若安装被中断，包已解压但可能没有 shim；同样直接使用
  `%USERPROFILE%\scoop\apps\gcc\current\bin`。
* Meson 需要名为 `python3` 的程序；Windows Store 的别名是空壳。构建脚本用
  `uv python find 3.13.5` 生成 `build/shim/python3.cmd`，不污染系统 PATH。
* SDCC 4.6 新增 **error 357**（只读 code 空间指针必须 const）。`tools/patch-smk.ps1`
  幂等修正 `src/smk/usb.c` 的 `APPEND()` 宏与 `src/sino51lib/flash.c` 的 MOVC 读取。
  SMK 其他官方板（nuphy-air60 等）在 4.6 下仍有 optimizer error 110/126，
  所以 `build-port.ps1` 只编译 yd-y65s 目标。

## 构建结果（2026-10-19）

* SDCC 4.6.0 / meson 1.12.1 / ninja 1.13.2 / gcc 15.2.0 / sinowisp 2.1.0。
* CSEG `0x144-0x36D6`（≈13.7 KiB），CONST ≈1.2 KiB；远低于 60 KiB 应用区。
* `yd-y65s_default_smk.interrupts-ok` 通过（无未声明中断向量 / ISR overlay 冲突）。
* `75 F0 A5 74 5A 02 FF 00` 位于 `0x2811`，`_isp_jump` @ `0x280F`；
  与厂商的 ISP 逃生桩一致。
* 仍未执行任何 flash 写入/擦除。

## 待办

1. 物理核对：列顺序（"left to right" 目前是推断）与 PWM 通道↔物理列。
2. 逆向逐键 RGB 拓扑（P4.4/P4.7、P7.4-P7.6 的角色；`0x08` LED 子码语义）。
3. 决定是否接入无线（BK3632）与厂商额外 HID collection。
4. 在 ucsim-sh68f90 里跑通，再考虑经用户许可后的首次写入。


## Timeline

- time: 2026-10-19T19:07:35
  kind: decision
  summary: "Created this page: SMK 移植细节 (YD-Y65S)"
  source: "tools/build-port.ps1 + src/keyboards/yd-y65s"
  affects: [smk-port]

- time: 2026-10-19T19:07:53
  kind: decision
  summary: "记录板级目录、键位生成器、Windows 构建链路与 SDCC 4.6 const 修正；首次构建通过"
  source: "tools/build-port.ps1 + src/keyboards/yd-y65s"
  affects: [smk-port]
