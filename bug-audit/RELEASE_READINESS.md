# Release readiness — current assessment

**Verdict: NOT READY for a production release.** The software and packaging gates
are green (735 tests, 93% branch coverage, smoke, soak, static security checks), but
the release-critical hardware/platform evidence is still missing, the OCP
threshold write has never touched a real PSU, and the published artifacts predate
this work.

## 1. Evidence that is green

| Gate | Evidence |
|---|---|
| Full test suite | **735 passed** (`pytest -q`) |
| Lint / format / types | ruff check + format clean, mypy clean (10 files) |
| Coverage | **93%** branch coverage (2957 stmts / 195 missed / 1084 branches, floor 90%) |
| Smoke (demo PSU, no hardware) | **58/58** passed, including daemon→prometheus→history→dashboard |
| Accelerated soak | `scripts/soak.sh 5000`: exit 0, peak RSS 16.4 MB, fd=3, state files fresh |
| Strict exposition | `tests/test_prometheus_exposition.py` parses HELP/TYPE, labels, finite values, duplicate series and the canonical `metric{} value` form |
| Hardware-kit self-test | `acceptance.sh --demo`: 30 PASS / 0 FAIL / 3 MANUAL / 2 SKIP |
| Static infra checks | shellcheck, systemd-analyze verify, udevadm verify, offline security analysis (exposure 3.3 OK) |
| Packaging logic | source .deb under umask 077; binary/kit scripts derive the version; no Python dependency in the binary .deb |
| Fuzz/robustness | 400 random 0xE0 payloads × 5 variants, 120 random config files, 120 random --ocp-set specs: no tracebacks, no NaN/inf escape |

## 2. Release blockers (unchanged)

| Blocker | Status |
|---|---|
| Real MSI PSU acceptance (5 models, alerts, writes, VIN, black box, OCP, multirail, unplug/reconnect) | **BLOCKED** — no hardware attached |
| **OCP threshold write on real hardware** (write, read-back, power-cycle persistence, restore from dump) | **BLOCKED** — demo/mock only; a protection write must be bench-validated before release use |
| arm64 binary execution (only x86_64 runner in this environment) | **BLOCKED** |
| Root/systemd/udev install + daemon start/stop on a real host | **BLOCKED** — no passwordless root |
| Desktop browser verification of the dashboard | **BLOCKED** — headless shell missing system libs; Node harness used instead |
| 24 h / 72 h soak | **NOT RUN** (accelerated 5k-sample gate and 50k local soak pass) |
| Published artifacts contain the latest fixes | **NO** — `v1.0.0` was built before this work; the tree is uncommitted |
| Official `promtool check metrics/rules` | **NOT RUN** — no promtool/network; replaced by the strict exposition test, not claimed as promtool |

## 3. What a release would require

1. Owner approval to commit/push, bump the version (e.g. `1.0.1`), update
   `CHANGELOG.md` and tag `v1.0.1`.
2. New CI release run on that tag; verify x86_64/arm64 assets, SBOMs, hardware kits,
   `SHA256SUMS` coverage, and that no source `_all.deb` is published (DEF-013 regression).
3. Hardware acceptance with the kit on the target machine, including the OCP
   threshold write item: dump the original values, write a legal set, verify by
   read-back and power-cycle, then restore with `--load-thresholds`. Return
   `/var/log/msi-psu-acceptance/<timestamp>.tar.gz`; never mark hardware checks PASS
   before they run.
4. Optional but recommended: `promtool check metrics` on the daemon textfile, a real
   desktop-browser pass, 24 h soak.

## 4. Risk statement

The code is materially better than the published `1.0.0`: the local threshold
alerting, OCP threshold write/dump/load, handshake retry, canonical Prometheus
exposition, live-dashboard contract, destructive output-path handling and several
daemon/alert consistency bugs now have real regressions. That is still not a claim
that no bugs remain. The dominant residual risks are (in order): the untested OCP
protection write, untested real-device protocol behaviour, arm64 execution, the
root/systemd/udev install path, and the absence of a 24 h soak.
