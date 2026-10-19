---
slug: background
title: Project background
role: project background
updated: "2026-10-19T16:45:17"
---

# Project background

## Why

YD-Y65S 是一把 USB 有线机械键盘（65% 配列，`258A:019D`），主控是 **Sinowealth SH68F90/A**
（8051 内核，64 KiB flash，其中 4 KiB 为 ISP bootloader）。厂商固件闭源、无公开 SDK，
用户希望：

1. 把固件**完整提取**出来（只读 dump）；
2. 把固件**解析清楚**——结构、协议、键位映射、外设用法；
3. 调查**自制固件**（自定义/开源固件）的可行路径。

## Goals

* 拿到可校验的完整 64 KiB flash dump，并拆成应用区 + bootloader。
* 建立一套可复用的分析工具链（反汇编、SFR 交叉引用、USB 描述符解析），
  能持续迭代而不是一次性脚本。
* 说清 ISP 协议、USB 描述符、矩阵扫描与键位表的位置与格式。
* 给出一条**可落地且可回滚**的自制固件路线（含风险与所需硬件）。

## Non-goals

* 不在未获明确许可前对键盘做任何写入/擦除。
* 不追求完整还原厂商固件源码级语义（只到移植自制固件所需的信息为止）。
* 不破解无线（2.4G/BT）私有协议——本机为单模 USB。

## Target user

键盘固件玩家 / 嵌入式逆向工程师：想在 Sinowealth 8051 键盘上跑自己的固件，
但需要先有一份可信的原始 dump 和一份说得清硬件连接的硬件档案。
