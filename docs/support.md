# Support and lifecycle

## Support window

| Release line | Released   | Supported until | Update channel |
|--------------|------------|-----------------|----------------|
| 1.0.x        | 2026-10-19 | 2027-10-19      | GitHub Releases |

Security fixes are backported to the latest minor release only. When a line
reaches end of support, its artifacts stay downloadable but receive no further
fixes; the supported line and its replacement are listed in the release notes.

## Update channel

Updates are manual: download the new artifact from GitHub Releases, verify it
against `SHA256SUMS` (and the attached SBOM), then install it the same way as
the first time. There is no auto-update and no update server. The previous
artifact can be kept offline for rollback.

## Compatibility

- Linux x86_64 and arm64, glibc 2.35 or newer (Ubuntu 22.04 / Debian 12).
- MSI PSUs: MPG Ai1300TS / Ai1600TS (REV6), MEG Ai1000P / Ai1300P / Ai1600T.
- Hardware-specific behaviour that still needs a real unit is listed in
  [docs/verify.md](docs/verify.md); the demo mode exercises the rest.

## Getting help

Open a GitHub issue for a reproducible bug or a feature request. Report a
security problem through the private channel described in [SECURITY.md](SECURITY.md).
