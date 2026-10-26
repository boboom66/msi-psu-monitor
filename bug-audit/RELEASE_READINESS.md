# Release readiness — current assessment

**Verdict: NOT READY for a production release.** The software and packaging gates
are green (803 tests, 94% branch coverage, smoke, soak, static security checks), and a
local x86_64 1.0.1 freeze now exists with clean-env and kit checks. The
release-critical hardware/platform evidence is still missing, the OCP threshold
write has never touched a real PSU, and no official 22.04/arm64 artifact has been
built or published.

## 1. Evidence that is green

| Gate | Evidence |
|---|---|
| Full test suite | **803 passed** (`pytest -q`) |
| Lint / format / types | ruff check + format clean, mypy clean (10 files) |
| Coverage | **94%** branch coverage (3166 stmts / 183 missed / 1174 branches, floor 90%) |
| Smoke (demo PSU, no hardware) | **58/58** passed, including daemon→prometheus→history→dashboard |
| Accelerated soak | `scripts/soak.sh 5000`: exit 0, peak RSS 18 436 KB, fd=3, state/latest/prom/daily written and non-empty |
| Strict exposition | `tests/test_prometheus_exposition.py` parses HELP/TYPE, labels, finite values, duplicate series and the canonical `metric{} value` form |
| Local 1.0.1 freeze | 2026-10-22 audit build: tar/deb/kit built on x86_64/glibc 2.39 (smoke only); tar SHA256SUMS and clean-env `--once` pass; extracted `.deb` runs; deb is `Depends: libc6 (>= 2.35), zlib1g`, no Python |
| Real-time demo soak | 180 samples at 1 s: exit 0, peak RSS 18 000 KB, fd=3, state dir 16 KiB (not 24 h) |
| Hardware-kit self-test | extracted `acceptance.sh --demo`: 30 PASS / 0 FAIL / 3 MANUAL / 2 SKIP |
| Official promtool | 2.45.3 on current daemon textfile: metrics exit 3 with 8 naming-policy warnings, **no syntax errors**; `check rules docs/prometheus-rules.yml` → SUCCESS (5 rules) |
| Static infra checks | shellcheck, systemd-analyze verify, udevadm verify, offline security analysis (exposure 3.3 OK) |
| Packaging logic | source .deb under umask 077; binary/kit scripts derive the version; no Python dependency in the binary .deb |
| Fuzz/robustness | 400 random 0xE0 payloads × 5 variants, 120 random config files, 120 random --ocp-set specs: no tracebacks, no NaN/inf escape |

## 2. Release blockers / open decisions

| Blocker | Status |
|---|---|
| Real MSI PSU acceptance (5 models, alerts, writes, VIN, black box, OCP, multirail, unplug/reconnect) | **BLOCKED** — no hardware attached |
| **OCP threshold write on real hardware** (write, read-back, power-cycle persistence, restore from dump) | **BLOCKED** — demo/mock only; a protection write must be bench-validated before release use |
| arm64 binary execution (only x86_64 runner in this environment) | **BLOCKED** |
| Root/systemd/udev install + daemon start/stop on a real host | **BLOCKED** — no passwordless root |
| Desktop browser verification of the dashboard | **BLOCKED** — headless shell missing system libs; Node harness used instead |
| 24 h / 72 h soak | **NOT RUN** (180 s real-time plus accelerated 5k and 50k soaks pass) |
| Official 22.04 / arm64 release artifacts | **NO** — only a local x86_64/glibc 2.39 smoke build exists; the arm64 and 22.04 artifacts must come from CI |
| Published artifacts contain the latest fixes | **NO** — `v1.0.0` predates the audit; the local 1.0.1 x86_64 build is not tagged or published |
| Prometheus naming policy | **OPEN DECISION** — 8 naming-policy warnings from current `promtool`; no parse errors, but renaming affects the REQ-8 dual energy export |

## 3. What a release would require

1. Owner approval to tag/push `v1.0.1` (the version and CHANGELOG are already at
   1.0.1; create the tag only after confirming the tree is clean).
2. CI release run on Ubuntu 22.04 / arm64; verify x86_64/arm64 assets, SBOMs, hardware
   kits, `SHA256SUMS` coverage, and that no source `_all.deb` is published (DEF-013
   regression). The current local build is x86_64/glibc 2.39 only and is not a
   substitute for this step.
3. Hardware acceptance with the kit on the target machine, including the OCP
   threshold write item: dump the original values, write a legal set, verify by
   read-back and power-cycle, then restore with `--load-thresholds`. Return
   `/var/log/msi-psu-acceptance/<timestamp>.tar.gz`; never mark hardware checks PASS
   before they run.
4. Resolve the 8 Prometheus naming-policy warnings or record them as accepted
   compatibility debt; the metric syntax already passes `promtool`.
5. Optional but recommended: a real desktop-browser pass and 24 h soak.

## 4. Risk statement

The code is materially better than the published `1.0.0`: the local threshold
alerting, OCP threshold write/dump/load, handshake retry, canonical Prometheus
exposition, live-dashboard contract, destructive output-path handling and several
daemon/alert consistency bugs now have real regressions. That is still not a claim
that no bugs remain. The dominant residual risks are (in order): the untested OCP
protection write, untested real-device protocol behaviour, arm64 execution, the
root/systemd/udev install path, and the absence of a 24 h soak.
