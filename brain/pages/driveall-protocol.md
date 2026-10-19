---
id: driveall-protocol
title: "driveall 通用外设协议 (ODM Web 驱动)"
category: reference
status: active
tags: [odm protocol screen hid]
created: "2026-10-19T22:46:33"
updated: "2026-10-19T22:46:33"
---

<!-- compiled_truth -->
ODM 通用外设协议（全称：driveall.cn 平台 Web 驱动协议）。它是**同代 ODM 键盘的完整主机侧协议参考实现**，可用于比对/推断 YD-Y65S 自己的主机命令通道。

## 来源与产物
- 来源：`https://yunzii.driveall.cn/`（Vite SPA，WebHID + wasm-bindgen）。已拉到 `build/odm/`：
  - `main-BnbZC7tT.js`（入口，2 KB）
  - `vendor-xxmc0x-d.js`（1.4 MB：GIF 解码器、md5、wasm-bindgen 胶水，含 `sendFeatureReport`/`receiveFeatureReport` 导入）
  - `layout-classic-Bylu1MNp.js`（770 KB：**协议实现 + 机型库 + i18n**）
  - `tui-image-editor-DuvR5kck.js`（图像编辑器）
  - `tft-DGEkbwnS.js`（屏幕编辑页 UI，9 KB，`assets/` 下同名可下载）
- 同平台/同类设备：YUNZII、前行者 HFD、狼蛛 `hea.aulacn.com`、达尔优 `qd.dareu.com`；本地服务固定 `http://127.0.0.1:9191`（`/api/keyboard/layout/base64`、`/api/keyboard/musiceffect`、`/api/audio/amplitude`、`/api/hardware/info`）。

## 传输层
- WebHID；设备匹配 = 某 collection 的 `usagePage === 0xFFE7` 且 `productId` 相符（`navigator.hid.getDevices()` 后用 `open()`）。
- 每包 = **8 字节头 + N 字节数据**；解析 `{header:[0], cmd:[1], lenOrType:[2], addr:[3]|[4]<<8, data:slice(8)}`，头字节不符会打印「数据包头错误:0x..」。
- 单包数据长度 = `输出报告 reportCount(bits)/8 - 8`；默认 `reportCount = 4104` bits（513 B）⇒ **505 字节/包**。
- 屏幕动画实测发送头：`AA <cmd> <idx_lo> <idx_hi> <total_lo> <total_hi> 50 06`（header=0xAA；分包序号 LE16；分包总数 LE16；常量 `6619136/4096 = 1616 = 0x0650` LE16）。
- 另有 CRC16-CCITT（poly 0x1021，init 0xFFFF）与 `COMMUNICATION_START(1)/COMMUNICATION_END(2)` 会话包裹。
- 应答等待：监听 `inputreport`，按 `cmd`（可选 `addr`）匹配；超时默认 50 ms，写操作 2000 ms；写命令支持 `maxRetries`。

## 命令号（`Je`，layout-classic 内嵌，十进制）
1 COMMUNICATION_START / 2 COMMUNICATION_END / 15 SET_FACTORY_RESET / 16 GET_DEVICE_INFO / 17 GET_GAME_MODE / 18 GET_KEY / 19 GET_LED_EFFECT / 20 GET_CUSTOM_LED_DATA / 21 GET_MACRO / 22 GET_FN_KEY / 27 GET_LIGHT_BOX / 29 GET_SIDE_LIGHT / 31 GET_DEFAULT_KEY_MATRIX / 33 SET_GAME_MODE / 34 SET_KEY / 35 SET_LED_EFFECT / 36 SET_CUSTOM_LED_DATA / 37 SET_MACRO / 38 SET_FN_KEY / 42 SET_DOT_MATRIX_MODE / 43 SET_LIGHT_BOX / 46 SET_TRIGGER_KEY / 48/49 自定义功能开关 / 50 GET_LED_DATA / 51 GET_ALL_LIGHTS_RGB / 52 SET_TEMPORARY_COMMAND_DATA / 53 SET_MUSIC_DATA / 54 CLEAR_LED_DATA / 55 GET_ALL_LIGHTS_RGB_24G / 59/60 24G 64 字节变体 / 61 GET_DOT_MATRIX_CONFIG / 64 SET_LED_BOOT_ANIMATION / 65 SET_LED_USER_ANIMATION / 66 SET_LED_DATA / 79 SET_FLASH_DOWNLOAD / **80 SET_TFT_USER_ANIMATION** / **81 SET_TFT_BUILT_IN_INDEX** / 96 磁轴状态 / 100–106 校准、仿真 / **128 OTA_GET_DEVICE_SYSTEM_INFO** / **129 OTA_VERIFY_FIRMWARE_INFO** / **130 OTA_DEVICE_ENTER_BOOT** / **131 OTA_SEND_FIRMWARE_INFO** / **132 OTA_GET_DEVICE_SN** / **133 OTA_SWITCH_APP_PARTITION** / **134 OTA_SET_DEVICE_SN** / 250 GET_DEVICE_NOTIFY / 251 磁轴校准数据 / 252 2.4G 断连通知。

