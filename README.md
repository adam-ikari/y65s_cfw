# y65s_cfw — YD-Y65S (Sinowealth SH68F90A) 固件逆向与自制固件

针对 USB 键盘 **YD-Y65S**（`258A:019D`，REV 3003，厂商串 `SINO WEALTH`）的固件提取、结构解析与
开源固件移植研究。

> ⚠️ **写入禁令**：在获得明确许可前，本项目**不做任何 flash 写入/擦除**。现有工作全部是只读 dump
> 与离线分析。

## 硬件

| 项目 | 值 |
|---|---|
| USB ID | `258A:019D`（bcdDevice `3003`） |
| 芯片 | Sinowealth **SH68F90/A**（8051 内核，24 MHz） |
| Flash | 64 KiB = `0x0000-0xEFFF` 应用 + `0xF000-0xFFFF` ISP bootloader |
| 配置 | 复合设备：IF0 = boot keyboard（EP1 IN，8B）；IF1 = 8 个 collection（EP2 IN，16B） |
| 厂商固件 | `YD-Y65S-5.0 A`（字符串 @ `0x7D82`） |
| bootloader | 4096 B，MD5 `3e0ebd0c440af5236d7ff8872343f85d`（社区已知版本） |

## 目录

```
firmware/    只读 dump（完整 64 KiB / 应用 60 KiB / bootloader 4 KiB）
analysis/    Python 分析工具链（纯标准库，uv 运行）
  mcs51.py          精确 MCS-51 反汇编器 + Intel HEX 读写
  fwdis.py          CLI：info / dis / xref / sfr / xdata / ports / strings / find
  usbdesc.py        USB 设备/配置/字符串/HID 报告描述符解析器
  keymap.py         键位表解码：dump / list / check（矩阵引脚 + 4 层 4 字节记录）
  gen_smk_layout.py 从 dump 生成 SMK `layout.c`（保证移植与厂商键位逐格一致）
  tools/            早期 JS 原型（已被 Python 版取代，留作参考）
src/         自制固件移植（纳入版本库）
  keyboards/yd-y65s/  SMK 板级目录：kbdef.h / user_matrix.c / user_init.c /
                      kb.c / user_sleep.c / layouts/default/layout.c
tools/       第三方工具与构建脚本
  fetch-tools.ps1   拉取 SMK / sinowisp（不纳入版本库的部分在 tools/smk、tools/bin）
  sync-port.ps1     把 src/keyboards/yd-y65s 同步进 tools/smk
  patch-smk.ps1     幂等的 SDCC 4.6 兼容修正（const code 指针）
  build-port.ps1    sync + patch + meson setup + ninja
  build-ucsim.ps1   在 WSL 里构建打过补丁的 uCsim（SH68F90 USB 中断模型）
  build-ucsim.sh    实际构建脚本（无需 root，私有解包 flex/bison）
  sim-tests.ps1     仿真测试入口（本仓库 + SMK 与板无关的部分）
  sim-tests.sh      实际测试脚本
tests/       仿真测试（在 WSL 里用打过补丁的 uCsim 跑固件）
  test_y65s_sim.py  YD-Y65S 列线模型：矩阵 → 扫描 → 键位 → HID 报告
build/       生成的清单/报告/构建目录（不纳入版本库）
brain/       项目知识库（通过 `brain` CLI 读写，勿手改）
```

## 用法

```powershell
uv run analysis/fwdis.py info    firmware/YD-Y65S_full.bin
uv run analysis/fwdis.py dis     firmware/YD-Y65S_firmware.bin --start 0x89D7 --len 0x60
uv run analysis/fwdis.py dis     firmware/YD-Y65S_firmware.bin --reachable --out build/fw_code.lst
uv run analysis/fwdis.py sfr     firmware/YD-Y65S_firmware.bin
uv run analysis/fwdis.py xdata   firmware/YD-Y65S_firmware.bin
uv run analysis/fwdis.py ports   firmware/YD-Y65S_firmware.bin
uv run analysis/fwdis.py find    firmware/YD-Y65S_firmware.bin "75 F0 A5 74 5A 02 FF 00"

uv run analysis/usbdesc.py firmware/YD-Y65S_firmware.bin --strings --string-range 0x4400:0x46A0 `
    --dev 0x4699 --hid 0x4526 --len 0x43 --hid 0x4569 --len 0x130

uv run analysis/keymap.py dump  firmware/YD-Y65S_firmware.bin --layer 0   # 列 × 行网格
uv run analysis/keymap.py list  firmware/YD-Y65S_firmware.bin --layer 2   # 已分配的键
uv run analysis/keymap.py check firmware/YD-Y65S_firmware.bin             # 副本校验 + 层间差异

# 从 dump 重新生成 SMK 键位（移植与厂商键位逐格一致）
uv run analysis/gen_smk_layout.py firmware/YD-Y65S_firmware.bin `
    > src/keyboards/yd-y65s/layouts/default/layout.c

# 构建自制固件（需要 sdcc / meson / ninja / gcc，见下）
powershell -ExecutionPolicy Bypass -File tools\fetch-tools.ps1
powershell -ExecutionPolicy Bypass -File tools\build-port.ps1
# 产物：build/smk-yd-y65s/yd-y65s_default_smk.hex

# 仿真验证（需要 WSL；模拟器是 Linux 二进制，在其中构建一次）
powershell -ExecutionPolicy Bypass -File tools\build-ucsim.ps1
powershell -ExecutionPolicy Bypass -File tools\sim-tests.ps1
```

