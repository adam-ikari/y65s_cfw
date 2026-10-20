---
id: rea-firmware-lane
title: "REA 固件通道 (REA firmware lane)"
category: reference
status: active
tags: [rea, firmware, tooling]
created: "2026-10-20T07:39:14"
updated: "2026-10-20T07:39:22"
---

<!-- compiled_truth -->
## 安装与配置

* `rea-agents` **6.7.0**，通过 `npx -y rea-agents@6.7.0` 运行；MCP 已注册在
  `~/.config/opencode/opencode.json`（server 名 `rea`，命令 `npx -y rea-agents@6.7.0 mcp`）。
* skill 位于 `~/.agents/skills/reverse-engineer-anything`。
* 固件通道依赖调用方自带的两个工具：
  * Binwalk **3.1.0** → `/home/gem/.cargo/bin/binwalk`（`cargo install binwalk --locked`）
  * Unblob **26.6.4** → `/home/gem/.local/bin/unblob`（`uv tool install unblob`）
* REA 要求绝对路径环境变量：`REA_BINWALK_COMMAND`、`REA_UNBLOB_COMMAND`
  （以及 `/usr/bin/prlimit`）。当前 MCP 注册未写入这两个变量，因此固件扫描走
  CLI；MCP 只在没有这两个依赖的命令上可用。

## 能力边界

* 固件 lane 只做两件事：Binwalk 签名区间扫描、Unblob 容器解包。
* 裸 8051 镜像不能进入原生反编译通道：`open_binary` / `inspect_artifact`
  要求 ELF/PE/Mach-O，Y65S 的 raw dump 被 `unsupported binary format` 拒绝。
* 8051 语义分析仍用仓库自带 `analysis/fwdis.py`（精确 MCS-51 反汇编）。

## 实测结果（2026-10-20）

对 `YD-Y65S_full.bin`、`YD-Y65S_firmware.bin`、`YD-Y65S_bootloader.bin`、
`backups/dongle_258a-0150_full_20261019.bin`、`backups/YD-Y65S_full_20261019.bin`
逐份跑 REA：

* Binwalk 3.1.0：全部 `0` 区间 / `0` 签名。
* Unblob 26.6.4：全部 `coverage=complete`、`0` 文件、`0` chunk、`0` gap。
* 独立签名扫描（gzip/ELF/uImage/SquashFS/JFFS2/CramFS/LZMA/XZ/ZIP/7z/RAR/DTB/ext/USTAR）同样 0 命中。

结论是**有界否定**：在这些工具的签名集合与默认 skip 规则下没有容器，
不等于镜像中不存在自定义压缩/加密数据。

## 备注

* 4 KiB bootloader 首次扫描出现过一次 `unreadable_output`，重跑即正常返回
  0 区间；属于小文件解析偶发问题，不要当成隐藏内容的证据。
* 证据记录：full `ev_036421407f192c4624578b9b790665376f2b6b77c8bbfe179840e1c912a90faa`，
  app `ev_99ad16655e1438a694226b451c18d47270851429ac55ef5a7fc2a0d573a1fbe9`，
  bootloader `ev_51b0e5d46103d8b2cf6f0a3e1cd261b13876d35d99954540fb62f02ef257484a`，
  dongle `ev_f94f905adec72e7ab5a626d198e00ec6d0d39129ea06af9e6a3a8340ff80680b`。


## Timeline

- time: 2026-10-20T07:39:14
  kind: decision
  summary: "Created this page: REA 固件通道 (REA firmware lane)"
  source: REA 6.7.0 session 2026-10-20
  affects: [rea-firmware-lane]

- time: 2026-10-20T07:39:22
  kind: decision
  summary: "REA 固件通道可用: binwalk/unblob 对 Y65S 全部镜像 0 区间/0 容器; 原生通道不接受裸 8051"
  source: "2026-10-20 REA 6.7.0 实测"
  affects: [rea-firmware-lane]
