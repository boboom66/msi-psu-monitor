"""Lock the USB product IDs across code, udev rule, installer and README.

A model that exists in ``protocol.py`` but not in the udev rule has no
``uaccess`` for non-root users, and one that exists in the README but not in
the code is a promise the tool cannot keep. Both are silent, so this module
cross-checks the four places that must agree.
"""

import re
import pathlib

from msi_psu_monitor.protocol import MSIPSU, PSU_PRODUCT_IDS

ROOT = pathlib.Path(__file__).resolve().parents[1]
HEX4 = re.compile(r'\b([0-9a-f]{4})\b', re.IGNORECASE)


def _text(relative):
    return (ROOT / relative).read_text(encoding='utf-8')


def _code_pids():
    return {f'{pid:04x}' for pid in PSU_PRODUCT_IDS}


def _variant_pids():
    return {f'{entry["pid"]:04x}' for entry in MSIPSU.VARIANTS.values()}


def _udev_pids():
    return {
        match.lower()
        for match in re.findall(
            r'idProduct\}=="([0-9A-Fa-f]{4})"', _text('systemd/99-msi-psu.rules')
        )
    }


def _installer_pids():
    line = next(row for row in _text('scripts/install.sh').splitlines() if 'for pid in' in row)
    return {match.lower() for match in HEX4.findall(line)}


def _readme_pids():
    return {match.lower() for match in re.findall(r'`0db0:([0-9A-Fa-f]{4})`', _text('README.md'))}


def test_protocol_list_and_variant_table_agree():
    assert _code_pids() == _variant_pids()


def test_udev_rule_covers_every_model():
    """All 5 PIDs, or a MEG owner gets EACCES on the hidraw node."""
    assert _udev_pids() == _code_pids()


def test_installer_probe_covers_every_model():
    assert _installer_pids() == _code_pids()


def test_readme_hardware_table_covers_every_model():
    assert _readme_pids() == _code_pids()


def test_readme_payload_sizes_match_the_parser():
    """The documented 0xE0 payload size is what ``_parse_bulk`` gates on."""
    rows = re.findall(r'\| ([^|]+?) \| `0db0:([0-9a-f]{4})` \| (\d+) bytes? \|', _text('README.md'))
    assert len(rows) == len(MSIPSU.VARIANTS)
    by_pid = {f'{entry["pid"]:04x}': entry for entry in MSIPSU.VARIANTS.values()}
    for _name, pid, size in rows:
        assert int(size) == by_pid[pid.lower()]['bulk_size'], pid


def test_every_variant_name_is_documented():
    readme = _text('README.md')
    for key, entry in MSIPSU.VARIANTS.items():
        # "MEG Ai1600(T)" documents the family, so compare without the suffix.
        name = entry['name'].split('(')[0].strip()
        assert name in readme, f'{key}: {name} missing from README'
