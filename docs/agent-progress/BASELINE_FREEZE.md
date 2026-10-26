# BASELINE FREEZE — 2026-10-26

## What is frozen

- Candidate tag: `baseline-2026-10-26` (failed docs-consistency candidate)
- Green tag: `baseline-2026-10-26-r2`
- Green branch: `baseline/pre-product-v2-r2`
- Green commit: `a21f971`
- Base before freeze: `aee015e` (`work/product-v2`).
- Package version: **1.0.1** (`pyproject.toml`).
- CI run: `40290163974` — all jobs green (3.10/3.12/3.13 + freeze).

This is a **test snapshot, not a release**:

- It is not a `v*` tag, so `.github/workflows/release.yml` is not triggered.
- It does not claim 1.0.1 is complete: the tree contains unreleased
  `--dashboard-text` / `--menu` work.
- The package version is intentionally not bumped before testing. The release
  version is decided after the baseline test report.

## Rules

1. The tag is immutable. Do not move, delete, or force-push it.
2. Code changes for fixes/improvements happen on `work/product-v2`, never on the
   tag.
3. A fix discovered by baseline testing gets a regression test first.
4. The baseline test report references the tag and the exact environment.
5. Do not create a `v*` tag or publish artifacts from this snapshot.

## Baseline test plan

See `BASELINE_TEST_PLAN.md`. Results are in `BASELINE_TEST_REPORT.md`.

The first candidate (`d0d8d91`, tag `baseline-2026-10-26`) failed the docs
consistency test because the new plan quoted a historical 645-test count as
current. The fix (`a21f971`) removes that quote; no product code changed. The
green tag is `baseline-2026-10-26-r2`.

## Status

- Freeze: **DONE** (`baseline-2026-10-26-r2`)
- Automated suite: **PASS** (CI run `40290163974`, 3.10/3.12/3.13 + freeze)
- Feature matrix: **PARTIAL** (automated paths pass; PTY/visual/5-model gaps)
- Hardware/root/arm64/24h: **BLOCKED** (human evidence)
- Static partial: `compileall` + `git diff --check` pass
