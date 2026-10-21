# Code audit — Phase 5

## 1. Scope actually read

| Area | Files | Size |
|---|---|---|
| Package | `msi_psu_monitor/{protocol,monitor,state,daemon,dashboard,alerts,config,demo,__init__,__main__}.py` | 5 525 lines (all read end to end) |
| Tests | all 24 `tests/test_*.py` modules | 7 355 lines (read; validity sampled and probed with mutation-style checks) |
| Scripts | `scripts/*.sh`, `scripts/hardware/*.sh`, `scripts/build_sbom.py` | read |
| Packaging | `pyproject.toml`, `systemd/*`, `.github/workflows/*`, `docs/msi-psu-monitor.conf.example` | read |
| Docs | README, AGENTS files, docs/*.md (verify/protocol/release/support/incident) | read for behavior claims |

Not audited here: `kernel/` (out-of-tree draft, explicitly unbuildable in this environment),
`uv.lock` internals, historical Phase evidence files.

## 2. Architecture and call chains checked

- **CLI**: `argparse → _validate_args → load_config → resolve_format → resolve_device →
  open_psu → init → (write | show-log | ocp | watch | once) → formatter → emit → exit code`.
- **Sample path**: `MSIPSU.get_sensors → 0xE0 payload gate → per-variant decode → read_vin`;
  enrichment: `read_fan_fields → collect_alerts (E1h ∪ pin mirror) → apply_stats → state.save`.
- **Daemon**: `tick → _ensure_psu (discovery throttle) → sample → failure counter/rescan →
  prometheus write/failure write → history+state → hourly prune`.
- **Dashboard**: single `_route()` for GET/HEAD → Host/CSP gate → file readers
  (`iter_history`, `read_live_snapshot`, `MonitorState.load(strict=True)`) → JSON/CSV.
- **Shared contracts**: sensors dict shape; `HISTORY_COLUMNS`; `EXIT_*`; `have_e1h`;
  `retain()` model-swap semantics; atomic-write rule; one synthetic data path (`demo`).

## 3. Why the found bugs were invisible to the existing suite

- DEF-022: every output test used a regular file or a non-existent path; no test created a
  symlink, and `/dev/stdout` only misbehaves when stdout is a regular file.
- DEF-023: HTTP tests asserted the `/api/live` body keys (raw sensor names) and the page text,
  but never executed the page JS nor compared the two key vocabularies.
- DEF-024: failure-injection tests covered sample/enrichment/history/prometheus, but the prune
  block (left unguarded) had no exception test.
- DEF-025: tests covered "E1h unanswered" and "model swap", but not "payload failed while E1h
  answered" — the only combination where a mirror alert loses its evidence.
- DEF-026/DEF-027: tests assert script contents, not what the scripts derive from
  `pyproject.toml`/the host; the hardcoded numbers were never exercised.
- DEF-029: the API contract (last-N lines) was tested; the memory behaviour of materialising
  every line first was not.
- DEF-031: tests always pointed the server at an existing state directory and only tested
  `/nope`, never an unknown `/api/` path without state.

## 4. Areas reviewed and found sound (so far)

- LINEAR11 decode pattern and per-variant dispatch, payload gates (44/40/20), NAK framing
  (including 0xFE as a payload byte), and the truncated TS-name refusal.
- `AlertEngine` debounce/edge/retain/take_cleared logic (except DEF-025's source-mixing),
  per-model E1h bit order, per-connector imbalance rule and its strict `> 5 A` boundary.
- Atomic state/prometheus writes (fsync + rename + dir fsync), history header repair,
  BOM/locale handling, energy integral freeze on gaps/backwards clock.
- Config precedence and range fallbacks (interval/port/retention/fan), empty/invalid file
  handling; unknown option/section warnings.
- Dashboard Host check, CSP/Permissions-Policy, HEAD/GET parity, CSV quoting, stale live 503,
  dir/file readability diagnostics, idle keep-alive timeout.
- EXIT code contract (0/1/2, argparse 2), stdout/stderr separation, broken-pipe and ENOSPC
  handling.
- Packaging invariants: no runtime Python for official artifacts, glibc floor, conffile,
  udev/unit hardening, shellcheck/systemd/udev validation, SBOM/checksums.

## 5. Remaining risk / not fully verifiable here

- Real hardware protocol behaviour (timing, per-model payload lengths, VIN scale, black-box
  pin/set byte meaning, write persistence across AC loss) — needs the acceptance kit.
- Prometheus text parser acceptance of the `metric {} value` spelling (NR-001).
- Concurrency: the daemon is single-threaded and the dashboard is read-only over atomically
  replaced files; a 300-sample concurrent hammer found no issue, but that is not proof for
  long-running mixed workloads on slow/network filesystems.
- systemd sandbox (`CapabilityBoundingSet=`, `Protect*`) has only been statically verified.
- Windows/macOS are out of scope (Linux hidraw only).
