"""Tests for the persistent cumulative state and the history/export helpers."""

import json
from datetime import date, datetime

import pytest

from msi_psu_monitor import state as stats


def sensors(power=600.0, efficiency=94.0, **extra):
    base = {
        'product': 'MPG Ai1600TS',
        'serial': 'SN1234',
        'vout_12v': (12.1, 'V'),
        'vout_5v': (5.04, 'V'),
        'vout_3v3': (3.32, 'V'),
        'iout_12v_total': (50.0, 'A'),
        'temp': (56.0, 'C'),
        'fan_rpm': (2050, 'RPM'),
        'power_total': (power, 'W'),
        'efficiency': (efficiency, '%'),
    }
    base.update(extra)
    return base


# ---- MonitorState -------------------------------------------------------


def test_empty_state_defaults_to_zero():
    monitor_state = stats.MonitorState()
    assert monitor_state.power_avg == 0.0
    assert monitor_state.efficiency_avg == 0.0
    assert monitor_state.total_energy_kwh == 0.0


def test_update_averages_and_energy_integral():
    monitor_state = stats.MonitorState()
    monitor_state.update(600.0, 94.0, ts=1000.0)  # first sample only starts the clock
    assert monitor_state.energy_wh == 0.0
    monitor_state.update(600.0, 90.0, ts=1100.0)  # 100 s at 600 W = 16.67 Wh
    assert monitor_state.count == 2
    assert monitor_state.power_avg == 600.0
    assert monitor_state.efficiency_avg == 92.0
    assert monitor_state.energy_wh == pytest.approx(600.0 * 100 / 3600)
    assert monitor_state.total_energy_kwh == pytest.approx(600.0 * 100 / 3600 / 1000)


def test_update_skips_energy_across_a_long_gap():
    monitor_state = stats.MonitorState()
    monitor_state.update(500.0, 90.0, ts=0.0)
    monitor_state.update(500.0, 90.0, ts=stats.MAX_SAMPLE_GAP_S + 1)
    assert monitor_state.energy_wh == 0.0
    assert monitor_state.count == 2  # the average still counts the sample


def test_prune_drops_old_daily_buckets_only():
    monitor_state = stats.MonitorState(daily={'2026-01-01': 1.0, '2026-02-01': 2.0, 'bogus': 3.0})
    dropped = monitor_state.prune(today=date(2026, 2, 10), days=30)
    assert sorted(dropped) == ['2026-01-01', 'bogus']
    assert list(monitor_state.daily) == ['2026-02-01']


def test_note_identity_keeps_the_latest_known_values():
    monitor_state = stats.MonitorState()
    monitor_state.note_identity(sensors())
    assert (monitor_state.product, monitor_state.serial) == ('MPG Ai1600TS', 'SN1234')
    monitor_state.note_identity({'product': '', 'serial': ''})
    assert (monitor_state.product, monitor_state.serial) == ('MPG Ai1600TS', 'SN1234')


def test_save_load_roundtrip(tmp_path):
    monitor_state = stats.MonitorState()
    monitor_state.note_identity(sensors())
    monitor_state.update(600.0, 94.0, ts=1000.0)
    monitor_state.update(600.0, 94.0, ts=1060.0)
    path = stats.state_path(tmp_path)
    monitor_state.save(path)

    reloaded = stats.MonitorState.load(path)
    assert reloaded.to_dict() == monitor_state.to_dict()
    assert reloaded.count == 2
    assert reloaded.product == 'MPG Ai1600TS'
    assert reloaded.energy_wh == pytest.approx(10.0)


def test_save_is_atomic_and_leaves_no_tmp_file(tmp_path):
    path = stats.state_path(tmp_path)
    stats.MonitorState(count=1).save(path)
    assert path.exists()
    assert not path.with_name(path.name + '.tmp').exists()


def test_load_tolerates_missing_and_corrupt_files(tmp_path):
    missing = tmp_path / 'nope.json'
    assert stats.MonitorState.load(missing).count == 0
    corrupt = stats.state_path(tmp_path)
    corrupt.write_text('{not json')
    assert stats.MonitorState.load(corrupt).count == 0
    corrupt.write_text(json.dumps({'version': 99, 'count': 5}))
    assert stats.MonitorState.load(corrupt).count == 0


# ---- history ------------------------------------------------------------


def test_append_history_writes_a_header_once(tmp_path):
    stats.append_history(tmp_path, sensors(), ts=1700000000.0)
    stats.append_history(tmp_path, sensors(), ts=1700000060.0)
    path = stats.history_path(tmp_path, date.fromtimestamp(1700000000.0))
    lines = path.read_text().splitlines()
    assert lines[0] == ','.join(stats.HISTORY_COLUMNS)
    assert len(lines) == 3
    expected = datetime.fromtimestamp(1700000000.0).strftime('%Y-%m-%dT%H:%M:%S')
    assert lines[1].startswith(expected)
    assert lines[1].split(',')[-1] == '94.00'


def test_iter_history_respects_the_since_cutoff(tmp_path):
    for offset in (0.0, 3600.0):
        stats.append_history(tmp_path, sensors(), ts=1700000000.0 + offset)
    rows = list(stats.iter_history(tmp_path, since_ts=1700000000.0 + 1))
    assert len(rows) == 1
    assert len(list(stats.iter_history(tmp_path))) == 2


def test_prune_history_removes_only_old_files(tmp_path):
    old = stats.history_path(tmp_path, date(2020, 1, 1))
    new = stats.history_path(tmp_path, date(2026, 2, 9))
    for path in (old, new):
        path.write_text('')
    removed = stats.prune_history(tmp_path, today=date(2026, 2, 10), days=30)
    assert removed == [old]
    assert new.exists()


# ---- --from / --columns / --export --------------------------------------


@pytest.mark.parametrize(
    'spec,expected',
    [('30m', 1800.0), ('2h', 7200.0), ('7d', 604800.0), ('1.5h', 5400.0), (' 5D ', 432000.0)],
)
def test_parse_from(spec, expected):
    assert stats.parse_from(spec) == expected


@pytest.mark.parametrize('spec', ['', 'soon', '2w', '-1h', 'h'])
def test_parse_from_rejects_bad_windows(spec):
    with pytest.raises(ValueError):
        stats.parse_from(spec)


def test_parse_columns_order_dedup_and_all():
    assert stats.parse_columns(None) == list(stats.EXPORT_COLUMNS)
    assert stats.parse_columns('all') == list(stats.EXPORT_COLUMNS)
    assert stats.parse_columns('eff,12v,eff') == ['12v', 'eff']
    with pytest.raises(ValueError):
        stats.parse_columns('wattage')


def test_build_export_marks_cpu_gpu_as_na(tmp_path):
    stats.append_history(tmp_path, sensors(), ts=1700000000.0)
    header, rows = stats.build_export(tmp_path, since_ts=None, columns=['cpu', 'gpu', 'temp'])
    assert header == ['time', 'cpu', 'gpu', 'temp']
    assert rows[0][1:3] == ['N/A', 'N/A']
    assert rows[0][3] == '56.0'
