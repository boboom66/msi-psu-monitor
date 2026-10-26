# T-005 — CI guard for script modes and line endings

Added to `.github/workflows/ci.yml`, `check` job, immediately after
`actions/checkout`:

```yaml
      - name: Shell script modes and line endings
        run: |
          bad=$(git ls-files -s -- 'scripts/*.sh' 'scripts/hardware/*.sh' | awk '$1 != "100755" {print $4}')
          if [ -n "$bad" ]; then
            echo "These shell scripts are not executable in the index:"
            echo "$bad"
            exit 1
          fi
          if git grep -Il $'\r' -- 'scripts/*.sh' 'scripts/hardware/*.sh'; then
            echo "CRLF found in shell scripts; .gitattributes must keep LF."
            exit 1
          fi
```

Why:

- A Windows checkout can silently turn `100755` into `100644`; a content diff
  does not show it.
- `scripts/install.sh` was `100644` in the index even on a Linux checkout, so
  `sudo ./scripts/install.sh` could fail.
- CRLF breaks the shipped shell scripts.

Status: **NOT EXECUTED YET** — it runs on the next CI push. Local Windows cannot
execute GitHub Actions. This is evidence of the change, not a pass claim.
