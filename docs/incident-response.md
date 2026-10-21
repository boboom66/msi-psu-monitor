# Incident response runbook

This is a small, local-only project, so the runbook is deliberately short. It
covers a compromised release artifact, a reported vulnerability, and a false or
suspicious alert flood.

## Triggers

- A report that an artifact, checksum or SBOM does not match the published source.
- A vulnerability report against the CLI, daemon, dashboard or release scripts.
- Evidence that untrusted device data reached a file, log or label unescaped.
- A dashboard reachable from something other than loopback.
- A PSU whose protection points look wrong after a manual `--ocp-set` /
  `--load-thresholds` run (wrong trip point, OCP no longer trips, or the model
  refuses to save).

## Immediate containment

1. Stop the daemon: `sudo systemctl stop msi-psu-monitor`.
2. Preserve the evidence before changing anything:
   `sudo cp -a /var/lib/msi-psu-monitor /var/tmp/msi-psu-evidence`.
3. Record the artifact hashes and the UTC time:
   `sha256sum msi-psu-monitor_*.tar.gz msi-psu-monitor_*.deb`.
4. Export the journal: `journalctl -u msi-psu-monitor --since ... > journal.txt`.
5. Do not delete `state.json`, `latest.json`, `daily-*.log` or `alerts-*.log`.

## Assessment

- Confirm the affected version and whether the official artifact is involved.
- Reproduce in demo mode (`MSI_PSU_DEMO=1`) before touching a real PSU.
- Classify: release integrity, code execution, data exposure, or availability.

## Release response

If a published artifact is affected, mark the release as withdrawn in the
release notes and remove the downloads (`gh release delete <tag> --yes` after
publishing an advisory), then ship a patch release. If signing is in use, rotate
the key and publish the new fingerprint.

## Recovery

Install the patched release, verify `SHA256SUMS`, restart the daemon, and watch
`journalctl -u msi-psu-monitor -f` for one full sampling cycle.

For a wrong OCP threshold write, restore the values captured before the change
(`--load-thresholds before.json`) or the factory set (12 A / 5 A / 20 s / 20 s /
180 s) with `--ocp-set`, verify the read-back, then power-cycle the host and
watch `--ocp` on the next boot. Record the write-audit line
(`write ocp_thresholds ...`) from the journal.

## After the incident

Write a short timeline (UTC), root cause, user impact and the regression test
that prevents a repeat. Update [SECURITY.md](../SECURITY.md).
