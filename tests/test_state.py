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


def test_load_ignores_wrong_types_in_a_valid_json_file(tmp_path):
    """Hand-edited state.json must not raise: bad values fall back to zero.

    ``{"count": "bad"}`` used to escape as ``ValueError`` from ``int()`` -- a
    traceback on a file that is valid JSON, which is exactly the kind of file a
    user produces by editing it.
    """
    path = stats.state_path(tmp_path)
    path.write_text(json.dumps({'version': 1, 'count': 'bad', 'last_ts': []}))
    monitor_state = stats.MonitorState.load(path)
    assert monitor_state.count == 0
    assert monitor_state.last_ts is None

    path.write_text(json.dumps({'version': 1, 'watt_sum': 'NaN', 'energy_wh': None}))
    monitor_state = stats.MonitorState.load(path)
    assert monitor_state.watt_sum == 0.0
    assert monitor_state.energy_wh == 0.0


def test_load_drops_daily_buckets_that_are_not_numbers(tmp_path):
    """A string bucket would turn the next sample into a TypeError mid-run."""
    path = stats.state_path(tmp_path)
    path.write_text(json.dumps({'version': 1, 'daily': {'2026-02-09': 'bad', '2026-02-10': 1.5}}))
    monitor_state = stats.MonitorState.load(path)
    assert monitor_state.daily == {'2026-02-10': 1.5}
    monitor_state.update(600.0, 94.0, ts=1700000000.0)
    assert monitor_state.energy_wh == 0.0  # still a clean, usable state


def test_a_backwards_clock_step_does_not_double_count_energy():
    """A step back must not move the clock back with it.

    Re-baselining on the older stamp made the next sample integrate the step plus
    the real interval: 600 W over 100 s became 33.3 Wh instead of 16.7 Wh.
    """
    monitor_state = stats.MonitorState()
    monitor_state.update(600.0, 90.0, ts=1000.0)
    monitor_state.update(600.0, 90.0, ts=900.0)
    assert monitor_state.last_ts == 1000.0
    monitor_state.update(600.0, 90.0, ts=1100.0)
    assert monitor_state.energy_wh == pytest.approx(600.0 * 100 / 3600)
    assert monitor_state.count == 3


# ---- history ------------------------------------------------------------


def test_append_history_writes_a_header_once(tmp_path):
    stats.append_history(tmp_path, sensors(), ts=1700000000.0)
    stats.append_history(tmp_path, sensors(), ts=1700000060.0)
    path = stats.history_path(tmp_path, date.fromtimestamp(1700000000.0))
    lines = path.read_text().splitlines()
    assert lines[0] == ','.join(stats.HISTORY_COLUMNS)
    assert len(lines) == 3
    expected = datetime.fromtimestamp(1700000000.0).astimezone().isoformat(timespec='seconds')
    assert lines[1].startswith(expected)
    columns = dict(zip(lines[0].split(','), lines[1].split(',')))
    assert columns['eff'] == '94.00'
    # Single-rail models have no discrete 12V rails, so the CPU/GPU wattage
    # columns stay empty and --export renders them as N/A.
    assert columns['cpu_w'] == ''
    assert columns['gpu_w'] == ''


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
    with pytest.raises(ValueError):
        stats.parse_columns('')  # an empty spec quietly meant "all columns"


def test_build_export_marks_cpu_gpu_as_na(tmp_path):
    stats.append_history(tmp_path, sensors(), ts=1700000000.0)
    header, rows = stats.build_export(tmp_path, since_ts=None, columns=['cpu', 'gpu', 'temp'])
    assert header == ['time', 'cpu', 'gpu', 'temp']
    assert rows[0][1:3] == ['N/A', 'N/A']
    assert rows[0][3] == '56.0'


def multi_rail_sensors(**extra):
    """Sensors of an Ai1000P/Ai1300P sample with five discrete 12V rails."""
    rails_v = [12.0, 12.0, 12.0, 12.0, 12.0]
    rails_a = [0.5, 2.0, 3.0, 1.0, 4.0]
    return sensors(
        vout_12v_rails=(rails_v, 'V'),
        iout_12v_rails=(rails_a, 'A'),
        **extra,
    )


def test_rail_watts_follows_the_msi_center_split():
    # CPU = 12V2, GPU = 12V3+12V4+12V5 (UC_Dashboard_Page.xaml.cs:203-204).
    assert stats.rail_watts(multi_rail_sensors()) == (24.0, 96.0)