## 已确认的关键事实

* **ISP 协议**：向 IF1 report 5 发送 feature report `[05 75 00 00 00 00]` → 设备重枚举为
  `0603:1020`/`0603:1021`。读 = `0x55` / `0x52`+addr / get_feature(report 6, 2048 B 页) / `0x5a`。
* **固件内 ISP 跳转桩** @ `0xB0EF`：`CLR IEN0.7` / `MOV B,#A5` / `MOV A,#5A` / `LJMP 0FF00h`
  —— 与 SMK 的 `isp_jump()` 完全一致。这是自制固件**必须保留**的逃生通道。
* **ISP 命令分发** @ `0x82EA`：EP0 OUT 收到 `05 75` 后跳到上述跳转桩。
* **USB 描述符** 原样存在于固件中：设备描述符 @ `0x4699`，IF0 报告描述符 @ `0x4526`（67 B），
  IF1 报告描述符 @ `0x4569`（304 B）。字符串：`YD-Y65S` / `SINO WEALTH` / `0001` / `BY Tech`。
* **矩阵引脚**（已确认，三处独立互证）：列引脚
  `P6.0-P6.7`, `P5.0-P5.2`, `P5.7`, `P4.0`, `P7.7`, `P4.5`（共 15 路，扫描时逐列推挽拉低）；
  行引脚 `P7.1`, `P7.2`, `P7.3`, `P5.3`, `P5.4`（共 5 路，读取时由 `0xB130` 打包进 `ACC` 位 1..5）。
  三处证据：① 扫描派发 `0x35E8`（10 入口跳转表）的每个处理块按固定次序 `CLR Px.y` 驱动一列，
  结果依次落进 `RAM_2C..RAM_3A`，这个次序就是上面的列序（第二遍写 `RAM_41..RAM_4F` 作上次状态，
  `RAM_2C ^ RAM_41` 可交叉验证）；② 行读取 `0xB130` 的 `CPL A` 使 `R7` bit0 恒 0、
  bit(1+k) = 物理行 k——这也是每列 slot0 空置的原因；③ 扫描序表 `0x0A90`（90 B，`col*8+slot`，
  未用槽 `0xFF`）。
  端口方向由 `0x94A3-0x9535` 的 `P6CR=0xFF` / `P5CR=0x87` / `P7CR=0xF0` / `P4CR=0xB1` 设定，
  即 `MATRIX_ROWS 5`、`MATRIX_COLS 15`。
* **键位表** 位于 `0xBC00-0xCC00`（低熵区），4 层 × `0x200` 字节，每层 90 条 4 字节记录、
  列优先、每列 slot0 空置（该行的行线不存在）：

  | 层 | 地址 | 重复副本 | 内容 |
  |---|---|---|---|
  | 0 | `0xBC00` | `0xC000` | mac 基础层 |
  | 1 | `0xBE00` | `0xC200` | win 基础层 |
  | 2 | `0xC400` | `0xC800` | mac Fn 层 |
  | 3 | `0xC600` | `0xCA00` | win Fn 层 |

  记录格式 `[class, mod, hi, usage]`：`0x00` 键盘（HID usage 在 `usage`，修饰位掩码在 `mod`，
  也用于 `00 10 00 52`=RCtrl+Up 这类组合键）；`0x02` consumer（16 位 usage `hi:usage`，
  如 `0x00EA`=音量减）；`0x0D` 未分配。层序与 SMK 的 `_MAC_BL/_WIN_BL/_MAC_FL/_WIN_FL` 一致：
  mac/win 基础层仅 3 格不同（Alt/Gui 互换），mac/win Fn 层仅 12 格不同（F1-F12 vs 媒体/亮度）。
* **键位表消费链**（已确认，见下节）。`0x748F` 是记录读取器：地址 =
  `base(S) + 0x200*mode + 4*idx`，其中 `S = xdata[0x0EC8]`（`0→0xBC`、`1→0xC4`、`2→0xCC`、
  `3→0xD4`）、`mode = xdata[0x0F25]`（0=Mac/1=Win）、`idx = xdata[0x0EC2]`；读出的 4 字节写进
  `xdata 0x0B91..0x0B94` 再按 `byte0` 分派。`S=1`/`S=2` 读出全零时回退 `S=0`（基础层）。
  除 4 张已确认的表外，`0xCC00/0xCE00`（S=2）和 `0xD400/0xD600`（S=3）两张表**全零**，
  是运行时可写的槽位。逐键选择子数组是 `xdata 0x0B0F + 21*row + col`。
* **class `0x07` = 厂商动作/组合键**（子码在 `byte3`）：`0x0D` 是 Fn 键（`07 00 00 0D`）；
  `0x01/0x05/0x06/0x07/0x08/0x0A` 落在左下 Alt/Cmd 与 Z/X/C/V/G 上，写入
  `xdata 0x0F29/0x0F7F/0x0B8E/0x0BAC`（厂商组合键状态机）与动作位 `BITS_35/37`；
  `0x20/0x21` 写 Mac/Win 标志 `xdata 0x0B8F`。
