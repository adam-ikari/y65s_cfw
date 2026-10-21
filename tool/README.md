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

### 补丁一：`no-volume-display`（已就位）

**要求**：没有我们的软件在跑时，屏幕上**不要出现音量** —— 那个值本来就不准，显示出来只会误导。

**成因**：厂商 app 用 `IAudioEndpointVolume` 读 0.0~1.0 的系统音量，乘 **100.0** 下发
（Y95 `0x4705c5 fmull 0x610a20`、K65 `0x4742d5 fmull 0x616f80`，两个 app 一致）；
8051 只是**原样转发**、零限幅：profile `0x31` → `xdata[0x0F12]` → 设置包 `0x0DBB`，
`0x5594` 起按 cmd `0x52` 逐字节发 128 B（源 `0x0D8A+计数`）。

**补丁**：`0x5557` 的那次拷贝（`90 0F 12 E0 90 0D BB F0`）改成写常量 `0xFF`：

```
90 0D BB    MOV  DPTR,#0x0DBB
74 FF       MOV  A,#0xFF        ; 超出 0~100 量程 ⇒ SoC 无法显示音量条
F0          MOVX @DPTR,A
00 00       NOP NOP
```

补丁的 `expect` 字节取自两份 dump（`firmware/YD-Y65S_full.bin` 与 `backups/YD-Y65S_full_20261019.bin`，
两处一致 ✓），单测 `shipped_patches_match_the_dumps` 会拿真实 dump 校验 ✓，
`shipped_patch_rewrites_only_the_volume_field` 保证补丁不越界改别的字节 ✓。

**推帧路线已放弃**（整屏一帧要 4 分钟，做不了任何动态内容），所以音量就由 SoC 那个值来显示 ⇒
补丁就是让它**没有可显示的音量**。哨兵值给了两个变体（`0xFF` / `0x00`），
哪个让 SoC 真正不画条，刷一次看屏幕即可定，改一个常量就行。

### 待补：校时包的位置

11 字节载荷已知（`[date][cpu][x]` + 年月日时分秒星期），落在哪条记录/哪个偏移还没钉死；
工具里的"扫描全部通道"会每条通道配一个不同分钟数，看屏幕停在哪一分钟即可反推。

## 目录

```
tool/
├── Cargo.toml           # workspace
├── crates/core/         # 协议 + HID + ISP + 补丁框架（无 UI 依赖，带单测）
├── src-tauri/           # Tauri v2 应用层（命令层）
└── webui/               # React + Vite + Tailwind 前端
```

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
