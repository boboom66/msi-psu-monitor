# FEATURE PORTFOLIO — proposal for G1

Status: **PROPOSED**, awaiting G1 approval.
Baseline: `baseline-2026-10-26-r2` (`a21f971`), CI run `40290163974`, automated
gates green; full feature matrix AMBER.

## How to read this

- **Decision**: Keep / Improve / Replace / Remove.
- **Priority**: P0 safety/release, P1 core UX, P2 polish, P3 optional.
- A feature is not "done" because code exists; it must pass the user journey and
  have evidence. The baseline report lists the gaps.

## Portfolio

| ID | Feature | User job | Baseline status | Decision | Priority | Next action |
|---|---|---|---|---|---|---|
| F-01 | CLI help/entry | Find the right command | Automated tests pass; flat 25+ flags | **Improve** | P1 | Grouped help + examples; no flag removal |
| F-02 | Device discovery | Pick the right PSU | `--serial` only | **Improve** | P1 | `--list` table, `--device`, safe default |
| F-03 | One-shot text | Read the PSU at a glance | Smoke passes | **Keep** | P1 | Golden-output polish only |
| F-04 | JSON | Script the readings | Smoke passes | **Keep** | P2 | Add schema version, keep keys |
| F-05 | Watch | Watch live in a terminal | Automated pass; TTY capture missing | **Improve** | P1 | Cursor restore, JSONL decision, PTY test |
| F-06 | `--dashboard-text` | No-browser live view | Unit tests pass; PTY capture missing | **Improve** | P1 | 80x24/120x40 capture, keys/footer, resize |
| F-07 | `--menu` | Discover commands without flags | Unit tests pass; overlaps watch/dashboard | **Replace or Improve** | P2 | Decide: launcher role, merge, or remove |
| F-08 | Web dashboard | See history/trends in a browser | HTTP smoke passes; visual states missing | **Improve** | P1 | Empty/stale/error banner, time range, responsive |
| F-09 | Export CSV | Report/share data | Smoke covers export | **Improve** | P1 | `--to`, `-O -`, timezone, column validation |
| F-10 | Alerts | Understand and act on a warning | Alert paths pass | **Improve** | P1 | measured vs limit, source, next command, recovery |
| F-11 | Local thresholds | Early warning before hardware trip | Config/alerts tests pass | **Keep + Improve** | P1 | Units/defaults docs, validation, `--doctor` |
| F-12 | Alert log viewer | See what happened | Smoke/pytest pass | **Improve** | P2 | `--since`, `--limit`, `--json` |
| F-13 | Fan control | Set/verify fan mode | Smoke passes | **Improve** | P1 | Dry-run, current-vs-requested, consistent verbs |
| F-14 | Zero Fan | Toggle Zero Fan safely | Smoke passes | **Improve** | P1 | Dry-run, model gate, read-back wording |
| F-15 | Buzzer | Toggle the OCP buzzer | Smoke passes; name is misleading | **Replace** | P1 | Rename to `--buzzer-toggle`; keep alias; never say "off" |
| F-16 | Multirail | Switch rail protection | Partial (needs dedicated check) | **Improve** | P1 | Dry-run, current mode, dedicated smoke |
| F-17 | OCP read | Inspect thresholds/state | Smoke passes | **Keep** | P1 | Units/table polish |
| F-18 | OCP write | Change protection thresholds | Range/read-back tested; no dry-run/backup UX | **Improve** | **P0** | `--dry-run`, backup, restore, confirmation, bench plan |
| F-19 | Black box | Inspect trip history | Smoke passes | **Keep + Improve** | P2 | Empty state, filters, JSON |
| F-20 | Daemon | Run 24/7 | Daemon/prom/history smoke passes | **Keep + Improve** | P1 | Startup log, `--doctor`, signal/restart tests |
| F-21 | Prometheus | Integrate with monitoring | Strict parser passes; promtool not in CI | **Improve** | P1 | `info`/`up`, naming decision, promtool check |
| F-22 | Config | Configure once | Config tests pass | **Improve** | P1 | Unknown-key warnings, validation, source in dump |
| F-23 | systemd/udev/install | Install on a real host | Scripts build; root path unproven | **Improve** | P1 | `--dry-run`, post-install check, uninstall test |
| F-24 | Packaging | Install/upgrade/uninstall | Deb/binaries/no-Python pass in CI | **Keep + Improve** | P1 | Man page/completions optional; upgrade test |
| F-25 | Demo | Try without hardware | Demo tests pass | **Keep + Improve** | P2 | `--demo` alias, clear labeling |
| F-26 | Diagnostics | Diagnose permissions/state | Missing | **Add** | P1 | `--doctor` + diagnostics bundle |
| F-27 | Version/rollback | Know what is installed | `--version` passes | **Keep + Improve** | P2 | Build info, rollback docs |
| F-28 | README/quick start | Get to first reading in 5 min | README long; no timed test | **Improve** | P1 | 3-command quick start, screenshots, timed check |
| F-29 | Accessibility | Use at 80x24/320px/no color | Unit coverage only | **Improve** | P2 | NO_COLOR, 80x24, 320px, color+symbol |
| F-30 | Support | Report a bug with context | Basic | **Improve** | P2 | Issue template, troubleshooting, diagnostics |

## Top five improvement themes

1. **CLI discoverability and grammar** (F-01, F-02, F-26)
   Grouped help, `--list`, `--doctor`; keep existing flags as aliases.
2. **Safe write UX** (F-18, F-13, F-14, F-16, F-15)
   Dry-run, current-vs-requested, confirmation, read-back, restore.
3. **Visual state quality** (F-05, F-06, F-08)
   PTY captures, empty/stale/error banners, responsive layout, keyboard exits.
4. **Naming and copy consistency** (F-10, F-15, F-04/F-09/F-21)
   `--buzzer-toggle`, measured vs limit, one name/unit per concept.
5. **Onboarding and support** (F-28, F-26, F-23)
   5-minute quick start, `--doctor`, clean install/upgrade/uninstall.

## G1 questions for the human

1. **`--menu` vs `--dashboard-text` vs `--watch`**: keep all three, make
   `--dashboard-text` the primary live view and `--menu` a launcher, or remove
   one? Recommendation: keep all three, define roles (watch = stream, dashboard
   = full-screen, menu = launcher).
2. **`--buzzer-off`**: approve renaming to `--buzzer-toggle` with a deprecated
   alias? Recommendation: yes; the current name lies about a toggle.
3. **Exit code `2`**: keep the documented compatibility (alert or usage), or
   plan a v3 breaking change? Recommendation: keep in v2, document.
4. **`--fan-mode performance`**: keep as an alias for the PSU curve, or remove
   from help? Recommendation: keep as a hidden alias, document `auto`.
5. **Scope**: approve the five themes above as the v2 improvement scope; defer
   man page/completions/localization to P3.

## Not in scope for this round

- Kernel module, GUI framework, cloud/telemetry, auto-update, Windows support.
- Any automatic PSU write.
- A full CLI subcommand rewrite; aliases first, v3 later if needed.

## Approval

Reply:

```text
G1: APPROVED
```

or list changes, e.g.:

```text
G1: APPROVED, but remove --menu; keep buzzer rename; defer F-24
```
