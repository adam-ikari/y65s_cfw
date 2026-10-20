---
id: module-link
title: "模块链路：主控 ↔ 屏幕/无线 SoC"
category: reference
status: active
tags: [module, uart, screen, protocol]
created: "2026-10-19T23:09:10"
updated: "2026-10-20T07:54:25"
---

<!-- compiled_truth -->
主控（SH68F90A）↔ 模块（第二颗 SoC：无线 + 彩色小屏）之间那条私有 UART 链路的完整现状。
相关页：[[screen-customization]]（目标）、[[host-vendor-channel]]（主机入口）、[[driveall-protocol]]（同族 ODM 主机协议）。

## 物理层

- 硬件 EUART：`SBUF=0xAA`、`SCON=0xD8`；初始化在 **`0xB15A..0xB187`**：`SCON=0x50`（模式 1，REN=1）、
  `SBRTH=0xFF`、`SBRTL=0xFB`、`SFINE=0x0C`、清 TI/RI、置 `PCON` bit6、开 `IEN1` bit6（UART 中断）。
  （`SADDR/SADEN` 在本固件未用；接收器固件用了 → 两边不同构建。）
- 发送是**中断驱动的分包发送**：帧缓冲 `xdata 0x11C1`，流描述符 `xdata[0x0F5C]`=空间选择（1=xdata）、
  `0x0F5D:0x0F5E`=指针、`0x0F5F:0x0F60`=剩余字节数；单字节出口 `0xA3D3` / `0xAEF7`（写 `SBUF`）。

## 帧格式

- 主控 → 模块：`50 <cmd> <len> <payload...> <sum>`，组帧 `0x9BF9`（软件组帧，把 payload 逐字节搬进
  `0x11C4+`，末尾追加 `0xB607` 的 8 位累加和），`<sum>` 覆盖 cmd+len+payload。
- 字节流路径（记录 0x04/0x05 用）：`0xBADB` → `0xA331`（存指针 + 用 `RAM_03` 查白名单）→ `0xB2F3`
  （IB 硬件寄存器直发，源地址 = `XPAGE`+`IB_OFFSET`，数据字节 = `RAM_05`）。
  白名单 = {0x52,0x5E,0x5F,0x62,0x63,0x66,0x67,0x6A,0x6B,0x54,0x56} ∪ [0x6E..0x75]；
  命中才发，否则**静默丢弃**。
- 大块帧：`50 81 <size_hi> <size_lo>` + payload，组帧 `0xB204`（唯一调用点 `0x063A`）。
  帧头写在 `xdata 0x08F1..0x08F4`，payload 缓冲 `xdata 0x08F5..0x0AFC`（恰好 520 B），
  size 常量 = `0x0208` = 520 ⇒ **线上共 524 B**（`0xB21F` 处长度 = R5+4 且高字节 R4=2）。
- 模块 → 主控：首字节 `0x5A` 或 **`0x55`**（`0xB9B0` 判 `0x0B90` 首字节：0x55 → `0xA175`；0xAA → `0x9FE2`）。
  `0x55` 正是 ODM 的应答包头 ⇒ **模块的应答侧是 ODM 兼容的**。

## 命令全集（`0x9BF9` 全部 12 个调用点）

| cmd | len | 发送点 | 备注 |
|---|---|---|---|
| `0x0A` | 14 | `0x009B` | payload 最大的一帧 |
| `0x1B` | 1 | `0x00E1` | |
| `0x08` | 1 | `0x011E` | |
| `0x02` | 1 | `0x01DE` | payload 先 `ORL A,#0x80` |
| `0x03` | 0 | `0x021A` | |
| `0x04` | 4 | `0x02A2` | |
| `0x13` | 1 | `0x0300` | payload 先 `ORL A,#0x08` |
| `0x15` | 2 | `0x035D`、`0x05F1` | |
| `0x17` | 1 | `0x044F` | payload 先 `ORL A,#0x80` |
| `0x18` | 1 | `0x0691` | |
| `0x1A` | 1 | `0x06D2` | |
| `0x81` | **520** | `0xB204`（唯一调用 `0x063A`） | 大块数据帧 |

