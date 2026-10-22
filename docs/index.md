---
layout: home

hero:
  name: YD-Y65S 工具
  text: 屏幕上的音量条，一键修好
  tagline: 键盘屏幕上那条音量条和系统音量对不上（甚至固定显示 100%）——这是厂商固件的转发逻辑问题，不是硬件坏了。
  image:
    src: /logo.svg
    alt: YD-Y65S
  actions:
    - theme: brand
      text: 下载 Windows 版
      link: /how-to
    - theme: alt
      text: 补丁说明
      link: /patches
    - theme: alt
      text: 源码
      link: https://github.com/adam-ikari/y65s_cfw

features:
  - title: 只改 22 个字节
    details: 出厂固件 + 两条可审计的字节级补丁。你的配置、灯效、键位、厂商 app 的设置全部原样保留。
  - title: 先备份，后写入
    details: 动手之前一定先把整片 flash 存成备份文件；写完再读回来逐字节比对，不一致就报错。
  - title: 旋钮照常
    details: 主机侧的系统音量调节完全不受影响（实测旋钮让音量从 50% 变到 48%），只是屏幕不再画那条不对的条子。
---

<div class="downloads">
  <a class="primary" href="https://github.com/adam-ikari/y65s_cfw/releases/latest/download/YD-Y65S-Tool_0.1.0_x64-setup.exe">下载 Windows 安装包</a>
  <a href="https://github.com/adam-ikari/y65s_cfw/releases">全部版本</a>
  <a href="https://github.com/adam-ikari/y65s_cfw">GitHub 仓库</a>
</div>

## 问题是什么

厂商 app 用 Windows 的 `IAudioEndpointVolume` 读系统音量（0.0~1.0），乘以 **100** 下发给键盘；
键盘主控（8051）**原样转发、零限幅**，屏幕模块照着画。键盘自己并不知道真实音量，
于是那条条子和系统音量对不上，甚至在 app 没运行时停在 100%。

音量旋钮在**主控**上（`0x2812` 采 `P4.2`/`P0.7` 正交解码）：它同时做两件事——

- 把 HID consumer 用量 `0xE9`/`0xEA` 发给主机（**系统音量照常增减**）；
- 再把状态字节 `0x81`/`0x82` 通知屏幕模块（屏幕据此画音量条）。

## 修完是什么样

- 屏幕上不再出现那条和系统对不上的音量条；
- 旋钮、键盘上的音量键依然正常调**主机**的系统音量；
- 你的 profile（灯效、模式、音量字段、时钟）、键位表、厂商 app 的设置一个字节没动。

## 下一步

- [怎么修](/how-to) —— 下载、安装、点一下按钮
- [补丁说明](/patches) —— 两条补丁分别改了什么字节
- [常见问题](/faq) —— 会不会丢配置、刷坏了怎么办
