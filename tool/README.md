# YD-Y65S 键盘工具

我们自己的 YD-Y65S 工具：**Tauri v2 桌面应用**（Windows / Linux / macOS 一套代码），
后端是 Rust（`crates/core`），前端是 React + Vite + Tailwind（`webui`）。

它替代厂商那套 `Y95 / K65 Keyboard Setup`（那两个 app 的 profile 与本机不匹配、
升级按钮会刷错固件，而且我们需要的"校时"在 Y95 版里是死配置）。

## 五大板块

| 板块 | 做什么 | 关键实现 |
|---|---|---|
| 状态 | 设备是否在线、HID 集合、链路模式 | `hidapi`（Win: hid.dll / Linux: hidraw / macOS: IOHIDManager） |
| 灯效 | 灯效序号、灯效模式、音量 | profile（模块命令 `0x52`）字段 `0x0A` / `0x33` / `0x31` |
| 校时 | 把 PC 的时间写进屏幕模块 | 厂商 11 字节时间包（`[date][cpu][x]` + 年月日时分秒星期） |
| 固件 | 备份 / 打补丁 / 刷写键盘 flash | 自己实现 Sinowealth ISP（`0x55/0x52/0x45/0x57/0x77/0x5a`） |
| 恢复默认 | 把出厂 profile 整块写回 | flash `0x9983` → 记录 `0x04` |
| 按键说明 | 按键组合、连接方式、灯效键 | 从键盘固件的键位表与 class `0x07/0x08` 动作读出 |

## 自制固件 = 原厂固件 + 补丁

我们**不改写整套固件**，而是在原厂 dump 上做**可审计的字节级补丁**
（`crates/core/src/patch.rs`）：

* 每条补丁带 `expect`（必须匹配的原字节）与 `replace`（写入的字节）；
* 对不上就**拒绝打**，绝不把补丁落到错的地方；
* 补丁表就是评审单元：一个地址 + 一个意图。

### 补丁一：`no-volume-send`（已就位）

**要求**：没有我们的软件在跑时，屏幕上**不要出现音量** —— 那个值本来就不准，显示出来只会误导。

**成因**：厂商 app 用 `IAudioEndpointVolume` 读 0.0~1.0 的系统音量，乘 **100.0** 下发
（Y95 `0x4705c5 fmull 0x610a20`、K65 `0x4742d5 fmull 0x616f80`，两个 app 一致）；
8051 只是**原样转发**、零限幅。

音量在固件里的完整链路（已逐条核对反汇编）：

| 步骤 | 位置 | 说明 |
|---|---|---|
| 存储 | flash `0xA431`（在用 profile `0xA400` + `0x31`） | app 写入；出厂 profile `0x9983`+`0x31` 也是同一字段 |
| 载入 | `0x7D00`：`MOVC A,@0xA431` → `xdata[0x0F12]` | 只有这一处把音量读进 RAM |
| 转发 | `0x5557`：`xdata[0x0F12]` → 设置包 `xdata[0x0DBB]` | **全固件唯一一处消费者**（`0x0F12` 只有两处被读：这里和 `0x7D05` 的载入） |
| 发送 | `0x5594`–`0x55CE`：按 cmd `0x52` 逐字节发 128 B（源 `0x0D8A+计数`） | 音量落在块内偏移 `0x31`（`0x0DBB-0x0D8A`），与 profile 字段号一致 |

**补丁**：`0x5557` 的那次拷贝（`90 0F 12 E0 90 0D BB F0`）整个去掉 —— **不发音量**，
不塞假值：

```
90 0F 12    MOV  DPTR,#0x0F12   ; 取 profile 的音量字段
E0          MOVX A,@DPTR
90 0D BB    MOV  DPTR,#0x0DBB   ; 设置包里的音量位置
F0          MOVX @DPTR,A
→ 00 00 00 00 00 00 00 00       ; 8 × NOP：音量字段从此不再被写入
```

