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
  mcs51.py     精确 MCS-51 反汇编器 + Intel HEX 读写
  fwdis.py     CLI：info / dis / xref / sfr / xdata / ports / strings / find
  usbdesc.py   USB 设备/配置/字符串/HID 报告描述符解析器
  tools/       早期 JS 原型（已被 Python 版取代，留作参考）
tools/       第三方工具（不纳入版本库，见 tools/fetch-tools.ps1）
build/       生成的清单/报告（不纳入版本库）
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
```

## 已确认的关键事实

* **ISP 协议**：向 IF1 report 5 发送 feature report `[05 75 00 00 00 00]` → 设备重枚举为
  `0603:1020`/`0603:1021`。读 = `0x55` / `0x52`+addr / get_feature(report 6, 2048 B 页) / `0x5a`。
* **固件内 ISP 跳转桩** @ `0xB0EF`：`CLR IEN0.7` / `MOV B,#A5` / `MOV A,#5A` / `LJMP 0FF00h`
  —— 与 SMK 的 `isp_jump()` 完全一致。这是自制固件**必须保留**的逃生通道。
* **ISP 命令分发** @ `0x82EA`：EP0 OUT 收到 `05 75` 后跳到上述跳转桩。
* **USB 描述符** 原样存在于固件中：设备描述符 @ `0x4699`，IF0 报告描述符 @ `0x4526`（67 B），
  IF1 报告描述符 @ `0x4569`（304 B）。字符串：`YD-Y65S` / `SINO WEALTH` / `0001` / `BY Tech`。
* **键位/矩阵表** 位于 `0xBC00-0xCC00`（低熵区），4 字节一条记录，按列优先排列，
  内容形如 `00 00 00 29`(Esc)、`00 00 00 2B`(Tab)、`00 00 00 39`(Caps)、`00 02 00 00`(修饰位)。
* **矩阵扫描例程** @ `0x35E8` 跳转表（10 个入口，按 bank 分批扫 P6.0-P6.7 / P5.0-P5.1 /
  P4.0/P4.5 / P7.7），扫描结果经 `0xB113` 写入 XDATA `0x0ECD`。
* **SFR 命名** 采用 SMK 逆向出的权威表（`tools/smk/src/sino51lib/sh68f90/sh68f90.h`），
  例如 `0x97=EP0CON`、`0x9B=IEP0CNT`、`0xE1-0xE7=P0CR..P6CR`、`0xB2=CLKCON`。

## 自制固件路线

社区已有完整可用的开源固件 **SMK**（`karstx/smk`，SDCC 构建，含 SH68F90 HAL / USB 栈 / BK3632
无线支持），与本机同 PID 平台的 SuperFrame Phantom 已在 `sinowisp` 设备表中。移植工作量集中在：

1. 用厂商固件确定矩阵行列引脚与 LED 驱动方式（PWM bank 映射）。
2. 新建 `src/keyboards/yd-y65s/`（`kbdef.h` / `user_matrix.c` / `kb.c` / layout）。
3. 保留 ISP 跳转与厂商 HID feature report，确保任何时候都能回到 bootloader。
4. 工具链：SDCC + meson + ninja + `sinowisp`（Windows 下需自行准备，SMK 官方走 Nix）。

## 致谢

* [karstx/sinowisp](https://github.com/karstx/sinowisp) — ISP 读写工具（本仓库用官方 v2.1.0 Windows 版）
* [karstx/smk](https://github.com/karstx/smk) — Sinowealth 8051 开源键盘固件
* [carlossless.io](https://carlossless.io/nuphy-air60-part-1) — NuPhy Air60 逆向系列文章