* **class `0x08` = LED/背光控制指令**（`byte1` = 动作号，`byte2` = 参数），8 条记录与副派发
  `0x55CF` 的跳转表 `0x55F4`（10 项）**逐条对上**：`0x00`=Fn+Del（预设）、`0x02`=Fn+PgUp、
  `0x03`=Fn+Up/Down（同轴 ±）、`0x04`=Fn+Right/Left（同轴 ±）、`0x07`=Fn+PgDn（复位）、
  `0xFF`=Fn+Space（开关）、`0x09`=直设灯效 `xdata[0x0F65]`。主派发 `0xB90D` 只处理 `0xFF`。
* **LED 子系统变量**：`xdata[0x0F65]` = 灯效索引（0..0x13，`0x95EE` 20 项表派发）；
  `xdata[0x0CA1]` = 预设号（0..0x0F），经 code 表 `0xD119`
  （`01 02 03 04 05 07 08 09 0A 0B 0C 0D 0F 10 11 13`）映射到 `0x0F65`；
  `xdata[0x0CA0]` = 状态机状态（0..0x0A，`0x2899` 11 项表），状态机 `0x2812` 由 4 分频的
  定时中断 `0x62E0` 调用（非按键路径）；`xdata[0x0C28]` = 灯效闩锁（`00/69/96/FF`）；
  `xdata[0x0C29]` = 长按计数（阈值 150/200）。
* **静态分析陷阱**：`analysis/fwdis.py` 的"可达性"输出存在大片 gap（如 `0x27B4..0x2AED`、
  `0x9355..0x9A02`），"全固件找不到 X"类结论必须用 `--start 0 --len 0xF000` 的全量线性反汇编复核。
* **LED 由芯片内置 PWM bank 直驱**（无外置驱动 IC）：`0x48BE-0x48FD` 写 `PWM00CON..PWM30CON`
  （4 bank × 6 通道 = 24 路），`0x46F9-0x48AB` 把 `PWMxxDUTY1L/H` / `DUTY2L/H` 设为 `0xB0`、
  `PERD=0xB0`（初值均匀，不携带走线信息）。效果渲染在 `0xD11` 起，索引的是抽象缓冲
  （code `0x9983` → XDATA `0x08F5` 共 128 B），并维护计数器 `0x0EB2/0x0EB3`；
  因此**每路 PWM ↔ 物理列/灯的对应关系仍未确定**，需要原理图或台架测量。
* **板上还有第二颗 SoC（无线 + 彩色小屏 + 旋钮），与主控之间是一条私有 UART** ——
  **小屏不是 8051 驱动的**：`fwdis.py sfr` / `xdata` 全量枚举显示，主控实际用到的外设只有
  4 组 PWM bank（LED）、UART、USB 与 GPIO，**没有** LCD 控制器 / SPI / I2C，flash 里也没有
  字模或点阵数据（`0x0700-0x0BFF` 是 PWM/曲线查表）。串口细节：
  * 初始化 `0xB169`（`SBRTH=0xFF, SBRTL=0xFB, SFINE=0x0C, SCON=0x50`）；
    接收中断 `0x8EF2`（RI → `xdata[0x0ECE]=SBUF`）；发送 `0xA3FC` / `0xAF18`（`MOV SBUF,A`）。
  * 收包缓冲 `xdata 0x1130..0x1143`（≤20 B，`xdata 0x0F56` 为收包索引，
    上限 `0x14`），首字节须为 **`0x5A`**（`0xAF25`），`xdata[0x0F61]=1` 表示收齐；
    处理 `0xAF1B` → `0xB4FC`（只认 `xdata[0x1131]` = `0xAC`/`0xFE`，其余走 `0xB73C`）。
  * **发送原语** = "从 XDATA 通用指针发 N 字节"：`xdata 0x0F5C..0x0F5E` 是 3 字节**通用指针**
    `{memtype=1, hi, lo}`、`xdata 0x0F5F:0x0F60` 是待发字节数，`0xA3DB` 逐字节 `MOV SBUF,A`。
    （注意：`01 11 C1` 是**指针值**，不是帧头。）已知发送源：`xdata 0x11C1`
    （首字节 `0x50`，见 `0x9C09`；负载在 `0x11C4..`）、`xdata 0x0C2D+16*n`
    （见下）、`xdata 0x11E0`。`P4.1` 是链路唤醒/握手脚。
  * **主机 ↔ 模块经 8051 透传**：`xdata 0x0C2D+16*n`（队列深 5，每记录带 8 位补码校验和，
    校验例程 `0xB4CC`）这组消息记录**会被原样发到模块**（发送点 `0x689F`）。即 PC 端驱动
    把命令经 HID/EP0 交给 8051，8051 转发给模块；模块用 `0x5A` 开头的帧回状态。
  * 链路状态 `xdata[0x0F29]`：`1` = USB 有线，`0x25/0x35/0x45/0x55` = 2.4G / BT1 / BT2 / BT3
    （写于 `0x1283/0x128F/0x129B/0x12A7`）；`xdata[0x0B8E]` = 上一档，`xdata[0x0BA7]` = 切换标志。
    四档与 SMK 的 `bk3632/rf_controller.h`（`RF_MODE_2_4G/BT1/BT2/BT3`）完全对应，但帧格式不同
    （SMK 用 `0xAA` 魔数，本机收包首字节固定 `0x5A`；早期的「`01 11 xx` 帧头」说法已作废 ——
    `01 11 C1` 是一个 XDATA 通用指针的值，不是帧头），SMK 的 BK3632 驱动不能直接套用。
  * **对自制固件的影响**：屏幕、旋钮、无线都挂在这颗模块上。不实现这条私有串口协议，
    屏幕不会有主机侧内容，2.4G/BT 与旋钮也不可用。
