# 文档归档

本目录保存历史快照，仅用于追溯，**不代表当前状态**。现行事实以下列文档为准：

完整的按主题文档导航见 [`../README.md`](../README.md)。

| 主题 | 现行文档 |
|------|----------|
| 功能、安装、用法 | [`../../README.md`](../../README.md) |
| 无硬件自检与质量门禁 | [`../verify.md`](../verify.md) |
| 协议与寄存器 | [`../protocol.md`](../protocol.md) |
| 需求溯源 | [`../requirements-traceability.md`](../requirements-traceability.md) |
| 当前缺陷与修复台账 | [`../../bug-audit/BUG_TRACKER.md`](../../bug-audit/BUG_TRACKER.md)、[`../../bug-audit/FIX_LOG.md`](../../bug-audit/FIX_LOG.md) |
| 当前发布判断 | [`../../bug-audit/RELEASE_READINESS.md`](../../bug-audit/RELEASE_READINESS.md) |
| Agent 任务台账 | [`../agent-progress/LEDGER.md`](../agent-progress/LEDGER.md) |

## 本归档内容

| 路径 | 内容 |
|------|------|
| `DEV_PROGRESS.md` | 截止 1.0.1 的开发进度流水账（原仓库根目录） |
| `新增功能指令与预览.md` | v1.0.0 时代的命令输出预览（原 `docs/`；标题即声明为历史快照） |
| `audit/CODE_AUDIT.md` | Phase 5 代码审计快照（原 `bug-audit/`） |
| `audit/TEST_REPORT.md` | Phase 5 审计测试报告快照（原 `bug-audit/`） |
| `testing/` | 2026-10 各阶段测试计划、用例、报告、差距分析与发布快照（原 `docs/testing/`） |

## 整理说明（2026-10-27）

- `DEV_PROGRESS.md` 的通过数/覆盖率引用冻结在记录时刻，不随当前代码更新；
  当前测试和门禁证据以 [`bug-audit/RELEASE_READINESS.md`](../../bug-audit/RELEASE_READINESS.md) 与 CI 为准。
- `新增功能指令与预览.md` 是 v1.0.0 的输出快照，不是当前 CLI 参考；当前输出以
  `--help`、[`../verify.md`](../verify.md) 和 README 为准。
- Phase 5 的 `CODE_AUDIT.md` / `TEST_REPORT.md` 只用于追溯当时的审计结论，当前缺陷与
  修复记录在 [`../../bug-audit/BUG_TRACKER.md`](../../bug-audit/BUG_TRACKER.md) 与
  [`../../bug-audit/FIX_LOG.md`](../../bug-audit/FIX_LOG.md)。
- 归档文件保留原内容与相对链接（链接已按新位置修正），不随当前代码更新。
- `docs/testing/` 已整体移入本目录（原样保留其内部索引与证据文件）；现行测试与发布结论以
  [`../verify.md`](../verify.md) 与
  [`../../bug-audit/RELEASE_READINESS.md`](../../bug-audit/RELEASE_READINESS.md) 为准。
