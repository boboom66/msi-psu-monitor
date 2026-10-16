"""Keep the facts quoted in the docs and metadata true.

Docs rot silently: a test count copied into three files drifts the moment a test
is added, a checklist that names the wrong module reads as authority, and a
version bump that misses one of its two homes ships a package that disagrees with
itself. All three are cheap to verify, so they are verified here instead of
trusted.
"""

import pathlib
import re
import subprocess
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = [
    ROOT / 'README.md',
    ROOT / 'DEV_PROGRESS.md',
    ROOT / 'AGENTS.md',
    ROOT / 'msi_psu_monitor' / 'AGENTS.md',
    *sorted((ROOT / 'docs').glob('*.md')),
    *sorted((ROOT / 'docs').glob('*.example')),
]
# "341 passed", "341 tests" and "341 个单测" all quote the same fact. No \b after
# the CJK alternatives: 测 is a word character, so \b would never match there.
TEST_COUNT_RE = re.compile(r'(\d+)\s*(?:passed|个单测|个單測|tests?\b)')
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


def test_version_matches_between_module_and_pyproject():
    """`--version`, the .deb control file and PyPI all read different copies."""
    import msi_psu_monitor

    project = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
    assert msi_psu_monitor.__version__ == project['version']


def test_build_script_takes_the_version_from_pyproject():
    """A hardcoded version in the packager would ship a stale .deb."""
    script = (ROOT / 'scripts' / 'build_deb.sh').read_text()
    assert 'pyproject.toml' in script
    assert not re.search(r'VERSION=\d', script), 'version is hardcoded again'


def test_the_quoted_smoke_check_count_matches_the_script():
    """The smoke script quotes its own total, and the docs quote that total."""
    script = (ROOT / 'scripts' / 'smoke.sh').read_text(encoding='utf-8')
    total = re.search(r'EXPECTED_TOTAL=(\d+)', script)
    assert total, 'smoke.sh must keep a quoted check total'
    expected = int(total.group(1))
    # The constant has to be checked against the real count, not just declared.
    assert '"$PASS" -ne "$EXPECTED_TOTAL"' in script

    # Only the two phrasings that quote the smoke total: a bare "N 项" also counts
    # the real-hardware checklist in verify.md §8, which is a different number.
    patterns = (
        re.compile(r'smoke\.sh\s*→\s*(\d+) 项'),
        re.compile(r'，共 (\d+) 项，失败即非零退出'),
    )
    quoted = 0
    stale = []
    for doc in DOCS:
        if not doc.is_file():
            continue
        text = doc.read_text(encoding='utf-8')
        for pattern in patterns:
            for claimed in pattern.findall(text):
                quoted += 1
                if int(claimed) != expected:
                    stale.append(f'{doc.relative_to(ROOT)}: says {claimed}, actual {expected}')
    assert quoted >= 2, 'the smoke total is no longer quoted in the docs'
    assert not stale, '\n'.join(stale)


HARDWARE_CLAIM_RE = re.compile(r'§8[（(，,]\s*共\s*(\d+)\s*项')
HARDWARE_ENTRY_RE = re.compile(r'^(?:\d+b?)\.\s', re.M)


def _verify_section_8():
    """The real-hardware checklist: everything after the §8 heading in verify.md."""
    verify = (ROOT / 'docs' / 'verify.md').read_text(encoding='utf-8')
    assert '## 8.' in verify
    return verify.split('## 8.', 1)[1]


def test_the_quoted_real_hardware_check_count_matches_verify_md():
    """That checklist is the last thing blocking release, and it grows by hand.

    DEV_PROGRESS.md once said "共 10 项" above a list of nine (item 4b and the
    Ai1600T case were added to verify.md and never mirrored), so the two numbers
    are now tied together instead of trusted.
    """
    expected = len(HARDWARE_ENTRY_RE.findall(_verify_section_8()))
    assert expected >= 10, f'only {expected} hardware checks found in verify.md §8'

    quoted = 0
    stale = []
    for doc in DOCS:
        if not doc.is_file():
            continue
        for claimed in HARDWARE_CLAIM_RE.findall(doc.read_text(encoding='utf-8')):
            quoted += 1
            if int(claimed) != expected:
                stale.append(f'{doc.relative_to(ROOT)}: says {claimed}, actual {expected}')
    assert quoted >= 2, 'the hardware checklist total is no longer quoted in the docs'
    assert not stale, '\n'.join(stale)

    # The list in DEV_PROGRESS.md mirrors verify.md by hand: make sure the two
    # agree item by item, not just in the total.
    progress = (ROOT / 'DEV_PROGRESS.md').read_text(encoding='utf-8')
    section = progress.split('### 真机验收', 1)[1].split('## ', 1)[0]
    assert len(HARDWARE_ENTRY_RE.findall(section)) == expected, (
        'DEV_PROGRESS.md lists a different number of hardware checks than verify.md §8'
    )
