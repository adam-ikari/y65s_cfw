---
id: isp-protocol
title: "ISP 协议 (ISP Protocol)"
category: reference
status: active
created: "2026-10-19T16:46:15"
updated: "2026-10-21T05:38:17"
---

<!-- compiled_truth -->
Sinowealth SH68F9x 的 ISP bootloader 通过 **USB HID feature report** 通信，本机（YD-Y65S）的实现与
`sinowisp` 源码一致，已在实机上只读与读写验证。

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
| `0x55` | 启用 flash 访问；**写完之后必须再发一次**，它负责"使能固件" |
| `0x52` + addr | 初始化读，随后用 get_feature(report 6) 反复取 2048 B 页 |
| `0x45` | 擦除 |
| `0x57` | 初始化写 |
| `0x77` | 写页 |
| `0x5a` | 重启（退出 ISP，回到应用模式） |

读操作的副作用：若 `flash[0xEFFB] != 0x02`，bootloader 会补写一个 `LJMP` 操作码。
正常设备该字节本就存在，因此读是安全的 —— 这条自愈也是 2026-10-21 事故后键盘自己恢复的原因。

## 读语义的坑

ISP 读回的 payload 中 `0x0001-0x0002` 实际来自 `flash[0xEFFC-0xEFFD]`（应用 reset vector 被
重定位），`flash[0xEFFB] = 0x02` 表示"固件已启用"。分析 64 KiB dump 时必须按此理解
`0x0000` 处的 `LJMP 0x89D7`。

读回的 payload 里 `0xEFFB-0xEFFE` 是**空的**（真机读回与出厂 dump 一致：那里是 `00 00 00`），
所以 dump 本身就可以直接当"写回用的 payload"用。

## 写语义的坑（2026-10-21 实机踩坑，键盘开不了机）

写页时 bootloader 自己搬向量，**不是** 1:1 写：

* payload 的第 0 字节起 3 字节（`0x0000-0x0002`）**不落到** `flash[0x0000]`；
* payload 的 `0x0001-0x0002` 被 bootloader 写到 `flash[0xEFFC-0xEFFD]`（规范副本）；
* `flash[0x0000]` 处的 `LJMP` 由 **`0x55` enable_firmware** 在写完之后根据
  `flash[0xEFFC-0xEFFD]` 现造，并置 `flash[0xEFFB] = 0x02`。

⇒ **`0x55` 必须在写页之后发**。若先 enable 再擦再写，擦除会把 `flash[0x0000]` 的 LJMP 和
`0xEFFB` 标记清掉，而写页又不会重建 `0x0000`，键盘就**开不了机**（现象：反复枚举成
`0603:1020`，`258a:019d` 不出现）。

`sinowisp` 的 `write_cycle` 就是这个顺序（erase → write → 读回校验 → **enable** → reboot），
并且写之前先把 `firmware[1..3]` 拷到 `firmware[0xEFFC..0xEFFE]`（规范副本），
读回校验前再把本地那份清零（因为读回来时那一段是空的）。

## 实测记录

* `sinowisp.exe read -d superframe-phantom -s full` → 65536 字节，MD5 `c94234578ba69c566576b6e2569dbb34`。
* 退出 ISP 后键盘正常重枚举为 `258A:019D`，无 `0603` 残留。
* 进入 ISP 期间键盘会断开约 2 秒以上，属正常现象。
* 2026-10-21 用 `tools/isp_flash.py`（自写，等价 sinowisp）刷回出厂固件：
  erase → write 61440 B → **enable** → reboot → 读回校验 MD5 `c94234578ba69c566576b6e2569dbb34`
  **与出厂 dump 逐字节一致**，键盘正常回到 `258a:019d` 并能应答 feature report 9（520 B 设备信息）。


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

- time: 2026-10-20T12:05:14
  kind: evidence
  summary: "2026-10-20 真机事故后远程软重启成功（不写 flash）：向 258a:019d 的 0xff00/0x0001、FeatureReportByteLength=6 的集合发 SetFeature(report 5, 05 75 00 00 00 00) 即进 ISP，设备重枚举为 0603:1020 'Gaming KB '（集合 0xff00/0x0001：feat=6 命令通道 + feat=2050 页通道）；再向同一集合发 SetFeature(report 5, 05 5a 00 00 00 00) 即回应用，设备重枚举回 258A:019D。细节：进入 ISP 的那次 HidD_SetFeature 返回 FALSE（设备在传输中跳走，传输被打断），'失败' 反而是成功的信号；退出 ISP 同理也是返回 FALSE。应用模式下 258a:019d 的两个 0xff00 集合是 feat=6（report 5 命令）与 feat=1032（report 6 页），别发错集合。"
  source: "omp-host 真机 2026-10-20 + 固件 0x8363/0x82DC 复核"
  affects: [isp-protocol, screen-customization]

- time: 2026-10-21T05:38:11
  kind: decision
  summary: "补上 ISP 写侧的重定位与 enable 顺序（写页后必须再发 0x55），并记录 2026-10-21 刷机开不了机的根因与恢复"
  source: "omp-host 真机 2026-10-21 + karstx/sinowisp 源码复核 (src/flasher.rs write_cycle / src/isp_device.rs write_page)"
  affects: [isp-protocol]

- time: 2026-10-21T05:38:17
  kind: evidence
  summary: "2026-10-21 真机事故与恢复：自写 tools/isp_flash.py 刷回出厂固件时按 0x55(enable)→0x45(erase)→0x57/0x77(write)→0x5a(reboot) 的错误顺序执行，erase 清掉 flash[0x0000] 的 LJMP 与 flash[0xEFFB] 标记，写页又不重建 0x0000（bootloader 只把 payload[1..2] 搬到 flash[0xEFFC]），键盘随即开不了机：设备反复枚举为 0603:1020，258a:019d 不出现。恢复办法：按 sinowisp 的顺序重刷（erase→write→read-back 校验→0x55 enable→reboot），payload 写前把 [1..3] 拷到 [0xEFFC..0xEFFE]，读回 MD5 c94234578ba69c566576b6e2569dbb34 与出厂 dump 逐字节一致，键盘回到 258a:019d 并能应答 feature report 9。"
  source: "omp-host 真机 2026-10-21"
  affects: [isp-protocol, no-write-policy, custom-firmware-path]
