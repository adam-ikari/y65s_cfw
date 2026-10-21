---
id: no-write-policy
title: "写入禁令 (No-Write Policy)"
category: decision
status: active
created: "2026-10-19T16:46:16"
updated: "2026-10-21T05:56:53"
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

## 音量显示策略（2026-10-21 修订）

**没有我们的软件在跑时，屏幕上不要出现音量** —— 那个值本来就不准，显示出来只会误导。

* 成因：厂商 app 用 `IAudioEndpointVolume` 读 0.0~1.0 的系统音量、乘 **100.0** 下发；
  8051 **原样转发、零限幅**。
* 音量在固件里的完整链路（已逐条核对反汇编）：flash `0xA431`（profile 字段 `0x31`）
  → `0x7D00` 载入 `xdata[0x0F12]` → `0x5557` 拷贝进设置包 `xdata[0x0DBB]` →
  `0x5594`–`0x55CE` 按 cmd `0x52` 逐字节发 128 B 给屏幕 SoC。`xdata[0x0F12]` 全固件
  只有两处被读（载入 + 那次拷贝），`xdata[0x0DBB]` 只有一处被写 ⇒ **那次拷贝是音量的唯一出口**。
* 修法 = 固件补丁 `no-volume-send`：`0x5557` 的拷贝整个去掉（8 × NOP）⇒ **不发音量**，
  不塞哨兵值/假值。设置包定长 128 B，那个字节照样发，但启动时 `0x89EE` 清零 xdata
  `0x0000-0x0FFF` ⇒ 该值恒为 0，模块拿不到会变的音量。
* **旋钮不受影响**（2026-10-21 更正）：旋钮本来就在 **主控** 上（`0x2812` 采 P4.2/P0.7 正交解码），
  旋钮的 HID consumer 报告（`RAM 0x57` = `0xE9/0xEA`）与设置包这条链完全无关 ⇒ 去掉那次拷贝动不了旋钮。
* **但屏幕会跟着旋钮跳**：旋钮事件还会写 `xdata[0x0EE4]=0x81/0x82` 并经 cmd `0x15` 通知屏幕 SoC，
  屏幕据此画音量条。要彻底不画，需再打补丁 `no-volume-ods`（`0x059C`）：不写 `0x0EE4`、
  旋钮分支直接跳到 `0x05FA`（跳过 cmd `0x15` 发送），主机侧 consumer 报告照旧。
* **推帧路线已放弃**（整屏一帧 4 分钟，做不了任何动态内容）⇒ 音量没有别的显示途径。
* 变体 `no-volume-send-zero`（显式写 0）留在补丁表里，效果与不写一致（xdata 开机清零）。


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

- time: 2026-10-20T13:14:54
  kind: decision
  summary: "2026-10-20 事故机理（可复用的教训）：厂商记录 0x08 的处理器 0x6B57 会把主机窗口按 (col=[0x0EC2], row=[0x0EC1]) 拷进 xdata 0x0377 + col*18 + row*3 的 3 字节单元表（6 行），而固件会把相关位图表持久化到 flash 0xA800 起（那份区与代码表 0xAA00 图案相同，恢复前整片与 2026-10-19 备份差 457 B 就是它被改写）。因此：对真机发记录时，0x08/0x0A 这类会落到持久化配置上的记录最危险（全零记录就能把键配置写坏，症状是按键失效但 RGB/屏幕/USB 正常）；0x04/0x05 只走模块链路相对安全（但 0x81 大块帧不要塞 ODM 包，会把模块带进等待流数据状态）。任何真机实验后如出现异常，先读 flash 比对再决定动作。"
  source: "omp-host 真机 2026-10-20 + fw_full.lst 0x6B57 复核"
  affects: [no-write-policy, screen-customization]

- time: 2026-10-21T01:27:09
  kind: decision
  summary: "2026-10-21 重要区分：两个官方 app 的 profile 不能混用。Y95 版(Y95 Keyboard Setup 20240228) 的 Dev/kb/Screen/KB.ini: VID=258a PID=019D、siScreen=240,135、MaxScreenFrame=40、ShowScreen=1、RGBScreen=1 ⇒ 与本机屏幕几何一致(我们上传 240x135 纯红成功、用户目视确认)，【可以用它写设置】。K65 版(K65 Keyboard Setup 20241026) 的 Dev/kb/KB.ini: siScreen=135,240、MaxScreenFrame=80、另有 K65 专属键位 ⇒ 【是另一块屏/另一套键位，写进去会让屏幕几何与键位全错，危险】。两个 app 的 VID/PID 都是 258a:019d，app 自己分不清机型，只按自己 profile 写。固件升级按钮同理危险(按 profile 下发对应固件)，本机 YD-Y65S 只能靠 sinowisp 写回 firmware/backups/YD-Y65S_full_20261019.bin 这份 64 KiB dump(2026-10-20 已验证：写后整片读回与备份逐字节一致)。K65 版唯一有价值之处是它的【每秒对时循环】(SendTimeOnOpenKB=1)，而该循环走的是 HID 运行期命令(不写 flash)，所以只让它对时、不点保存/升级是安全的。"
  source: "K65/Y95 两个官方包对比 2026-10-21"
  affects: [no-write-policy, screen-customization, module-link]

- time: 2026-10-21T02:54:27
  kind: decision
  summary: "2026-10-21 用户定的音量策略：没有我们的软件在跑时，屏幕上不要显示音量（那个值本来就不准，显示只会误导）⇒ 做固件补丁 no-volume-display：8051 在 0x5557 把 profile 音量字段(0x31)转发进设置包(0x0DBB)的那次拷贝(90 0F 12 E0 90 0D BB F0)改成写常量 0xFF(90 0D BB 74 FF F0 00 00)，超出 0~100 量程 ⇒ SoC 显示不出音量条。补丁 expect 字节取自 firmware/YD-Y65S_full.bin 与 backups/YD-Y65S_full_20261019.bin(两处一致)，由单测 shipped_patches_match_the_dumps / shipped_patch_rewrites_only_the_volume_field 校验(20 项单测全绿)。需要显示音量时改由我们自己的推帧负责。"
  source: "2026-10-21 固件补丁设计"
  affects: [no-write-policy, custom-firmware-path, module-link]

- time: 2026-10-21T03:13:36
  kind: decision
  summary: "写入禁令不变；新增音量显示策略：不喂音量给模块（补丁 no-volume-send，去掉那次拷贝，不用哨兵值），并记录推帧路线已放弃"
  source: "2026-10-21 音量补丁修订 + 推帧路线放弃"
  affects: [no-write-policy]

- time: 2026-10-21T03:20:25
  kind: decision
  summary: "写入禁令不变；音量显示策略补全固件链路证据（唯一出口 0x5557、xdata 开机清零、旋钮链路独立）"
  source: "2026-10-21 反汇编逐条核对"
  affects: [no-write-policy]

- time: 2026-10-21T05:56:53
  kind: decision
  summary: "音量策略补充：旋钮在主控上，旋钮事件另有一条 cmd 0x15 通知屏幕的通道（0x0EE4=0x81/0x82），新增补丁 no-volume-ods 专门切断它"
  source: "2026-10-21 反汇编复核 0x0594/0x05E7"
  affects: [no-write-policy]