* **矩阵扫描例程** @ `0x35E8` 跳转表（10 个入口，按 bank 分批扫 P6.0-P6.7 / P5.0-P5.2 / P5.7 /
  P4.0/P7.7/P4.5），扫描结果经 `0xB113` 写入 XDATA `0x0ECD`。
* **SFR 命名** 采用 SMK 逆向出的权威表（`tools/smk/src/sino51lib/sh68f90/sh68f90.h`），
  例如 `0x97=EP0CON`、`0x9B=IEP0CNT`、`0xE1-0xE7=P0CR..P6CR`、`0xB2=CLKCON`。

## 设备备份与「第二颗 SoC」的固件

* 2026-10-19 用 `sinowisp read`（只读，不擦不写）读出整片 64 KiB：
  * 键盘本体 `258a:019d` → `firmware/backups/YD-Y65S_full_20261019.bin`
    （MD5 `3F7EE6AE90E5568FE4B9E34CC71E2135`；连读两次逐字节一致，读路径确认无擦除）。
    与存档 `firmware/YD-Y65S_full.bin` 仅差 1 字节：`0xA44F` = 本体 `0x57` vs 存档 `0x05`，
    落在 `0xA400-0xA47F` 这段 128 B 数据表内（被 `0x7C97`/`0x7D00-0x7D2D`/`0xD021`/`0x78A9` 等引用）；
    两次读取稳定 ⇒ 是设备里的一个数据字节，不是读取噪声。
  * 2.4G 接收器 `258a:0150` → `firmware/backups/dongle_258a-0150_full_20261019.bin`
    （MD5 `38EFE2AA9E91B9A9B8A82C69E3C52DDB`）。它与模块是同一对 RF 伙伴，是目前**能拿到的最接近模块的固件样本**：
    64 KiB、Sinowealth 8051、复位向量 `LJMP 0x27DA`、含 UTF-16LE USB 字符串（`Gaming KB`），
    `0xF000` 起是同族 ISP bootloader（与该键盘的 bootloader 是不同构建）。
* **模块（第二颗 SoC）自己的固件目前读不出来**，原因均有证据：
  * Sinowealth 的 ISP bootloader **只走 USB**：反汇编 `firmware/YD-Y65S_bootloader.bin` 里
    对 `SBUF`/`SCON` 的引用为 **0**（`fwdis.py sfr` 也显示 `SBRTH`/`SADDR`/`SADEN` 未使用），
    因此无法把 ISP 命令经 8051 的 UART 转给模块。
  * 8051 ↔ 模块之间只有一条普通 EUART（`SBUF=0xAA`、`SCON=0xD8`；TX `0xAF18`/`0xA3FC`、RX `0x8EF5`），
    固件里**没有**任何「读模块 flash 并回传」的路径：主机命令通道（`xdata[0x0B91]` 起，见 [[firmware-layout]]）
    只有状态/通知类帧与 16 B 记录透传。
  * 结论：dump 模块固件只能在硬件层接线（模块的 ISP/SWD 焊盘 / 拆机）——用户无法拆机 ⇒ 目前受阻。
* **同族 ODM 的主机侧协议已有完整参考**（见 [[driveall-protocol]]）：driveall 前端（`build/odm/`）里
  命令号 80 = `SET_TFT_USER_ANIMATION`，payload = 256 B 延时表 + RGB565 小端像素流，
  505 B/包、包头 `AA cmd idx total 50 06`、等应答 `65`；屏幕尺寸来自机型 `tftConfig`
  （96×160 / 135×240 / 240×240 / 240×135）。该前端要求 usage page `0xFFE7`，
  而本机厂商通道是 `0xFF02`（`258a:019d`）⇒ 不能直接用，但可用于比对固件里的主机命令通道。

## 主机厂商通道（usage `0xff02` / HID report 9）

* 键盘 IF1 的厂商命令通道是 **col07 = `usagePage 0xff02` / `usage 0x0002`**：
  **Input report 9 = 7 字节**（总共 8 B），**Feature report 9 = 519 字节**（总共 520 B）。
  另有 col03 = `0xff02/0x0001`（4 B input，无 feature）。
* **IF1 里没有任何 Output report**（描述符：col01/02/03/04/07 是 input，col05/06/09 是 feature）
  ⇒ 主机只能用 `SetFeature`/`GetFeature`（EP0 控制传输）跟厂商固件讲话，driveall 那种 `sendReport` 前端
  从原理上就用不了本机。
