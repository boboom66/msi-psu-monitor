"""Tests for the sysfs device-discovery parser (`protocol.detect_devices`).

This seam had no test at all: every other automated path monkeypatches
``detect_device``/``detect_devices`` or runs with ``MSI_PSU_DEMO=1``, which
bypasses sysfs. That is how ``/dev/device`` (the parent directory name, not the
hidraw node) shipped while 400+ tests stayed green -- and on real hardware it
turns "PSU is plugged in" into "not found" / "could not open any MSI PSU device".

The tests build a fake sysfs tree and point the scan at it through
``SYSFS_HIDRAW_GLOB``; the parser itself is never stubbed.
"""

from pathlib import Path

import pytest

from msi_psu_monitor import monitor, protocol

VENDOR = protocol.PSU_VENDOR_ID


def _uevent(root, node, hid_id):
    """Create ``<root>/<node>/device/uevent`` for the fake sysfs tree."""
    path = Path(root) / node / 'device' / 'uevent'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'DRIVER=hid-generic\nHID_ID={hid_id}\nHID_NAME=MSI PSU\n')


def _hid_id(product, vendor=VENDOR):
    return f'0003:{vendor:08X}:{product:08X}'


@pytest.fixture
def fake_sysfs(tmp_path, monkeypatch):
    """Redirect the sysfs scan at a temporary tree, and return it."""
    root = tmp_path / 'sys' / 'class' / 'hidraw'
    root.mkdir(parents=True)
    monkeypatch.setattr(protocol, 'SYSFS_HIDRAW_GLOB', str(root / 'hidraw*' / 'device' / 'uevent'))
    return root


def test_the_scanned_pattern_names_the_node_two_levels_up():
    """The parser derives the node as the grandparent of the uevent file.

    Pinned to the shipped pattern so the extraction and the pattern cannot drift
    apart: if the pattern stops being ``.../hidraw*/device/uevent``, the
    grandparent is no longer "hidrawN" and this fails before hardware does.
    """
    pattern = Path(protocol.SYSFS_HIDRAW_GLOB)
    assert pattern.name == 'uevent'
    assert pattern.parent.name == 'device'
    assert pattern.parent.parent.name == 'hidraw*'


def test_detect_devices_maps_a_sysfs_uevent_to_its_hidraw_node(fake_sysfs):
    _uevent(fake_sysfs, 'hidraw5', _hid_id(0x808C))
    assert protocol.detect_devices() == ['/dev/hidraw5']
    assert protocol.detect_device() == '/dev/hidraw5'


def test_detect_devices_never_returns_the_device_directory_name(fake_sysfs):
    """Regression for ``/dev/device``: the node must not be the "device" dir."""
    _uevent(fake_sysfs, 'hidraw12', _hid_id(0x808C))
    assert protocol.detect_devices() == ['/dev/hidraw12']
    assert '/dev/device' not in protocol.detect_devices()


@pytest.mark.parametrize('product', protocol.PSU_PRODUCT_IDS)
def test_every_shipped_product_id_is_discovered(fake_sysfs, product):
    _uevent(fake_sysfs, 'hidraw3', _hid_id(product))
    assert protocol.detect_devices() == ['/dev/hidraw3']


def test_detect_devices_returns_all_matches_in_sorted_order(fake_sysfs):
    _uevent(fake_sysfs, 'hidraw9', _hid_id(0xAA6F))
    _uevent(fake_sysfs, 'hidraw5', _hid_id(0x808C))
    _uevent(fake_sysfs, 'hidraw1', _hid_id(0x56D4))
    # The glob is sorted, so discovery order is the node name order; detect_device
    # takes the first, and a caller passing --serial walks the rest.
    assert protocol.detect_devices() == ['/dev/hidraw1', '/dev/hidraw5', '/dev/hidraw9']
    assert protocol.detect_device() == '/dev/hidraw1'


