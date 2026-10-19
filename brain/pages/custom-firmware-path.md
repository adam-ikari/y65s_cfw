---
id: custom-firmware-path
title: "自制固件路线 (Custom Firmware Path)"
category: decision
status: active
created: "2026-10-19T16:46:15"
updated: "2026-10-19T17:50:37"
---


<!-- compiled_truth -->
## 结论

自制固件走 **SMK 移植**路线，而不是从零写 8051 USB 栈、也不是等 QMK 支持。

`karstx/smk`（"SMK — Small Mechanical Keyboard firmware"）已经是一个可用的
Sinowealth 8051 键盘固件，用 SDCC 构建，包含：

* `src/sino51lib/sh68f90/` — SH68F90/A 的 HAL：GPIO、时钟、PWM、USB、SPI、Flash/SSP、ISP、Power-Down；
* `src/smk/usb.c` + `usbdef.h` — USB 描述符与 HID 栈（含 ISP feature report）；
* `src/kb/` — 键扫、去抖、按键处理、指示灯；
* `src/peripherals/bk3632/` — BK3632 无线模块（2.4G/BT）支持；
* `tools/ucsim/` — 打过补丁的 SDCC uCsim，能模拟 SH68F90 的 USB 中断（向量 7 @ `0x3B`）。

已支持的板子：NuPhy Air60 v1（SH68F90A）、E-YOOSO Z11、Genesis Thor 300（SH68F881）、
CIY X77（SH68F89）。**本机的 `258A:019D` 已在 `sinowisp` 的设备表中（`superframe-phantom`），
说明同一平台已被社区验证过。**

## 移植步骤

1. ~~**确定硬件连接**：从厂商固件 `0x35E8` 的扫描跳转表 + `ports` 分析推出矩阵行列引脚，
   并确认 LED 是 PWM bank 直驱还是外置驱动 IC。~~ **已完成**：矩阵 15 列 × 5 行、
   键位表 4 层格式、LED 内置 PWM bank 直驱，细节见 `matrix-and-keymap`。
2. **新建板级目录** `src/keyboards/yd-y65s/`：`kbdef.h`（`MATRIX_ROWS/COLS`、行/列引脚、
   LED PWM 映射、`LED_CAPS`）、`user_matrix.c`、`kb.c`、`user_init.c`、`user_sleep.c`、
   `layouts/default/{layout,indicators}.c`，并在 `src/keyboards/meson.build` 注册。
   直接可用的输入：`MATRIX_COLS 15`、`MATRIX_ROWS 5`、`COL_PINS = {P6.0-P6.7, P5.0-P5.2,
   P5.7, P4.0, P7.7, P4.5}`、`ROW_PINS = {P7.1, P7.2, P7.3, P5.3, P5.4}`、4 层键位按
   `analysis/keymap.py` 输出转换为 SMK layout。
3. **保留逃生通道**：`-Disp=enabled`（默认），确保厂商 HID feature report `05 75` 仍能触发
   `isp_jump()`；这是砖机与不砖机的分界线。
4. **构建**：SDCC + meson + ninja，`meson compile -C build yd-y65s_default_smk.hex`。
5. **验证**：先只用 `sinowisp read` 回读校验，不写入；写入必须另行获得许可。

## 风险

* SMK 自述 "highly experimental"，且警告：如果写入的固件不能跳回 ISP，设备就变砖。
* 兜底方案是硬件编程器（Arduino Nano + `sinodude-serial`，或 SinoWealth SinoLink + ProWriter），
  本机目前没有。
* 无线部分（若本机实际带 BK3632）在 SMK 中仍是 `[~]` 未完成状态。
* 矩阵列序与 PWM 通道↔物理列的对应尚为推断，移植前应尽量用按键/台架核对。

## 为什么不是其他路线

* **QMK**：不支持 Sinowealth 8051（社区明确说明该架构无 QMK 支持）。
* **从零写**：需要自己逆向 USB SFR、端点缓冲、时钟/PLL、flash 编程时序，
  成本远高于在 SMK 上加一块板。
* **Ghidra 反编译厂商固件再改**：厂商固件是 SDCC 之外的编译器产物且无符号，
  改造成本高、可维护性差。


## Timeline

- time: 2026-10-19T16:46:15
  kind: decision
  summary: "Created this page: \""
  source: created via brain create-page
  affects: [custom-firmware-path]

- time: 2026-10-19T16:47:21
  kind: decision
  summary: "\""
  source: brain update-truth
  affects: [custom-firmware-path]

- time: 2026-10-19T17:50:37
  kind: decision
  summary: "移植步骤 1（确定矩阵引脚与 LED 驱动方式）已完成，可直接用 matrix-and-keymap 的引脚/层数据构建板级目录"
  source: "analysis/keymap.py + fwdis.py"
  affects: [custom-firmware-path]
