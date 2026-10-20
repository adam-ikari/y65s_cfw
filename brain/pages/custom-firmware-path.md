---
id: custom-firmware-path
title: "自制固件路线 (Custom Firmware Path)"
category: decision
status: active
created: "2026-10-19T16:46:15"
updated: "2026-10-20T10:52:58"
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
   并确认 LED 是 PWM bank 直驱还是外置驱动 IC。~~ **已完成**：矩阵 15 列 × 5 行已由三处
   独立证据互证（扫描派发引脚次序 + 行读取 `0xB130` 位打包 + 扫描序表 `0x0A90` 的
   `col*8+slot` 编码），键位表 4 层格式、LED 内置 PWM bank 直驱，细节见 `matrix-and-keymap`。
2. ~~**新建板级目录** `src/keyboards/yd-y65s/`。~~ **已完成（2026-10-19）**：
   `kbdef.h` / `user_matrix.c` / `user_init.c` / `kb.c` / `user_sleep.c` /
   `layouts/default/layout.c` / `meson.build` 已入库；`tools/sync-port.ps1` 把它镜像进
   `tools/smk/src/keyboards/yd-y65s`（SMK 本身不入库）。键位表由
   `analysis/gen_smk_layout.py` 从 dump 逐格生成，层序为
   `_WIN_BL=0 / _MAC_BL=1 / _WIN_FL=2 / _MAC_FL=3`，即 SMK 默认层 0 = Windows 基础层。
3. **保留逃生通道**：`-Disp=enabled`（默认）。构建产物中
   `75 F0 A5 74 5A 02 FF 00` 位于 `_isp_jump`（本次链接 @ `0x280F`），与厂商桩一致；
   仿真里 feature report id 5 + OUT `05 75` 确实进入 `isp_jump()`。
4. ~~**构建**：SDCC + meson + ninja。~~ **已完成（2026-10-19）**：
   SDCC 4.6.0 / meson 1.12.1 / ninja 1.13.2 / gcc 15.2.0 / sinowisp 2.1.0；
   `tools/build-port.ps1` 产出 `build/smk-yd-y65s/yd-y65s_default_smk.hex`
   （CSEG ≈ 13.7 KiB + CONST ≈ 1.2 KiB，远小于 60 KiB 应用区）。
   SDCC 4.6 新增 error 357（code 空间指针必须为 const），由
   `tools/patch-smk.ps1` 对 `src/smk/usb.c` 与 `src/sino51lib/flash.c` 做幂等修正；
   脚本只编译 `yd-y65s_default_smk.hex`，因为其他官方板在 4.6 下仍会触发 opt 错误。
5. **验证**：**仿真已跑通（2026-10-19）**——WSL 里构建补丁版 uCsim，29 项测试全绿
   （启动/枚举/描述符/HID/ISP/中断/栈 + YD-Y65S 键位核验），见 `smk-port` 与
   `tools/build-ucsim.*`、`tools/sim-tests.*`。上机前只用 `sinowisp read` 回读校验，
   写入必须另行获得许可。

## 风险

* SMK 自述 "highly experimental"，且警告：如果写入的固件不能跳回 ISP，设备就变砖。
* 兜底方案是硬件编程器（Arduino Nano + `sinodude-serial`，或 SinoWealth SinoLink + ProWriter），
  本机目前没有。
* 无线部分（若本机实际带 BK3632）在 SMK 中仍是 `[~]` 未完成状态。
* **PWM 通道 ↔ 物理 LED 走线的对应关系仍未确定**：厂商把 `PWMxxDUTY` 初值一律设为 `0xB0`、
  `PERD=0xB0`（均匀），效果引擎索引的是抽象缓冲，静态无法反推走线；需要原理图或台架测量。
  （矩阵的列序→引脚映射已从厂商代码验证，不再是风险。）
* 仿真只覆盖 MCU 模型 + 测试侧的矩阵，未覆盖真实 RGB/RF 硬件、供电与 USB 主机的差异。
* 逐键 RGB 尚未实现：当前 `user_matrix_sinks_off` 为空、未定义 `led_cols`；Fn 层共 16 格
  落成 `KC_NO /* ... */`（6 个 class `0x07` 私有动作、8 个 class `0x08` LED 动作、
  Fn+6 的多修饰组合、Fn+O 的 consumer `0x018A`）。
* 未接入厂商的 8 个 HID collection；SMK 只提供标准 keyboard / NKRO / consumer 等。

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

- time: 2026-10-19T19:07:18
  kind: decision
  summary: "板级目录、键位生成器与 Windows 构建链路完成；yd-y65s_default_smk.hex 在 SDCC 4.6.0 下构建通过，ISP 跳转桩保留"
  source: "tools/build-port.ps1 + analysis/gen_smk_layout.py"
  affects: [custom-firmware-path]

- time: 2026-10-19T19:38:16
  kind: decision
  summary: "第 5 步（验证）在仿真里跑通：29 项测试全绿，含真实 isp_jump 握手与 YD-Y65S 键位核验；写入设备仍需明确许可"
  source: "tools/sim-tests.sh + tests/test_y65s_sim.py"
  affects: [custom-firmware-path]

- time: 2026-10-19T19:52:54
  kind: decision
  summary: "矩阵几何风险消除（三处互证）；剩余风险改为 PWM 走线未定 + RGB 未实现（Fn 层 16 格 KC_NO）"
  source: "fwdis.py dis 0x3590-0x37E0/0xB108-0xB148 + 0x0A90"
  affects: [custom-firmware-path]

- time: 2026-10-19T23:09:56
  kind: decision
  summary: "新增判定：自制固件不可能做在屏幕模组(第二颗 SoC)上(固件不可读/型号未知/无烧写通道)；SMK 主控固件才是唯一落点，且应在其中实现主控<->模块 UART 链路(0x50 帧 + 0x81 大块转发)与 feature 9 接收，见 module-link"
  source: build/fw_full.lst
  affects: [custom-firmware-path, module-link, screen-customization]

- time: 2026-10-20T10:37:02
  kind: note
  summary: "2026-10-20 用户把自制固件目标从主控 SMK 转向屏幕/无线模组. 旧结论『模组自制固件不可行』依据是无固件/无型号/无烧写通道, 目前仍未发现反证, 但开始硬件识别: 拆机看 SoC 丝印、外部 SPI flash(用户动画区 0x650000 暗示 >=8MB 外部 flash)、SWD/UART 测试点; 若能 dump 固件或找到调试口, 再评估自定义固件与工具链"
  source: "用户决策 + OEM 工具资源扫描"
  affects: [custom-firmware-path]

- time: 2026-10-20T10:52:58
  kind: evidence
  summary: "2026-10-20 排除『借厂商 OTA 通道给模组刷自制固件』: ODM 网页 OTA 实为 Sonix 主控 ISP(仅 0x0C45 设备/WASM sn_isp_lib), 而 Y95 的 258A:019D 记录协议白名单不含 OTA 命令, 原厂安装包/更新服务器也没有模组固件. 所以本页的 SMK 主控固件仍是唯一可自制的固件载体; 模组侧只能当显示外设驱动."
  source: "build/odm/layout-classic-Bylu1MNp.js + gm 表 + build/fw_full.lst 0xA331"
  affects: [custom-firmware-path]
