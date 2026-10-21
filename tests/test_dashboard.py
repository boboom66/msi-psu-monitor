"""Tests for the local dashboard HTTP endpoints (no hardware, no network egress)."""

import contextlib
import csv
import io
import json
import os
import pathlib
import re
import select
import shutil
import socket
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from msi_psu_monitor import dashboard
from msi_psu_monitor import state as stats


def _sensors():
    return {
        'vout_12v': (12.1, 'V'),
        'vout_5v': (5.04, 'V'),
        'vout_3v3': (3.32, 'V'),
        'iout_12v_total': (50.0, 'A'),
        'temp': (56.0, 'C'),
        'fan_rpm': (2050, 'RPM'),
        'power_total': (600.0, 'W'),
        'efficiency': (94.0, '%'),
    }


@pytest.fixture
def live_server(tmp_path):
    now = time.time()
    monitor_state = stats.MonitorState(product='MPG Ai1600TS', serial='SN1')
    monitor_state.update(600.0, 94.0, ts=now - 60)
    monitor_state.update(600.0, 94.0, ts=now)
    monitor_state.save(stats.state_path(tmp_path))
    stats.append_history(tmp_path, _sensors(), ts=now)

    httpd = dashboard.make_server('127.0.0.1', 0, tmp_path)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{httpd.server_port}'
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _get(url):
    with urlopen(url, timeout=5) as response:
        return response.status, response.read().decode('utf-8')


def test_page_renders_without_placeholder_leftovers(live_server):
    status, body = _get(live_server + '/')
    assert status == 200
    assert '<title>MSI PSU Monitor</title>' in body
    assert '__REFRESH_MS__' not in body
    assert '__ROW_LIMIT__' not in body
    assert 'setInterval(load, 30000)' in body
    assert 'const ROW_LIMIT = 20000;' in body


def test_every_placeholder_the_page_uses_is_substituted():
    """A placeholder nobody substitutes reaches the browser verbatim.

    The page used to reference the Python constant ``ROW_LIMIT`` directly, so
    ``load()`` threw a ReferenceError before drawing anything: every endpoint was
    healthy and the page stayed empty.
    """
    used = set(re.findall(r'__[A-Z0-9_]+__', dashboard.PAGE))
    assert used
    assert used <= set(dashboard.PAGE_SUBSTITUTIONS)
    for name in used:
        assert name not in dashboard.render_page()


def test_the_page_script_declares_every_constant_it_uses():
    """The embedded JS may only use constants it declares or that it is given.

    ``const``/``let``/``var`` declarations and the injected placeholders are the
    only sources a browser has; every other UPPER_SNAKE name would be a
    server-side constant that the page cannot see.
    """
    script = dashboard.PAGE.split('<script>', 1)[1].split('</script>', 1)[0]
    # Identifiers inside a string literal or a comment are data, not references.
    code = re.sub(r"'[^']*'|\"[^\"]*\"|`[^`]*`", ' ', script, flags=re.S)
    code = re.sub(r'//[^\n]*', ' ', code)
    declared = set(re.findall(r'\b(?:const|let|var)\s+([A-Z][A-Z0-9_]*)', code))
    injected = {name.strip('_') for name in re.findall(r'__[A-Z0-9_]+__', code)}
    browser_globals = {'JSON', 'URL'}
    used = set(re.findall(r'\b([A-Z][A-Z0-9_]{2,})\b', code))
    assert used <= declared | injected | browser_globals


def test_history_endpoint_returns_rows(live_server):
    status, body = _get(live_server + '/api/history?from=2h')
    payload = json.loads(body)
    assert status == 200
    assert payload['count'] == 1
    assert payload['rows'][0]['power'] == '600.0'


def test_history_endpoint_supports_all(live_server):
    _, body = _get(live_server + '/api/history?from=all')
    assert json.loads(body)['count'] == 1


def test_state_endpoint_exposes_totals(live_server):
    _, body = _get(live_server + '/api/state')
    payload = json.loads(body)
    assert payload['product'] == 'MPG Ai1600TS'
    assert payload['serial'] == 'SN1'
    assert payload['count'] == 2
    assert payload['power_avg'] == 600.0
    assert payload['total_energy_kwh'] == pytest.approx(0.01)
    assert len(payload['daily']) == 1


