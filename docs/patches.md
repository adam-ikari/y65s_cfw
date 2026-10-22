---
title: 补丁说明
---

# 补丁说明

自制固件 = **原厂固件 + 补丁**。不改写整套固件，只做字节级补丁：每条带 `expect`
（必须匹配的原字节），对不上就**拒绝打**。

| 补丁 | 地址 | 字节 | 作用 |
|---|---|---|---|
| `no-volume-send` | `0x5557` | 8 | 去掉 8051 把 profile 音量字节拷进「发给屏幕的设置包」那一次拷贝 |
| `no-volume-ods` | `0x059C` | 40 | 旋钮不再写 `xdata[0x0EE4]=0x81/0x82`、不再发 cmd `0x15` |

两条一共 **22 字节**。`no-volume-ods` 保留 `RAM 0x57` 的 HID consumer 用量
`0xE9`/`0xEA`，所以**主机侧音量照常增减**。

音量在固件里的唯一出口就是 `0x5557` 那次拷贝：profile 字段 `0x31`（flash `0xA431`）
→ `xdata[0x0F12]` → 拷进设置包 `xdata[0x0DBB]` → cmd `0x52` 发 128 B 给屏幕 SoC。
去掉它，屏幕就拿不到会变的音量。

补丁表在 `tool/crates/core/src/patch.rs`，有单测盯着：每条 `expect` 必须逐字节对得上
仓库里的出厂 dump；应用后除自己那几十字节外一个字节都不能变。

## 写入顺序

`erase → 写页 → enable(0x55) → 重启`。`enable` 必须排在所有写页之后 —— bootloader
用它存在 `0xEFFC` 的复位向量重建 `0x0000` 的跳转指令，顺序反了键盘就开不了机。
顺序集中在 `tool/crates/core/src/isp.rs` 的 `write_plan()`，也有单测盯着。
