---
id: smk-port
title: "SMK 移植细节 (YD-Y65S)"
category: reference
status: active
tags: [smk, port, build, sdcc]
created: "2026-10-19T19:07:35"
updated: "2026-10-19T22:20:04"
---

<!-- compiled_truth -->
## 结论

YD-Y65S 的 SMK 移植已经从"计划"变成**可编译、可在仿真里跑通的板级目录 + 可复现的构建/验证链路**，
产物为 `build/smk-yd-y65s/yd-y65s_default_smk.hex`。尚未写入设备。

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
* `tests/test_y65s_sim.py` — 仿真测试：YD-Y65S 列线模型驱动矩阵，断言解析出的
  HID 用法与 dump 一致。`tools/sim-tests.ps1` / `sim-tests.sh` 跑它 + SMK 与板无关的测试。

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
class `0x08`（LED 控制指令：动作号 = `byte1`、参数 = `byte2`）与多修饰组合键 → `KC_NO /* 原始字节 */`。
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

## 仿真验证（2026-10-19）

模拟器是 Linux 二进制，只在 WSL 内构建/运行，Windows 侧不需要额外东西。

* 构建：`tools/build-ucsim.ps1` → `tools/build-ucsim.sh`。复刻 SMK flake 的派生：
  取 SDCC **4.5.0** 源码，套用 `tools/ucsim/sh68f90-register.patch`，拷入
  `sh68f90.cc`/`sh68f90cl.h`，`flex` 重新生成 `cmdlex.cc`，只 `configure` 出 mcs51 模拟器。
  **无需 root**：flex/bison 用 `apt-get download` 取 .deb 再 `dpkg-deb -x` 到私有前缀；
  bison 必须设 `BISON_PKGDATADIR` 指向解包目录（否则找不到 `m4sugar.m4`）。
  产物 `~/ucsim-build/sdcc-4.5.0/sim/ucsim/src/sims/s51.src/ucsim_51`。
* 运行：`tools/sim-tests.ps1` → `tools/sim-tests.sh`，跑两组共 29 项，全部通过
  （SMK 1 项按板跳过）：
  1. `tests/test_y65s_sim.py`：YD-Y65S 列线模型 + 真实扫描路径，断言 EP1 报告等于
     dump 中 win-base 层在该 (col,row) 的用法（Esc/W/A/D 四个位置，覆盖 P6/P5/P4）。
  2. SMK 与板无关的测试：复位→主循环、USB 枚举到 CONFIGURED、描述符分包、HID
     idle/protocol/LED、字符串描述符、中断向量压栈、栈溢出。
* 关键证据：`test_set_report_isp_jumps_to_bootloader` 证明 feature report id 5 + OUT
  `05 75` 真的执行了 `isp_jump()`（ACC=0x5A / B=0xA5）——即新固件的逃生通道在仿真里可用。
* SMK 自带的 `TestKeyEvent` / `TestWorstCaseStack` 用的是 **Air60 列线**（`devices.py`
  顶部硬编码），在本机上会把 (col=1,row=2) 认成 Air60 的 P5.1，而固件扫的是 P6.1，
  于是解析到 HID `0x0F`（L）而非 `0x04`（A）。这是**测试模型**的差异，不是固件缺陷；
  已由本仓库的 YD-Y65S 模型取代，故 `sim-tests.sh` 排除这两个类。

## 待办

1. 物理核对：列顺序（"left to right" 目前是推断）与 PWM 通道↔物理列。
2. 逆向逐键 RGB 拓扑（P4.4/P4.7、P7.4-P7.6 的角色）。`0x08` LED 子码语义已解码（见 `matrix-and-keymap` 页）。
3. 决定是否接入无线（BK3632）与厂商额外 HID collection。
4. 首次写入设备必须经用户明确许可（见 `no-write-policy`）；写入前后用 `sinowisp read`
   回读校验。


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

- time: 2026-10-19T19:12:21
  kind: evidence
  summary: "新固件的 ISP 触发路径与厂商一致：feature report id 5 -> EP0 OUT 05 75 -> usb_isp_requested=1 -> isp_jump()（src/smk/usb.c:1086/1161/461）；链接后桩位于 0x280F"
  source: "tools/smk/src/smk/usb.c + build map"
  affects: [smk-port, custom-firmware-path]

- time: 2026-10-19T19:37:18
  kind: decision
  summary: "仿真验证通过：WSL 里构建补丁版 uCsim 0.8.15，29 项测试全绿（含真实 isp_jump 握手）；新增 tests/test_y65s_sim.py 用 YD-Y65S 列线模型核验键位"
  source: "tests/test_y65s_sim.py + tools/build-ucsim.sh + tools/sim-tests.sh"
  affects: [smk-port]

- time: 2026-10-19T21:02:03
  kind: decision
  summary: "class 0x08 LED 子码语义已解码，移植仍映射 KC_NO"
  source: "matrix-and-keymap 页面 + analysis/gen_smk_layout.py"
  affects: [smk-port]

- time: 2026-10-19T21:02:03
  kind: decision
  summary: "确认 class 0x08 是 LED/背光控制指令（动作号 byte1、参数 byte2），8 条记录与副派发 0x55CF 跳转表逐条对上；移植端仍映射为 KC_NO + 原始字节注释，因为 SMK 的灯效由自身 RGB 层管理；剩余未解的是 PWM 通道↔物理灯"
  source: "brain/pages/matrix-and-keymap.md + analysis/gen_smk_layout.py"
  affects: [smk-port matrix-and-keymap]

- time: 2026-10-19T22:20:04
  kind: decision
  summary: "板上有第二颗 SoC（无线+小屏+旋钮），屏幕不是 8051 驱动的；主控与它只靠一条私有 UART（魔数 0x5A + 帧头 01 11 xx，收包缓冲 xdata 0x1130，链路状态 xdata 0x0F29 = 1/USB 与 0x25/0x35/0x45/0x55 = 2.4G/BT1/BT2/BT3）。移植不做这条协议则屏幕无主机侧内容、2.4G/BT 与旋钮不可用。细节见 firmware-layout。"
  source: "fwdis.py sfr/xdata + fw_full.lst (0x8EF2/0xA3FC/0xAF1B/0x1283)"
  affects: [smk-port]
