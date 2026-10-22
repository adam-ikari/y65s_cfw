---
title: 怎么修
---

# 怎么修

<div class="downloads">
  <a class="primary" href="https://github.com/adam-ikari/y65s_cfw/releases/latest/download/YD-Y65S-Tool_0.1.0_x64-setup.exe">下载 Windows 安装包</a>
  <a href="https://github.com/adam-ikari/y65s_cfw/releases">全部版本</a>
</div>

安装包是 NSIS 格式：双击，一路下一步。装完在开始菜单里找「YD-Y65S 键盘工具」。

1. 插上键盘的 USB 线（首页会显示 9 个 HID 集合）。
2. 左侧 **固件** 页 → 最上面那张卡 **「一键修复音量条」** → 点按钮。
3. 等十几秒，最后一行是 `读回逐字节一致 ✓` 就成了。

::: warning
写入过程中不要拔线。
:::

工具会：读出整片 flash → 存一份备份 → 打补丁 → 擦除写入 → 读回校验 → 重启。
备份在当前目录的 `YD-Y65S_backup_*.bin`（64 KiB），留着它。

## 手动刷

「固件」页还能备份整片 flash、把任意镜像刷回去（只擦应用区 `0x0000`–`0xEFFF`，
bootloader 不碰）。

出厂固件 + 修复的镜像：[YD-Y65S_factory_volume_fixed.bin](/YD-Y65S_factory_volume_fixed.bin)
（md5 `4322b1c5b5d18ecd3644241637b1630f`）。

::: warning
刷这个镜像会把 profile 换回出厂值。只想修音量条就用「一键修复音量条」——
它在你自己这块键盘的固件上打补丁，不动 profile。
:::
