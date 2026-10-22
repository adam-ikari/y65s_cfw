---
layout: home

hero:
  name: YD-Y65S 工具
  text: 屏幕上的音量条，一键修好
  tagline: 屏幕上那条音量条和系统音量对不上（甚至固定 100%）。这是厂商固件的转发逻辑问题，改 22 个字节就好。
  image:
    src: /logo.svg
    alt: YD-Y65S
  actions:
    - theme: brand
      text: 下载 Windows 版
      link: /how-to
    - theme: alt
      text: 源码
      link: https://github.com/adam-ikari/y65s_cfw

features:
  - title: 只改 22 字节
    details: 出厂固件 + 两条可审计的字节级补丁，配置、灯效、键位全保留。
  - title: 先备份后写入
    details: 动手前存一份整片 flash 备份，写完读回逐字节校验。
  - title: 旋钮照常
    details: 主机音量照常增减，只是不再往屏幕上画那条不对的条子。
---

<div class="downloads">
  <a class="primary" href="https://github.com/adam-ikari/y65s_cfw/releases/latest/download/YD-Y65S-Tool_0.1.0_x64-setup.exe">下载 Windows 安装包</a>
  <a href="https://github.com/adam-ikari/y65s_cfw/releases">全部版本</a>
  <a href="https://github.com/adam-ikari/y65s_cfw">GitHub</a>
</div>

## 为什么不对

厂商 app 把系统音量乘以 100 下发给键盘，键盘主控**原样转发、零限幅**，屏幕照着画 ——
键盘并不知道真实音量。旋钮在主控上，转动时既发 HID consumer（主机音量照常变），
又通知屏幕画条子。补丁把这两条"通知屏幕"的路径都切掉。

[补丁说明](/patches) · [常见问题](/faq)