def test_rail_watts_needs_both_rail_lists():
    assert stats.rail_watts(sensors()) is None
    assert stats.rail_watts(sensors(vout_12v_rails=([12.0] * 5, 'V'))) is None
    # A truncated rail list must not silently shift the CPU/GPU mapping.
    assert (
        stats.rail_watts(
            sensors(vout_12v_rails=([12.0, 12.0], 'V'), iout_12v_rails=([1.0, 2.0], 'A'))
        )
        is None
    )


def test_history_records_cpu_gpu_watts_for_multi_rail(tmp_path):
    stats.append_history(tmp_path, multi_rail_sensors(), ts=1700000000.0)
    path = stats.history_path(tmp_path, date.fromtimestamp(1700000000.0))
    header, line = path.read_text().splitlines()[:2]
    row = dict(zip(header.split(','), line.split(',')))
    assert row['cpu_w'] == '24.0'
    assert row['gpu_w'] == '96.0'


def test_build_export_uses_recorded_cpu_gpu_watts(tmp_path):
    stats.append_history(tmp_path, multi_rail_sensors(), ts=1700000000.0)
    header, rows = stats.build_export(tmp_path, since_ts=None, columns=['cpu', 'gpu', 'temp'])
    assert header == ['time', 'cpu', 'gpu', 'temp']
    assert rows[0][1:3] == ['24.0', '96.0']
    assert rows[0][3] == '56.0'


def test_build_export_reads_older_history_without_rail_columns(tmp_path):
    """A history file written before this feature still exports N/A."""
    path = stats.history_path(tmp_path, date(2026, 2, 9))
    path.write_text(
        'time,12v,5v,3v3,total_a,temp,fan,power,eff\n'
        '2026-02-09T10:00:00,12.100,5.040,3.320,50.000,56.0,2050,600.0,94.00\n'
    )
    _, rows = stats.build_export(tmp_path, since_ts=None, columns=['cpu', 'gpu'])
    assert rows[0][1:3] == ['N/A', 'N/A']


def test_append_history_repairs_a_headerless_file(tmp_path):
    """A day file that exists but is empty must get its header, not lose its columns.

    Without this, a crash between open() and the header write leaves a file whose
    first data row DictReader reads as column names -- every export for that day
    silently shifts by one column.
    """
    path = stats.history_path(tmp_path, date.fromtimestamp(1700000000.0))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()

    stats.append_history(tmp_path, sensors(), ts=1700000000.0)
    lines = path.read_text().splitlines()
    assert lines[0] == ','.join(stats.HISTORY_COLUMNS)
    assert len(lines) == 2

    header, rows = stats.build_export(tmp_path, None, ['12v', 'cpu'])
    assert header == ['time', '12v', 'cpu']
    assert rows[0][1] == '12.100'
    assert rows[0][2] == stats.NOT_AVAILABLE


def test_append_history_repairs_a_header_truncated_mid_write(tmp_path):
    """A crash mid-header leaves a fragment that must not become the columns.

    With ``time,12v`` as the header, DictReader filed every later value under the
    wrong name and the export reported the day as empty.
    """
    path = stats.history_path(tmp_path, date.fromtimestamp(1700000000.0))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        'time,12v\n2026-02-09T10:00:00,12.100,5.040,3.320,50.000,56.0,2050,600.0,94.00\n'
    )

    stats.append_history(tmp_path, sensors(), ts=1700000000.0)
    lines = path.read_text().splitlines()
    assert lines[0] == ','.join(stats.HISTORY_COLUMNS)
    assert len(lines) == 3  # the salvageable data row survived

    _, rows = stats.build_export(tmp_path, None, ['12v', 'temp'])
    assert rows[0][1:3] == ['12.100', '56.0']
    assert rows[1][1:3] == ['12.100', '56.0']


def test_append_history_keeps_a_legacy_headerless_file_intact(tmp_path):
    """A file that starts with data gets the header prepended, nothing dropped."""
    path = stats.history_path(tmp_path, date.fromtimestamp(1700000000.0))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('2026-02-09T10:00:00,12.100,5.040,3.320,50.000,56.0,2050,600.0,94.00\n')

    stats.append_history(tmp_path, sensors(), ts=1700000000.0)
    lines = path.read_text().splitlines()
    assert lines[0] == ','.join(stats.HISTORY_COLUMNS)
    assert lines[1].startswith('2026-02-09T10:00:00,12.100')