def test_foreign_and_unknown_devices_are_skipped(fake_sysfs):
    _uevent(fake_sysfs, 'hidraw2', _hid_id(0x808C, vendor=0x1234))  # wrong vendor
    _uevent(fake_sysfs, 'hidraw4', _hid_id(0xDEAD))  # unknown product
    _uevent(fake_sysfs, 'hidraw6', 'not-a-hid-id')  # no colons
    _uevent(fake_sysfs, 'hidraw7', _hid_id(0x808C).replace('00000DB0', 'ZZZZZZZZ'))
    assert protocol.detect_devices() == []
    assert protocol.detect_device() is None


def test_a_tree_without_psus_reports_nothing(fake_sysfs):
    _uevent(fake_sysfs, 'hidraw0', '')  # empty HID_ID value
    _uevent(fake_sysfs, 'hidraw1', '0003')  # no vendor/product fields
    assert protocol.detect_devices() == []
    assert protocol.detect_device() is None


def test_an_unreadable_uevent_is_skipped_not_fatal(fake_sysfs):
    """A directory where the uevent should be: ``open()`` raises, scan continues."""
    (fake_sysfs / 'hidraw4' / 'device' / 'uevent').mkdir(parents=True)
    _uevent(fake_sysfs, 'hidraw8', _hid_id(0x808C))
    assert protocol.detect_devices() == ['/dev/hidraw8']


def test_detect_devices_is_deduplicated(fake_sysfs):
    """Two HID_ID lines for the same node must not yield the node twice."""
    path = fake_sysfs / 'hidraw5' / 'device' / 'uevent'
    path.parent.mkdir(parents=True)
    path.write_text(f'HID_ID={_hid_id(0x808C)}\nHID_ID={_hid_id(0x808C)}\n')
    assert protocol.detect_devices() == ['/dev/hidraw5']


def test_resolve_device_uses_the_real_parser(fake_sysfs, monkeypatch):
    """End-to-end through ``monitor.resolve_device`` with only the USB I/O stubbed."""

    class StubHID:
        def open(self):
            return self

        def close(self):
            pass

    class StubPSU:
        def __init__(self, hid):
            self.serial = 'TS-SERIAL'

        def open(self):
            return self

        def close(self):
            pass

        def init(self):
            return 'MPG Ai1600TS'

    monkeypatch.setattr(monitor, 'HIDDevice', lambda path: StubHID())
    monkeypatch.setattr(monitor, 'MSIPSU', StubPSU)
    _uevent(fake_sysfs, 'hidraw5', _hid_id(0x808C))

    assert monitor.resolve_device(None) == ('/dev/hidraw5', [], [])
    assert monitor.resolve_device('TS-SERIAL') == ('/dev/hidraw5', ['TS-SERIAL'], [])
    assert monitor.resolve_device('OTHER') == (None, ['TS-SERIAL'], [])


def test_resolve_device_reports_a_device_that_cannot_be_opened(fake_sysfs, monkeypatch):
    """An unopenable node is "blocked", never "no PSU with that serial"."""

    class StubHID:
        def open(self):
            raise PermissionError(13, 'Permission denied')

        def close(self):
            pass

    monkeypatch.setattr(monitor, 'HIDDevice', lambda path: StubHID())
    _uevent(fake_sysfs, 'hidraw5', _hid_id(0x808C))

    assert monitor.resolve_device('TS-SERIAL') == (None, [], ['/dev/hidraw5'])


def test_demo_mode_never_touches_sysfs(fake_sysfs, monkeypatch):
    """``MSI_PSU_DEMO=1`` short-circuits before the scan (why CI never saw /dev/device)."""
    monkeypatch.setenv('MSI_PSU_DEMO', '1')
    # The fake tree is deliberately empty: if the demo branch ever fell through to
    # the sysfs scan, this would be the "no PSU found" tuple instead.
    assert monitor.resolve_device(None) == (
        monitor.demo.DEVICE_PATH,
        [monitor.demo.DEMO_SERIAL],
        [],
    )
    assert protocol.detect_devices() == []
