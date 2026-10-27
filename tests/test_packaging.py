"""Install-path invariants: the unit, the installers and the config example.

These guard the failure mode where every documented way to install the tool
enabled a daemon whose ExecStart named a config file that no installer ever
created: the unit restarted forever with a traceback, while `apt` printed
success. Reading the files is enough to catch it -- the shipped example is a
conffile, so installing it changes no value.
"""

from __future__ import annotations

import configparser
import re
from pathlib import Path

from msi_psu_monitor.config import DEFAULTS, load_config

ROOT = Path(__file__).resolve().parent.parent
UNIT = ROOT / 'systemd' / 'msi-psu-monitor.service'
EXAMPLE = ROOT / 'docs' / 'msi-psu-monitor.conf.example'
INSTALL_SH = ROOT / 'scripts' / 'install.sh'
BUILD_DEB_SH = ROOT / 'scripts' / 'build_deb.sh'
BUILD_BINARY_SH = ROOT / 'scripts' / 'build_binary.sh'
BUILD_DEB_BINARY_SH = ROOT / 'scripts' / 'build_deb_binary.sh'
INSTALL_BINARY_SH = ROOT / 'scripts' / 'install_binary.sh'
UNINSTALL_BINARY_SH = ROOT / 'scripts' / 'uninstall_binary.sh'
RELEASE_DOC = ROOT / 'docs' / 'release.md'
CI_YML = ROOT / '.github' / 'workflows' / 'ci.yml'
RELEASE_YML = ROOT / '.github' / 'workflows' / 'release.yml'
PYPROJECT = ROOT / 'pyproject.toml'
README = ROOT / 'README.md'

#: Where the daemon looks for a config when --config is not given.
DEFAULT_CONFIG_PATH = '/etc/msi-psu-monitor.conf'


def _version() -> str:
    """The single home of the version: pyproject.toml."""
    text = PYPROJECT.read_text(encoding='utf-8')
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    assert match, 'no project version in pyproject.toml'
    return match.group(1)


def _exec_start_paths() -> list[str]:
    """Paths passed as `--config <path>` on the unit's ExecStart line."""
    text = UNIT.read_text(encoding='utf-8')
    line = next(ln for ln in text.splitlines() if ln.startswith('ExecStart='))
    return re.findall(r'--config[= ](\S+)', line)


def test_the_unit_does_not_require_a_config_nothing_installs():
    """Either the unit passes no --config, or every installer ships that path.

    The check is deliberately the general one: a future author may put
    --config back, as long as something creates the file.
    """
    deb = BUILD_DEB_SH.read_text(encoding='utf-8')
    sh = INSTALL_SH.read_text(encoding='utf-8')
    for path in _exec_start_paths():
        assert f'$STAGE{path}' in deb or f'"$STAGE{path}"' in deb, (
            f'the unit needs {path}, but build_deb.sh never stages it'
        )
        assert path in sh, f'the unit needs {path}, but install.sh never installs it'


def test_the_unit_starts_with_the_default_search_path():
    """The shipped unit must work on a box where nobody configured anything."""
    assert _exec_start_paths() == [], (
        'the unit should let the daemon use CONFIG_FILES instead of pinning a path'
    )


def test_the_shipped_config_example_is_all_defaults():
    """Installing the example must not change a single value.

    That is what makes "ship it as a conffile in /etc" safe: it gives the user
    something to edit without enabling anything.
    """
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(EXAMPLE, encoding='utf-8')
    cfg = load_config(str(EXAMPLE))
    for key, expected in DEFAULTS.items():
        assert cfg[key] == expected, f'{key} changed just by installing the example'
    # Every option that is set must still be the documented default, so the file
    # cannot drift into "quietly different behaviour" either.
    assert parser.sections(), 'the example should show the sections'


def test_the_example_only_sets_keys_the_loader_knows():
    """A typo in the example would be swallowed as an unknown option."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(EXAMPLE, encoding='utf-8')
    for section in parser.sections():
        for option in parser[section]:
            assert option in DEFAULTS, f'[{section}] {option} is not a known setting'


def test_both_installers_ship_the_config_example():
    """apt and install.sh must leave the same file behind."""
    assert f'"$STAGE{DEFAULT_CONFIG_PATH}"' in BUILD_DEB_SH.read_text(encoding='utf-8')
    assert DEFAULT_CONFIG_PATH in INSTALL_SH.read_text(encoding='utf-8')


def test_install_sh_never_overwrites_an_existing_config():
    """The user's edited config survives a reinstall."""
    text = INSTALL_SH.read_text(encoding='utf-8')
    guard = re.search(r'if \[ -e (\S+) \]; then', text)
    assert guard is not None, 'install.sh overwrites /etc/msi-psu-monitor.conf'
    assert guard.group(1) == DEFAULT_CONFIG_PATH


