---
id: screen-customization
title: "目标：自定义 Y65S 屏幕显示内容"
category: project
status: active
tags: [screen, uart, module, goal]
created: "2026-10-19T22:31:11"
updated: "2026-10-20T16:10:12"
---

<!-- compiled_truth -->
用户的目标是**自定义 Y65S 小屏幕的显示内容**（不只是键盘固件 / 按键重映射）。这条需求重定义了整件事的性质：从“移植键盘固件”变成“打通屏幕这条链路”。

## 架构现实（已确认）

- 屏幕**不由主控 SH68F90A 驱动**：该芯片没有 LCD / SPI / I2C 外设，只有 4 组 PWM、UART、USB、GPIO；flash 内没有字库 / 位图。
- 屏幕由**第二颗 SoC（无线 / 伴生模块）**驱动；主控与模块之间只有一条**私有 UART 链路**（帧格式见 [[module-link]]）。
- 主控同时是**透传桥**：PC 工具经 HID/EP0 注入的 519 B 记录会被转发给模块：
  - 记录 0x04 → 模块 cmd 0x52，转发 128 B 窗口（payload[7..134]）
  - 记录 0x05 → 模块 cmd 0x6E+sub，转发 512 B 窗口（payload[7..518]）
  - 记录 0x0B/0x0C/0x0D → 模块 cmd 0x81，整块 520 B 一次转发
- 模块的**应答**是 ODM 风格（首字节 0x55），但它的**请求载荷是原生长度内容块**
  （固件内置会话里 cmd 0x52 的 128 B 首字节是 00 而不是 ODM 的 AA）⇒
  “模块完全就是 ODM 设备”只是**部分成立**，别把 ODM 前端整套照搬。

## 已实测成立的结论

1. **主机 → 屏幕的通路是通的**：记录 0x0D/0x0C 会让屏幕换背景图；记录 0x04 的 128 B 窗口能让屏幕切页/重绘
   （同时会关掉键盘 RGB，副作用）；固件内置会话里的 128 B 内容表原样发出去能复现开机画面。
2. **校时从未成功**：屏幕时钟一直是模块自己走时的（用户观察：约差 6 分钟）。
3. **135×240 自定义图上传失败**（2026-10-20 实测）：按 ODM `SET_TFT_USER_ANIMATION` 逐字节复刻厂商格式，
   256 B 延时表 + RGB565 小端像素，130 个 512 B 块（8 B 包头 `AA 50 idx total 50 06` + 504 B 数据），
   全部写入成功且模块逐字节应答，但屏幕毫无变化。

## 失败原因分析（2026-10-20）

- **帧格式本身已核对无误**：2026-10-20 重新下载厂商前端（`build/odm/`）逐字节复核了 `xn/mt/nu/zu/Hu/Gu`：
  包头、延时表、RGB565 小端、分包计数、应答 cmd 全部与我们的实现一致（见 [[driveall-protocol]]）。
- **剩下的两个未定量**（都可能单独致命）：
  1. **每包数据长度**：ODM 的「每包 = 设备报告长度 − 8」是按设备定的。我们走 0x05 通道 ⇒ 每包 504 B 数据、
     total=130；若模块要的是 0x81 通道那种 511 B（519 − 8）⇒ 永远凑不满一帧，屏幕必然不变。
  2. **窗口内偏移**：所有记录的数据窗都从 `payload[7]` 起。上一轮校时实验把 ODM 包放在了 `payload[0]`，
     等于整体右移 7 字节再发给模块 ⇒ 模块收到的是错位的包，**校时失败很可能就是这个**。
- 还有两处次要嫌疑：屏幕真实分辨率（135×240 是从同族 YUNZII IF75 推的，固件里查不到该屏尺寸）、
  以及模块是否要求先发一次 `SET_TFT_BUILT_IN_INDEX`（厂商在 `builtInCount>1` 时会先发）。

## 下一步：实验矩阵（`tools/tft_probe.py`，2026-10-20 新增）

按“每步都能被肉眼判定”的原则排布，一次跑完只要几分钟：