def test_export_endpoint_returns_csv(live_server):
    _, body = _get(live_server + '/api/export?from=2h&columns=temp,fan')
    lines = body.strip().splitlines()
    assert lines[0] == 'time,temp,fan'
    assert lines[1].endswith(',56.0,2050')


def test_bad_window_is_rejected(live_server):
    with pytest.raises(HTTPError) as exc:
        _get(live_server + '/api/history?from=fortnight')
    assert exc.value.code == 400
    with pytest.raises(HTTPError) as exc:
        _get(live_server + '/api/export?columns=wattage')
    assert exc.value.code == 400


def test_state_endpoint_exposes_the_last_sample_time(live_server):
    """Without last_ts the page cannot tell a live daemon from a week-old file."""
    _, body = _get(live_server + '/api/state')
    payload = json.loads(body)
    assert payload['last_ts'] == pytest.approx(time.time(), abs=120)


def test_blank_query_values_are_400_not_defaults(live_server):
    """`?from=` and `?columns=` are hard errors on the CLI; the HTTP API agrees.

    parse_qs dropped blank values by default, so `?from=` silently became the
    default window and `?columns=` silently exported every column -- the same
    input the CLI rejects with exit 1.
    """
    for route in (
        '/api/history?from=',
        '/api/export?from=',
        '/api/export?columns=',
    ):
        with pytest.raises(HTTPError) as exc:
            _get(live_server + route)
        assert exc.value.code == 400, route


def test_a_missing_state_file_is_still_a_normal_first_run(tmp_path):
    """Strict mode must not turn "the daemon has not run yet" into a 503."""
    httpd = dashboard.make_server('127.0.0.1', 0, tmp_path)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _get(f'http://127.0.0.1:{httpd.server_port}/api/state')
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
    payload = json.loads(body)
    assert status == 200
    assert payload['count'] == 0
    assert payload['last_ts'] is None


def test_a_corrupt_state_file_is_a_503_while_history_still_serves(tmp_path):
    """Zero totals next to a full curve is the contradiction this guards.

    MonitorState.load() recovers from every damaged file by returning empty
    state, which is right for the CLI/daemon and wrong for the dashboard: HTTP
    200 with count 0 looks exactly like a daemon that never recorded anything,
    while /api/history happily returns real rows.
    """
    monitor_state = stats.MonitorState(product='MPG Ai1600TS')
    monitor_state.update(600.0, 94.0, ts=time.time())
    stats.append_history(tmp_path, _sensors(), ts=time.time())
    # Write the good file first, then damage it in place.
    monitor_state.save(stats.state_path(tmp_path))
    stats.state_path(tmp_path).write_text('{not json', encoding='utf-8')

    httpd = dashboard.make_server('127.0.0.1', 0, tmp_path)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{httpd.server_port}'
    try:
        with pytest.raises(HTTPError) as exc:
            _get(base + '/api/state')
        assert exc.value.code == 503
        assert b'not valid JSON' in exc.value.read()
        # The history is still readable and must keep being served.
        status, body = _get(base + '/api/history?from=all')
        assert status == 200
        assert json.loads(body)['count'] == 1
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


@pytest.mark.skipif(os.geteuid() == 0, reason='root can read a chmod 000 file')
def test_an_unreadable_state_file_is_a_503_with_its_path(tmp_path):
    monitor_state = stats.MonitorState(product='MPG Ai1600TS')
    monitor_state.update(600.0, 94.0, ts=time.time())
    path = stats.state_path(tmp_path)
    monitor_state.save(path)
    httpd = dashboard.make_server('127.0.0.1', 0, tmp_path)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        path.chmod(0o000)
        with pytest.raises(HTTPError) as exc:
            _get(f'http://127.0.0.1:{httpd.server_port}/api/state')
    finally:
        path.chmod(0o600)
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
    assert exc.value.code == 503
    body = exc.value.read()
    assert str(path).encode() in body
    assert b'not readable' in body