这些调用点集中在 `0x008B..0x06EE`（模块事件/状态处理区），由主控状态变化驱动 ⇒ **主控对模块说的是"状态"，不是"内容"**。

## 主机记录协议（feature 9 → 8051 记录分发器）★ 已实测打通

- `SetFeature(feature 9)` 传输完成后：USB ISR（`0xA114`）尾部调 `0x6346`：若 `xdata[0x0D85]==1`（本次传输收尾），
  读 `xdata[0x08F6]` = **记录命令字节**（合法范围 `0x03..0x0E`，跳表 `0x6373`，越界忽略）。
- 记录缓冲：`0x08F5`=report ID(`0x09`)、`0x08F6`=命令字节(=主机 payload[0])、`0x08F7`=子参数(payload[1])、
  `0x08FA`=payload[4]。**各记录的数据窗都从 `payload[7]` 开始**（`0x08F5+8`）——
  `0x7E5B`(记录0x04) 与 `0x8715`(记录0x05) 都把 `[0x0EC7]=8` 加到记录基址上。
- 分发表：
  - `0x03` → 子分发 `0x08F7`=1..4 → `0x923E`/`0x92D8`/`0x8DB3`/`0x8D13`（8 B 记录，**未触碰**）
  - `0x04` → `0x7E5B`：**把 payload[7..134] 共 128 B 转发给模块**（每字节一帧 `50 52 01 <b> <sum>`，`0xBADB`）；
    另：若 payload[8]==1 则把 payload[17] 改写为 0x13
  - `0x05` → `0x8715`：模块 cmd = `0x6E + payload[4]`（payload[4] 必须 0..7，否则丢弃）；
    转发 **payload[7..518] 共 512 B**（每字节一帧，cmd = 0x6E+sub）
  - `0x06` → `0x6F1F`：代码表 `0xAD7A` 126 B → `0x0D8A`，两轮（122+126 B）以模块 cmd `0x56` 发出；
    置 TFT 模式 `xdata[0x0F2F]=0x5A`、`[0x0F62]=0x56`
  - `0x08` → `0x6B57`（只改 RAM 配置表，无擦写）
  - `0x0A` → `0x6DE2`（模块 cmd `0x54`）
  - `0x0B` → `0x6474` / `0x0C` → `0x644D` / `0x0D` → `0x641B`：
    置 `[0x0ED7] bit0` ⇒ 状态机 `0x0628` 触发 **0x81 大块帧**（把整块 520 B 转发给模块），并置 `[0x0E0A]=1`
- **忙标志**：`xdata[0x0F2F]==0x5A` 表示"模块忙"，此时记录 0x04/0x05 **整条丢弃**（`0x8724`/`0x7E6B`）。
  `xdata[0x0F62]`=待发模块命令，`xdata[0x0F6E]`=超时计数（0x32）。
- 流控：每个模块字节帧都要等模块 `0x55` 应答才发下一字节（`0xB970`→`0xA33A`→`0xB2F3`，
  应答缓冲 `xdata 0x0B90` 首字节判 `0x55`/`0xAA`（`0xB9B0`））。

## 固件内置的模块会话回放器（`0x0D11..0x10B1`，主循环 `0x85AC` 在 `[0x0F17].0` 置位时执行）

这是厂商自己给模块下发的完整会话序列，**是理解模块协议最硬的证据**：