| 命令 | 变量 | 判定 |
|---|---|---|
| `tft_probe.py clock` | 4 种窗口布局（ODM 包头 len=0x18/0x0A 在 payload[7]、裸载荷在 payload[7]、ODM 包在 payload[0]） | 屏幕时钟跳到目标时间 ⇒ 找到正确布局 |
| `tft_probe.py native` | 固件内置 128 B 内容表原样 / 尾部像素改红 / 改蓝 / 清零 | 画面随改随变 ⇒ 128 B 原生内容块就是可自定义通道 |
| `tft_probe.py tft --path 05` | 512 B 窗（504 B 数据） | 已知失败，作为对照 |
| `tft_probe.py tft --path 81` | 0x81 批量通道（511 B 数据） | 新假设 |
| `tft_probe.py builtin --index N` | 内置图索引（0x6F）两条通道 | 屏幕换图 ⇒ cmd 0x6F 语义确认 |

`clock` 这一步最关键：它是**唯一能判定“模块到底吃不吃 ODM 包”的低成本实验**，
而且顺带就把“窗口偏移”这件事钉死。`native` 是绕开 ODM、直接改模块原生内容块的后手。

## 约束

- [[no-write-policy]]：任何 flash 写 / 擦除都必须有用户逐次明确授权。
- 用户无法拆机（不能鉴定芯片），厂家已失联 ⇒ 只能走“不接触硬件”的路线。


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

- time: 2026-10-19T23:09:46
  kind: decision
  summary: "在原有内容后追加『可行性判定(2026-10-19)』：给模组换自制固件不可行(读不到/型号未知/无烧写通道)；可行的是把应用跑在主控/PC 侧，走 feature 9 -> 520B -> 模块 的内容管道；下一步需实测 520B 块语义"
  source: "build/fw_full.lst + README 模块链路节"
  affects: [screen-customization]

- time: 2026-10-20T00:20:18
  kind: evidence
  summary: "实测打通主机→屏幕内容通路: feature9 记录 cmd 0x04 可注入 ODM 包(时间包触发屏幕时钟重置为正确现实时间), cmd 0x0D/0x0C(灯效模式2)实测切换了屏幕背景(显示人物图). 下一步: ODM SET_TFT_BUILT_IN_INDEX(81)/SET_TFT_USER_ANIMATION(80)"
  source: "build/probe/payload_rec04_time.bin, payload_rec04_t2/t3.bin, payload_cmd0d/0c.bin; fw_full.lst 0x6346-0x6495"
  affects: [screen-customization]

- time: 2026-10-20T00:57:45
  kind: decision
  summary: "决定: 官方厂商工具不可用(网页版走 output report,本键盘无 output report; Windows 驱动无法获取),改用自研 GUI 工具 tools/y65s_tool.py 作为厂商工具替代品"
  source: "build/odm/layout-classic-Bylu1MNp.js mt()/sendReport; tools/vendorhid.py"
  affects: [screen-customization]

- time: 2026-10-20T01:35:10
  kind: evidence
  summary: "内容窗口帧格式实测确认(默认窗口转发→屏幕+RGB均有反应). 解码出固件内置默认内容表(@0x9983 128B: 开头 00 03 03 00 00 00 13 04 0b 00 0b 20 01, 从0x999B起有一段重复的 14 17 字节串=疑似颜色/图案数据, 位尾 5a a5). 下一步: 修改表内容做自定义呈现"
  source: "firmware/backups/YD-Y65S_full_20261019.bin 0x9983; payload_rec04_replay_w1.bin 实测"
  affects: [screen-customization]

- time: 2026-10-20T01:52:19
  kind: decision
  summary: "用户明确授权(2026-10-20)向模块用户动画区(模块flash 0x650000, 非主固件)写入测试图, 分辨率按屏幕长宽比 9:16 取 135x240. 内置图仍可通过 记录0x05 payload[4]=1 payload[7]=0 切回. 上传脚本 build/tft_upload.py"
  source: "用户问答: 授权先传测试图 / 约9:16 -> 135x240"
  affects: [screen-customization]