def test_the_page_shows_sample_age_and_marks_stale_data(live_server):
    """A stopped daemon keeps answering 200 from state.json; only age shows it."""
    page = _get(live_server + '/')[1]
    assert 'const STALE_AFTER_S = 300;' in page
    assert 'st.last_ts' in page
    assert 'last sample ' in page
    assert "info.classList.toggle('stale'" in page


def test_the_chart_x_axis_uses_real_timestamps():
    """Row-number spacing made a six-hour outage look like two adjacent samples."""
    page = dashboard.PAGE
    assert 'Date.parse(r.time)' in page
    assert 'useTime' in page
    # The row index survives only as the documented fallback position.
    assert '[Number.isFinite(t) ? t / 1000 : null, i, v]' in page
    assert 'pad + (p[1] / span)' in page
    # and the y/legend readers must use the value slot, not the row slot.
    assert 'y(p[2])' in page
    assert 's.pts[s.pts.length - 1][2]' in page


def test_the_weekly_canvas_is_drawn_at_its_css_height():
    """The page drew at 150 px inside a 120 px box and squashed every bar."""
    page = dashboard.PAGE
    assert ' canvas { width: 100%; display: block; }' in page
    assert ' #grid canvas { height: 120px; }' in page
    assert ' #weekly { height: 150px; }' in page
    assert 'canvas.clientHeight || 150' in page


def test_unknown_route_is_404(live_server):
    with pytest.raises(HTTPError) as exc:
        _get(live_server + '/nope')
    assert exc.value.code == 404


def test_the_default_host_is_loopback(tmp_path):
    """The loopback promise lives in run_dashboard/DEFAULT_HOST, not in the bind.

    The old version of this test asserted the host it had just passed in, so it
    would have passed with ``0.0.0.0`` too -- the README's "loopback only" claim
    had no test that could fail.
    """
    from msi_psu_monitor import monitor

    assert dashboard.DEFAULT_HOST == '127.0.0.1'
    seen = {}

    def fake_serve(host=None, port=None, state_dir=None):
        seen.update(host=host, port=port)
        return 0

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(dashboard, 'serve', fake_serve)
        monitor.run_dashboard(monitor.build_parser().parse_args(['--dashboard']), {})
    assert seen['host'] == '127.0.0.1'


def test_a_bracket_mangled_request_target_is_a_400(tmp_path):
    """`GET http://[/x HTTP/1.1` makes urlparse raise; it must not drop the socket."""
    httpd = dashboard.make_server('127.0.0.1', 0, tmp_path)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        sock = socket.create_connection(('127.0.0.1', httpd.server_port), timeout=5)
        sock.sendall(b'GET http://[/x HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n')
        reply = sock.recv(200)
        sock.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
    assert b'400' in reply.split(b'\r\n')[0]


def test_an_unreadable_state_dir_is_a_503_not_zero_data(tmp_path):
    """0 samples / 0.000 kWh / 200 is what a daemon that never ran looks like too."""
    monitor_state = stats.MonitorState(product='MPG Ai1600TS')
    monitor_state.update(600.0, 94.0, ts=time.time())
    monitor_state.save(stats.state_path(tmp_path))
    httpd = dashboard.make_server('127.0.0.1', 0, tmp_path)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{httpd.server_port}'
    try:
        assert _get(base + '/api/state')[0] == 200
        tmp_path.chmod(0o000)
        for route in ('/api/state', '/api/history', '/api/export'):
            with pytest.raises(HTTPError) as exc:
                _get(base + route)
            assert exc.value.code == 503
            assert b'not readable' in exc.value.read()
        assert _get(base + '/')[0] == 200  # the page itself still loads
    finally:
        tmp_path.chmod(0o700)
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_a_missing_state_dir_says_so_instead_of_zero(tmp_path):
    httpd = dashboard.make_server('127.0.0.1', 0, tmp_path / 'never-created')
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(HTTPError) as exc:
            _get(f'http://127.0.0.1:{httpd.server_port}/api/history')
        assert exc.value.code == 503
        assert b'no state directory' in exc.value.read()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_the_page_reports_why_a_poll_failed():
    """The fetch helper must surface the server's reason, not just the status."""
    assert 'await response.text()' in dashboard.PAGE