两点说明：

* 设置包是**定长 128 B**，字节位置照样发出去，但那个值再也不会变：启动时
  `0x89EE` 清零 xdata `0x0000-0x0FFF`，而 `0x0DBB` 全固件只有这一处写 ⇒ 恒为 `0x00`。
  ⇒ 模块拿不到一个会变的音量。
* 紧邻的指令各自重新装载 `DPTR/A`，寄存器不跨这段 ⇒ 去掉拷贝不影响别的字段
  （`0x1F`/`0x33`/`0x35`/`0x36`/`0x37` 各有各的拷贝）。

**旋钮不受影响**（2026-10-21 更正）：旋钮本来就在**主控**上 —— `0x2812` 采
`P4.2`/`P0.7` 两个 GPIO 的正交相并自己解码方向（6 位历史寄存器，`0x284C` 判
`hist==7`、`0x2853` 判 `hist==11`）。旋钮的 HID consumer 报告与设置包这条链完全
无关 ⇒ 去掉那次拷贝动不了旋钮，旋钮照常调节系统音量。

### 补丁二：`no-volume-ods`（旋钮不通知屏幕）

**要求**：旋钮转动时**屏幕不要画音量**，只把音量调节指令发给主机。

**成因**：旋钮事件在主控里分两路走 ——

| 去向 | 内容 | 后果 |
|---|---|---|
| HID（主机） | `RAM 0x57` = `0xE9`/`0xEA`（consumer 页 16 位用量 = Volume Increment/Decrement），report id 2 | 主机系统音量增减 ✓ 保留 |
| cmd `0x15`（模块） | `xdata[0x0EE4]` = `0x81`/`0x82`（状态类 8 = 音量变化） | 屏幕画音量条 ✗ 切断 |

**补丁**：`0x059C` 起 40 B，四处改动：

```
0x059C  90 0E E4 74 81 F0   → 00 00 00 00 00 00   ; 不再写 0x0EE4=0x81
0x05A2  78 57 76 E9         → 不变                  ; HID consumer 用量 0xE9 保留
0x05AB  70 3A               → 70 4D                ; JNZ 0x05E7 → 0x05FA
0x05AD  90 0E E4 74 82 F0   → 00 00 00 00 00 00   ; 不再写 0x0EE4=0x82
0x05B3  78 57 76 EA         → 不变                  ; HID consumer 用量 0xEA 保留
0x05C2  80 23               → 80 36                ; SJMP 0x05E7 → 0x05FA
```

`0x05E7` 是 cmd `0x15` 的组帧+发送，`0x05FA` 是它后面的运行记录发布（清 `0x0ED9`
bit5）。跳到 `0x05FA` = 只发记录、不发 cmd `0x15`，同时也跳过了 `[0x0F2A]=1`
（不再等一个不会来的模块应答）。两处跳转都要改：`0x05AB` 的 `JNZ` 是"方向既不是 1
也不是 2"的兜底路径，也不能把状态字节发出去。

为什么不能只去掉状态字节的写入：`0x0EE4` 是模块状态字节，`0x04AC`/`0x04AF` 两个
派发表项会**直接**把当前 `0x0EE4` 当作 cmd `0x15` 的载荷发出去 —— 残留的 `0x81/0x82`
会被别的状态事件带出去。

补丁的 `expect` 字节取自两份 dump（`firmware/YD-Y65S_full.bin` 与 `backups/YD-Y65S_full_20261019.bin`，
两处一致 ✓），单测 `shipped_patches_match_the_dumps` 会拿真实 dump 校验 ✓，
`shipped_patch_rewrites_only_the_volume_field` 保证补丁不越界改别的字节 ✓。

**推帧路线已放弃**（整屏一帧要 4 分钟，做不了任何动态内容），所以音量只能靠
"不喂数据"来屏蔽。备选变体 `no-volume-send-zero`（显式写 `0x00`）也留在补丁表里 ——
效果与上面一致（xdata 开机清零），留着是为了真机上想换写法时不用改代码。

