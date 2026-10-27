# 文档归档

本目录保存历史快照，仅用于追溯，**不代表当前状态**。现行事实以下列文档为准：

| 主题 | 现行文档 |
|------|----------|
| 功能、安装、用法 | [`../../README.md`](../../README.md) |
| 无硬件自检与质量门禁 | [`../verify.md`](../verify.md) |
| 协议与寄存器 | [`../protocol.md`](../protocol.md) |
| 需求溯源 | [`../requirements-traceability.md`](../requirements-traceability.md) |
| 当前缺陷与修复台账 | [`../../bug-audit/BUG_TRACKER.md`](../../bug-audit/BUG_TRACKER.md)、[`../../bug-audit/FIX_LOG.md`](../../bug-audit/FIX_LOG.md) |
| 当前发布判断 | [`../../bug-audit/RELEASE_READINESS.md`](../../bug-audit/RELEASE_READINESS.md) |

## 内容

| 路径 | 内容 |
|------|------|
| `DEV_PROGRESS.md` | 截止 1.0.1 的开发进度流水账（原仓库根目录） |
| `testing/` | 2026-10-19 至 10-22 的分阶段测试计划、用例、报告、差距分析与证据文件 |
| `audit/CODE_AUDIT.md` | Phase 5 代码审计快照 |
| `audit/TEST_REPORT.md` | Phase 5 测试报告快照 |

## 整理说明（2026-10-27）

- `docs/testing/fix-log.md`、`docs/testing/release-readiness.md` 与 `bug-audit/FIX_LOG.md`、
  `bug-audit/RELEASE_READINESS.md` 内容重复，已删除；需要旧版本时从 git 历史取回。
- `docs/新增功能指令与预览.md`（v1.0.0 的命令输出预览）已过时，已删除；当前输出以
  `README.md` 与 `docs/verify.md` 为准。
- 归档文件中的相对链接已按新位置修正，文档内容本身保持原样（不随当前代码更新）。
