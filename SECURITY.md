# Security policy

This policy covers the msi-psu-monitor code, its release artifacts and the
local daemon/dashboard. It does not cover MSI PSU firmware or hardware, which
are outside this project.

## Supported versions

| Version | Supported | Notes |
|---------|-----------|-------|
| 1.0.x   | yes       | Current release line; security fixes land here |

The support window is 12 months from the release date; see
[docs/support.md](docs/support.md) for the exact dates and the end-of-support
policy. Older releases do not receive security fixes.

## Reporting a vulnerability

Use GitHub private vulnerability reporting on this repository
(Security -> Report a vulnerability). Do not open a public issue for a
security problem.

Please include:

- the affected version and the SHA-256 of the artifact,
- a reproduction (command line, PSU model/firmware if relevant),
- impact and any known mitigation.

We aim to acknowledge within 7 days, triage within 30 days, and ship a fix or
a documented mitigation within 90 days. We will credit reporters who ask for
credit.

## Security properties

- No network service: the CLI and daemon only read `/dev/hidraw*` and write
  local files. The dashboard binds to loopback, rejects a non-loopback `Host`
  header with 421 (DNS-rebinding defence), and sends a self-contained CSP plus
  Permissions-Policy on every response.
- No runtime Python dependency in the official download; the binaries are
  frozen in CI on Ubuntu 22.04 and the `.deb` declares only libc6 and zlib1g.
- Device-supplied strings (product, vendor, serial, firmware revision) are
  untrusted input and are filtered before they reach journald, Prometheus or
  CSV. Alert and black-box data are length-checked before decoding.
- The daemon runs as root only because hidraw requires it; the systemd unit
  removes capabilities, restricts address families, and protects the rest of
  the system. `PrivateDevices` is deliberately not set.
- Release artifacts are covered by `SHA256SUMS` and a CycloneDX SBOM. GPG
  signing is not implemented yet; verify the checksums before installing.
- No auto-update: install a newer release explicitly, and keep the last known
  good offline artifact if a rollback is needed.
- The hardware OCP threshold write is a local, root-only CLI operation
  (`--ocp-set`/`--load-thresholds`); there is no network path to it, the daemon
  never calls it automatically, and values are range-checked and read-back-verified.
  Treat it as a physical-access operation: it changes real over-current protection
  points and must be bench-validated on a unit before production use.

## Supply chain

- Runtime dependencies: none (Python standard library only).
- Build dependency: PyInstaller is pinned in the `build` group and used only
  when producing the official binaries.
- SBOM: every release attaches `SBOM-<arch>.json` (CycloneDX 1.5) with the
  artifact hashes and the bundled CPython/OpenSSL/zlib components.

## Disclosure

We follow a 90-day coordinated disclosure window. If a fix cannot be shipped
in time, we will publish the mitigation and the residual risk instead of
silently leaving users exposed.
