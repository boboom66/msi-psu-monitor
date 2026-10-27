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

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: the stdlib module arrives in 3.11
    import tomli as tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = [
    ROOT / 'README.md',
    ROOT / 'AGENTS.md',
    ROOT / 'msi_psu_monitor' / 'AGENTS.md',
    *sorted((ROOT / 'docs').glob('*.md')),
    *sorted((ROOT / 'docs').glob('*.example')),
]
# "341 passed", "341 tests" and "341 个单测" all quote the same fact. No \b after
# the CJK alternatives: 测 is a word character, so \b would never match there.
TEST_COUNT_RE = re.compile(r'(\d+)\s*(?:passed|个单测|个單測|tests?\b|通过|通過)')
PY_FILE_RE = re.compile(r'`tests/(test_[a-z0-9_]+\.py)`')
COVERAGE_ROW_RE = re.compile(r'^\| `tests/(test_[a-z0-9_]+\.py)` \| (.+) \|$', re.M)
COVERAGE_NAME_RE = re.compile(r'`(test_[a-z0-9_]+)`')


def _test_files():
    return {path.name for path in (ROOT / 'tests').glob('test_*.py')}


_COLLECTED = {}


def _collect():
    """Return (count, names) from one pytest collection run.

    names is the set of (file, function) pairs pytest actually collected, which
    is how the coverage table is checked against reality rather than against its
    own prose.
    """
    if not _COLLECTED:
        result = subprocess.run(
            [sys.executable, '-m', 'pytest', '--collect-only', '-q', '--no-header'],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        match = re.search(r'(\d+) tests? collected', result.stdout)
        assert match, result.stdout
        _COLLECTED['count'] = int(match.group(1))
        _COLLECTED['names'] = set(
            re.findall(r'^(tests/test_[a-z0-9_]+\.py)::(test_[a-z0-9_]+)', result.stdout, re.M)
        )
    return _COLLECTED['count'], _COLLECTED['names']


def _collected_count():
    """The number pytest would run, without running it."""
    return _collect()[0]


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


def test_the_coverage_table_names_real_test_functions():
    """The §1.1 table is read as authority even when it credits the wrong module.

    It used to say tests/test_protocol.py covers frame assembly and NAK handling
    (it only exercises lin11_to_int) and that tests/test_schema.py covers the
    prometheus contract (it imports format_json only). Every row now has to name
    at least one function pytest actually collects, and every test module has to
    have a row at all.
    """
    verify = (ROOT / 'docs' / 'verify.md').read_text(encoding='utf-8')
    rows = COVERAGE_ROW_RE.findall(verify)
    assert rows, 'verify.md §1.1 no longer has a coverage table'

    documented = [filename for filename, _ in rows]
    assert len(documented) == len(set(documented)), 'duplicate rows in the coverage table'
    missing = sorted(set(_test_files()) - set(documented))
    assert not missing, f'test modules missing from the §1.1 table: {missing}'

    _, collected = _collect()
    problems = []
    for filename, cell in rows:
        named = COVERAGE_NAME_RE.findall(cell)
        if not named:
            problems.append(f'{filename}: names no test function')
        for name in named:
            if (f'tests/{filename}', name) not in collected:
                problems.append(f'{filename}: {name} is not collected by pytest')
    assert not problems, '\n'.join(problems)


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
    assert quoted >= 1, 'the smoke total is no longer quoted in the docs'
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

    An archived progress log once said "共 10 项" above a list of nine (item 4b and
    the Ai1600T case were added to verify.md and never mirrored). The living docs
    quote verify.md §8, so the quoted total is tied to the real list here.
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
    assert quoted >= 1, 'the hardware checklist total is no longer quoted in the docs'
    assert not stale, '\n'.join(stale)


STALE_FORMAT_BAN_RE = re.compile(
    r'must NOT be enforced repo-wide|不要全仓跑 ruff format|絕不要全倉跑 ruff format'
)


def test_no_document_still_forbids_repo_wide_ruff_format():
    """A note telling an agent to undo a green CI gate is worse than no note.

    msi_psu_monitor/AGENTS.md is auto-loaded for work under that package and still
    said "ruff format must NOT be enforced repo-wide" after the exclusion list
    made that check safe and CI started running it.
    """
    offenders = [
        str(doc.relative_to(ROOT))
        for doc in DOCS
        if doc.is_file() and STALE_FORMAT_BAN_RE.search(doc.read_text(encoding='utf-8'))
    ]
    assert not offenders, f'still forbids repo-wide formatting: {offenders}'


SCRIPT_ARTIFACT_RE = re.compile(
    r'msi-psu-monitor_\d+\.\d+\.\d+_(?:all|amd64|arm64|linux_[a-z0-9_]+)'
)


def test_shell_scripts_do_not_hardcode_the_release_artifact_version():
    """A literal artifact name silently inspects the previous release after a bump.

    scripts/smoke.sh hardcoded msi-psu-monitor_1.0.0_all.deb, so the next version
    bump would have built a new .deb and then read the old one's contents (or a
    missing file) for the packaging checks.
    """
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
    offenders = []
    for path in sorted((ROOT / 'scripts').rglob('*.sh')):
        for literal in SCRIPT_ARTIFACT_RE.findall(path.read_text(encoding='utf-8')):
            if not literal.startswith(f'msi-psu-monitor_{version}_'):
                offenders.append(f'{path.relative_to(ROOT)}: {literal} (project {version})')
    assert not offenders, '\n'.join(offenders)


def test_the_readme_has_no_duplicate_section_heading():
    """A duplicated `## ...` heading means a merge lost a paragraph boundary.

    `## Kernel Module` appeared twice in a row (the second copy was empty), which
    renders as one section and hides the accidental duplication.
    """
    text = (ROOT / 'README.md').read_text(encoding='utf-8')
    headings = re.findall(r'^## (.+)$', text, re.M)
    duplicates = {h for h in headings if headings.count(h) > 1}
    assert not duplicates, f'duplicate README headings: {sorted(duplicates)}'