def test_the_deb_does_not_inherit_the_builders_umask():
    """Modules are staged with install(1) -m, not cp(1).

    Under `umask 077` a bare `cp` produced root-only files, so the udev rule's
    uaccess promise for non-root users was broken by packaging.
    """
    text = BUILD_DEB_SH.read_text(encoding='utf-8')
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('cp ') or stripped.startswith('install ') and '-m' not in stripped:
            # `install -d` needs no mode; a file copy without -m is the bug.
            if stripped.startswith('cp ') or not re.search(r'install\s+-d', stripped):
                assert False, f'unpinned mode for a staged file: {stripped}'


def test_the_readme_fan_snippet_is_copy_pasteable():
    """The documented `[fan]` example must parse into the values it names.

    ConfigParser does not strip trailing `;` comments, so `mode = customized   ;
    auto | customized` loads as an unknown mode, which the daemon warns about and
    then ignores -- a documented feature that silently does nothing.
    """
    blocks = re.findall(r'```ini\n(.*?)```', README.read_text(encoding='utf-8'), re.S)
    snippets = [b for b in blocks if b.lstrip().startswith('[fan]')]
    assert len(snippets) == 1, f'expected exactly one [fan] snippet, found {len(snippets)}'
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(snippets[0])
    assert parser.get('fan', 'mode') == 'customized'
    assert parser.getint('fan', 'duty') == 60
    # The keys are real, too: an unknown option is dropped by the loader.
    for option in parser['fan']:
        assert f'fan_{option}' in DEFAULTS or option in DEFAULTS


def test_the_unit_keeps_the_hardening_baseline_without_breaking_hidraw():
    """Defence in depth that cannot lock the daemon out of /dev/hidraw*.

    PrivateDevices would hide the hidraw node the daemon exists to read, and a
    0077 umask would make state.json unreadable to the uaccess user running the
    dashboard. Both stay out on purpose.
    """
    text = UNIT.read_text(encoding='utf-8')
    # Only active directives: the comments explain why PrivateDevices/UMask are
    # absent, and those words must not count as the setting itself.
    active = {
        line.split('=', 1)[0].strip(): line.split('=', 1)[1].strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith('#') and '=' in line
    }
    for name, value in (
        ('ProtectSystem', 'full'),
        ('ProtectHome', 'yes'),
        ('PrivateTmp', 'yes'),
        ('NoNewPrivileges', 'yes'),
        ('ProtectKernelTunables', 'yes'),
        ('ProtectKernelModules', 'yes'),
        ('ProtectKernelLogs', 'yes'),
        ('ProtectControlGroups', 'yes'),
        ('ProtectClock', 'yes'),
        ('RestrictSUIDSGID', 'yes'),
        ('LockPersonality', 'yes'),
        ('RestrictRealtime', 'yes'),
        ('RestrictNamespaces', 'yes'),
        ('RestrictAddressFamilies', 'AF_UNIX AF_NETLINK'),
        ('SystemCallArchitectures', 'native'),
        ('ProtectProc', 'invisible'),
        ('ProcSubset', 'pid'),
        ('PrivateIPC', 'yes'),
        ('CapabilityBoundingSet', ''),
    ):
        assert active.get(name) == value, f'{name} must be {value}'
    assert 'PrivateDevices' not in active
    assert 'UMask' not in active


def test_the_release_is_a_self_contained_onefile_freeze():
    """The official download must not need a Python installation."""
    text = BUILD_BINARY_SH.read_text(encoding='utf-8')
    assert '--onefile' in text and '--strip' in text
    assert 'uv run --frozen --group build pyinstaller' in text
    assert 'GLIBC_FLOOR=2.35' in text
    for name in ('msi-psu-monitor', 'msi-psu-monitor-daemon'):
        assert name in text
    assert 'sha256sum' in text
    assert 'BUILD-INFO' in text
    assert 'MSI_PSU_DEMO=1' in text  # the freeze is smoke-tested before packaging


def test_pyinstaller_is_a_pinned_build_only_dependency():
    text = PYPROJECT.read_text(encoding='utf-8')
    groups = text.split('[dependency-groups]', 1)[1].split('[tool.', 1)[0]
    assert re.search(r'build\s*=\s*\["pyinstaller==[0-9.]+"\]', groups)
    # PyInstaller is build-only; it must not leak into [project].
    project = text.split('[project]', 1)[1].split('[project.scripts]', 1)[0]
    assert 'pyinstaller' not in project


def test_the_tarball_installer_never_requires_python():
    text = INSTALL_BINARY_SH.read_text(encoding='utf-8')
    for forbidden in ('python3', 'pip install', 'uv run', 'python -m'):
        assert forbidden not in text, forbidden
    assert 'PREFIX=' in text
    assert 'install -m 755' in text
    assert '99-msi-psu.rules' in text
    assert 'msi-psu-monitor.service' in text
    assert 'msi-psu-monitor.conf.example' in text
    # The user's edited config is never overwritten.
    assert 'if [ -e "$CONFIG" ]' in text


def test_the_binary_uninstaller_keeps_data_until_purge():
    text = UNINSTALL_BINARY_SH.read_text(encoding='utf-8')
    assert '--purge' in text
    purge_branch = text.index('"$PURGE" = "--purge"')
    assert text.index('rm -rf "$STATE"') > purge_branch
    assert 'rm -f "$CONFIG"' in text[purge_branch:]


