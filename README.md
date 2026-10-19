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
    （SMK 用 `0xAA` 魔数，本机是 `0x5A` + `01 11 xx`），SMK 的 BK3632 驱动不能直接套用。
  * **对自制固件的影响**：屏幕、旋钮、无线都挂在这颗模块上。不实现这条私有串口协议，
    屏幕不会有主机侧内容，2.4G/BT 与旋钮也不可用。
* **矩阵扫描例程** @ `0x35E8` 跳转表（10 个入口，按 bank 分批扫 P6.0-P6.7 / P5.0-P5.2 / P5.7 /
  P4.0/P7.7/P4.5），扫描结果经 `0xB113` 写入 XDATA `0x0ECD`。
* **SFR 命名** 采用 SMK 逆向出的权威表（`tools/smk/src/sino51lib/sh68f90/sh68f90.h`），
  例如 `0x97=EP0CON`、`0x9B=IEP0CNT`、`0xE1-0xE7=P0CR..P6CR`、`0xB2=CLKCON`。

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
