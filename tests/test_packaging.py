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
README = ROOT / 'README.md'

#: Where the daemon looks for a config when --config is not given.
DEFAULT_CONFIG_PATH = '/etc/msi-psu-monitor.conf'


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