1. 把代码 `0x9983` 的 **128 B** 复制到 `xdata 0x08F5..0x0974`（终止条件：低字节==0 且高字节==0x80 ⇒ 0x0080）。
2. 依次发：
   - cmd **0x52**：那 128 B（逐字节，`0xBADB`）
   - cmd **0x5E** / **0x5F** 各 1 B，2 轮（代码表 `0x0C00` / `0x0C20`）
   - cmd **0x62** / **0x63** 各 1 B，2 轮（代码表 `0x0C80` / `0x0CA0`）
   - cmd **0x66**、**0x67**（无数据）
   - cmd **0x6A**、**0x6B**（无数据）
   - cmd **0x6E..0x75** 各 1 次（**无数据**，8 个命令）
   - cmd **0x54**：2 B（代码表 `0xAA00`）
   - cmd **0x56**：126 B（代码表 `0xAD7A`，先复制到 `0x08F5`）
3. `[0x0F8A]=5`、`[0x0F8B]=0x0A` 是 IB 发送器配置常量，不是握手。

**内置 128 B 内容表（`0x9983`）不是 ODM 包**：首字节是 `00`（不是 `0xAA`），尾字节 `5A A5`；
中段 `00 00 64 01 01 00 00 01 FF FF` 之后是 `14 17` 重复 32 次 + `14 14` 重复 8 次（疑似 RGB565 像素）。
⇒ **模块的 cmd 0x52 载荷是"原生长度内容块"，不是 ODM 请求包**；只有*应答*侧是 ODM 风格（0x55 头）。

## 两条"内容"通道的对比（2026-10-20 结论）

| 通道 | 记录 | 转发内容 | 每包数据长度 |
|---|---|---|---|
| 字节流 | 0x04 | payload[7..134]（128 B），cmd 0x52 | 固定 128 B 窗 |
| 字节流 | 0x05 | payload[7..518]（512 B），cmd 0x6E+sub | 固定 512 B 窗 = 8 B 包头 + 504 B 数据 |
| 批量 | 0x0B/0x0C/0x0D | 整块 520 B（report ID + 519 payload），cmd 0x81 | 520 B 块 = 1 B ID + 519 B |

- ODM 的 TFT 上传包是 `8 B 包头 + N B 数据`，N = 设备报告长度 − 8（见 [[driveall-protocol]]）。
  对 YD-Y65S：0x05 通道 ⇒ N = 504；0x81 通道 ⇒ N = 511（519 − 8）。
  **两种 N 只能选一个，模块端固定**。之前按 504 传、total=130，若模块要 511，则永远凑不满一帧 ⇒ 屏幕不变。
- 0x81 块的第一个字节是 report ID `0x09`、第二个字节是记录命令 ⇒ ODM 包头在块内的位置不是 0。

## 未解 / 待验证

- 模块每个 TFT 包期望的数据长度到底是 **504 还是 511**（或别的）。
- 模块 cmd 0x52 的 128 B 原生内容块的字段结构（时间字段在哪、像素区从哪开始）。
- 记录 0x03 子分发（`0x923E`/`0x92D8`/`0x8DB3`/`0x8D13`）的语义；`xdata 0x0BA6`/`0x0B8D` 的最终消费者。


## Timeline

- time: 2026-10-19T23:09:10
  kind: decision
  summary: "Created this page: 模块链路：主控 ↔ 屏幕/无线 SoC"
  source: "build/fw_full.lst + README 2026-10-19"
  affects: [module-link]

- time: 2026-10-19T23:09:10
  kind: decision
  summary: "主控↔模块 UART 链路全貌：0x50/0x5A 帧、命令全集、50 81 大块帧、以及 feature 9 → 520B → 模块 的内容管道；模块固件不可读不可写"
  source: "build/fw_full.lst + analysis/lst.py"
  affects: [module-link]

- time: 2026-10-19T23:09:10
  kind: evidence
  summary: "解出模块链路发送引擎(流描述符 0x0F5C-0x0F60 + SBUF 中断发包, UART 初始化 0xB15A)、0x9BF9 全部 12 个命令调用点(cmd 02/03/04/08/0A/13/15/17/18/1A/1B)、大块帧 50 81 0208(0xB204, 缓冲 0x08F5..0x0AFC=520B)"
  source: build/fw_full.lst
  affects: [module-link, host-vendor-channel, screen-customization]

