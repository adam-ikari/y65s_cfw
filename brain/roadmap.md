---
slug: roadmap
title: Roadmap
role: milestones
updated: "2026-10-19T16:47:41"
---

# Roadmap

## Milestones

```mermaid
gantt
  title YD-Y65S 固件逆向与自制固件
  dateFormat YYYY-MM-DD
  axisFormat %m-%d
  section 已完成
  设备识别与 ISP 提取 (dump + 校验)        :done, a1, 2026-10-17, 1d
  工具链迁移到 Python (反汇编/SFR/USB)     :done, a2, after a1, 1d
  USB 描述符与 ISP 跳转桩定位              :done, a3, after a2, 1d
  section 进行中
  矩阵行列引脚与键位表解析                 :active, b1, 2026-10-19, 3d
  LED 驱动方式确认 (PWM bank vs 外置 IC)   :b2, after b1, 2d
  section 待开始
  Windows 构建环境 (SDCC + meson)          :c1, after b2, 2d
  新建 yd-y65s 板级目录并编译出 hex        :c2, after c1, 3d
  仿真验证 (ucsim-sh68f90)                 :c3, after c2, 3d
  写入验证 (需用户明确许可)                :crit, c4, after c3, 1d
```

## 当前状态

* **已完成**：完整 64 KiB dump（MD5 已记录）、bootloader 校验、Python 分析工具链、
  中断向量表、USB 描述符全解、ISP 协议与跳转桩、键位表区域定位。
* **进行中**：矩阵扫描例程 `0x35E8` 的 10 个入口与引脚映射关系；
  `0xBC00-0xCC00` 的 4 字节记录格式。
* **阻塞**：无。
* **红线**：写入验证必须等用户明确许可。
