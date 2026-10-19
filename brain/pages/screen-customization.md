---
id: screen-customization
title: "目标：自定义 Y65S 屏幕显示内容"
category: project
status: active
tags: [screen, uart, module, goal]
created: "2026-10-19T22:31:11"
updated: "2026-10-19T22:46:33"
---

<!-- compiled_truth -->
## 目标

用户的目标是**自定义 Y65S 小屏幕的显示内容**（不只是键盘固件 / 按键重映射）。这条需求重定义了整件事的性质：从“移植键盘固件”变成“打通屏幕这条链路”。

## 架构现实（已确认）

- 屏幕**不由主控 SH68F90A 驱动**：该芯片没有 LCD / SPI / I2C 外设（全 SFR/XSFR 枚举），也没有软件模拟的总线；只有 4 组 PWM、UART、USB、GPIO。flash 内没有字库 / 位图。
- 屏幕由**第二颗 SoC（无线 / 伴生模块）**驱动；主控与模块之间只有一条**私有 UART 链路**。
- 链路帧格式（部分已解码）：
  - 主控→模块：`50 <cmd> <len> <payload...> <chk>`；`chk` = `cmd+len+payload` 的 8 位累加和（组帧 `0x9BF9`，求和 `0xB607`）。帧缓冲 `xdata 0x11C1`。
  - 主控→模块第二条通道：`50 81 <len> ...`，payload 取自 `xdata 0x08F4/0x08F5` 缓冲区（该缓冲区此前被记为 LED 效果渲染缓冲，128 B）——**这是目前最有希望的“大块数据送给模块”的通道**。
  - 模块→主控：首字节 `0x5A`，≤20 B，缓冲 `xdata 0x1130..0x1143`；`xdata 0x0ECE` 保存最近一字节。
  - 已见主控→模块命令码：`02 03 04 08 0A 13 15 17 18 1A 1B`（payload 多为 1..14 B，取自 `xdata 0x0EE4`），另有 `81`（大 payload）。
- 主控同时是**透传桥**：PC 工具经 HID/EP0 注入的 16 字节带校验记录（`xdata 0x0C2D+16n`）会被转发给模块。

## 决定可行性的关键未知

1. **模块是否接受内容？**
   - (a) 模块自己生成全部 UI（连接中 / 时钟 / 动画 / 电量 / 音量）→ 想自定义只能改模块固件 ⇒ 需拆机 + 未知 ISP，目前不可行。
   - (b) 模块接受主控送来的内容 → 我们可直接驱动 ⇒ 可行，只缺协议。
   `81` 号命令 + 128 B payload 是判断 (b) 成立的主要线索。
2. **是否还留有厂家的 PC 上位机 / 驱动？** 若有，用 USBPcap 抓一次“修改屏幕设置”的 USB 报文即可**零风险**确定协议（甚至直接用厂家功能达成目的）。注意厂家已失联，但软件可能仍在下载站。
3. 用户希望显示什么：文字 / 静态图 / 动图 / 主机数据（音量、温度……）？这决定需要多大带宽的内容通道。

## 新线索（2026-10-19）：这类键盘的上位机普遍支持“屏幕传图”，且是**网页版**

检索发现同风格（小屏 + 旋钮 + 三模）键盘的厂家上位机生态：

- **YUNZII** 用网页驱动 `https://yunzii.driveall.cn/`（前端是 Vite 打包的 SPA，资源含 `tui-image-editor`⇒ 有图像编辑/上传功能）；同一平台 `driveall.cn` 还为其它品牌出 `cp.driveall.cn/logo/<brand>/…`、`config.driveall.cn/logo/<brand>/…`、`prod.driveall.cn`（HFD-HUB，含 “Add New Device”）。
- **狼蛛(AULA)**：`https://hea.aulacn.com/`（网页在线驱动，WebHID）。NOVA75/NOVA98 评测明确说：**可以把屏幕换成自己的 GIF**，且“屏幕设置只在**有线模式**下出现，2.4G 模式没有”，**最大 141 帧**。
- **Keydous**：NJ68 Pro 可上传 **1 个 GIF + 5 张静态图**，NJ98 可上传 **3 个 GIF + 5 张静态图**（“Select the layer when upload an image”）。
- **前行者(EWEADN)** E HUB：网页版/客户端，明确列出支持型号。
- 微博/新浪 2024 贴：“支持屏幕传图（静态或GIF），仅对带屏版有效”。