def _head(url):
    """HEAD the URL and return (status, headers) without reading a body."""
    request = Request(url, method='HEAD')
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, dict(response.headers)
    except HTTPError as exc:
        return exc.code, dict(exc.headers)


def test_head_matches_get_headers_for_the_page(live_server):
    status, headers = _head(live_server + '/')
    assert status == 200
    assert headers['Content-Type'] == 'text/html; charset=utf-8'
    # Content-Length must describe the GET entity, not an empty body.
    assert int(headers['Content-Length']) > 1000


def test_head_reports_a_missing_route_as_404(live_server):
    """A blind 200 would let a link checker think /nope exists."""
    assert _head(live_server + '/nope')[0] == 404


def test_head_reports_a_bad_window_as_400(live_server):
    assert _head(live_server + '/api/history?from=fortnight')[0] == 400


def test_head_of_export_keeps_the_download_headers(live_server):
    status, headers = _head(live_server + '/api/export?from=2h')
    assert status == 200
    assert headers['Content-Type'] == 'text/csv; charset=utf-8'
    assert headers['Content-Disposition'] == 'attachment; filename="msi-psu.csv"'


def test_serve_prints_the_url_before_it_blocks(tmp_path):
    """Under systemd/journald stdout is a pipe: the URL must not sit in a buffer.

    The documented way to find the port is that banner, and this process only
    exits on Ctrl-C -- unflushed, the line is invisible for the whole run.
    """
    root = pathlib.Path(__file__).resolve().parents[1]
    code = (
        'import sys; from msi_psu_monitor import dashboard; '
        f'sys.exit(dashboard.serve("127.0.0.1", 0, {str(tmp_path)!r}))'
    )
    proc = subprocess.Popen(
        [sys.executable, '-c', code], cwd=root, stdout=subprocess.PIPE, text=True
    )
    try:
        ready, _, _ = select.select([proc.stdout], [], [], 10)
        assert ready, 'the dashboard URL stayed in the stdout buffer'
        line = proc.stdout.readline()
        assert line.startswith('msi-psu-monitor dashboard: http://127.0.0.1:')
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_serve_reports_an_out_of_range_port(tmp_path, caplog):
    """bind() raises OverflowError (not OSError) for a port outside 0-65535."""
    code = dashboard.serve('127.0.0.1', 99999, tmp_path)
    assert code == 1
    assert any('cannot serve' in record.message for record in caplog.records)


def test_serve_reports_a_port_that_is_already_taken(tmp_path, caplog):
    """A second --dashboard must print one line, not a traceback."""
    first = dashboard.make_server('127.0.0.1', 0, tmp_path)
    try:
        code = dashboard.serve('127.0.0.1', first.server_port, tmp_path)
    finally:
        first.server_close()
    assert code == 1
    assert any('cannot serve' in record.message for record in caplog.records)


def test_an_early_client_disconnect_does_not_print_a_traceback(tmp_path):
    """Closing a tab mid-response is routine; socketserver used to print a traceback."""
    httpd = dashboard.make_server('127.0.0.1', 0, tmp_path)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    captured = io.StringIO()
    status = None
    request = b'GET / HTTP/1.1\r\nHost: x\r\n\r\n'
    try:
        with contextlib.redirect_stderr(captured):
            for _ in range(3):
                sock = socket.create_connection(('127.0.0.1', httpd.server_port), timeout=5)
                sock.sendall(request)
                sock.close()
            time.sleep(0.5)
        status, _ = _get(f'http://127.0.0.1:{httpd.server_port}/api/state')
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
    assert status == 200, 'the server must keep serving after a hang-up'
    assert 'Traceback' not in captured.getvalue()
    assert 'Exception occurred' not in captured.getvalue()


def test_security_headers_are_present_on_every_route(live_server):
    """Cheap hardening; the page is local but a future embedded link is not."""
    for route in ('/', '/api/state', '/api/history?from=2h'):
        status, headers = _head(live_server + route)
        assert status == 200
        assert headers['X-Content-Type-Options'] == 'nosniff'
        assert headers['X-Frame-Options'] == 'DENY'
        assert headers['Referrer-Policy'] == 'no-referrer'
        csp = headers['Content-Security-Policy']
        assert "default-src 'none'" in csp
        assert "script-src 'unsafe-inline'" in csp
        assert "connect-src 'self'" in csp
        assert headers['Permissions-Policy'] == 'camera=(), microphone=(), geolocation=()'