- time: 2026-10-20T07:10:15
  kind: note
  summary: "用户裁决(2026-10-20): 测试图没写进去, 本轮上传方向按失败记录, 先归档尝试链路再继续. 已知唯一对屏幕有可见效果的主机命令仍是 记录0x04 (0x52 通道, 会让模块切页/重绘), 记录0x05 的 0x6E 上传通道无视觉反馈."
  source: "用户: 没有写进去, 记录尝试提交推送"
  affects: [screen-customization]

- time: 2026-10-20T07:34:44
  kind: evidence
  summary: "用户补充观察(2026-10-20): 屏幕上的时间从来没准过, 大约比真实时间早/晚 6 分钟左右 —— 说明屏幕时钟是模块自己自由走时的, 我们发送的 Hu 时间包(记录0x04 + 5A 01 5A yy mm dd hh mi ss wd) 从未真正落地. 结合上传测试同样无效, 结论: 记录0x04 能让模块切页/重绘, 但载荷语义尚未被模块采用; 校时与自定义图两条路都还差最后一层(很可能是 ODM 包头的 size/addr 字段或每包会话前提)."
  source: "用户口述: 时间从未正确, 大约比显示早6分钟"
  affects: [screen-customization]

- time: 2026-10-20T07:54:42
  kind: decision
  summary: "2026-10-20 复盘 135x240 上传失败：帧格式与厂商逐字节一致，失败点在『每包数据长度』与『窗口内偏移』两处未定；新增 tools/tft_probe.py 实验矩阵"
  source: "build/odm/layout-classic JS 复核 + fw_full.lst + 实测记录"
  affects: [screen-customization]

- time: 2026-10-20T10:00:11
  kind: evidence
  summary: "原生 TFT 上传链路在真实 Y65S 上打通(2026-10-20 主机实测): 按 OemDrv.exe 解出的 record 0x0D SetGIFParam(flag=1,nframes,delay) -> record 0x0C AccessData_Page(page=帧号, seq=全帧内 512B 块序号, RGB565BE) -> 末帧后 record 0x0D(flag=0); 240x135(64800B,127 块) 与 135x240 两版全部分块均收到 [09 0A 06 01 seq] 应答, 末条 flag=0 也应答. 注意: 该应答由主控在 520B 帧从 UART 发完时本地合成(0x9BA7, 0xD84=AA), 不代表模块渲染成功. OemDrv 设备配置 Dev/kb/Screen/KB.ini(VID=258a PID=019D 与本机一致) 给出 siScreen=240,135, MaxScreenFrame=40, RGBScreen=1 ⇒ 屏幕按 240x135 横屏处理. 屏幕实拍结果待用户确认."
  source: "host HID 实测 2026-10-20 + /tmp/y95drv/app/app/Dev/kb/Screen/KB.ini"
  affects: [screen-customization, module-link]

- time: 2026-10-20T10:30:35
  kind: evidence
  summary: "原生 TFT 上传协议端到端验证成功(2026-10-20): 按 OemDrv BurnScreenThread 时序(Sleep50 -> 0x0D flag=1 -> Sleep120 -> 每帧 0x0C page/seq 512B -> Sleep50 -> 0x0D flag=0 -> Sleep500) 上传 240x135 纯红 RGB565BE, 用户目视确认屏幕显示红色. 说明模块确实采纳并渲染, 记录 0x0C 的 page/seq 语义与 RGB565BE 字节序均正确; 主机 ACK 之外需要 OEM 时序才能落地(此前无 Sleep 的版本未被采纳). 下一步: 用四角标记图确认屏幕方向/旋转和最终上传工具化"
  source: "host HID 实测 2026-10-20 + 用户目视确认『看到红色图片』"
  affects: [screen-customization]

- time: 2026-10-20T10:37:02
  kind: decision
  summary: "用户目标升级(2026-10-20): 不只是上传图片, 而是要破解屏幕/无线模组固件、在第二颗 SoC 上运行自定义应用. 现状: OEM 工具不含模组固件或升级包(仅屏幕素材), 设备信息只暴露主控版本; 已知模组 UART 协议与用户动画区 0x650000, 但没有 SoC 型号、固件或烧写通道. 下一步: 拆机拍照识别模组 SoC 丝印、外部 SPI flash、SWD/UART 测试点, 再选 SWD/JTAG 读取、SPI flash 夹取或 UART bootloader 路线"
  source: "用户: 但是我想要破解固件运行应用 (选择屏幕/无线模组) + /tmp/y95drv 资源扫描"
  affects: [screen-customization]

