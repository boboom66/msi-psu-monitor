"""--watch text-console behaviour: redraw, terminal capability, cleanup.

The interactive path used to shell out to ``clear`` on every frame, which broke
on a console without ``TERM`` (the error text landed inside the frame) and wiped
the scrollback on every refresh. These tests pin the replacement: ANSI redraw on
a real terminal, plain frames everywhere else, and a cursor/signal cleanup that
runs even when the device disappears mid-session.
"""

import io
import logging
import signal
import sys
import types

import pytest

from msi_psu_monitor import monitor
from msi_psu_monitor.monitor import EXIT_ERROR, EXIT_OK


class FakeStream(io.StringIO):
    """StringIO that answers isatty() the way a real terminal or pipe does."""

    def __init__(self, tty):
        super().__init__()
        self._tty = tty

    def isatty(self):
        return self._tty


class FramePSU:
    """Return a fixed list of frames, then stop the loop with KeyboardInterrupt."""

    def __init__(self, frames):
        self._frames = frames
        self.calls = 0

    def get_sensors(self):
        if self.calls >= len(self._frames):
            raise KeyboardInterrupt
        frame = self._frames[self.calls]
        self.calls += 1
        return dict(frame)

    def read_fan_state(self):
        return {'mode': 1, 'duty': 30, 'zero_fan': True}


def sample(**extra):
    base = {
        'product': 'MPG Ai1600TS',
        'serial': 'SN1',
        'vendor': 'MSI',
        'fw_revision': '1.0',
        'vout_12v': (12.1, 'V'),
        'iout_12v_total': (50.0, 'A'),
        'power_total': (600.0, 'W'),
        'efficiency': (94.0, '%'),
        'temp': (56.0, 'C'),
    }
    base.update(extra)
    return base


def run_watch_once(monkeypatch, frames, *, tty, term, columns, rows=40):
    """Drive one --watch session against fakes; return (code, stdout, stderr)."""
    args = types.SimpleNamespace(
        interval=0.01,
        watch=0.01,
        output=None,
        quiet=True,
        no_alerts=True,
    )
    cfg = {'interval': 0.01, 'retention_days': 30}

    out = FakeStream(tty)
    err = FakeStream(False)
    monkeypatch.setattr(sys, 'stdout', out)
    monkeypatch.setattr(sys, 'stderr', err)
    if term is None:
        monkeypatch.delenv('TERM', raising=False)
    else:
        monkeypatch.setenv('TERM', term)
    monkeypatch.setattr(monitor, '_terminal_size', lambda stream=None: (columns, rows))
    monkeypatch.setattr(
        monitor.os, 'system', lambda *a, **k: pytest.fail('--watch must not shell out')
    )

    code = monitor.run_watch(FramePSU(frames), args, cfg, None, None)
    return code, out.getvalue(), err.getvalue()


def test_tty_redraw_is_ansi_and_never_calls_clear(monkeypatch):
    code, out, err = run_watch_once(
        monkeypatch, [sample(), sample(temp=(57.0, 'C'))], tty=True, term='xterm', columns=120
    )
    assert code == EXIT_OK
    assert '\x1b[H\x1b[J' in out
    assert '\x1b[?25l' in out and '\x1b[?25h' in out
    assert 'MSI PSU Monitor' in out and 'Ctrl-C to stop' in out
    assert 'MSI PSU: MPG Ai1600TS' in out
    assert 'TERM environment variable not set' not in out + err
    assert out.count('\x1b[H\x1b[J') == 2


def test_pipe_mode_stays_a_plain_parseable_stream(monkeypatch):
    code, out, _ = run_watch_once(
        monkeypatch, [sample(), sample()], tty=False, term='xterm', columns=120
    )
    assert code == EXIT_OK
    assert '\x1b' not in out
    assert 'Ctrl-C to stop' not in out
    assert out.count('MSI PSU: MPG Ai1600TS') == 2


def test_dumb_terminal_is_not_sent_escape_codes(monkeypatch):
    code, out, _ = run_watch_once(monkeypatch, [sample()], tty=True, term='dumb', columns=120)
    assert code == EXIT_OK
    assert '\x1b' not in out


def test_missing_term_is_treated_as_plain_output(monkeypatch):
    code, out, err = run_watch_once(monkeypatch, [sample()], tty=True, term=None, columns=120)
    assert code == EXIT_OK
    assert '\x1b' not in out
    assert 'TERM environment variable' not in out + err


def test_narrow_terminal_warns_once_and_streams_frames(monkeypatch):
    code, out, err = run_watch_once(
        monkeypatch, [sample(), sample()], tty=True, term='xterm', columns=39
    )
    assert code == EXIT_OK
    assert '\x1b' not in out
    assert '39 columns wide' in err
    assert err.count('columns wide') == 1
    assert out.count('MSI PSU: MPG Ai1600TS') == 2


