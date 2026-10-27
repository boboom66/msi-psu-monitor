# Test documentation index

> **Archived folder.** These are dated test records, kept for traceability only.
> Current verification and release status live outside this folder.

The current verification procedure and current release verdict are maintained
outside this historical test-record folder:

- [Verification guide](../../verify.md): current no-hardware checks and hardware checklist.
- [Release readiness](../../../bug-audit/RELEASE_READINESS.md): latest recorded CI result and release blockers.
- [Test-function coverage map](../../verify.md#11-测试模块清单): maps each test module to collected test functions.

The documents below record earlier test rounds. Their counts, environment details,
and pass/fail statuses are frozen at the date stated in each document; do not use
them as the current test count or release verdict.

Two files overlap the current ledgers and are kept only as Phase 3/5 history:
`fix-log.md` is superseded by [`bug-audit/FIX_LOG.md`](../../../bug-audit/FIX_LOG.md)
and `release-readiness.md` by
[`bug-audit/RELEASE_READINESS.md`](../../../bug-audit/RELEASE_READINESS.md).

| Group | Files | Purpose |
|---|---|---|
| Plans and cases | [test-plan.md](test-plan.md), [test-cases.md](test-cases.md) | Historical test scope and case inventory |
| Results | [test-report.md](test-report.md), [test-coverage.md](test-coverage.md), [ai1300ts-test-report.md](ai1300ts-test-report.md) | Dated test and coverage results |
| Findings and fixes | [bug-report.md](bug-report.md), [fix-log.md](fix-log.md), [psu-file-gap-analysis.md](psu-file-gap-analysis.md) | Historical defects and comparison with the source archive |
| Release/build evidence | [release-readiness.md](release-readiness.md), [build-2204-chroot.md](build-2204-chroot.md), [evidence-ci-release.txt](evidence-ci-release.txt), [evidence-2204-build.txt](evidence-2204-build.txt) | Earlier release assessments and build evidence |
