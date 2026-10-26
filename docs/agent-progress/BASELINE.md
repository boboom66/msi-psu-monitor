# BASELINE — before Product v2

## Repository state

| Item | Value |
|---|---|
| Original worktree | `C:\Users\timzhang\Desktop\project\msi-psu-monitor` |
| Product v2 worktree | `C:\Users\timzhang\Desktop\project\msi-psu-product-v2` |
| `master` | `ca8a6d5` (clean) |
| Preserved work | `wip/pre-agent-2026-10-26` @ `6a0191f` |
| Integration branch | `work/product-v2` @ `6a0191f` |
| Version | `1.0.1` (`pyproject.toml`) |
| Remotes | `origin` = upstream; `fork` = `boboom66/msi-psu-monitor` |

`6a0191f` contains 29 files, +3689/−62: the user's uncommitted feature work plus
the two Product v2 planning docs. The original 32-file diff included 11 scripts
whose only change was a lost executable bit; those modes are now normalized in
the index and the content diff is 21 files.

## User-added features carried into Product v2

| Feature | Entry point | Files | Status |
|---|---|---|---|
| Terminal dashboard | `--dashboard-text` | `msi_psu_monitor/termdash.py`, `monitor.py` | Present; needs UX review |
| Interactive menu | `--menu` | `msi_psu_monitor/menu.py`, `monitor.py` | Present; overlaps with dashboard/watch |
| ANSI live redraw for watch | `--watch` on a TTY | `monitor.py` | Present; needs cursor/signal review |
| Local threshold alerts | `[alerts]` | `alerts.py`, `config.py` | Present; needs UX/copy review |
| OCP threshold write | `--ocp-set`, `--load-thresholds`, `--dump-thresholds` | `protocol.py`, `monitor.py` | Present; hardware write unproven |
| Live dashboard aliases | `/api/live` | `dashboard.py` | Present; needs stale/empty state review |
| Handshake retry | init | `protocol.py` | Present |
| Alert log viewer | `--show-alert-log` | `monitor.py`, `state.py` | Present |
| Hardware kit / packaging | scripts | `scripts/` | Present; install path unproven |
| New tests | — | `tests/test_dashboard_text.py`, `test_menu.py`, `test_watch_console.py` | Present; not run here |

## Existing feature surface (for Phase 1 inventory)

- Acquisition: `--once`, `--watch`, `--format`, `--output`, `--serial`
- Interaction: `--dashboard-text`, `--menu`, `--watch` redraw
- Web: `--dashboard`, `--port`, `/api/live`
- History/export: `--export`, `--from`, `--columns`, `daily-*.log`, `state.json`
- Alerts: E1h, `[alerts]`, `--show-alert-log`, exit 2, daemon alert log
- Control: `--fan-mode`, `--fan-duty`, `--zero-fan`, `--buzzer-off`, `--set-rail`
- OCP: `--ocp`, `--dump-thresholds`, `--ocp-set`, `--load-thresholds`, `--show-log`
- Operations: daemon, Prometheus, alert rules, `--dump-config`, systemd/udev
- Delivery: `.deb`, tarball, binary, hardware kit, install/uninstall, demo
- Support: `--help`, `--version`, docs, troubleshooting

## Documentation-count discrepancy

| Source | Count | Nature |
|---|---|---|
| `AGENTS.md` (before edit) | 859 | Current instruction |
| `msi_psu_monitor/AGENTS.md` (before edit) | 859 | Current instruction |
| `bug-audit/RELEASE_READINESS.md` | 803 | 2026-10-22 audit snapshot |
| `docs/testing/release-readiness.md` | 645 | Historical Phase 3 snapshot |
| `docs/verify.md` | 859 | Historical run note |

The current tree's count is **unverified** because no Linux environment is
available. Current instructions now say "run for current count"; historical
snapshots keep their dates. After G0, record the measured count here.

## Release blockers (from the existing readiness document)

- Real-hardware acceptance for 5 models.
- OCP threshold write: dump → write → read-back → power-cycle → restore.
- Root/systemd/udev install/start/stop on a real host.
- arm64 execution (CI build only).
- 24h/72h soak.
- Official 22.04/arm64 artifacts and publication.
- Prometheus naming-policy warnings (accepted debt or fix).
- `Development Status :: 4 - Beta`; ruff `E,F`; mypy non-strict.

## What is not verified

- The 859/803 test counts.
- The new `--dashboard-text`/`--menu`/watch tests.
- Any UX claim from code inspection alone.
- Any hardware write or real-device behavior.
- The CI guard added in T-005 (not executed yet).
