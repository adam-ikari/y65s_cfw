---
id: brain-maintenance
title: "Brain 维护须知 (CRLF 陷阱)"
category: reference
status: active
tags: [brain, tooling, git, crlf]
created: "2026-10-19T18:14:17"
updated: "2026-10-19T18:14:27"
---

<!-- compiled_truth -->
## 症状

`brain update-truth` / `append-timeline` / `set-tags` 在部分页面上不替换已有的 `updated:`，而是**追加**一行，
导致 frontmatter 出现重复键；随后 `list-pages` 把这些页显示为 `(untitled)` / `category: ?` / `status: ?`。

## 根因

* `brain` CLI（`@mindmux/brain-md`，`skills/brain-page/lib/brain.mjs` 的 `setFrontmatterField`）
  用 `^\s*<key>:\s*.*$` 逐行匹配，**写文件时用 LF**。
* JS 正则 `.` 不匹配行终止符，且非多行模式下 `$` 不能匹配结尾的 `\r`。
  因此当文件是 **CRLF** 时，`updated:` 行匹配失败 → CLI 追加而不是替换。
* 本仓库 `core.autocrlf=true` 且**没有** `.gitattributes`，checkout 时把跟踪文件恢复成 CRLF，
  于是每次更新都会再次踩坑（索引里其实是 `i/lf`，工作区是 `w/crlf`）。

## 修复

* 新增 `.gitattributes`：`brain/** text eol=lf`，把 brain 目录在**工作区**钉死为 LF。
* 用一次性脚本 `build/fix_brain.py`（gitignored）把所有 `brain/**/*.md` 归一化为 LF，
  去掉重复 frontmatter 键（保留最后一次/最新），并修复 4 个 title 被损坏成字面量 `"` 的旧页面。
* 之后 `brain reindex`。`list-pages` 恢复正常。

## 维护规则

* 不要手动创建/保存 brain 文件为 CRLF；用 CLI 写入，或确保编辑器按 LF 保存。
* 若再次出现 `(untitled)` / 重复 `updated:`，先检查 `git ls-files --eol brain`
  的工作区 eol 是否为 `w/lf`。
* `title` 目前只能通过 `create-page` 设定，**没有** `set-title`；一旦损坏只能直接修文件
  （超出了 "只用 CLI 写 brain" 的常规约定，属于已知例外）。


## Timeline

- time: 2026-10-19T18:14:17
  kind: decision
  summary: "Created this page: Brain 维护须知 (CRLF 陷阱)"
  source: "本轮排障"
  affects: [brain-maintenance]

- time: 2026-10-19T18:14:27
  kind: decision
  summary: "记录 brain CLI 的 CRLF 陷阱：CRLF 会令 frontmatter 更新退化为追加重复 updated:，用 .gitattributes(brain/** eol=lf) 修复"
  source: "本轮排障 + 复现 setFrontmatterField"
  affects: [brain-maintenance]

- time: 2026-10-19T18:14:27
  kind: note
  summary: "确认 .gitattributes 后 CLI 追加 timeline 不再产生重复 updated 键"
  source: "验证"
  affects: [brain-maintenance]