## 设备信息（`GET_DEVICE_INFO = 16`，48 字节）
`romSize[0]`、`macroSpaceSize[2]|<<8`、`vid[4]`、`pid[6]`、`version`(BCD: `(([8]&15)+(([8]&240)>>4)*10+[9]*100)/100`)、`sensor[10]`、`manufacturer[12]`、`product[14]`、`workMode[16]`、`batteryLevel[17]`、`chargeStatus[18]`、`currentProfile[19]`、`axisInfo[20]`、**`tftMaxFrames[22]`、`gifMaxFrames[24]`、`ledMaxFrames[26]`**、`tftDirection[28]`、`rtPrecision[29]`、`frameVersion[30]`、`lightingVersion[31]`、`firmwareStatus[32]`。

## TFT（小屏）内容协议 —— `SET_TFT_USER_ANIMATION = 80`
payload = **256 字节延时表 + RGB565 像素流**（连续字节流，被 505 字节分包切分）：
- 延时表 `g`：`g[0] = 帧数 n`；`g[1..n-1] = delay*5`（GIF/视频逐帧延时）；`g[n] = 0`；其余填 `0xFF`。
- 像素：逐帧 `width*height` 像素，**RGB565 小端 2 字节/像素**（canvas `getImageData` → RGB → 565 → `[lo,hi]`）。
- 尺寸来自机型 `tftConfig.width/height`；帧数上限 `tftMaxFrames`（超出需用户确认）。
- 等应答 `cmd = SET_LED_USER_ANIMATION (65)`（实现中的 `responseCmd`）。
- 多内置位图机型先发 `SET_TFT_BUILT_IN_INDEX (81)`（1 字节槽号）；`builtInCount > 1` 时 UI 显示「内置 N」。
- 校时 `setTftDateTime` = `"YYYY-MM-DD HH:mm:ss"` + 星期；部分机型 `hideScreenTimeCalibration`/`isShowTftInfo`。
- 屏幕页仅在**有线（USB）模式**可见；2.4G 睡眠时前端显示 sleeping-tips（`is24GSleeping`）。

## 机型库（layout-classic 内嵌）
条目形如 `{vendorId, productId, supplierName, name, connectType, routesName, keyboardImg, customKeysConfig, lightingConfig, musicConfig, macroConfig, tftConfig, settingsConfig, keyList, ...}`；`routesName` 含 `"tft"` 才有屏幕页。已知带屏机型：
- YUZII B68 PRO：`vendorId 3141 (0x0C45)`、`productId 32778 (0x800A)`，屏幕 **96×160**
- YUZII B68 PRO Max：**240×240**
- YUNZII IF75：`vendorId 14502 (0x38A6)`，**135×240**
- `hfd`（前行者）：**240×135**，`builtInCount 1`，隐藏时间校准
`localforageKey` 形如 `w96h160`，前端把用户 GIF 按分辨率缓存在浏览器本地。

## 与 YD-Y65S 的关系（结论）
- YD-Y65S 是 Sinowealth `258a:019d`，其厂商 HID 通道 usage page 为 **0xFF02**（不是 0xFFE7），且 `258a:019d` 不在本例机型库中 ⇒ **这套前端不能直接驱动 YD-Y65S**。
- 但它是同代 ODM 的完整协议参考：命令号语义、8 字节头 + 分包、延时表/像素格式都可以用来比对 8051 固件里解出的主机命令通道（`xdata[0x0B91]` 起的命令字节，见 [[firmware-layout]]）。


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