def test_cursor_is_restored_when_the_device_errors(monkeypatch):
    code, out, _ = run_watch_once(
        monkeypatch,
        [sample(), {'product': 'MPG Ai1600TS', 'error': 'device unplugged'}],
        tty=True,
        term='xterm',
        columns=120,
    )
    assert code == EXIT_ERROR
    assert '\x1b[?25l' in out
    assert '\x1b[?25h' in out


def test_short_terminal_streams_instead_of_scrolling_the_header_away(monkeypatch):
    code, out, err = run_watch_once(
        monkeypatch, [sample()], tty=True, term='xterm', columns=120, rows=8
    )
    assert code == EXIT_OK
    assert '\x1b' not in out
    assert '8 rows high' in err
    assert 'Streaming frames instead' in err


def test_width_check_uses_the_real_frame_including_the_header(monkeypatch):
    """60 columns fits every sensor line but not the ~70-column status header."""
    code, out, err = run_watch_once(
        monkeypatch, [sample()], tty=True, term='xterm', columns=60, rows=40
    )
    assert code == EXIT_OK
    assert '\x1b' not in out
    assert '60 columns wide' in err


def test_terminal_probes_survive_a_detached_stdout():
    class BrokenTTY(io.StringIO):
        def isatty(self):
            raise ValueError('closed')

    class NoFileno(io.StringIO):
        def fileno(self):
            raise OSError('detached')

    assert monitor._stdout_is_tty(BrokenTTY()) is False
    assert monitor._terminal_size(NoFileno()) == (0, 0)


def test_unknown_terminal_size_keeps_the_redraw(monkeypatch):
    code, out, _ = run_watch_once(
        monkeypatch, [sample()], tty=True, term='xterm', columns=0, rows=0
    )
    assert code == EXIT_OK
    assert '\x1b[H\x1b[J' in out


def test_ctrl_c_outside_watch_exits_one_without_a_traceback(monkeypatch, capsys):
    def interrupted():
        raise KeyboardInterrupt

    monkeypatch.setattr(monitor, '_main', interrupted)
    with pytest.raises(SystemExit) as exc:
        monitor.main()
    assert exc.value.code == 1
    assert 'Interrupted.' in capsys.readouterr().err


def test_sigterm_is_mapped_to_keyboard_interrupt_and_restored(monkeypatch):
    if not hasattr(signal, 'SIGTERM'):  # pragma: no cover - Linux-only project
        pytest.skip('SIGTERM is not available on this platform')
    before = signal.getsignal(signal.SIGTERM)
    previous = monitor._watch_enable_soft_termination()
    try:
        handler = signal.getsignal(signal.SIGTERM)
        assert handler is not before
        with pytest.raises(KeyboardInterrupt):
            handler(signal.SIGTERM, None)
    finally:
        monitor._watch_restore_signals(previous)
    assert signal.getsignal(signal.SIGTERM) is before


def test_plain_cursor_mode_leaves_signal_handlers_alone(monkeypatch):
    if not hasattr(signal, 'SIGTERM'):  # pragma: no cover - Linux-only project
        pytest.skip('SIGTERM is not available on this platform')
    before = signal.getsignal(signal.SIGTERM)
    run_watch_once(monkeypatch, [sample()], tty=False, term='xterm', columns=120)
    assert signal.getsignal(signal.SIGTERM) is before


def test_a_frame_without_payload_is_skipped_not_rendered(monkeypatch, caplog):
    """Ident-only replies must warn and retry, never print a half-empty frame."""
    ident_only = {'product': 'MPG Ai1600TS', 'vendor': 'MSI', 'serial': 'SN1'}
    with caplog.at_level(logging.WARNING, logger='msi_psu'):
        code, out, _ = run_watch_once(
            monkeypatch, [ident_only, sample()], tty=False, term='xterm', columns=120
        )
    assert code == EXIT_OK
    assert 'frame skipped' in caplog.text
    assert out.count('MSI PSU: MPG Ai1600TS') == 1


def test_unwritable_frame_file_returns_error_instead_of_raising(monkeypatch, tmp_path):
    args = types.SimpleNamespace(
        interval=0.01,
        watch=0.01,
        output=str(tmp_path),  # a directory: open(..., 'a') must fail
        quiet=True,
        no_alerts=True,
    )
    cfg = {'interval': 0.01, 'retention_days': 30}
    monkeypatch.setattr(sys, 'stdout', FakeStream(False))
    monkeypatch.setattr(sys, 'stderr', FakeStream(False))
    code = monitor.run_watch(FramePSU([sample()]), args, cfg, None, None)
    assert code == EXIT_ERROR
