---
id: driveall-protocol
title: "driveall 通用外设协议 (ODM Web 驱动)"
category: reference
status: active
tags: [odm protocol screen hid]
created: "2026-10-19T22:46:33"
updated: "2026-10-20T07:54:00"
---

<!-- compiled_truth -->
ODM 通用外设协议（全称：driveall.cn 平台 Web 驱动协议）。它是**同代 ODM 键盘的完整主机侧协议参考实现**，可用于比对/推断 YD-Y65S 自己的主机命令通道。

## 来源与产物
- 来源：`https://yunzii.driveall.cn/`（Vite SPA，WebHID + wasm-bindgen）。2026-10-20 重新下载到 `build/odm/`（build/ 在 .gitignore 内，需重下）：
  - `main-BnbZC7tT.js`（入口，2 KB）
  - `vendor-xxmc0x-d.js`（1.4 MB：GIF 解码器、md5、wasm-bindgen 胶水，含 `sendFeatureReport`/`receiveFeatureReport` 导入）
  - `layout-classic-Bylu1MNp.js`（770 KB：**协议实现 + 机型库 + i18n**）
  - `tui-image-editor-DUVr5kck.js`（图像编辑器，文件名大小写与旧记录不同）
  - `tft-DGEkbwnS.js`（屏幕编辑页 UI，9 KB）
  - 路由是动态 import，tft 页在 `layout-classic` 末尾的 `import("./tft-DGEkbwnS.js")`。
- 同平台/同类设备：YUNZII、前行者 HFD、狼蛛 `hea.aulacn.com`、达尔优 `qd.dareu.com`；本地服务固定 `http://127.0.0.1:9191`。

## 传输层
- WebHID；设备匹配 = 某 collection 的 `usagePage === 0xFFE7`（`jn(productId, usagePage=65383)`）且 `productId` 相符。
- **包头 `xn(cmd, len, addr, data, size, otherHeader, customHeader, isLast)`**：
  `i[0]=0xAA, i[1]=cmd, i[2]=len, i[3]=addr_lo, i[4]=addr_hi, i[5..7]=otherHeader(最多3)`；
  没有 otherHeader 时 `i[6] = isLast ? 1 : 0`；数据从 offset 8 起放。报告其余部分补 0。
  ⇒ 通用包头 = `AA <cmd> <len> 00 00 00 <isLast> 00`（8 字节，第 6 字节是"最后一片"标志）。
  **注意 `len` 是命令的 contentSize（厂商约定的载荷区长度），不是实际有效数据长度**：
  校时包 contentSize=24 而有效数据只有 10 字节 ⇒ 包头 `AA 34 18 00 00 00 01 00`。
- **发送器 `mt`**：单包数据长度 = `reportCount - headerCount`（`reportCount` 取自设备 output report 的
  `reportCount` 字段，厂商按**字节**用，缺省 4104）；`contentSize` 决定包数；`customHeader` 存在时整包头被替换。
- 应答等待 `ss`/`nu`：输入报告首字节必须是 `0x55`，头同为 8 字节 `55 <cmd> <len> <addr_lo> <addr_hi>`，
  按 cmd（可选 addr）匹配；超时默认 50 ms，写命令 2000 ms；写命令支持 `maxRetries`。
- 另有 CRC16-CCITT（poly 0x1021, init 0xFFFF, `ou`）与 `COMMUNICATION_START(1)/COMMUNICATION_END(2)` 会话包裹
  （本套 TFT 流程里没有用到）。

## 命令号（`Je`，十进制）
1 COMMUNICATION_START / 2 COMMUNICATION_END / 15 SET_FACTORY_RESET / 16 GET_DEVICE_INFO / 17 GET_GAME_MODE / 18 GET_KEY / 19 GET_LED_EFFECT / 20 GET_CUSTOM_LED_DATA / 21 GET_MACRO / 22 GET_FN_KEY / 27 GET_LIGHT_BOX / 29 GET_SIDE_LIGHT / 31 GET_DEFAULT_KEY_MATRIX / 33 SET_GAME_MODE / 34 SET_KEY / 35 SET_LED_EFFECT / 36 SET_CUSTOM_LED_DATA / 37 SET_MACRO / 38 SET_FN_KEY / 42 SET_DOT_MATRIX_MODE / 43 SET_LIGHT_BOX / 46 SET_TRIGGER_KEY / 48/49 自定义功能开关 / 50 GET_LED_DATA / 51 GET_ALL_LIGHTS_RGB / 52 SET_TEMPORARY_COMMAND_DATA / 53 SET_MUSIC_DATA / 54 CLEAR_LED_DATA / 55 GET_ALL_LIGHTS_RGB_24G / 59/60 24G 64 字节变体 / 61 GET_DOT_MATRIX_CONFIG / 64 SET_LED_BOOT_ANIMATION / 65 SET_LED_USER_ANIMATION / 66 SET_LED_DATA / 79 SET_FLASH_DOWNLOAD / **80 SET_TFT_USER_ANIMATION** / **81 SET_TFT_BUILT_IN_INDEX** / 96 磁轴状态 / 100–106 校准、仿真 / **128 OTA_GET_DEVICE_SYSTEM_INFO** … **134 OTA_SET_DEVICE_SN** / 250 GET_DEVICE_NOTIFY / 251 磁轴校准数据 / 252 2.4G 断连通知。