def test_an_unexpected_handler_error_keeps_its_traceback(tmp_path, caplog):
    """A hang-up is routine; a real bug must still land in the journal with a stack."""
    httpd = dashboard.make_server('127.0.0.1', 0, tmp_path)
    try:
        with caplog.at_level('ERROR', logger='msi_psu.dashboard'):
            try:
                raise RuntimeError('boom')
            except RuntimeError:
                httpd.handle_error(None, ('127.0.0.1', 1))
    finally:
        httpd.server_close()
    assert 'Unhandled error while serving' in caplog.text
    assert 'RuntimeError: boom' in caplog.text


def test_an_idle_connection_cannot_pin_a_thread_forever():
    assert 0 < dashboard.DashboardHandler.timeout <= 60


def test_the_seven_charts_match_the_msi_dashboard(live_server):
    """MSI's real-time dashboard has seven specific curves.

    The page used to chart 12V total current instead of a standalone efficiency
    graph and mixed efficiency into the wattage chart, so it was neither MSI's
    set nor a coherent seven-chart layout.
    """
    status, body = _get(live_server + '/')
    assert status == 200
    ids = re.findall(r"\{id:'([a-z0-9]+)'", body)
    assert ids == ['12v', '5v', '3v3', 'eff', 'temp', 'fan', 'power']
    assert "['eff','#6ea8fe']" in body
    assert "['cpu_w'" in body and "['gpu_w'" in body
    power_card = body.split("{id:'power'", 1)[1].split('],', 1)[0]
    assert "'eff'" not in power_card, 'efficiency belongs in its own chart (percent axis)'
    assert 'loadLive' in body
    assert "fetch('/api/live')" in body
    assert 'setInterval(loadLive, 1000)' in body


def test_live_endpoint_serves_a_fresh_snapshot(live_server, tmp_path):
    sensors = _sensors()
    sensors['iout_12v_rails'] = ([10.0, 20.0, 15.0, 5.0, 0.0], 'A')
    sensors['vout_12v_rails'] = ([12.1, 12.1, 12.1, 12.1, 12.1], 'V')
    stats.write_live_snapshot(tmp_path, sensors, ts=time.time())
    status, body = _get(live_server + '/api/live')
    assert status == 200
    payload = json.loads(body)
    assert payload['vout_12v'] == 12.1
    assert payload['cpu_w'] == 242.0
    assert 'serial' not in payload


def test_the_live_snapshot_can_feed_every_charted_series(live_server, tmp_path):
    """The 1 s overlay reused the history column names only by accident.

    latest.json stores the daemon's sensor keys (vout_12v, power_total, ...)
    while the charts read daily-*.log column names (12v, power, ...). The page
    pushes /api/live straight into the history rows, so without the alias only
    'temp' -- the one name the two shapes share -- ever moved live; every other
    chart stayed frozen between the one-minute history writes.
    """
    sensors = _sensors()
    sensors['iout_12v_rails'] = ([10.0, 20.0, 15.0, 5.0, 0.0], 'A')
    sensors['vout_12v_rails'] = ([12.1, 12.1, 12.1, 12.1, 12.1], 'V')
    stats.write_live_snapshot(tmp_path, sensors, ts=time.time())
    _, body = _get(live_server + '/api/live')
    payload = json.loads(body)
    chart_keys = set(re.findall(r"\['([0-9a-z_]+)','#", dashboard.PAGE))
    assert chart_keys, 'the chart definitions moved; update this assertion'
    missing = chart_keys - set(payload)
    assert not missing, f'live payload cannot feed these series: {sorted(missing)}'
    # The raw sensor keys stay available to other consumers of /api/live.
    assert payload['vout_12v'] == 12.1


def test_live_endpoint_is_503_without_a_fresh_snapshot(live_server):
    with pytest.raises(HTTPError) as excinfo:
        _get(live_server + '/api/live')
    assert excinfo.value.code == 503


