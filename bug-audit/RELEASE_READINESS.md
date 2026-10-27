# Release readiness — current assessment

> Updated 2026-10-27 on `work/product-v2`. Latest recorded CI:
> run `40441033415` on the T-022 code commit; the 3.10/3.12/3.13 matrix and
> frozen-release job passed. Changes after that run are documentation-only.

**Verdict: NOT READY for a production release.** The latest recorded CI run passes
the software and packaging gates and collects **889 tests**. Release-critical
hardware/platform evidence is still missing, the OCP threshold write has never
touched a real PSU, and no official 1.0.1 release has been published. The published
release remains v1.0.0.

## 1. Evidence that is green

| Gate | Evidence |
|---|---|
| Full test suite | **889 tests collected**; latest recorded CI run `40441033415` passed |
| Lint / format / types | Latest recorded CI run passed the configured checks |
| Coverage | Latest recorded CI run passed the configured coverage gate (90% floor); see CI output for the measured percentage |
| Smoke / accelerated soak | Latest recorded CI run passed the smoke and soak jobs; their exact current output is in CI run `40441033415` |
| Strict exposition | `tests/test_prometheus_exposition.py` parses HELP/TYPE, labels, finite values, duplicate series and the canonical `metric{} value` form |
| Local 1.0.1 freeze | Historical 2026-10-22 x86_64/glibc 2.39 smoke build; not an official release artifact |
| Earlier local demo checks | Historical: 180 samples at 1 s and hardware-kit `acceptance.sh --demo` passed; these are not 24 h hardware evidence |
| Official promtool | Historical 2.45.3 check: no syntax errors, 8 naming-policy warnings; rules check found 5 rules. Re-run against the release candidate before publishing |
| Static infra checks | Historical local run: shellcheck, systemd-analyze verify, udevadm verify, offline security analysis (exposure 3.3 OK) |
| Packaging logic | source .deb under umask 077; binary/kit scripts derive the version; no Python dependency in the binary .deb |
| Robustness tests | Included in the latest passing CI suite; the exact randomized counts below are from the historical audit |

## 2. Release blockers / open decisions

| Blocker | Status |
|---|---|
| Real MSI PSU acceptance (5 models, alerts, writes, VIN, black box, OCP, multirail, unplug/reconnect) | **BLOCKED** — no hardware acceptance evidence recorded |
| **OCP threshold write on real hardware** (write, read-back, power-cycle persistence, restore from dump) | **BLOCKED** — demo/mock only; a protection write must be bench-validated before release use |
| arm64 binary execution (only x86_64 runner in this environment) | **BLOCKED** |
| Root/systemd/udev install + daemon start/stop on a real host | **BLOCKED** — no real-host acceptance evidence recorded |
| Desktop browser verification of the dashboard | **BLOCKED** — no real-browser acceptance evidence recorded; earlier checks used a Node harness |
| 24 h / 72 h soak | **NOT RUN**; earlier short/accelerated demo runs do not satisfy this check |
| Official v1.0.1 22.04 / arm64 artifacts | **NO** — the CI freeze job passed, but no v1.0.1 release artifacts have been published; v1.0.0 is the published release |
| Published artifacts contain the latest fixes | **NO** — `v1.0.0` predates the audit; the local 1.0.1 x86_64 build is not tagged or published |
| Prometheus naming policy | **OPEN DECISION** — a historical `promtool` run found 8 naming-policy warnings and no parse errors; rerun before release, since renaming affects the REQ-8 dual energy export |

## 3. What a release would require

1. Owner approval to tag/publish `v1.0.1` (the version and CHANGELOG are already at
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
4. Re-run `promtool` on the release candidate; resolve any naming-policy warnings or
   record them as accepted compatibility debt.
5. Optional but recommended: a real desktop-browser pass and 24 h soak.

## 4. Risk statement

The code is materially better than the published `1.0.0`: the local threshold
alerting, OCP threshold write/dump/load, handshake retry, canonical Prometheus
exposition, live-dashboard contract, destructive output-path handling and several
daemon/alert consistency bugs now have real regressions. That is still not a claim
that no bugs remain. The dominant residual risks are (in order): the untested OCP
protection write, untested real-device protocol behaviour, arm64 execution, the
root/systemd/udev install path, and the absence of a 24 h soak.
