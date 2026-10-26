# BASELINE FREEZE — 2026-10-26

## What is frozen

- Tag: `baseline-2026-10-26` (annotated)
- Branch: `baseline/pre-product-v2`
- The tag points to the commit that adds this file.
- Base before freeze: `aee015e` (`work/product-v2`).
- Package version: **1.0.1** (`pyproject.toml`).

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

See `BASELINE_TEST_PLAN.md`. Results go to `BASELINE_TEST_REPORT.md` after the
Linux environment runs the suite.

## Status

- Freeze: **DONE**
- Automated suite: **NOT RUN** (no Linux environment)
- Feature matrix: **NOT RUN** (no Linux environment)
- Static partial: `compileall` + `git diff --check` pass