- time: 2026-10-19T23:09:10
  kind: evidence
  summary: "主机->模块内容管道闭环: SetFeature(feature 9,IF1,wLength=519) 在 0x8363 判 SETUP(wValue低=9/wValue高=3/wIndex低=1) -> 偏移/剩余清零 -> 每个 8 字节 EP0 OUT 包(源 xdata 0x1100) 经 0x6CA2/0xA650 追加进 0x08F5+偏移 -> 收尾后由 timer2 状态机以 50 81 02 08 + 520B 发给模块; 即 519B feature 写入 == 一个 520B 模块数据块"
  source: "build/fw_full.lst + 报告描述符 0x4569"
  affects: [module-link, host-vendor-channel, screen-customization]

- time: 2026-10-19T23:18:47
  kind: evidence
  summary: "受控写入探测（第一阶段：结构性）：对 IF1 feature report 9 写入 519 B 全 0（tools/vendorhid.py set --report 9 --file）。

结果：
1) HidD_SetFeature 返回成功（ok=True, err=0）。
2) 写后 get_feature(9) 读回的 520 B 缓冲首字节由写前的 00 变成 09 —— 证明设备侧 EP0 OUT 缓冲 byte0 = report ID（与 ISP 检查读 xdata[0x1100]==0x05 一致），主机 payload 落在 0x1101..。
3) 同一次写覆盖了 xdata 0x1100..0x1306，把 0x1149..0x114E 的 SETUP 副本清零，描述符/闪存读取窗口指针因此复位（写后再读 feature 9 从 iProduct 字符串处重新开始流）。说明 feature 9 的 IN 方向是\"闪存流窗口\"（8 B 块经 0xA78E 泵入 EP0 IN 缓冲）。
4) 30 s 内 input report 9 无任何帧：模块没有回包，也不是周期性上报。

结论：主机→模块的 519 B 内容管道在设备侧被接受（代码路径 0x8363 → EP0 状态 0x0B → 0x6CA2/0xA650 追加 → 50 81 02 08 + 520 B 转发），但单块写入没有可观测回执。该 520 B 块的语义（屏幕内容 / LED 参数 / 字体 / 其他）仍然只能靠屏幕侧观察或继续静态解码来确定。
"
  source: "tools/vendorhid.py set --report 9 --file build/probe/payload_zero.bin; build/probe/"
  affects: [module-link]

- time: 2026-10-20T00:20:01
  kind: decision
  summary: "主机记录协议(feature 9)已实测打通: cmd 0x04 转发128B到模块, cmd 0x0D/0x0C 切换屏幕背景图"
  source: "build/fw_full.lst 0x6346-0x6495; build/probe/ 实测"
  affects: [module-link]

- time: 2026-10-20T01:13:50
  kind: evidence
  summary: "复现规律确认: 任何记录0x04(模块cmd 0x52字节流)包都会关闭键盘RGB(校时/切内置图/会话包均如此); ODM 0x34 时间结构值不生效(2027-03-08/2099-06-15/真实时间三种值屏幕均无变化),首次的时钟重置是模块进入屏幕会话状态的副作用; 记录0x0D(灯效模式2)/0x0C多数时候能恢复,但会话态深了之后救不回,需要断电重启复位"
  source: "实测 2026-10-20, tools/y65s_tool.py 校时/救援按钮观察"
  affects: [module-link]

