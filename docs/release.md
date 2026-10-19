# Release engineering (no Python on the target machine)

The official download is a **self-contained binary release**: the target machine
needs no Python, pip or network access. Two one-file executables bundle CPython
and the stdlib-only package; the data files (systemd unit, udev rule, config
example, docs) ship next to them in a tarball.

## Artifacts

| File | Arch | Contents |
|------|------|----------|
| `msi-psu-monitor_<version>_linux_x86_64.tar.gz` | x86_64 | both executables, `install.sh`, `uninstall.sh`, unit, udev rule, config example, README/LICENSE/docs, `SHA256SUMS` |
| `msi-psu-monitor_<version>_linux_aarch64.tar.gz` | arm64 | same |
| `msi-psu-monitor_<version>_amd64.deb` | x86_64 | the same executables under `/usr/bin`, `Depends: libc6 (>= 2.35), zlib1g` |
| `msi-psu-monitor_<version>_arm64.deb` | arm64 | same |
| `SBOM-x86_64.json` / `SBOM-aarch64.json` | per arch | CycloneDX 1.5 SBOM: project, CPython, PyInstaller, OpenSSL, zlib, bzip2, xz and the SHA-256 of every artifact |
| `msi-psu-monitor-hardware-kit_<version>_linux_<arch>.tar.gz` | per arch | test-machine kit: binaries, source fallback, `setup.sh`, `acceptance.sh`, `uninstall.sh`, udev/unit/config, docs, `SHA256SUMS`; not the end-user install package |

The tarball is the recommended download. The `.deb` exists for Debian/Ubuntu
users who prefer `apt`; it is built from the same binaries and does **not**
depend on `python3`.

The **hardware kit** is a separate test artifact, built by
`scripts/build_hardware_kit.sh` and attached to the same release. It adds the
one-shot `setup.sh`, the read-only-by-default `acceptance.sh` (evidence +
report), and a source fallback for machines whose glibc cannot run the frozen
binary. See [hardware-acceptance.md](hardware-acceptance.md).

## Why Ubuntu 22.04

The binaries link the build host's glibc. A release built on 24.04 (glibc 2.39)
will not start on 22.04 / Debian 12 (glibc 2.35). `scripts/build_binary.sh`
refuses a newer build host unless `ALLOW_NEWER_GLIBC=1` is set, which is only
for local smoke builds.

The CI release job therefore runs on `ubuntu-22.04` (x86_64) and
`ubuntu-22.04-arm` (arm64). If the arm label is unavailable in your repository,
drop that matrix entry and build arm64 on a native 22.04 arm64 machine.

## Build

```bash
uv sync --group dev --group build     # PyInstaller is build-only, never runtime
uv run --group dev pytest -q          # source tests first
bash scripts/build_binary.sh          # dist/bin/... + dist/*.tar.gz + .sha256
bash scripts/build_deb_binary.sh      # dist/*.deb from the same binaries
python3 scripts/build_sbom.py --dist dist --output dist/SBOM-x86_64.json --arch x86_64
```

`scripts/build_binary.sh` also smoke-tests the frozen executables before
packaging: `--version`, `--once` on `MSI_PSU_DEMO=1`, one daemon iteration,
`--zero-fan off` and `--buzzer-off` (all without a PSU). A freeze that loses a
module or an import fails the build instead of shipping.

The tarball is assembled deterministically: sorted names, fixed mtimes, numeric
owners and `gzip -9n`, so rebuilding the same source on the same runner should
produce the same archive.

## Install (end user)

```bash
tar xzf msi-psu-monitor_<version>_linux_x86_64.tar.gz
cd msi-psu-monitor_<version>_linux_x86_64
sudo ./install.sh
```

`install.sh` copies the two executables to `/usr/local/bin`, installs the udev
rule and the systemd unit, writes `/etc/msi-psu-monitor.conf` only if it does
not exist, and enables/starts the daemon. `PREFIX=/usr` overrides the install
prefix. `uninstall.sh` removes the program files and keeps the config/state;
`--purge` removes those too.

## Verify a release

```bash
sha256sum -c msi-psu-monitor_<version>_linux_x86_64.tar.gz.sha256
cd msi-psu-monitor_<version>_linux_x86_64
sha256sum -c SHA256SUMS
ldd ./msi-psu-monitor                      # libc/zlib only, no libpython
env -i PATH=/usr/bin:/bin HOME=/tmp MSI_PSU_DEMO=1 ./msi-psu-monitor --once
```

The `env -i` check is deliberate: it proves the binary does not pick up a
developer virtualenv or a Python from `PATH`.

## Checksums and signing

Every release publishes `SHA256SUMS` for the full set of artifacts (including
the per-arch SBOM) and a `<artifact>.sha256` next to each tarball. GPG signing is
not implemented yet (there is no project release key); if the official site needs
signatures, add a detached `.asc` per artifact and publish the public key
fingerprint. The broader security/support commitments are in [SECURITY.md](../SECURITY.md),
[docs/support.md](support.md) and [docs/incident-response.md](incident-response.md);
the SBOM fulfils the supply-chain baseline and should be regenerated for every
release, never hand-edited.

## Versioning

The version comes from `pyproject.toml`; the release tag must be
`v<version>` (the workflow checks this). `--version` in the binary reports the
same string, and `BUILD-INFO` records the version, architecture and build-host
glibc.
