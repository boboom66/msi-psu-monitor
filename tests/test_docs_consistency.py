"""Keep the numbers and file lists quoted in the docs true.

Docs rot silently: a test count copied into three files drifts the moment a test
is added, and a checklist that names the wrong module reads as authority. Both
are cheap to verify, so they are verified here instead of trusted.
"""

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = [
    ROOT / 'README.md',
    ROOT / 'DEV_PROGRESS.md',
    ROOT / 'AGENTS.md',
    ROOT / 'msi_psu_monitor' / 'AGENTS.md',
    *sorted((ROOT / 'docs').glob('*.md')),
    *sorted((ROOT / 'docs').glob('*.example')),
]
TEST_COUNT_RE = re.compile(r'(\d+)\s+passed')
PY_FILE_RE = re.compile(r'`tests/(test_[a-z_]+\.py)`')


def _test_files():
    return {path.name for path in (ROOT / 'tests').glob('test_*.py')}


def _collected_count():
    """The number pytest would run, without running it."""
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', '--collect-only', '-q', '--no-header'],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    match = re.search(r'(\d+) tests? collected', result.stdout)
    assert match, result.stdout
    return int(match.group(1))


def test_quoted_test_counts_are_accurate():
    """A stale "N passed" is a lie the reviewer cannot spot by reading."""
    expected = _collected_count()
    stale = []
    for doc in DOCS:
        if not doc.is_file():
            continue
        for claimed in TEST_COUNT_RE.findall(doc.read_text(encoding='utf-8')):
            if int(claimed) != expected:
                stale.append(f'{doc.relative_to(ROOT)}: says {claimed}, actual {expected}')
    assert not stale, '\n'.join(stale)


def test_named_test_modules_exist():
    """Checklists and AGENTS notes must point at real files."""
    known = _test_files()
    missing = set()
    for doc in DOCS:
        if not doc.is_file():
            continue
        for name in PY_FILE_RE.findall(doc.read_text(encoding='utf-8')):
            if name not in known:
                missing.add(f'{doc.relative_to(ROOT)} -> tests/{name}')
    assert not missing, '\n'.join(sorted(missing))


def test_every_test_module_is_documented():
    """A test file nobody can find in the docs is a test nobody will run."""
    text = '\n'.join(doc.read_text(encoding='utf-8') for doc in DOCS if doc.is_file())
    undocumented = sorted(name for name in _test_files() if name not in text)
    assert not undocumented, f'not mentioned in any doc: {undocumented}'


def test_readme_usage_matches_the_real_cli():
    """The usage block is copied by hand, so verify it against argparse itself."""
    from msi_psu_monitor.monitor import build_parser

    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    assert '## Usage' in readme and '### Examples' in readme
    section = readme.split('## Usage', 1)[1].split('### Examples', 1)[0]
    documented = set(re.findall(r'--[a-z][a-z-]+', section))

    real = {
        option
        for action in build_parser()._actions
        for option in action.option_strings
        if option.startswith('--') and option != '--help'
    }
    assert not real - documented, f'undocumented flags: {sorted(real - documented)}'
    assert not documented - real, f'flags that no longer exist: {sorted(documented - real)}'