- time: 2026-10-20T01:35:10
  kind: evidence
  summary: "重大: 固件内置完整模块会话回放器(0x0D11..): 主循环0x85AC在[0x0F17].0置位时执行,将384B内置表(代码0x9983)装入xdata 0x08F5,然后发全序: 0x52内容窗口(128B)+0x5E/0x5F/0x62/0x63(各2x1B从代码表0x0C00/0xC20/0xC80/0xCA0)+0x66/0x67(空)+0x6A/0x6B+0x6E..0x75(8x1B)+0x54+0x56(代码表0xAD7A 126B); [0x0F8A]=5/[0x0F8B]=0x0A是发送器配置常量非握手. 实测: 把默认内容窗口第1个128B经记录0x04原样发出,屏幕有反应(RGB灭+屏幕切页)=传输帧格式确认正确"
  source: "fw_full.lst 0x0D11-0x10B1, 0x85AC, 0x87DE(0x0F17|=1), fw 0x9983; probe payload_rec04_replay_w1.bin"
  affects: [module-link]

- time: 2026-10-20T01:40:47
  kind: reversal
  summary: "修正: 内置内容表复制长度是128字节(终止条件 counter lo==0 且 hi==0x80 => 0x0080), 源码 0x9983..0x9A02 -> xdata 0x08F5..0x0974. 之前说的384字节是误读(把 hi==0x80 当成0x180). 该128字节正是记录0x04的内容窗口"
  source: "fw_full.lst 0x0D12-0x0D50 逐条复核"
  affects: [module-link]

- time: 2026-10-20T01:52:19
  kind: evidence
  summary: "ODM 协议静态完全解出: 包构建器 xn = 8字节头 AA <cmd> <len_lo> <len_hi> <addr_lo> <addr_hi> <h5> <h6>, 数据从 offset 8 开始; 发送器 mt 用 output report 0 (reportCount 默认32) 按 reportCount-8 分块; 应答解析 nu 要求首字节0x55, 头同为8字节(55 <cmd> <len> <addr ...>). 关键映射: 模块帧命令字节 = ODM 命令 + 0x1E (52->0x52, 64->0x5E, 65->0x5F, 80->0x6E, 81->0x6F ...)"
  source: "build/odm/layout-classic-Bylu1MNp.js: xn/mt/nu/Je"
  affects: [module-link]

- time: 2026-10-20T01:52:19
  kind: evidence
  summary: "SET_TEMPORARY_COMMAND_DATA(=ODM 52=模块0x52=记录0x04) 是屏幕数据通道, JS 里有三种载荷: 屏幕时间 Hu=[5A 01 5A yy mm dd hh mi ss wd]; 系统信息 Wu=24B(y[6]=5A, y[12..20]=CPU占用/CPU温度/GPU占用/GPU温度/当前温度/最高/最低/天气码/湿度); PC时间 ju=[3A 01 5A ...]. 厂商工具在设备连接时自动发 setTftDateTime(=Hu), tftDirection==255 时跳过 => 255 表示无屏. 设备信息字段位置: batteryLevel l[17], tftMaxFrames l[22..23], tftDirection l[28], frameVersion l[30]"
  source: "layout-classic JS: Hu/Wu/ju, 设备信息解析器"
  affects: [module-link]

- time: 2026-10-20T01:52:19
  kind: evidence
  summary: "记录通道精确语义修正: 记录0x04 数据窗口 = payload[7..134] 128字节(发送地址=0x08F5+8, 已实测确认), 且入口若 [0x0F2F]==0x5A(TFT忙) 直接丢弃整条记录; 记录0x05 的 payload[4] 选模块命令 (cmd=payload[4]+0x6E, 有效0x00..0x07), 实际发送循环上界 0x0200 => 每次发 payload[7] 起的512字节"
  source: "fw_full.lst 0x7E5C-0x7F39, 0x87A0-0x87C8"
  affects: [module-link]

- time: 2026-10-20T01:52:19
  kind: evidence
  summary: "TFT 用户动画上传格式(厂商 zu): 载荷 = 256字节帧头([0]=帧数, [1..n-1]=延迟x5, [n]=0, 其余0xFF) + RGB565小端像素(r>>3<<11|g>>2<<5|b>>3); 每块数据504字节, 块头 AA 50 <idx_lo> <idx_hi> <cnt_lo> <cnt_hi> 50 06 (常数6619136/4096=1616=0x650 => 模块flash 0x650000 用户动画区); 固件侧用记录0x05 payload[4]=0 每次送512字节(块头8+504数据)"
  source: "layout-classic JS: zu, Eo, \\; 0xB204 中 R4=2,R5=8"
  affects: [module-link]