def test_the_binary_deb_has_no_python_dependency():
    text = BUILD_DEB_BINARY_SH.read_text(encoding='utf-8')
    control = (
        text.split('cat > "$STAGE/DEBIAN/control"', 1)[1].split('<<EOF', 1)[1].split('EOF', 1)[0]
    )
    depends = next(line for line in control.splitlines() if line.startswith('Depends:'))
    assert depends == 'Depends: libc6 (>= 2.35), zlib1g'
    assert 'python' not in depends.lower()
    assert 'Architecture: $DEB_ARCH' in control
    assert 'dpkg-deb --build --root-owner-group' in text
    for name in ('msi-psu-monitor', 'msi-psu-monitor-daemon'):
        assert name in text


def test_ci_builds_and_checks_the_frozen_release_on_2204():
    text = CI_YML.read_text(encoding='utf-8')
    assert 'freeze:' in text
    assert 'runs-on: ubuntu-22.04' in text
    assert 'scripts/build_binary.sh' in text
    assert 'scripts/build_deb_binary.sh' in text
    assert 'grep -q python' in text


def test_the_release_workflow_covers_both_arches_and_publishes_checksums():
    text = RELEASE_YML.read_text(encoding='utf-8')
    assert 'ubuntu-22.04' in text
    assert 'ubuntu-22.04-arm' in text
    assert 'python-version' in text
    assert 'SHA256SUMS' in text
    assert 'gh release create' in text
    # The release tarball must be matched narrowly: dist/*.tar.gz also matches
    # the hardware kit and then the explicit kit glob passes it twice to
    # gh release create.
    assert 'dist/msi-psu-monitor_*.tar.gz' in text
    assert 'dist/msi-psu-monitor_*_amd64.deb' in text
    assert 'dist/msi-psu-monitor_*_arm64.deb' in text
    assert 'dist/*.deb' not in text
    assert 'dist/*.tar.gz' not in text
    # The smoke test builds a source .deb (Depends: python3); the release must
    # drop it instead of uploading it next to the self-contained binaries.
    assert 'Drop the source .deb' in text


def test_the_release_doc_states_the_no_python_glibc_contract():
    text = RELEASE_DOC.read_text(encoding='utf-8')
    assert 'no Python' in text
    assert 'glibc 2.35' in text
    assert 'SHA256SUMS' in text
    assert 'ubuntu-22.04-arm' in text


PROMETHEUS_RULES = ROOT / 'docs' / 'prometheus-rules.yml'
BUILD_HARDWARE_KIT_SH = ROOT / 'scripts' / 'build_hardware_kit.sh'


def test_the_prometheus_alert_rules_are_shipped():
    """The ops deliverable must exist and be staged by every installer."""
    text = PROMETHEUS_RULES.read_text(encoding='utf-8')
    for needle in (
        'MsiPsuDown',
        'MsiPsuStale',
        'MsiPsuScrapeError',
        'MsiPsuHardwareAlert',
        'MsiPsuThresholdAlert',
        'msi_psu_threshold_alert',
    ):
        assert needle in text, needle
    for script in (BUILD_DEB_SH, BUILD_DEB_BINARY_SH, BUILD_BINARY_SH, BUILD_HARDWARE_KIT_SH):
        assert 'prometheus-rules.yml' in script.read_text(encoding='utf-8'), script


CHANGELOG = ROOT / 'CHANGELOG.md'
CI_WORKFLOW = ROOT / '.github' / 'workflows' / 'ci.yml'
SOAK_SH = ROOT / 'scripts' / 'soak.sh'


def test_the_changelog_is_shipped_and_the_soak_gate_is_in_ci():
    """Release/ops artifacts must be in every package, not only in the tree."""
    assert CHANGELOG.is_file()
    changelog = CHANGELOG.read_text(encoding='utf-8')
    # The changelog must carry the section for the version being released.
    assert f'## [{_version()}]' in changelog
    for script in (BUILD_DEB_SH, BUILD_BINARY_SH, BUILD_HARDWARE_KIT_SH):
        assert 'CHANGELOG.md' in script.read_text(encoding='utf-8'), script
    assert SOAK_SH.is_file()
    assert 'scripts/soak.sh 5000' in CI_WORKFLOW.read_text(encoding='utf-8')


def test_the_psu_shortcut_is_shipped_by_every_installer():
    """`psu` is the menu front door: source install, tarball and both .debs."""
    assert 'psu = "msi_psu_monitor.psu:main"' in PYPROJECT.read_text(encoding='utf-8')
    assert '"psu:psu"' in BUILD_DEB_SH.read_text(encoding='utf-8')
    assert '"$SRC/psu"' in INSTALL_BINARY_SH.read_text(encoding='utf-8')
    assert '"$PREFIX/bin/psu"' in UNINSTALL_BINARY_SH.read_text(encoding='utf-8')
    assert 'psu menu "$@"' in BUILD_BINARY_SH.read_text(encoding='utf-8')
    assert '/usr/bin/psu' in BUILD_DEB_BINARY_SH.read_text(encoding='utf-8')