* SETUP 包暂存区在 `xdata 0x1147..0x114E`：`0x1149` = wValue **低**字节（= **report ID**）、
  `0x114A` = wValue 高字节（`0x03` = Feature）、`0x114B/0x114C` = wIndex（`0x0001` = IF1）、
  `0x114D/0x114E` = wLength 低/高。`xdata[0x1150]` = EP0 状态（SETUP 时存 bRequest，多包传输中被改写成子状态）。
  描述符服务 `0x1575..0x1889` 就是按 `xdata[0x114A]`（描述符类型 1/2/3）选 flash 地址的 ⇒ 这个布局可反证。
* **EP0 OUT 数据缓冲 = `xdata 0x1100`，第 0 字节是 report ID**：ISP 入口即 `SetFeature(report 5)`，
  固件在 `0x82C7` 把指针设为 `0x1100` 后判 `xdata[0x1100]==0x05 && xdata[0x1101]==0x75` → `LJMP 0xB0ED`
  —— **这就是 sinowisp 进 ISP 的真实路径**。（旧记录里的 `xdata[0x0011]`/`[0x0012]` 是地址笔误。）
* `xdata[0x0F83:0x0F84]` 是**代码空间(flash)读指针**：`0xA78E` 从 flash 拷 8 B 到 `xdata[0x1108]` 再喂给 EP0；
  描述符服务（`0x1575..0x1889`）与 EP0 数据泵（`0x9771..0x97F8`）都用它 ⇒ 主机可经此通道读 flash。
* 实测（只读）：`get_feature(9)` 返回的是 **USB 描述符暂存区**内容 ⇒ feature 9 与描述符服务共用
  `xdata 0x1100` 起同一块内存（空闲时那里是描述符残留）；空闲 12 s 内 input report 9 无任何帧（不是周期上报）。
* 探测工具：`uv run tools/vendorhid.py list|desc|get|set|watch --vid 258a --pid 019d --page ff02 --usage 2`
  （纯 stdlib + ctypes；代码内硬性拒绝触碰 report 5/6 与键鼠集合）。

## 模块（屏幕 / 无线 SoC）链路：主机 → 模块 的内容管道

`0x50` / `0x5A` 帧的收发引擎（全线性反汇编，`build/fw_full.lst`）：

* 发送端是**带中断的分包发送**：帧缓冲 `xdata 0x11C1`；流描述符 `xdata[0x0F5C]` = 空间选择（1 = xdata）、
  `xdata[0x0F5D:0x0F5E]` = 数据指针、`xdata[0x0F5F:0x0F60]` = 剩余字节数。每发一字节（`0xA3D3`）
  指针 +1 / 计数 −1，UART TX 中断续发。UART 初始化在 `0xB15A..0xB187`：`SCON=0x50`、`SBRTH=0xFF`、
  `SBRTL=0xFB`、`SFINE=0x0C`、开 UART 中断（`IEN1` bit6）。
* 组帧 `0x9BF9`：`50 <cmd> <len> <payload...> <sum>`（`0xB607` = 8 位累加和）。
* **主控→模块命令全集**（`0x9BF9` 全部 12 个调用点 + `0xB204` 唯一的调用点）：

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

* **大块帧** = `50 81 <size_hi> <size_lo>` + 520 B：帧头写在 `xdata 0x08F1..0x08F4`，
  payload 缓冲 `xdata 0x08F5..0x0AFC`（恰好 520 B），`0xB204` 组好帧后一次性交给发送引擎。

**主机怎么把数据灌进这 520 B（这就是"屏幕内容上传"的那条管道）**：

1. 主机对 IF1 写 `SetFeature(report 9)`（`wLength=519`）⇒ 固件 `0x8363` 判 SETUP 字段：
   `wValue 低=9`（report ID）、`wValue 高=3`（Feature）、`wIndex 低=1`（IF1）⇒ 置 EP0 状态 `0x1150=0x0B`、
   偏移 `xdata[0x0B08:0x0B09]=0`、把**剩余长度 = wLength** 写入 `xdata[0x0B0A:0x0B0B]`。
2. 随后每个 **8 字节 EP0 OUT 包**（EP0 `mps=8`，见设备描述符）从 `xdata 0x1100` 起，
   由 `0x6CA2` → `0xA650` **追加到 `0x08F5 + 偏移`**，同时剩余长度 −8、偏移 +8。
3. 剩余长度归零即收尾（清 EP0 状态、`xdata[0x0F8A]=0`），再由模块链路状态机（timer 2 驱动）把整块以
   `50 81 02 08` + 520 B 发给模块。
   ⇒ **一次 519 B 的 feature 9 写入 ≈ 一个 520 B 的模块数据块，一一对应**，且**不需要改任何固件**。
   （细节待实测确认：EP0 缓冲第 0 字节是 report ID，所以 519 B 报告对应 520 B 块；偏移与尾巴多包的对齐
   目前按上面的解码成立，尚未实机验证。）
* 反方向：input report 9（7 B）是「模块 → 主机」的通知帧；`GetFeature(9)` 读的是同一块 EP0 暂存区。
* **模块固件既读不到也写不了**：模块命令集里没有任何擦除 / 写入 / 进 bootloader 的命令，唯一的批量通道就是
  上面这块 520 B 数据帧；8051 侧也不存在「读 flash 回传」的路径 ⇒ 想碰模块 flash 只能硬件接线。

