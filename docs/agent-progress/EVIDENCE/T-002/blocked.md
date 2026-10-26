# T-002 — Baseline gates: BLOCKED

## Environment probes

| Probe | Output | Meaning |
|---|---|---|
| `wsl.exe -l -v` | no distribution installed | no WSL Linux |
| `docker --version` | command not found | no container runtime |
| `uv --version` | command not found | no uv on Windows |
| `gh auth status` | not logged into any GitHub host | no fork Actions path |
| `.venv/pyvenv.cfg` | `home = /usr/bin`, CPython 3.12.3 | Linux venv; not runnable on Windows |
| `msi_psu_monitor/protocol.py` | imports `fcntl`; `menu.py` imports `termios` | package cannot import natively on Windows |

## Partial checks that did run

```text
python -m compileall -q msi_psu_monitor tests
# exit 0

git diff --check
# exit 0
```

These prove syntax and whitespace only. They do **not** prove pytest, ruff,
mypy, coverage, smoke, soak, packaging, or UX behavior.

## Conclusion

**BLOCKED** until G0 selects a Linux execution path:

- A: WSL2 + Ubuntu 22.04
- B: `gh auth login` + GitHub Actions on `fork`
- C: SSH Linux host
- D: static-only (gates remain BLOCKED; cannot release)

No pass is claimed. `STATE.md` records the blocker.