含义：

1. **屏幕内容是可上传的**（静态图 + GIF），上传通道就是主控 ↔ 模块这条链路（厂家上位机 → HID/EP0 → SH68F90A 透传记录 → 模块）。这印证了主控固件里看到的“16 字节带校验记录队列 + 转发”就是**图像上传的搬运通道**。
2. 这些网页驱动是 **JS**（WebHID），**协议就写在可下载的前端代码里** ⇒ 即使它不认我们的 VID/PID，我们也能**直接读出“屏幕传图”的报文格式**并在 PC 端复现（喂给 Y65S 的 8051 透传通道）。
3. Y65S 的模块极可能与狼蛛 NOVA75/NOVA98、Keydous NJ68 Pro 等**是同一块屏/同一方案**（1.14"/小彩屏 + 旋钮 + 三模），所以协议大概率通用。

这条线索把“可行性”从“未知”提高到“很可能可做，且不需要改设备固件”。

## 可行路径（按代价排序）

| 路径 | 需要什么 | 风险 |
|---|---|---|
| A. 厂家或同方案上位机改屏幕 | 找到能识别该键盘的 PC/网页驱动 | 无 |
| A2. **复用 ODM 网页驱动的“屏幕传图”协议** | 读同方案（狼蛛/YUNZII/Keydous）网页驱动 JS，抽出传图报文，用 PC 端工具喂给 Y65S 的透传通道 | 无（无需改固件） |
| B. 抓上位机 USB 报文、复刻协议 | 上位机 + USBPcap | 无 |
| C. 我方固件 + “PC→模块”透传桥 | 一次刷写（需逐次授权）；先补全协议 | 中（有 ISP 逃生口，可恢复） |
| D. 换模块固件 / 换屏自驱 | 拆机、焊接、鉴定模块与屏 | 高：用户明确无法拆机 |

## 约束

- [[no-write-policy]]：任何 flash 写 / 擦除都必须有用户逐次明确授权。
- 用户无法拆机（不能鉴定芯片），厂家已失联 —— 因此只能走“不接触硬件”的路线 A/B/C。


## Timeline

- time: 2026-10-19T22:31:11
  kind: decision
  summary: "Created this page: 目标：自定义 Y65S 屏幕显示内容"
  source: user request 2026-10-19
  affects: [screen-customization]

- time: 2026-10-19T22:31:26
  kind: decision
  summary: "新需求：自定义屏幕显示内容；记录架构约束、UART 帧格式与四条可行路径"
  source: "user request + firmware decode"
  affects: [screen-customization]

- time: 2026-10-19T22:33:35
  kind: decision
  summary: "新增关键线索：同类键盘上位机普遍支持屏幕传图(静态/GIF)且为网页驱动(WebHID)，协议可在前端 JS 中提取；新增路径 A2"
  source: "web search 2026-10-19 (yunzii.driveall.cn / hea.aulacn.com / Keydous / EWEADN)"
  affects: [screen-customization]

- time: 2026-10-19T22:46:33
  kind: evidence
  summary: "找到同代 ODM 的完整主机侧协议参考(见 [[driveall-protocol]]): SET_TFT_USER_ANIMATION=80 的 payload = 256 字节延时表(首字节帧数, delay*5)+RGB565 小端像素流, 505 字节/包, 头 AA cmd idx total 50 06, 等应答 65; 另有 SET_TFT_BUILT_IN_INDEX=81 与 OTA 命令 128-134。局限: 该协议走 usagePage 0xFFE7, 而 YD-Y65S 是 258a:019d/0xFF02 且不在其机型库"
  source: build/odm/layout-classic-Bylu1MNp.js
  affects: [screen-customization]
