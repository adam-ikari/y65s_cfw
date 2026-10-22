---
title: 怎么修
---

# 怎么修

只需要一个 **Windows 桌面程序**（其它平台暂时没有）。

## 1. 下载

<div class="downloads">
  <a class="primary" href="https://github.com/adam-ikari/y65s_cfw/releases/latest/download/YD-Y65S-Tool_0.1.0_x64-setup.exe">下载 YD-Y65S-Tool（Windows 安装包）</a>
  <a href="https://github.com/adam-ikari/y65s_cfw/releases">全部版本</a>
</div>

安装包是 NSIS 格式：双击 → 一路下一步 → 装完。装完在开始菜单里能找到
「YD-Y65S 键盘工具」。

::: tip 备用下载
GitHub 的下载有时会跳转到 `objects.githubusercontent.com` 被网络挡掉。
站点上也留了一份出厂固件镜像（[下载](/YD-Y65S_factory_volume_fixed.bin)），
可以用它手工刷。
:::

## 2. 接上键盘

插上键盘的 USB 线。工具首页会显示键盘的 HID 集合（正常是 9 个）。

## 3. 点一下

打开工具 → 左侧 **固件** 页 → 最上面那张卡 **「一键修复音量条」** → 点按钮。

工具会按固定顺序做这几步，每一步都在界面下方打印日志：

```
读出整片 flash（64 KiB）→ 存一份备份 → 打两条字节级补丁
→ 擦除应用区 → 写入 → 读回逐字节校验 → 重启
```

::: warning 写入过程中不要拔线
擦除和写入大约十几秒。这段时间里不要拔 USB 线、不要按键盘上的复位键。
:::

## 4. 看结果

- 最后一行是 `读回逐字节一致 ✓` ⇒ 成功，键盘已重启回应用模式；
- 屏幕上那条不对的音量条没了；
- 转一下旋钮，主机音量照常变化。

备份文件在**当前工作目录**下，叫 `YD-Y65S_backup_<时间戳>.bin`（64 KiB）。
留着它 —— 万一以后要回退，直接用工具的「固件」页把它刷回去。

## 想手动刷出厂固件

工具的「固件」页还可以把整片 flash 备份/刷回任意镜像：

- **备份整片 flash**：只读，不写任何东西；
- **刷回这个镜像**：先擦除应用区（`0x0000`–`0xEFFF`）再写入，bootloader 区
  （`0xF000`–`0xFFFF`）不碰。

出厂固件 + 音量条修复的镜像在这里：
[YD-Y65S_factory_volume_fixed.bin](/YD-Y65S_factory_volume_fixed.bin)
（md5 `4322b1c5b5d18ecd3644241637b1630f`，与出厂 dump 恰好差 22 字节）。

::: warning 注意
刷这个镜像会把 profile 换回**出厂值**（灯效、模式等回到默认）。
只想修音量条的话，用「一键修复音量条」——它在**你自己这块键盘**的固件上打补丁，
不动 profile。
:::