def test_an_unknown_api_route_is_404_even_without_a_state_dir(tmp_path):
    """A client typo must not be reported as a broken installation.

    The state-directory check ran for every /api/ path before routes were
    matched, so /api/typo answered 503 "no state directory" on a host where the
    daemon had never run -- blaming the server for the caller's bad URL.
    """
    missing = tmp_path / 'never-created'
    httpd = dashboard.make_server('127.0.0.1', 0, missing)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{httpd.server_port}'
    try:
        with pytest.raises(HTTPError) as excinfo:
            _get(base + '/api/typo')
        assert excinfo.value.code == 404
        with pytest.raises(HTTPError) as excinfo:
            _get(base + '/api/state')
        assert excinfo.value.code == 503
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _raw_http(url, host_header):
    """Send a raw GET with an explicit Host header; return the response text."""
    rest = url.split('://', 1)[1]
    host, port = rest.rsplit(':', 1)
    with socket.create_connection((host, int(port)), timeout=5) as sock:
        request = (f'GET / HTTP/1.1\r\nHost: {host_header}\r\nConnection: close\r\n\r\n').encode(
            'ascii'
        )
        sock.sendall(request)
        chunks = []
        while True:
            data = sock.recv(4096)
            if not data:
                break
            chunks.append(data)
    return b''.join(chunks).decode('latin-1')


def test_a_non_loopback_host_header_is_rejected(live_server):
    """A DNS-rebinding page can resolve its name to 127.0.0.1 and reach the
    dashboard; the Host header is the only server-side proof it is not us."""
    response = _raw_http(live_server, 'evil.example')
    assert response.startswith(('HTTP/1.1 421', 'HTTP/1.0 421'))


def test_loopback_host_headers_are_accepted(live_server):
    port = live_server.rsplit(':', 1)[1]
    for host in (f'127.0.0.1:{port}', f'localhost:{port}', f'[::1]:{port}'):
        response = _raw_http(live_server, host)
        assert response.startswith(('HTTP/1.1 200', 'HTTP/1.0 200')), host