- time: 2026-10-20T10:52:47
  kind: reversal
  summary: "2026-10-20 用户新目标改为『破解固件在屏幕上运行应用』, 目标芯片=屏幕/无线模组, 硬约束=不能拆机(无 SWD/SPI/UART 接触). 结论: 现有全部软件通道均无法把自定义代码写入/替换模组固件(主控记录协议只放行 0x03..0x0D 且模块命令白名单不含 OTA; 厂商 OTA 是 Sonix 主控 ISP; 无 Y95 模组固件包). 可执行的替代: (A, 推荐) PC 侧运行时经已打通的 0x0D/0x0C 协议实时推帧, 应用跑在 PC 上; (B) 主控 SMK 自制固件把屏幕当显示器, 应用跑在 SH68F90A(需主控 flash 写入授权); (C) 用户提供原厂模组 OTA/固件包后再离线逆. 拆机改装不在选项内."
  source: "2026-10-20 会话调查: fw_full.lst 0x6346/0xA331, ODM JS/wasm, OEM 安装包, 固件 API, host 实测"
  affects: [screen-customization]

- time: 2026-10-20T11:41:16
  kind: evidence
  summary: "2026-10-20 真机实验事故：19:2x-19:3x 在 Windows 宿主上对真机跑记录矩阵(0x03/0x04/0x05/0x06/0x08/0x0A 等)后，键盘失去输入能力(无法打字)；设备仍能响应 USB GetFeature(report 9)并回 8 字节状态帧，说明 MCU 的 USB ISR 还活着、卡住的是主循环/按键扫描或主机侧 USB 实例。"
  source: "omp-host 真机探测 2026-10-20"
  affects: [screen-customization, module-link, no-write-policy]

- time: 2026-10-20T12:37:12
  kind: decision
  summary: "2026-10-20 校时打通：ODM 前端的时间包必须 (a) 用 xn 头 AA 34 <contentSize=24> 00 00 00 01 00，(b) contentSize 取厂商默认 24（不是 10，时间只有 10 B、其余补 0），(c) 装在 520 B 大块帧里经记录 0x0B/0x0C/0x0D 下发（模块 cmd 0x81），ODM 包头落在 payload[1]。此前一直走 0x04/0x05 那两条窗（模块 cmd 0x52 / 0x6E+sub），命令号对不上，所以校时从未成功。实测：0x0C @payload[1] 下发后屏幕时钟从『慢 6 分钟』变为与宿主一致。"
  source: "omp-host 真机 2026-10-20 + build/odm/ 前端逐字节复核"
  affects: [screen-customization, module-link, driveall-protocol]

- time: 2026-10-20T13:14:54
  kind: evidence
  summary: "2026-10-20 校时已排除的组合（真机，屏幕时间未变）：记录 0x04 @payload[7] 的 raw/odm(AA 34 18 头)/dotmatrix(首字节 3A)/cmdprefix(34 前缀) 四种、记录 0x05 sub=0 的 raw/odm、记录 0x03 sub=1 的 raw/odm，全部无效；模块时钟只是自由走时（实测屏上 20:55 对宿主 20:51、快约 4~6 分钟，与旧记录『慢 6 分钟』方向相反）。尚未试：记录 0x05 的 sub=2..7（模块 cmd 0x70..0x75 = ODM 0x52..0x57，通用命令表里这档是空的=设备私有的屏幕命令族，固件开机正是拿 0x6E..0x75 逐个探测能力）——这是当前最强候选。另一条待验证路线：时间可能是 cmd 0x52 那 128 B profile 里的某个字段（需要按偏移暴力扫）。"
  source: "omp-host 真机 2026-10-20 批量实验"
  affects: [screen-customization, module-link]