### 主机记录协议（feature 9 写入后的分发器，2026-10-20 实测打通）

`SetFeature(report 9)` 传输收尾后，USB ISR（`0xA114`，向量 `0x0003`）尾调 `0x6346`：当 `xdata[0x0D85]==1`
（本次传输完成标志）时置 `xdata[0x0F8A]=5`，按 `xdata[0x08F6]` = **主机 payload[0]** 分发（合法 `0x03..0x0E`，
跳表 `0x6373`）。记录缓冲：`0x08F5`=report ID、`0x08F6`=payload[0]（命令）、`0x08F7`=payload[1]（子参数）、
`0x08FA`=payload[4]；每条记录按 8 B 处理。

| cmd | 处理 | 语义 |
|---|---|---|
| `0x03` | `0x63A3` 子分发 payload[1]=1..4 → `0x923E/0x92D8/0x8DB3/0x8D13` | 疑似键位/灯效配置写入，**可能写闪存，未触碰** |
| `0x04` | `0x7E5B` | **把 payload[7..134] 共 128 B 逐字节以模块帧 `50 52 01 <b> <sum>` 发给模块**（每字节等 `0x55` 应答，超时 ~48 ms）；且 payload[16]==1 时改写 payload[17]=0x13 |
| `0x05` | `0x8715` | **payload[4] 选模块命令号**（`cmd = payload[4]+0x6E`，合法 `0x6E..0x75`），随后把 **payload[7..518] 共 512 B** 逐字节以 `50 <cmd> 01 <b> <sum>` 发出（地址 = `0x08F5+8+counter`，循环上界 `counter_hi<2` ⇒ 恰好 512 次） |
| `0x06` | `0x6F1F` | 代码表 `0xAD7A` 126 B → `0x0D8A`，以模块 cmd `0x56` 分两轮发出；置 TFT 模式 `[0x0F2F]=0x5A` |
| `0x08` | `0x6B57` | 按记录字节索引 code 表 `0x0377`（0x12 步长、6 项），结果写入 xdata `0x0300+` 区；**无 IAP 调用 ⇒ 只改 RAM 配置表**，拔插即从 flash 恢复 |
| `0x0A` | `0x6DE2` | 模块 cmd `0x54`（同 128 B 窗口） |
| `0x0B` | `0x6474` | 置 `[0x0ED8]\|=1`（0x81 大块帧转发许可）、EP0 状态收尾 |
| `0x0C` | `0x644D` | 同 `0x0B` + `[0x0D86]=0x32` |
| `0x0D` | `0x641B` | **灯效模式=2、亮度=0**（`[0x0CA0]=2,[0x0CA1]=0,[0x0F64]=2`，仅 RAM） |

模块侧 ODM 协议层（`build/odm/layout-classic-Bylu1MNp.js`，2026-10-20 重新下载后逐字节复核）：
模块的**应答**是 ODM 风格（首字节 `0x55`），**请求侧**则不全是 ODM 包 —— 固件内置会话里 cmd 0x52 的
128 B 内容块首字节是 `00` 而不是 `0xAA`（尾字节 `5A A5`），所以模块有自己的「原生长度内容块」格式。
厂商前端的关键命令与包格式：

| ODM 命令 | 载荷 | 包头 |
|---|---|---|
| `SET_TEMPORARY_COMMAND_DATA=52 (0x34)` | 时间 10 B `5A 01 5A yy mm dd hh mi ss wd`（contentSize=24） | `AA 34 18 00 00 00 01 00` |
| `SET_TFT_BUILT_IN_INDEX=81 (0x51)` | 1 B 索引 | `AA 51 01 00 00 00 01 00` |
| `SET_TFT_USER_ANIMATION=80 (0x50)` | 256 B 延时表 + RGB565 小端像素 | `AA 50 <idx_lo> <idx_hi> <total_lo> <total_hi> 50 06` |

包头第 2 字节是**命令的 contentSize**（校时包写 `0x18`=24，而有效数据只有 10 B），第 6 字节是"最后一片"标志。
TFT 上传每包数据长度 = **设备报告长度 − 8**（厂商设备 4104 B/包）⇒ **对 YD-Y65S 必须按自己的窗口尺寸推**：
走 0x05 通道是 512 B 窗（504 B 数据），走 0x81 批量通道是 519 B（511 B 数据）。

### 固件内置的模块会话回放器（`0x0D11..0x10B1`）

厂商自己给模块下发的完整会话序列，是理解模块协议最硬的证据（主循环 `0x85AC` 在 `[0x0F17].0` 置位时执行）：

1. 把代码 `0x9983` 的 **128 B** 复制到 `xdata 0x08F5..0x0974`；
2. 依次发：cmd `0x52`（那 128 B）→ cmd `0x5E`/`0x5F` 各 1 B ×2 轮（代码表 `0x0C00`/`0x0C20`）→
   cmd `0x62`/`0x63` 各 1 B ×2 轮（`0x0C80`/`0x0CA0`）→ cmd `0x66`/`0x67`（无数据）→ cmd `0x6A`/`0x6B`（无数据）→
   cmd `0x6E..0x75` 各 1 次（无数据）→ cmd `0x54`（2 B，代码表 `0xAA00`）→ cmd `0x56`（126 B，代码表 `0xAD7A`）。