def test_the_embedded_javascript_is_syntactically_valid(tmp_path):
    """HTTP tests do not execute JS; a syntax error would leave a blank page."""
    node = shutil.which('node')
    if node is None:
        pytest.skip('node is not installed')
    page = dashboard.render_page()
    script = page.split('<script>', 1)[1].split('</script>', 1)[0]
    target = tmp_path / 'page.js'
    target.write_text(script, encoding='utf-8')
    result = subprocess.run([node, '--check', str(target)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


_LIVE_JS_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const pagePath = process.argv[2];
const livePath = process.argv[3];
const page = fs.readFileSync(pagePath, 'utf8');
const live = JSON.parse(fs.readFileSync(livePath, 'utf8'));
class El {
  constructor() {
    this.textContent = ''; this.innerHTML = ''; this.dataset = {}; this.href = '';
    this.style = {}; this.classList = {toggle() {}, add() {}, remove() {}};
    this.clientWidth = 340; this.clientHeight = 120;
  }
  addEventListener() {}
  getContext() {
    return new Proxy({}, {get: (target, name) => {
      if (name === 'measureText') return () => ({width: 10});
      if (name === 'canvas') return {};
      if (name in target) return target[name];
      return () => {};
    }});
  }
}
const els = {};
function el(id) { return els[id] || (els[id] = new El()); }
const histRow = {time: '2000-01-01T00:00:00+00:00', '12v': '12.100', '5v': '5.040',
  '3v3': '3.320', total_a: '50.000', temp: '56.0', fan: '2050', power: '600.0',
  eff: '94.00', cpu_w: '242.0', gpu_w: '121.0'};
const statePayload = {product: 'MPG Ai1600TS', serial: 'SN1', count: 1, power_avg: 600.0,
  efficiency_avg: 94.0, total_energy_kwh: 0.01, last_ts: 1600000000, daily: {}};
let liveCalls = 0;
const sandbox = {
  console,
  document: {getElementById: el, createElement: () => new El(), querySelector: () => new El(),
             querySelectorAll: () => []},
  window: {devicePixelRatio: 1, addEventListener() {}},
  fetch: async (url) => ({
    ok: true,
    async json() {
      if (url.includes('/api/history')) return {rows: [histRow]};
      if (url.includes('/api/state')) return statePayload;
      if (url.includes('/api/live')) {
        const out = Object.assign({}, live);
        out.ts = 1600000000 + (++liveCalls);
        return out;
      }
      return {};
    },
    async text() { return ''; },
  }),
  setInterval: () => 0,
  Date, JSON, Math, Number, Object, Array, String, isNaN, parseFloat, parseInt,
  URL: {createObjectURL: () => 'blob:x', revokeObjectURL() {}},
  Blob: function () {},
  setTimeout, Promise,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(page, sandbox, {filename: 'page.js'});
(async () => {
  await new Promise(resolve => setTimeout(resolve, 20));
  await sandbox.__api.load();
  const before = sandbox.__probe();
  await sandbox.__api.loadLive();
  await sandbox.__api.loadLive();
  const after = sandbox.__probe();
  console.log(JSON.stringify({before, after}));
})();
"""


def test_the_live_overlay_actually_moves_every_chart_series(tmp_path):
    """Execute the page JS with the real /api/live payload shape.

    A Python-side check that the keys exist cannot prove the browser uses them;
    the page pushes the JSON straight into its history rows. This harness runs
    the shipped script against a stubbed DOM/fetch: before the server added the
    history aliases the 12V series kept exactly one point while three rows were
    on screen, because only 'temp' existed under both names.
    """
    node = shutil.which('node')
    if node is None:
        pytest.skip('node is not installed')
    sensors = _sensors()
    sensors['iout_12v_rails'] = ([10.0, 20.0, 15.0, 5.0, 0.0], 'A')
    sensors['vout_12v_rails'] = ([12.1, 12.1, 12.1, 12.1, 12.1], 'V')
    stats.write_live_snapshot(tmp_path, sensors, ts=1600000000)
    served = dashboard._live_view(stats.read_live_snapshot(tmp_path, now=1600000001))
    assert served is not None

    script = dashboard.render_page().split('<script>', 1)[1].split('</script>', 1)[0]
    script += (
        '\n;globalThis.__api = {load, loadLive};'
        '\nglobalThis.__probe = () => ({'
        '\n  rows: rows.length,'
        '\n  charts: Object.fromEntries(CHARTS.map(c => [c.id,'
        ' c.keys.map(([key]) => series(key).length)])),'
        '\n  last12: document.getElementById("last-12v").textContent,'
        '\n});'
    )
    (tmp_path / 'page.js').write_text(script, encoding='utf-8')
    (tmp_path / 'live.json').write_text(json.dumps(served), encoding='utf-8')
    (tmp_path / 'harness.js').write_text(_LIVE_JS_HARNESS, encoding='utf-8')
    result = subprocess.run(
        [
            node,
            str(tmp_path / 'harness.js'),
            str(tmp_path / 'page.js'),
            str(tmp_path / 'live.json'),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    probes = json.loads(result.stdout)
    assert probes['before']['rows'] == 1
    assert probes['after']['rows'] == 3
    for chart, lengths in probes['after']['charts'].items():
        assert lengths == [3] * len(lengths), f'{chart} did not move live: {lengths}'
    assert probes['after']['last12'] != '--'


def test_export_endpoint_quotes_a_comma_in_a_value(tmp_path):
    """A hand-edited history value with a comma must not shift the CSV columns."""
    path = stats.history_path(tmp_path)
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle, lineterminator='\n')
        writer.writerow(stats.HISTORY_COLUMNS)
        writer.writerow(['2026-01-01T00:00:00+00:00', 'a,b'] + [''] * 9)
    httpd = dashboard.make_server('127.0.0.1', 0, tmp_path)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        _, body = _get(f'http://127.0.0.1:{httpd.server_port}/api/export?from=all&columns=12v')
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
    lines = body.splitlines()
    assert lines[0] == 'time,12v'
    assert lines[1].endswith('"a,b"')


def test_the_chart_grid_can_shrink_below_its_desktop_minimum():
    """A 320px viewport must not scroll horizontally: minmax(340px) overflowed."""
    assert 'minmax(min(340px, 100%), 1fr)' in dashboard.PAGE