## TFT（小屏）内容协议 —— `SET_TFT_USER_ANIMATION = 80`（2026-10-20 逐字节复核）
厂商函数 `zu(device, model, delays[], rgb565Bytes[], onProgress)`：

1. 延时表 256 B：`g[0] = 帧数 n`；`g[1..n-1] = delay*5`；`g[n] = 0`；其余 `0xFF`。
2. 像素流 = 各帧的 `width*height` 像素 **RGB565 小端**（`Eo(r,g,b)=(r&248)<<8|(g&252)<<3|(b&248)>>3`，
   `$o` 拆成 `[hi,lo]` 后 `push(lo,hi)`）。忽略 alpha；画布先 `clearRect` 再 `drawImage`。
3. `stream = 256 B 延时表 ++ 像素流`。
4. 分包：每包 `dataPer = reportCount - 8` 字节；包数 `_ = ceil(stream.length / dataPer)`；
   **每包 8 字节自定义包头** `AA 50 <idx_lo> <idx_hi> <total_lo> <total_hi> 50 06`
   （`50`=cmd 80；`idx`=包序号 LE16；`total`=总包数 LE16；`50 06` = 1616 = 0x650，
   即模块 flash 0x650000 用户动画区 ÷4096）。
5. 发送：`mt(..., {cmd:80, contentSize:dataPer, data:chunk, headerCount:8, customHeader:F, timeout:2000, responseCmd:65})`
   —— **等应答 cmd = 65（SET_LED_USER_ANIMATION）**，不是 80。
6. **上传前后没有别的步骤**：只有当 `tftConfig.builtInCount > 1` 时，先发一次
   `setTftBuiltInIndex(currentBuiltIn)`（`Gu`：cmd 81，1 字节载荷，contentSize=1）。

### 校时 / 系统信息（都走 cmd 52 = SET_TEMPORARY_COMMAND_DATA）
- `Hu` 屏幕时间：10 B `5A 01 5A yy mm dd hh mi ss wd`（yy=年%100，wd=0..6，周日=0），contentSize=24。
- `ju` 点阵屏时间：`3A 01 5A yy mm dd hh mi ss wd`。
- `Wu` 系统信息：24 B，`[6]=0x5A`，`[12..20]=CPU占用/CPU温度/GPU占用/GPU温度/当前温度/最高/最低/天气码/湿度`。
- 厂商在设备连接时自动发 `setTftDateTime`；`tftDirection===255` 时整个 tft 页面被跳过（无屏机型）。

## 设备信息（`GET_DEVICE_INFO = 16`，48 字节）
`romSize[0]`、`macroSpaceSize[2]|<<8`、`vid[4]`、`pid[6]`、`version`(BCD)、`sensor[10]`、`manufacturer[12]`、
`product[14]`、`workMode[16]`、`batteryLevel[17]`、`chargeStatus[18]`、`currentProfile[19]`、`axisInfo[20]`、
**`tftMaxFrames[22]`、`gifMaxFrames[24]`、`ledMaxFrames[26]`**、`tftDirection[28]`、`rtPrecision[29]`、
`frameVersion[30]`、`lightingVersion[31]`、`firmwareStatus[32]`。

## 机型库（`layout-classic` 内嵌）
带屏机型（`routesName` 含 `"tft"`）已知：YUZII B68 PRO `0x0C45:0x800A` 屏 **96×160**；B68 PRO Max **240×240**；
YUNZII IF75 `0x38A6` **135×240**；`hfd`（前行者）**240×135**、`builtInCount 1`、隐藏时间校准。
`tftConfig` = `{width,height,builtInCount,hideScreenTimeCalibration,isShowTftInfo}`；`localforageKey` 形如 `w96h160`。

## 与 YD-Y65S 的关系（结论）
- YD-Y65S 是 Sinowealth `258a:019d`，厂商 HID 通道 usage page 为 **0xFF02**（不是 0xFFE7），且 `258a:019d`
  不在本例机型库中 ⇒ **这套前端不能直接驱动 YD-Y65S**。
- 但它仍是唯一的同代主机侧协议参考：命令号语义、8 字节包头、分包、延时表/像素格式都能用来比对
  8051 固件解出的主机命令通道。**关键提醒**：ODM 的"每包数据长度 = 设备报告长度 − 8"是**按设备**定的
  （厂商设备 4104 B/包），所以"包长"不能照抄，必须按 YD-Y65S 自己的窗口尺寸推。


## Timeline

- time: 2026-10-19T22:46:33
  kind: decision
  summary: "Created this page: driveall 通用外设协议 (ODM Web 驱动)"
  source: "build/odm (https://yunzii.driveall.cn/)"
  affects: [driveall-protocol]

- time: 2026-10-19T22:46:33
  kind: decision
  summary: "记录 driveall 前端的 HID 报文格式(AA+8字节头+分包)、命令表(含 TFT 80/81、OTA 128-134)与屏幕上传协议(256B延时表+RGB565)"
  source: build/odm/layout-classic-Bylu1MNp.js
  affects: [driveall-protocol]

- time: 2026-10-20T07:54:00
  kind: decision
  summary: "2026-10-20 复核厂商前端 JS（重新下载 build/odm/），把 TFT 上传包头/分包/延时表/像素格式逐字节定死"
  source: "build/odm/layout-classic-Bylu1MNp.js (xn/mt/nu/zu/Hu/Gu/Wu) + tft-DGEkbwnS.js"
  affects: [driveall-protocol]