内置 128 B 内容表（`0x9983`）首字节是 `00`、尾字节 `5A A5`，中段是 `14 17` 重复 ⇒ **模块 cmd 0x52 的载荷
是原生长度内容块，不是 ODM 请求包**（只有应答侧是 ODM 风格的 `0x55` 头）。

### 实测效果（`build/probe/`，全部为 RAM/模块链路操作，无闪存写入）

1. cmd `0x04` + ODM 时间包（`AA 34 0A 00 00 00 01 00 | 5A 01 5A yy mm dd hh mi ss wd`）→
   当时观察到**屏幕时钟被重置为正确现实时间并连续走时**（10-20 00:01→00:02）；但随后多次注入的未来时间
   （2027-03-08 05:09、2099-06-15 23:10）均未显示，用户后来也确认**时钟其实从未被校准**（见第 7 条）——
   首次的"重置"只是模块进入屏幕会话状态的副作用。
2. cmd `0x0D`（灯效模式 2）+ cmd `0x0C` → **屏幕背景图片改变（显示人物图）** ⇒ 屏幕显示内容可由主机切换。
3. 副作用：一次短暂按键无响应（自行恢复）、一次背光熄灭。
4. cmd `0x04` 数据窗口（128 B，从 `payload[7]`）**确实生效**：转发 `0x9983` 处的固件内置窗口会让屏幕换页/重绘。
5. cmd `0x05` + `payload[4]=0`（模块 `0x6E` = `SET_TFT_USER_ANIMATION`）上传 135×240 测试图
   （256 B 帧头 + RGB565 小端 = 65056 B，130 块 × 512 B，块头 `AA 50 idx cnt 50 06`）：
   **130 块全部 `ok=True`、236 秒跑完（模块对每个字节都应答，否则每字节 48 ms 超时会慢一个数量级），
   但屏幕画面无任何变化**（仍是内置人像图）；随后 `payload[4]=1`（模块 `0x6F` 内置图索引）0/1 也无变化。
   ⇒ **数据送到了模块，但模块没有采用这次上传**；上传格式/会话前提仍未对。
6. 主机回包：任何有效记录约 0.55 s 后回一条 input report `09 0a 06 00 01 00 00 00`（`0x0D` 为
   `09 0a 06 01 00 00 00 00`，被忽略的 `0x07/0x09/0x0E` 不回）。该回包与模块是否接受数据**无关**
   （非法包头/非法子命令的载荷完全一致），只能当"记录已处理"的节拍用。
7. 屏幕时钟**从未被校时生效**：用户观察屏幕时间始终比真实时间差约 6 分钟 ⇒ 模块时钟是自由走时的，
   `Hu` 时间包未落地。
8. **2026-10-20 复盘（上传失败的两个候选原因）**：
   * **窗口内偏移**：所有记录的数据窗都从 `payload[7]` 起（`0x7E5B`/`0x8715` 都把 `[0x0EC7]=8` 加到记录基址）。
     上一轮校时实验把 ODM 包放在了 `payload[0]` ⇒ 整体右移 7 字节才发给模块，**包是错位的**。
   * **每包数据长度**：厂商 TFT 包 = 8 B 头 + N B 数据，N = 报告长度 − 8。我们走 0x05 通道 ⇒ N=504、total=130；
     若模块要的是 0x81 批量通道那种 N=511，则永远凑不满一帧，屏幕必然不变。
   * 次要嫌疑：屏幕真实分辨率（135×240 是从同族 YUNZII IF75 推的，固件里查不到）、模块是否要求先发一次
     `SET_TFT_BUILT_IN_INDEX`（厂商在 `builtInCount>1` 时会先发）。

### 实验矩阵：`tools/tft_probe.py`（2026-10-20 新增）

按"每一步都能被肉眼判定"排布的受控实验（只写 HID feature，不碰键盘闪存）：

```bash
uv run tools/tft_probe.py clock      # 4 种窗口布局的校时包 -> 哪个让屏幕时钟跳到目标时间
uv run tools/tft_probe.py native     # 复现固件内置 128 B 内容块 + 改写尾部像素
uv run tools/tft_probe.py builtin --index 0   # 内置图索引 (模块 cmd 0x6F)
uv run tools/tft_probe.py tft --path 05 --w 135 --h 240   # 0x05 通道上传 (504 B/包)
uv run tools/tft_probe.py tft --path 81 --w 135 --h 240   # 0x81 批量通道上传 (511 B/包)
uv run tools/tft_probe.py raw --cmd 04 --file payload.bin # 任意记录
```

`clock` 是**唯一能低成本判定"模块到底吃不吃 ODM 包"的实验**（顺带把窗口偏移钉死）；
`native` 是绕开 ODM、直接改模块原生内容块的后手。

### 「给屏幕 SoC 做自制固件、支持装应用」可行性判定（2026-10-19）

* **不可行**：给模组（第二颗 SoC）换自制固件。三条互相独立的硬阻碍：
  1. 固件**读不出**（软件通道不存在，见上）；
  2. 芯片**型号未知**（用户无法拆机）⇒ 没有 SDK / 工具链 / 引脚与显存接口定义；
  3. 就算写出来也**没有烧写通道**。
