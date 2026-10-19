---
id: isp-protocol
title: "\""
category: reference
status: active
created: "2026-10-19T16:46:15"
updated: "2026-10-19T16:46:29"
---

<!-- compiled_truth -->
Sinowealth SH68F9x 的 ISP bootloader 通过 **USB HID feature report** 通信，本机（YD-Y65S）的实现与
`sinowisp` 源码一致，已在实机上只读验证。

## 设备侧入口

* 应用模式下，USB 复合设备的 **interface 1** 暴露多个 vendor collection：
  * report id **5** — 命令通道，5 字节 feature report（`usage_page 0xFF00`）；
  * report id **6** — 数据通道，2048 字节页（`usage_page 0xFF00`）。
* 进入 ISP：向 report 5 发送 `[05 75 00 00 00 00]`。设备随后**重枚举**为
  `0603:1020` / `0603:1021`（product string "Gaming KB"）。
* 固件中对应的分发点在 `0x82EA`：EP0 OUT 收到 `05 75` 后 `LJMP 0xB0ED`，即：

  ```
  B0ED: C2 AF        CLR IEN0.7
  B0EF: 75 F0 A5     MOV B,#0A5h
  B0F2: 74 5A        MOV A,#5Ah
  B0F4: 02 FF 00     LJMP 0FF00h
  ```

  这与 SMK 的 `isp_jump()` 逐字节一致 —— 说明 `A5/5A` + `LJMP 0xFF00` 就是该芯片的
  bootloader 入口约定。

## bootloader 侧命令

| 命令 | 含义 |
|---|---|
| `0x55` | 启用 flash 访问 |
| `0x52` + addr | 初始化读，随后用 get_feature(report 6) 反复取 2048 B 页 |
| `0x45` | 擦除 |
| `0x57` | 初始化写 |
| `0x77` | 写页 |
| `0x5a` | 重启（退出 ISP，回到应用模式） |

读操作的副作用：若 `flash[0xEFFB] != 0x02`，bootloader 会补写一个 `LJMP` 操作码。
正常设备该字节本就存在，因此读是安全的。

## 读语义的坑

ISP 读回的 payload 中 `0x0001-0x0002` 实际来自 `flash[0xEFFC-0xEFFD]`（应用 reset vector 被
重定位），`flash[0xEFFB] = 0x02` 表示"固件已启用"。分析 64 KiB dump 时必须按此理解
`0x0000` 处的 `LJMP 0x89D7`。

## 实测记录

* `sinowisp.exe read -d superframe-phantom -s full` → 65536 字节，MD5 `c94234578ba69c566576b6e2569dbb34`。
* 退出 ISP 后键盘正常重枚举为 `258A:019D`，无 `0603` 残留。
* 进入 ISP 期间键盘会断开约 2 秒以上，属正常现象。


## Timeline

- time: 2026-10-19T16:46:15
  kind: decision
  summary: "Created this page: \""
  source: created via brain create-page
  affects: [isp-protocol]

- time: 2026-10-19T16:46:29
  kind: decision
  summary: "\""
  source: brain update-truth
  affects: [isp-protocol]