- time: 2026-10-20T07:10:15
  kind: evidence
  summary: "逐字节发送链路精确语义: 0xA331 把 (R6,R7) 存到帧缓冲后, 用 R3(cmd) 查白名单 {0x52,0x5E,0x5F,0x62,0x63,0x66,0x67,0x6A,0x6B,0x54,0x56} 以及区间 0x6E..0x75, 命中则令 R7=1 (返回 1) 否则 R7=0; 0xBADB 只有在 R7==1 时才 LCALL 0xB2F3 真正发射, 否则只丢弃. 所以 记录0x04(0x52) 和 记录0x05(0x6E..0x75) 的每个字节都确实发出去了, 而其它命令号的字节会被静默丢弃. 0xB2F3 是寄存器级发送(IB_* 硬件)."
  source: "fw_full.lst 0xA331-0xA381, 0xBADB-0xBAF5, 0xB2F3-0xB32B"
  affects: [module-link]

- time: 2026-10-20T07:10:15
  kind: evidence
  summary: "TFT 用户动画上传(记录0x05 payload[4]=0 -> 模块0x6E, 512B/块) 实测失败: 135x240 RGB565小端 + 256字节帧头 = 65056 B, 切成 130 块 (块头 AA 50 idx cnt 50 06 + 504 数据), 1.8s/块, 236 秒全部 ok=True 且模块对每字节都应答(否则每字节48ms超时, 130块不可能这么快). 但屏幕画面无任何变化(仍是内置人像图), 之后发 内置图索引0/1 也无变化. 结论: 模块收到并 ack 了数据, 但没有显示/没有接受该上传; 上传格式或会话前提仍不对."
  source: "build/tft_upload.py 运行日志 build/tft_upload.log; 用户目视确认"
  affects: [module-link]

- time: 2026-10-20T07:10:15
  kind: evidence
  summary: "主机侧回包: 任何有效记录(0x04/0x05/0x06/0x08)都会在约0.55s后回一条 input report 09 0a 06 00 01 00 00 00; 记录0x0D 回 09 0a 06 01 00 00 00 00; 记录0x07/0x09/0x0E 这类被忽略的不回. 空闲时不回. 该回包与模块是否接受数据无关(非法包头/非法子命令的载荷完全一致), 只能当\\"
  source: "build/probe_io.py 四组对比"
  affects: [module-link]

- time: 2026-10-20T07:10:15
  kind: evidence
  summary: "记录0x08 实际行为: 0x6410 -> R6R7=0x08F5(记录缓冲) R5=8 -> 0x6B57, 该函数按记录字节索引 code 表 0x0377(0x12 步长, 6 项) 并把结果写进 xdata 0x0300+ 区, 全程没有 IAP 擦写调用 => 只改 RAM 配置表, 不是 flash. 全 0 载荷会把这几个表项清零, 拔插一次键盘即从 flash 恢复."
  source: "fw_full.lst 0x6410-0x6419, 0x6B57-0x6C30; 0x2CF0/0x2CFC 为纯 xdata 存取"
  affects: [module-link]

- time: 2026-10-20T07:54:25
  kind: decision
  summary: "2026-10-20 复核记录窗口偏移(0x04/0x05 数据都在 payload[7])、固件内置模块会话序列、0x81 批量帧几何；判定 0x52 载荷不是 ODM 包、且 ODM 每包数据长度可能是 511 而非 504"
  source: "build/fw_full.lst (0x7E5B/0x8715/0x0D11-0x10B1/0xB204/0xB2F3) + build/odm/*.js"
  affects: [module-link]