- time: 2026-10-20T15:24:14
  kind: evidence
  summary: "2026-10-20 找到本机官方厂商包：/tmp/y95drv（Y95 Keyboard Setup v2.0 安装包 + app/app/OemDrv.exe + Dev/kb/Screen/KB.ini + Text/sc/text.xml）。结论：官方驱动【没有校时功能】——UI 文本里没有『校时/时间/日期』，配置里的 SendTimeOnOpenKB / SendSysParam / SyncMask 三个键在 OemDrv.exe 里被读入对象(偏移 0x2830/0x2834)后【从未被读】(grep 全 .text 只有写没有读)，SendTimeOnOpenKB 是死配置 ⇒ 屏幕时钟是模块自己的自由走时钟(实测快约 2~3%%：20:51→20:55、23:02→23:09)，用户只能靠我们自己下发校时。KB.ini 其它事实：VID=258a PID=019D、siScreen=240,135(横屏)、MaxScreenFrame=40、RGBScreen=1、SendSysParam=2000、SyncMask=2。"
  source: "本机 /tmp/y95drv 厂商包 + objdump 反汇编 2026-10-20"
  affects: [screen-customization, driveall-protocol, module-link]

- time: 2026-10-20T15:32:06
  kind: evidence
  summary: "2026-10-20 校时结论(第 N 轮)：用 Cloudflare/Google 的 HTTP Date 头交叉验证，宿主 PC 时钟准确(误差<1s)，所以『屏幕快 7 分钟』是实锤。模块的钟【速率正确、恒定偏 7 分钟、整机复位后仍保持】⇒ 它是模块自己的持久 RTC，只被设偏过一次。已穷举的可达模块命令(0x52 128B / 0x5E,0x62,0x66,0x6A 512B / 0x6E..0x75 512B / 0x81 520B) × 内容形状(raw 10B / ODM AA 34 18 头 / 3A 点阵版 / 34 前缀) 全部无效；profile 128B 的 0x00..0x39 逐字节偏移扫描(0-99)也无效(但证明 cmd 0x52 会被模块采纳：覆盖灯效字段 RGB 立刻变)。8051 侧全固件无任何时间逻辑(无 RTC SFR、无 5A 01 5A 模板、profile 里无时间字段)，官方 OemDrv.exe 也没有校时功能(SendTimeOnOpenKB/SendSysParam 是死配置)⇒ 主机→模块必有一条我们还没试到的『设时间』通道。"
  source: "omp-host 真机 2026-10-20 多轮"
  affects: [screen-customization, module-link]

- time: 2026-10-20T16:10:12
  kind: decision
  summary: "2026-10-20 校时线结论(穷尽)：主机可达的模块命令被 8051 固件写死为 0x52(记录0x04)、0x6E..0x75(记录0x05, sub<=7 故 0x75 是上限)、0x62/0x66/0x6A/0x5E(记录0x03 子分发1..4)、0x81(记录0x0B/0x0C/0x0D)；记录 0x06/0x0A 用 flash 固定表(主机改不了)、记录 0x08 写 RAM 配置表且会持久化到 flash 0xA800(危险)。已扫 ~60 个组合仍全灭：通道(上述 13 个) × 内容形状(raw 10B / AA 34 18 头 contentSize 24 与 10 / 3A 点阵版 / 34 前缀 / 5A 5A 重复 tag / 星期前置 / BCD / 十进制 / isLast=0 / 星期以周一为 0) + profile 偏移 0..99 × 2 格式 + 节拍(连发3次/120ms)。⇒ 若『设时间』命令存在，其命令号必在上述集合内，而该集合已扫遍 ⇒ 结论：这条 HID 桥没有可用的校时通道，模块 RTC 的 +7 分钟是出厂常量(速率正确、重启保留、BLE 用 PC 测不同步因 Windows 不提供 CTS)。唯一剩余机制是 BLE Current Time Service，须用手机(Android 提供 CTS)配对 BT1(Fn+Z)验证。"
  source: "omp-host 真机 2026-10-20 多轮穷举"
  affects: [screen-customization, module-link, driveall-protocol]
