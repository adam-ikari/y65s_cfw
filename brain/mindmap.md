---
slug: mindmap
title: Feature mindmap
role: feature mindmap
updated: "2026-10-19T16:47:42"
---

# Feature mindmap

## 功能脑图

```mermaid
mindmap
  root((YD-Y65S 固件))
    固件提取
      ISP 进入 (report 5 = 05 75)
      页读取 (report 6, 2048B)
      退出 (0x5a reboot)
      校验 (MD5 / bootloader 3e0ebd0c)
    静态分析
      反汇编 (MCS-51 表驱动)
      中断向量表 (13 项)
      SFR 交叉引用 (SMK 权威命名)
      XSFR / PWM bank
      MOVC 查表基址
      端口访问 (矩阵扫描)
    固件结构
      USB 描述符 (设备/配置/字符串/HID)
      8 个 HID collection
      ISP 命令分发 (0x82EA)
      ISP 跳转桩 (0xB0ED)
      键位表 (0xBC00-0xCC00)
      版本串 (0x7D82)
    自制固件
      SMK 移植
        SH68F90 HAL
        USB HID 栈
        键扫 + 去抖
        LED PWM
        BK3632 无线
      板级适配
        矩阵行列引脚
        LED 驱动映射
        布局与键位
      安全
        保留 ISP 逃生通道
        硬件编程器兜底
```