* **可行**：把"应用"跑在**主控 / PC 侧**，把模组当"显示 + 无线外设"来驱动。两条落地路线：
  * 路线 1（零刷写、风险最低）：**PC 端上位机**用 feature report 9 往 520 B 块管道里喂内容/命令。
    通道已解码，缺的只是"块内语义"。
  * 路线 2（真正的自制固件）：在 **SMK 移植的主控固件**里实现同一套链路（UART 帧引擎 + feature 9 接收 +
    `0x81` 转发），应用逻辑放主控/HID 侧。这是唯一可能实现的"自制固件 + 装应用"形态。
* **还差的一步**：520 B 块在模组端被当成什么（屏幕图像？灯效参数？字库？）。这需要一次受控写入探测
  （只写 HID feature，不碰 flash，最坏重插电即可恢复），建议在能看着屏幕的时候做。

## 自制固件路线

社区已有完整可用的开源固件 **SMK**（`karstx/smk`，SDCC 构建，含 SH68F90 HAL / USB 栈 / BK3632
无线支持），与本机同 PID 平台的 SuperFrame Phantom 已在 `sinowisp` 设备表中。移植工作量集中在：

1. ~~用厂商固件确定矩阵行列引脚与 LED 驱动方式（PWM bank 映射）。~~（已完成，见上）
2. ~~新建 `src/keyboards/yd-y65s/`（`kbdef.h` / `user_matrix.c` / `kb.c` / layout）。~~（已完成）
3. 保留 ISP 跳转与厂商 HID feature report，确保任何时候都能回到 bootloader。
4. ~~工具链：SDCC + meson + ninja + `sinowisp`。~~（已完成，Windows 下可用 scoop + uv）

### 移植现状（SMK）

* 板级目录 `src/keyboards/yd-y65s/`：`kbdef.h`、`user_matrix.c`、`user_init.c`、`kb.c`、
  `user_sleep.c`、`layouts/default/layout.c`、`meson.build`。`tools/sync-port.ps1` 把它镜像进
  `tools/smk/src/keyboards/yd-y65s`（SMK 本身不入库）。
* 键位表由 `analysis/gen_smk_layout.py` 直接从 dump 生成，四层按
  `_WIN_BL=0 / _MAC_BL=1 / _WIN_FL=2 / _MAC_FL=3` 排列；SMK 默认层 0 即 Windows 基础层。
  Fn 键对应 `MO(_WIN_FL)`，Mac 基础层对应 `MO(_MAC_FL)`。
* 尚缺：逐键 RGB 拓扑（走线未确定，`user_matrix_sinks_off` 目前为空）、无线模块、
  厂商 8 个 HID collection。Fn 层落成 `KC_NO` 的共 16 格：6 个 `0x07` 厂商动作 + 8 个 `0x08`
  LED 控制 + Fn+6（`00 A0 00 21`，RShift+RGui+4）+ Fn+O（consumer `0x018A`），均带原始字节注释。
  其中 `0x08` 的语义**已解码**（见上节），仍落 `KC_NO` 是因为 SMK 的灯效由自身 RGB 层管理，
  不属于键码映射；需要保留厂商灯效行为时可据此实现。
* USB 身份暂用 SMK 默认 `258a:dead`（板级 `options` 未覆盖），便于与厂商固件区分；
  需要沿用 `258A:019D` 时再改 `meson.build`。
* 构建（2026-10-19 验证）：SDCC 4.6.0 / meson 1.12.1 / ninja 1.13.2 / gcc 15.2.0 /
  sinowisp 2.1.0。CSEG ≈ 13.7 KiB + CONST ≈ 1.2 KiB，远小于 60 KiB 应用区；
  ISP 跳转桩 `75 F0 A5 74 5A 02 FF 00` 出现在 `0x2811`（`_isp_jump` @ `0x280F`）。
* SDCC 4.6 新增 error 357（code 空间指针必须为 const），SMK 需要两处 `const` 修正；
  `tools/patch-smk.ps1` 幂等地应用到 `tools/smk`。其他官方板（如 nuphy-air60）在 4.6 下仍有
  opt 错误，因此 `build-port.ps1` 只编译 `yd-y65s_default_smk.hex` 目标。
* **仿真验证通过（2026-10-19，WSL + 打过补丁的 uCsim 0.8.15）**：SMK 与板无关的 27 项测试
  （启动到主循环、USB 枚举、描述符分包、HID idle/protocol/LED、ISP 跳转握手、中断向量压栈、
  栈溢出）全部通过；`tests/test_y65s_sim.py` 另用 YD-Y65S 列线模型验证 4 个按键位置，
  期望值直接取自 dump（矩阵 → 扫描 → 键位 → HID 报告）。SMK 自带的 Air60 按键测试因板级
  接线不同被排除——同一个测试位置在本机解析为 HID `0x0F`（L）而不是 `0x04`（A）。
* 仍**未**向设备写入任何数据。

## 致谢

* [karstx/sinowisp](https://github.com/karstx/sinowisp) — ISP 读写工具（本仓库用官方 v2.1.0 Windows 版）
* [karstx/smk](https://github.com/karstx/smk) — Sinowealth 8051 开源键盘固件
* [carlossless.io](https://carlossless.io/nuphy-air60-part-1) — NuPhy Air60 逆向系列文章