### 待补：校时包的位置

11 字节载荷已知（`[date][cpu][x]` + 年月日时分秒星期），落在哪条记录/哪个偏移还没钉死；
工具里的"扫描全部通道"会每条通道配一个不同分钟数，看屏幕停在哪一分钟即可反推。

## 目录

```
tool/
├── Cargo.toml           # workspace
├── crates/core/         # 协议 + HID + ISP + 补丁框架 + 一键流程（无 UI 依赖，带单测）
├── crates/cli/          # 命令行版：y65s fix-volume / backup / flash / patch
├── cli/fix-volume.bat   # Windows 用户的「双击即用」入口
├── src-tauri/           # Tauri v2 应用层（命令层）
└── webui/               # React + Vite + Tailwind 前端
```

## 命令行版（一键修复音量条）

```bash
cargo build --release -p y65s-cli     # 产物：target/release/y65s(.exe)

y65s fix-volume        # 一键修复音量条：读出 → 备份 → 打补丁 → 写入 → 读回逐字节校验
y65s backup <路径>      # 只读出整片 flash，不写任何东西
y65s flash <镜像>       # 刷写镜像（写入前自动备份到 <镜像>.pre-flash-backup.bin）
y65s patch <dump> <输出> # 给 dump 打补丁生成新镜像，不碰设备
y65s patches            # 列出补丁表
y65s info               # 键盘连接状态
```

**写入顺序**：`erase → write pages → enable → reboot`。`enable`（`0x55`）必须排在所有写页之后 ——
bootloader 用它存在 `0xEFFC` 的复位向量重建 `0x0000` 的跳转指令；顺序反了键盘就开不了机。
这个顺序集中在 `isp::write_plan()` 里，并有单测盯着。

## 构建与运行

```bash
cd tool
cargo test -p y65s-core          # 核心库单测（不需要设备）
npm --prefix webui install       # 前端依赖
npm --prefix webui run build     # 产出 webui/dist
cargo tauri dev                  # 开发
cargo tauri build                # 打包（Windows / Linux / macOS）
```

## Linux 权限

`hidraw` 节点默认只有 root 能读写。给这台键盘加一条 udev 规则：

```bash
echo 'KERNEL=="hidraw*", ATTRS{idVendor}=="258a", ATTRS{idProduct}=="019d", MODE="0660", TAG+="uaccess"' \
  | sudo tee /etc/udev/rules.d/99-y65s.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

然后重新插拔键盘。

## 协议速查（我们逆出来的）

```
feature report 9, usage page 0xff02 / usage 0x0002, 519 字节
  payload[0] = 记录命令, payload[7..] = 数据窗

0x03 子分发 1..4  -> 模块命令 0x62 / 0x66 / 0x6A / 0x5E
0x04 128B 窗      -> 模块命令 0x52（设备 profile）
0x05 512B 窗      -> 模块命令 0x6E + payload[4]
0x06              -> 模块命令 0x56（TFT 模式）
0x08              -> RAM 配置表（**会写键盘 flash**，别乱发）
0x0A              -> 模块命令 0x54（固定代码表）
0x0B/0x0C/0x0D   -> 模块命令 0x81（520B 原始流：屏幕内容）

profile：128B，出厂 0x9983 / 实时 0xA400，尾部 0x7E/0x7F = 5A A5 标记
屏幕：240x135，RGB565 **大端**；传图节拍 120/50/50/500 ms（缺了就只收不渲染）
```

## 安全红线

* 记录 `0x08` 会把配置持久化进键盘 flash（我们上次就是这么把键配置写坏的）⇒ 工具里不提供它。
* 刷写 flash 需要显式确认；刷写前先备份。
* 校时、灯效、推屏都只改模块与屏幕，不碰键盘 flash。
