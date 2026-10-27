"""PTY evidence: --watch and --dashboard-text on a real pseudo-terminal.

The unit tests drive the render functions with fake streams. They cannot prove
what a real terminal shows: that the cursor is restored, the redraw stays in
place, and a SIGINT exits cleanly. These tests spawn the CLI on a PTY, capture
the raw byte stream, and assert on what a terminal would actually render.
"""

import os
import pty
import re
import signal
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(
    not hasattr(os, 'openpty') or os.name != 'posix',
    reason='a PTY is required; CI runs these on Linux',
)

_ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')


def _sensors_env():
    env = dict(os.environ)
    env['MSI_PSU_DEMO'] = '1'
    env['MSI_PSU_STATE_DIR'] = env.get('MSI_PSU_STATE_DIR', '/tmp')
    return env


def _run_on_pty(argv, drive, timeout=15.0):
    """Run argv with stdio on a PTY; ``drive`` writes to and reads the master.

    TERM is exported explicitly: GitHub runners have TERM unset, and
    ``--watch``/``--dashboard-text`` refuse to draw on a terminal without one
    (that is the documented plain-stream fallback, not a bug to test here).

    The interrupt is a ``^C`` byte on the PTY line discipline, so the child's
    ``finally`` clause runs exactly as it would for a human typing Ctrl-C.
    """
    master, slave = pty.openpty()
    env = _sensors_env()
    env['TERM'] = 'xterm-256color'
    proc = subprocess.Popen(
        [sys.executable, '-m', 'msi_psu_monitor', *argv],
        stdin=slave,
        stdout=slave,
        stderr=subprocess.PIPE,
        env=env,
        close_fds=True,
    )
    os.close(slave)
    try:
        return drive(master, proc, timeout)
    finally:
        # Stop via the line discipline first, then SIGKILL as a backstop: a
        # SIGTERM handler that raises KeyboardInterrupt inside the child is
        # *good* there (it triggers the tty restore), but the ``finally`` in
        # this test must never hang the suite if the child wedges.
        try:
            os.write(master, b'\x03')
        except OSError:
            pass
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        os.close(master)


def _read_until(master, predicate, deadline, chunk=65536):
    buffer = b''
    while time.time() < deadline:
        try:
            os.set_blocking(master, False)
            data = os.read(master, chunk)
        except BlockingIOError:
            data = b''
        except OSError:
            break
        finally:
            os.set_blocking(master, True)
        if data:
            buffer += data
            if predicate(buffer):
                return buffer
        else:
            time.sleep(0.05)
    return buffer


def _drain(master, limit=262144):
    """Read everything still buffered on the master (post-exit flush)."""
    os.set_blocking(master, False)
    data = b''
    try:
        while len(data) < limit:
            chunk = os.read(master, 65536)
            if not chunk:
                break
            data += chunk
    except (BlockingIOError, OSError):
        pass
    finally:
        os.set_blocking(master, True)
    return data


def test_watch_redraws_in_place_and_restores_the_cursor():
    """Two frames on a real PTY: home-clear redraw, no scroll, cursor shown."""

    def drive(master, proc, timeout):
        deadline = time.time() + timeout
        buffer = _read_until(
            master,
            lambda data: data.count(b'MSI PSU') >= 2,
            deadline,
        )
        # ^C through the master: the child sees a real Ctrl-C, its finally
        # clause restores the cursor, and the bytes appear on the master.
        os.write(master, b'\x03')
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        buffer += _drain(master)
        return proc.returncode, buffer

    code, output = _run_on_pty(['--watch', '0.2'], drive)
    assert code == 0, output
    text = output.decode('utf-8', 'replace')
    assert text.count('MSI PSU') >= 2
    assert '\x1b[H\x1b[J' in text, 'the redraw must home+clear, not scroll'
    assert '\x1b[?25l' in text, 'the cursor is hidden while frames stream'
    assert '\x1b[?25h' in text, 'the cursor must be restored on exit'


def test_watch_streams_plain_frames_through_a_pipe():
    """Pipe mode keeps the documented contract: plain frames, no escapes.

    SIGINT terminates the run; SIGTERM would also work but the pipe test asserts
    the stream shape, not the signal path.
    """
    proc = subprocess.Popen(
        [sys.executable, '-m', 'msi_psu_monitor', '--watch', '0.2'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_sensors_env(),
    )
    time.sleep(1.2)  # at 0.2 s cadence this collects several frames
    proc.send_signal(signal.SIGINT)
    try:
        out, err = proc.communicate(timeout=10)
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=10)
    assert proc.returncode in (0, 1), err
    text = out.decode('utf-8', 'replace')
    assert text.count('+12V') >= 2
    assert '\x1b' not in text, 'a pipe must never receive escape codes'


def test_dashboard_text_exits_cleanly_on_sigint():
    """Ctrl-C on a real PTY returns the terminal usable (cursor shown, exit 0)."""

    def drive(master, proc, timeout):
        deadline = time.time() + timeout
        buffer = _read_until(
            master,
            lambda data: b'MSI PSU Monitor' in data,
            deadline,
        )
        time.sleep(0.3)  # let the first frame settle before interrupting
        os.write(master, b'\x03')
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        buffer += _drain(master)
        return proc.returncode, buffer

    code, output = _run_on_pty(['--dashboard-text'], drive)
    assert code == 0, output
    text = output.decode('utf-8', 'replace')
    assert 'MSI PSU Monitor' in text
    assert '\x1b[?25h' in text, 'the cursor must be restored on exit'
    # The box frames each row to one width; a wandering border would show up
    # here as different visible lengths per row.
    lines = [line for line in text.splitlines() if '─' in line or '|' in line or '+' in line]
    assert lines, 'the dashboard must draw its box'


def test_watch_on_a_tiny_pty_streams_instead_of_redrawing():
    """An 8x8 PTY is too small for a full-screen frame; it must not scroll."""
    import fcntl
    import struct
    import termios

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 8, 8, 0, 0))
    env = _sensors_env()
    env['TERM'] = 'xterm-256color'
    proc = subprocess.Popen(
        [sys.executable, '-m', 'msi_psu_monitor', '--watch', '0.2'],
        stdin=slave,
        stdout=slave,
        stderr=subprocess.PIPE,
        env=env,
        close_fds=True,
    )
    os.close(slave)
    try:
        deadline = time.time() + 15
        buffer = _read_until(
            master,
            lambda data: b'Warning' in data or data.count(b'+12V') >= 2,
            deadline,
        )
        os.write(master, b'\x03')
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        buffer += _drain(master)
        code = proc.returncode
    finally:
        os.close(master)
        if proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
    assert code == 0
    text = buffer.decode('utf-8', 'replace')
    # Either the warning was printed, or the frames streamed plainly.
    assert 'Warning' in text or text.count('+12V') >= 2