def test_iter_history_skips_junk_rows_and_undecodable_files(tmp_path):
    """A damaged day must be skipped, not exported as empty or raised as a crash."""
    good = stats.history_path(tmp_path, date(2026, 2, 9))
    good.write_text(
        ','.join(stats.HISTORY_COLUMNS) + '\n'
        '2026-02-09T10:00:00,12.100,5.040,3.320,50.000,56.0,2050,600.0,94.00,24.0,96.0\n'
        '\x00\n'
    )
    binary = stats.history_path(tmp_path, date(2026, 2, 10))
    binary.write_bytes(b'time,12v\n\xff\xfe\n')

    rows = list(stats.iter_history(tmp_path))
    assert len(rows) == 1
    assert rows[0]['time'] == '2026-02-09T10:00:00'
    assert stats.build_export(tmp_path, None, ['12v'])[1] == [['2026-02-09T10:00:00', '12.100']]


def test_state_dir_prefers_the_explicit_override(monkeypatch, tmp_path):
    monkeypatch.setenv('MSI_PSU_STATE_DIR', str(tmp_path / 'explicit'))
    monkeypatch.setenv('STATE_DIRECTORY', str(tmp_path / 'systemd'))
    assert stats.default_state_dir() == tmp_path / 'explicit'


def test_state_dir_honours_the_systemd_state_directory(monkeypatch, tmp_path):
    """StateDirectory= in the unit must win: ProtectHome makes $HOME unusable."""
    monkeypatch.delenv('MSI_PSU_STATE_DIR', raising=False)
    monkeypatch.setenv('STATE_DIRECTORY', f'{tmp_path / "srv"}:/run/other')
    assert stats.default_state_dir() == tmp_path / 'srv'


def test_load_survives_a_state_file_that_is_not_utf8(tmp_path, caplog):
    """A UTF-16/latin-1 state.json must not be a traceback, and must not be silent.

    ``read_text`` raises UnicodeDecodeError -- a ValueError, not an OSError -- so
    the old ``except OSError`` let it escape ``load``: a traceback at daemon
    startup, i.e. a 5 s crash loop under ``Restart=always``.
    """
    path = stats.state_path(tmp_path)
    path.write_bytes(b'{"version":1,"product":"\xff\xfe"}')
    with caplog.at_level('WARNING'):
        monitor_state = stats.MonitorState.load(path)
    assert monitor_state.count == 0
    assert 'Cannot read the state file' in caplog.text


def test_load_says_so_when_it_ignores_a_state_file(tmp_path, caplog):
    """Zeroed totals that look measured are the thing this module promises not to do."""
    path = stats.state_path(tmp_path)
    path.write_text(json.dumps({'version': 99, 'count': 5, 'energy_wh': 12.0}))
    with caplog.at_level('WARNING'):
        monitor_state = stats.MonitorState.load(path)
    assert monitor_state.count == 0
    assert 'format version 99' in caplog.text


def test_load_of_a_missing_file_is_not_a_warning(tmp_path, caplog):
    """The first run has no state file: that is normal, not a problem to report."""
    with caplog.at_level('WARNING'):
        assert stats.MonitorState.load(stats.state_path(tmp_path)).count == 0
    assert caplog.text == ''


def test_iter_history_reads_columns_positionally_without_a_header(tmp_path):
    """A headerless day file used to read as empty: DictReader ate the first row.

    With no header, DictReader adopts the first *data* row as its fieldnames, so
    every row looks like it has no ``time`` and the whole day is invisible to
    --export and to the dashboard, with nothing logged.
    """
    path = stats.history_path(tmp_path, date(2026, 2, 9))
    path.write_text('2026-02-09T10:00:00,12.100,5.040,3.320,50.000,56.0,2050,600.0,94.00,\n')
    rows = list(stats.iter_history(tmp_path))
    assert [row['time'] for row in rows] == ['2026-02-09T10:00:00']
    assert rows[0]['12v'] == '12.100'
    assert rows[0]['temp'] == '56.0'


def test_iter_history_reads_columns_positionally_with_a_renamed_header(tmp_path):
    """A hand-renamed or BOM'd header must not cost the whole day either."""
    path = stats.history_path(tmp_path, date(2026, 2, 9))
    path.write_text(
        'timestamp,volts,amps\n'
        '2026-02-09T10:00:00,12.100,5.040,3.320,50.000,56.0,2050,600.0,94.00,\n'
    )
    rows = list(stats.iter_history(tmp_path))
    assert len(rows) == 1
    assert rows[0]['12v'] == '12.100'


def test_iter_history_warns_about_a_non_canonical_header(tmp_path, caplog):
    path = stats.history_path(tmp_path, date(2026, 2, 9))
    path.write_text('\ufeff' + ','.join(stats.HISTORY_COLUMNS) + '\n')
    with caplog.at_level('WARNING'):
        assert list(stats.iter_history(tmp_path)) == []
    assert 'no canonical header' in caplog.text


