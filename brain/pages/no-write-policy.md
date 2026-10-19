---
id: no-write-policy
title: "写入禁令 (No-Write Policy)"
category: decision
status: active
created: "2026-10-19T16:46:16"
updated: "2026-10-19T16:47:21"
---

<!-- compiled_truth -->
## 规则

**在用户明确许可之前，绝不对键盘执行任何 flash 写入/擦除操作。**

这条规则覆盖所有工具与路径，包括但不限于：

* `sinowisp write` / `sinowisp flash` / `sinowisp erase`
* SMK 的 `*_flash` meson 目标（内部会调用 `sinowisp` 写入）
* 任何自写脚本对 HID report 5/6 发送 `0x45`（erase）/`0x57`（init write）/`0x77`（write page）

## 允许的操作

* `sinowisp read`（提取固件）—— 用户已明确要求，无需再确认。
* 一切离线分析：反汇编、结构解析、描述符解析、熵/字符串统计。
* 编译自制固件、生成 `.hex`（产物落盘不算写入设备）。

## 为什么

* 键盘是用户正在使用的设备，写坏后需要拆壳 + 硬件编程器才能恢复。
* ISP 读本身是安全的（唯一的副作用是 `flash[0xEFFB]` 的 `0x02` 标记，
  正常设备已存在），而写在任何一步中断都可能留下半擦除的 flash。
* 这条规则是**用户提出的硬约束**，不是技术判断，因此不因"技术上可行"而放宽。

## 解除条件

只有用户以明确措辞（例如"可以写入"/"烧录吧"）授权后，才可执行写入；
授权应针对**具体的一次操作**，而不是一次性永久放行。


## Timeline

- time: 2026-10-19T16:46:16
  kind: decision
  summary: "Created this page: \""
  source: created via brain create-page
  affects: [no-write-policy]

- time: 2026-10-19T16:47:21
  kind: decision
  summary: "\""
  source: brain update-truth
  affects: [no-write-policy]
