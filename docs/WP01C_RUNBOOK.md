# WP-01C 完成运行手册

状态：历史完成记录。

## 基线

```text
起始 docs 基线：e44855d0256234724b9320122454da0d25be13d1
实现：29a042f7b9fc80d3356cd5c63df1cd26b4078d9b
标签：wp01c-stable
```

## 流程

```text
只读设计
→ 协议冻结
→ Codex 实现
→ Mac 测试
→ 完整 patch/报告
→ 独立审查
→ 聚焦修复
→ 最终复核
→ main 发布
→ A100 fast-forward 验收
→ 稳定标签和 docs-only 收尾
```

## 最终验收

```text
Mac：421 passed
GitHub Actions：CPU checks #7 success
A100：421 passed in 16.54s
```

## 发布器经验

若两份完整 patch 仅 Diff 段顺序不同，raw SHA 会不同。后续发布器应使用稳定文件排序或 canonical per-file digest；不得仅因顺序差异绕过内容比较。

## 后续

进入 WP-02 只读设计，不修改 WP-01 v1 外部协议。