def test_iter_history_ignores_something_that_is_not_a_regular_file(tmp_path, caplog):
    """The glob matches a FIFO or /dev/zero; reading one never returns."""
    import os

    os.symlink('/dev/zero', tmp_path / 'daily-20240101.log')
    with caplog.at_level('WARNING'):
        assert list(stats.iter_history(tmp_path)) == []
    assert 'not a regular file' in caplog.text


def test_append_history_does_not_glue_a_row_onto_a_torn_one(tmp_path, caplog):
    """A partial flush (ENOSPC, power cut) must not shift the columns of the next row."""
    path = stats.history_path(tmp_path, date(2026, 2, 9))
    path.write_text(
        ','.join(stats.HISTORY_COLUMNS) + '\n'
        '2026-02-09T09:00:00,12.100,5.040,3.320,50.000,56.0,2050,600.0,94.00,24.0,96.0\n'
        '2026-02-09T10:00:00,12.100,5.0'
    )
    with caplog.at_level('WARNING'):
        stats.append_history(tmp_path, sensors(), ts=datetime(2026, 2, 9, 10, 1).timestamp())
    lines = path.read_text().splitlines()
    assert lines[-1].startswith('2026-02-09T10:01:00')  # this row is intact
    assert ',12.100,5.040,' in lines[-1]  # and its columns are not shifted
    assert lines[-2] == '2026-02-09T10:00:00,12.100,5.0'  # the torn row stays its own line
    assert 'the last line was incomplete' in caplog.text
    assert len(list(stats.iter_history(tmp_path))) == 3


def test_history_timestamps_are_absolute_instants(tmp_path):
    """A naive local stamp cannot say which of the two 02:30s it means.

    On a fall-back night ``datetime.fromisoformat('...T02:30:00')`` resolves to
    the *first* 02:30, so a row written at the second one was read an hour too
    old and silently fell out of a ``--from 90m`` window. The offset is written
    from now on; older naive rows keep working (and keep that ambiguity).
    """
    stamp = datetime(2026, 10, 25, 2, 30, tzinfo=datetime.now().astimezone().tzinfo).timestamp()
    stats.append_history(tmp_path, sensors(), ts=stamp)
    row = next(stats.iter_history(tmp_path))
    written = datetime.fromisoformat(row['time'])
    assert written.utcoffset() is not None
    assert abs(written.timestamp() - stamp) < 0.5


def test_old_naive_history_rows_still_read(tmp_path):
    """The format change must not orphan the rows already on disk."""
    path = stats.history_path(tmp_path, date(2026, 2, 9))
    path.write_text(
        ','.join(stats.HISTORY_COLUMNS)
        + '\n2026-02-09T10:00:00,12.100,5.040,3.320,50.000,56.0,2050,600.0,94.00,24.0,96.0\n'
    )
    assert stats.build_export(tmp_path, None, ['12v'])[1] == [['2026-02-09T10:00:00', '12.100']]


def test_a_backwards_clock_says_the_integral_is_frozen(tmp_path, caplog):
    """The AVG keeps moving while the kWh total stops: that must not be silent."""
    monitor_state = stats.MonitorState()
    monitor_state.update(600.0, 94.0, ts=1000.0)  # starts the clock
    monitor_state.update(600.0, 94.0, ts=1010.0)
    energy = monitor_state.energy_wh
    assert energy > 0
    with caplog.at_level('WARNING'):
        monitor_state.update(600.0, 94.0, ts=1005.0)  # NTP stepped the clock back
        monitor_state.update(600.0, 94.0, ts=1006.0)  # still behind: no new spam
    assert monitor_state.energy_wh == energy
    assert monitor_state.count == 4  # the average still counts the sample
    assert caplog.text.count('clock went backwards') == 1
    with caplog.at_level('WARNING'):
        monitor_state.update(600.0, 94.0, ts=1020.0)  # caught up: integrates again
    assert monitor_state.energy_wh > energy


def test_load_ignores_a_state_file_that_is_not_a_regular_file(tmp_path, caplog):
    """A symlink to /dev/zero (or a FIFO) must not be read until MemoryError."""
    import os

    path = stats.state_path(tmp_path)
    os.symlink('/dev/zero', path)
    with caplog.at_level('WARNING'):
        assert stats.MonitorState.load(path).count == 0
    assert 'not a regular file' in caplog.text
