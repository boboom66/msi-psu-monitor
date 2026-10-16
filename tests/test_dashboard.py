"""Tests for the local dashboard HTTP endpoints (no hardware, no network egress)."""

import json
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
    assert 'setInterval(load, 30000)' in body


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


def test_unknown_route_is_404(live_server):
    with pytest.raises(HTTPError) as exc:
        _get(live_server + '/nope')
    assert exc.value.code == 404


def test_server_binds_loopback_only(tmp_path):
    httpd = dashboard.make_server('127.0.0.1', 0, tmp_path)
    try:
        assert httpd.server_address[0] == '127.0.0.1'
    finally:
        httpd.server_close()


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
