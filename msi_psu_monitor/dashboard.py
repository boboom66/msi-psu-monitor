#!/usr/bin/env python3
"""Local read-only dashboard for msi-psu-monitor (stdlib only, Python 3.10+).

Serves the daemon history (``daily-*.log``) and the cumulative state as plain
HTML + hand-drawn ``<canvas>`` charts on loopback (D-01: local charts on
demand, no GUI stack, no third-party web framework).

Endpoints:
    /                       the dashboard
    /api/history?from=2h    history rows as JSON (``all`` also accepted)
    /api/state              cumulative state as JSON
    /api/export?from=2h     the same slice as a CSV download

The page draws its own charts and exports each one to PNG with
``canvas.toDataURL()``; nothing is fetched from the network.

The HTML/CSS/JS is embedded in ``PAGE`` on purpose: a single module keeps the
``.deb`` free of package-data plumbing (no ``importlib.resources`` lookup, no
missing-file failure mode) and the server is one file to audit.
"""

from __future__ import annotations

import json
import logging
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from msi_psu_monitor import state as stats

logger = logging.getLogger('msi_psu.dashboard')

DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 8899
ROW_LIMIT = 20000
#: How old the newest sample may be before the page calls the data stale. The
#: daemon persists state.json with each prometheus write (every 30 s by
#: default), so five minutes is ten missed writes: long enough to ride out one
#: slow disk, short enough that a stopped daemon is visible before the numbers
#: are trusted. Page-only; no endpoint changes shape because of it.
STALE_AFTER_S = 300

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>MSI PSU Monitor</title>
<style>
 :root { color-scheme: dark; }
 body { margin: 0; padding: 16px 20px 40px; background: #14171c; color: #dfe4ea;
        font: 14px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif; }
 h1 { font-size: 18px; margin: 0 0 4px; }
 .sub { color: #8b98a8; font-size: 12px; margin-bottom: 14px; }
 .sub.stale { color: #e0a25c; }
 .bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 16px; }
 button, a.btn { background: #222831; color: #dfe4ea; border: 1px solid #333c47;
        border-radius: 5px; padding: 5px 11px; font-size: 13px; cursor: pointer;
        text-decoration: none; }
 button.on { background: #2f6fb5; border-color: #3f86d4; }
 .grid { display: grid; gap: 14px; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); }
 .card { background: #1b1f26; border: 1px solid #262d36; border-radius: 8px; padding: 10px 12px 6px; }
 .card h2 { font-size: 13px; font-weight: 600; margin: 0 0 2px; color: #b9c4d1; }
 .last { font-size: 18px; font-variant-numeric: tabular-nums; }
 .meta { font-size: 11px; color: #7c8794; margin-bottom: 6px; }
 canvas { width: 100%; display: block; }
 #grid canvas { height: 120px; }
 #weekly { height: 150px; }
 .foot { font-size: 12px; color: #7c8794; margin-top: 6px; }
</style>
</head>
<body>
<h1>MSI PSU Monitor</h1>
<div class="sub" id="info">loading&hellip;</div>
<div class="bar">
  <span>Range</span>
  <button data-from="30m">30m</button>
  <button data-from="2h">2h</button>
  <button data-from="7d" class="on">7d</button>
  <a class="btn" id="csv" href="/api/export?from=7d">Export CSV</a>
</div>
<div class="grid" id="grid"></div>
<div class="card" style="margin-top:14px">
  <h2>Weekly energy (kWh per day)</h2>
  <div class="meta" id="weeklyMeta">&nbsp;</div>
  <canvas id="weekly" height="150"></canvas>
</div>
<div class="foot">Data source: daily-*.log written by msi-psu-monitor-daemon. Local only.</div>
<script>
const CHARTS = [
  {id:'12v',   title:'+12V',              unit:'V',   keys:[['12v','#e05c5c']]},
  {id:'5v',    title:'+5V',               unit:'V',   keys:[['5v','#5cc9e0']]},
  {id:'3v3',   title:'+3.3V',             unit:'V',   keys:[['3v3','#c9a05c']]},
  {id:'total', title:'12V total current', unit:'A',   keys:[['total_a','#8f7ce0']]},
  {id:'temp',  title:'Temperature',       unit:'\\u00b0C', keys:[['temp','#e0a25c']]},
  {id:'fan',   title:'Fan speed',         unit:'RPM', keys:[['fan','#5ce09b']]},
  {id:'power', title:'Power / efficiency',unit:'W / %', keys:[['power','#e05cc9'],['eff','#6ea8fe']]},
];
let range = '7d', rows = [];
// Injected by the server (see PAGE_SUBSTITUTIONS): a Python constant is not
// visible to the browser, and a bare reference here only throws at runtime.
const ROW_LIMIT = __ROW_LIMIT__;
// A successful /api/state is not proof of a live daemon: state.json survives a
// stop, so the age of its last sample is the only evidence the page has.
const STALE_AFTER_S = __STALE_AFTER_S__;

function buildCards() {
  const grid = document.getElementById('grid');
  grid.innerHTML = CHARTS.map(c => `
    <div class="card">
      <h2>${c.title} <span style="color:#7c8794;font-weight:400">${c.unit}</span></h2>
      <div class="last" id="last-${c.id}">--</div>
      <div class="meta" id="meta-${c.id}">&nbsp;</div>
      <canvas id="cv-${c.id}" height="120"></canvas>
      <div class="bar" style="margin:6px 0 2px">
        <button data-png="${c.id}">PNG</button>
        <button data-csv="${c.id}">CSV</button>
      </div>
    </div>`).join('');
}

function num(v) { const n = parseFloat(v); return Number.isFinite(n) ? n : null; }

function series(key) {
  const pts = [];
  rows.forEach((r, i) => {
    const v = num(r[key]);
    if (v === null) return;
    const t = Date.parse(r.time);
    // [epoch, row index, value]: the row number is the fallback position, and an
    // unparseable timestamp stays null instead of collapsing onto epoch 0.
    pts.push([Number.isFinite(t) ? t / 1000 : null, i, v]);
  });
  return pts;
}

function fmtStamp(sec, from, to) {
  const d = new Date(sec * 1000), pad2 = n => String(n).padStart(2, '0');
  const hm = pad2(d.getHours()) + ':' + pad2(d.getMinutes());
  const sameDay = new Date(from * 1000).toDateString() === new Date(to * 1000).toDateString();
  return sameDay ? hm : pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) + ' ' + hm;
}

function draw(canvas, all, showAxis) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 320, h = canvas.clientHeight || 120;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  const pad = 26;
  let lo = Infinity, hi = -Infinity, t0 = Infinity, t1 = -Infinity, timed = true;
  all.forEach(s => s.pts.forEach(p => {
    if (p[2] < lo) lo = p[2];
    if (p[2] > hi) hi = p[2];
    if (p[0] === null) timed = false;
    else { if (p[0] < t0) t0 = p[0]; if (p[0] > t1) t1 = p[0]; }
  }));
  if (!Number.isFinite(lo)) { ctx.fillStyle = '#7c8794'; ctx.fillText('no data', 8, 20); return []; }
  if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
  // X is wall-clock whenever every point has a timestamp: spacing by row number
  // makes a six-hour outage look like two adjacent samples, and pins the newest
  // point to the right edge, which reads as "live" even when nothing is.
  const span = rows.length > 1 ? rows.length - 1 : 1;
  const useTime = timed && Number.isFinite(t0) && t1 > t0;
  const x = p => useTime
    ? pad + ((p[0] - t0) / (t1 - t0)) * (w - pad - 6)
    : pad + (p[1] / span) * (w - pad - 6);
  const y = v => h - 16 - ((v - lo) / (hi - lo)) * (h - 28);

  ctx.strokeStyle = '#262d36'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(pad, 4); ctx.lineTo(pad, h - 16); ctx.lineTo(w - 6, h - 16); ctx.stroke();

  if (showAxis) {
    ctx.fillStyle = '#7c8794'; ctx.font = '10px sans-serif';
    ctx.fillText(hi.toFixed(hi >= 100 ? 0 : 2), 2, 12);
    ctx.fillText(lo.toFixed(lo >= 100 ? 0 : 2), 2, h - 18);
    if (useTime) {
      ctx.fillText(fmtStamp(t0, t0, t1), pad, h - 3);
      const tail = fmtStamp(t1, t0, t1);
      ctx.fillText(tail, w - 6 - ctx.measureText(tail).width, h - 3);
    }
  }

  all.forEach(s => {
    ctx.strokeStyle = s.color; ctx.lineWidth = 1.6; ctx.beginPath();
    s.pts.forEach((p, k) => { const px = x(p), py = y(p[2]); k ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
    ctx.stroke();
  });
  return [lo, hi];
}

function render() {
  CHARTS.forEach(c => {
    const canvas = document.getElementById('cv-' + c.id);
    const all = c.keys.map(([k, color]) => ({color, pts: series(k)}));
    const range2 = draw(canvas, all, true);
    const last = all.map(s => s.pts.length ? s.pts[s.pts.length - 1][2] : null);
    document.getElementById('last-' + c.id).textContent = last
      .map((v, i) => v === null ? '--' : v.toFixed(c.id === 'fan' ? 0 : 2) + ' ' + (c.keys[i][0] === 'eff' ? '%' : c.unit))
      .join('   ');
    const pts = all.reduce((n, s) => n + s.pts.length, 0);
    document.getElementById('meta-' + c.id).textContent =
      pts ? `min ${range2[0].toFixed(2)} / max ${range2[1].toFixed(2)} \\u00b7 ${rows.length} samples` : 'no data in range';
  });
  drawWeekly();
}

function toCsv(keys, name) {
  const head = ['time'].concat(keys.map(k => k[0]));
  const body = rows.map(r => head.map(k => r[k] ?? '').join(','));
  const blob = new Blob([head.join(',') + '\\n' + body.join('\\n') + '\\n'], {type: 'text/csv'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = `msi-psu-${name}.csv`; a.click();
  URL.revokeObjectURL(a.href);
}

function toPng(id) {
  const canvas = document.getElementById('cv-' + id);
  const a = document.createElement('a');
  a.href = canvas.toDataURL('image/png'); a.download = `msi-psu-${id}.png`; a.click();
}

function drawWeekly() {
  const canvas = document.getElementById('weekly');
  const entries = Object.entries(daily).slice(-7);
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 640, h = canvas.clientHeight || 150;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  if (!entries.length) { ctx.fillStyle = '#7c8794'; ctx.fillText('no energy recorded yet', 8, 20); return; }
  const max = Math.max(...entries.map(e => e[1])) || 1;
  const bw = (w - 20) / entries.length;
  entries.forEach((e, i) => {
    const bh = ((h - 34) * e[1]) / max;
    ctx.fillStyle = '#2f6fb5';
    ctx.fillRect(12 + i * bw, h - 22 - bh, bw * 0.7, bh);
    ctx.fillStyle = '#8b98a8'; ctx.font = '10px sans-serif';
    ctx.fillText(e[0].slice(5), 12 + i * bw, h - 8);
    ctx.fillText(e[1].toFixed(2), 12 + i * bw, h - 26 - bh);
  });
  document.getElementById('weeklyMeta').textContent =
    `total ${entries.reduce((n, e) => n + e[1], 0).toFixed(2)} kWh over ${entries.length} day(s)`;
}

let daily = {};

async function okJson(response) {
  if (!response.ok) {
    // The reason is in the text body (503: unreadable state dir, 400: bad
    // window); "HTTP 503" alone tells the operator nothing actionable.
    const detail = await response.text().catch(() => '');
    throw new Error(`HTTP ${response.status}${detail ? ': ' + detail.trim() : ''}`);
  }
  return response.json();
}

function ago(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return 'unknown';
  if (seconds < 90) return Math.round(seconds) + 's';
  if (seconds < 5400) return Math.round(seconds / 60) + 'm';
  if (seconds < 172800) return Math.round(seconds / 3600) + 'h';
  return Math.round(seconds / 86400) + 'd';
}

async function load() {
  const info = document.getElementById('info');
  const problems = [];
  let hist = null, st = null;
  // Two independent fetches: an unreadable state.json (503 + reason) must not
  // blank the history charts, which are still perfectly readable.
  try { hist = await fetch('/api/history?from=' + range).then(okJson); }
  catch (err) { problems.push('history unavailable (' + err + ')'); }
  try { st = await fetch('/api/state').then(okJson); }
  catch (err) { problems.push('totals unavailable (' + err + ')'); }
  if (hist) rows = hist.rows.slice(-ROW_LIMIT);
  if (st) daily = st.daily || {};

  const now = Date.now() / 1000;
  let text;
  if (st) {
    text = (st.product || 'MSI PSU') + ' \\u00b7 samples ' + st.count + ' \\u00b7 avg ' +
      st.power_avg.toFixed(2) + ' W \\u00b7 avg eff ' + st.efficiency_avg.toFixed(2) + ' % \\u00b7 total ' +
      st.total_energy_kwh.toFixed(3) + ' kWh';
    text += st.last_ts
      ? ' \\u00b7 last sample ' + ago(now - st.last_ts) + ' ago'
      : ' \\u00b7 no sample timestamp';
  } else {
    text = 'Totals unavailable';
  }
  if (problems.length) text += ' \\u00b7 ' + problems.join('; ');
  info.textContent = text;
  // HTTP 200 is not freshness: state.json outlives the daemon, so a stopped
  // process keeps answering with its last totals. Age, not status, decides.
  const age = st && st.last_ts ? now - st.last_ts : NaN;
  // A negative age is a clock step, not freshness: treat it as stale too.
  const stale = !Number.isFinite(age) || age < 0 || age > STALE_AFTER_S || problems.length > 0;
  info.classList.toggle('stale', stale);
  render();
}

document.getElementById('grid').addEventListener('click', e => {
  const png = e.target.dataset.png, csv = e.target.dataset.csv;
  if (png) toPng(png);
  if (csv) toCsv(CHARTS.find(c => c.id === csv).keys, csv);
});
document.querySelector('.bar').addEventListener('click', e => {
  if (!e.target.dataset.from) return;
  range = e.target.dataset.from;
  document.querySelectorAll('[data-from]').forEach(b => b.classList.toggle('on', b === e.target));
  document.getElementById('csv').href = `/api/export?from=${range}`;
  load();
});
window.addEventListener('resize', render);
buildCards();
load();
setInterval(load, __REFRESH_MS__);
</script>
</body>
</html>
"""


# Values the embedded page needs but cannot see. A Python constant is invisible
# to the browser, so each one is named here and injected by ``render_page()``;
# a page that references a server constant directly only fails at runtime.
PAGE_SUBSTITUTIONS = {
    '__REFRESH_MS__': '30000',
    '__ROW_LIMIT__': str(ROW_LIMIT),
    '__STALE_AFTER_S__': str(STALE_AFTER_S),
}


def render_page():
    """Return the dashboard HTML with every ``__PLACEHOLDER__`` substituted."""
    page = PAGE
    for name, value in PAGE_SUBSTITUTIONS.items():
        page = page.replace(name, value)
    return page


def _state_dir_problem(state_dir):
    """Return why the state directory cannot be read, or ``None`` when it is fine.

    Without this, an unreadable directory answers exactly like a daemon that
    never ran: ``count: 0``, ``power_avg: 0.0``, ``total_energy_kwh: 0.0``, HTTP
    200. The distinction matters -- one means "nothing was recorded", the other
    means "the numbers on screen are not the numbers on disk".

    Only the directory is checked here, because that gates every ``/api/`` route:
    without it even the history files cannot be listed. A problem with the
    ``state.json`` file itself is reported by ``/api/state`` alone, so one damaged
    file cannot hide a month of readable history.
    """
    path = Path(state_dir)
    if not path.is_dir():
        return f'no state directory at {path} (has the daemon run yet?)'
    if not os.access(path, os.R_OK | os.X_OK):
        return f'{path} is not readable by this user'
    return None


def _history_payload(state_dir, from_spec):
    """Return the JSON payload for ``/api/history``.

    A blank ``?from=`` raises like ``--from ''`` does on the CLI: it must not
    silently become the default window.
    """
    window = None if from_spec is None or from_spec == 'all' else stats.parse_from(from_spec)
    since = None if window is None else time.time() - window
    rows = list(stats.iter_history(state_dir, since_ts=since))
    return {'from': from_spec or 'all', 'count': len(rows), 'rows': rows}


def _state_payload(state_dir):
    """Return the JSON payload for ``/api/state``.

    Raises ``stats.StateError`` when an existing ``state.json`` cannot be used;
    the route turns that into a 503 with the reason. Answering zeros for a file
    we could not read would be indistinguishable from a daemon that never ran.

    ``last_ts`` travels with the totals on purpose: an HTTP 200 only proves the
    file was readable, not that the daemon is still writing it. Without the
    timestamp, a week-old state.json renders exactly like a live one.
    """
    path = stats.state_path(state_dir)
    if path.exists() and not os.access(path, os.R_OK):
        # read_text() would raise PermissionError and be reported generically;
        # this names the file and the fix ("run as the user that owns it").
        raise stats.StateError(f'{path} is not readable by this user')
    monitor_state = stats.MonitorState.load(path, strict=True)
    return {
        'product': monitor_state.product,
        'serial': monitor_state.serial,
        'count': monitor_state.count,
        'power_avg': monitor_state.power_avg,
        'efficiency_avg': monitor_state.efficiency_avg,
        'total_energy_kwh': monitor_state.total_energy_kwh,
        'last_ts': monitor_state.last_ts,
        'daily': dict(sorted(monitor_state.daily.items())),
    }


class DashboardHandler(BaseHTTPRequestHandler):
    """Read-only HTTP handler bound to one state directory."""

    server_version = 'msi-psu-monitor'
    state_dir = Path('.')

    def log_message(self, fmt, *args):  # pragma: no cover - quiet by default
        pass

    def _send(self, status, body, content_type, extra_headers=(), with_body=True):
        """Write one response; ``with_body=False`` keeps HEAD honest.

        The Content-Length always describes the entity a GET would return, so a
        HEAD carries the same status, type and length as its GET twin.
        """
        payload = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        for name, value in extra_headers:
            self.send_header(name, value)
        self.end_headers()
        if with_body:
            self.wfile.write(payload)

    def _query(self):
        # keep_blank_values: ``?from=`` and ``?columns=`` are hard errors on the
        # CLI (parse_from('')/parse_columns('') raise), so they must be 400s
        # here too instead of silently selecting the default.
        return parse_qs(urlparse(self.path).query, keep_blank_values=True)

    def _from_spec(self):
        return (self._query().get('from') or ['2h'])[0]

    def _since_ts(self):
        """Return the epoch cutoff for the requested window (None = everything)."""
        spec = self._from_spec()
        return None if spec == 'all' else time.time() - stats.parse_from(spec)

    def _columns(self):
        raw = (self._query().get('columns') or [None])[0]
        return stats.parse_columns(raw)

    def _route(self):
        """Resolve the request into ``(status, body, content type, headers)``.

        Split out from ``do_GET`` so HEAD can reuse it verbatim and cannot drift
        into answering 200 for a route that GET would 404.
        """
        try:
            # Inside the try on purpose: a request target with an unbalanced
            # bracket ("GET http://[/x HTTP/1.1" is a legal request line) makes
            # urlparse raise ValueError("Invalid IPv6 URL"), which used to escape
            # do_GET entirely -- the client saw a dropped connection and a
            # traceback instead of a 400.
            route = urlparse(self.path).path
            if route in ('/', '/index.html'):
                page = render_page()
                return 200, page, 'text/html; charset=utf-8', ()
            if route.startswith('/api/'):
                problem = _state_dir_problem(self.state_dir)
                if problem is not None:
                    # An unreadable directory yields the same "0 samples / 0.000
                    # kWh / 200" as a daemon that never ran, and the operator has
                    # no way to tell the two apart. The CLI can: it fails loudly.
                    return 503, f'{problem}\n', 'text/plain; charset=utf-8', ()
            if route == '/api/history':
                payload = _history_payload(self.state_dir, self._from_spec())
                return 200, json.dumps(payload), 'application/json', ()
            if route == '/api/state':
                try:
                    payload = _state_payload(self.state_dir)
                except stats.StateError as exc:
                    # A damaged state file is not "0 samples": say which file and
                    # why, and leave /api/history untouched.
                    return 503, f'{exc}\n', 'text/plain; charset=utf-8', ()
                return 200, json.dumps(payload), 'application/json', ()
            if route == '/api/export':
                header, rows = stats.build_export(
                    self.state_dir,
                    self._since_ts(),
                    self._columns(),
                )
                lines = [','.join(str(cell) for cell in row) for row in [header] + rows]
                return (
                    200,
                    '\n'.join(lines) + '\n',
                    'text/csv; charset=utf-8',
                    (('Content-Disposition', 'attachment; filename="msi-psu.csv"'),),
                )
        except ValueError as exc:
            return 400, f'{exc}\n', 'text/plain; charset=utf-8', ()
        return 404, 'not found\n', 'text/plain; charset=utf-8', ()

    def do_GET(self):
        self._send(*self._route())

    def do_HEAD(self):
        status, body, content_type, extra_headers = self._route()
        self._send(status, body, content_type, extra_headers, with_body=False)


def make_server(host=DEFAULT_HOST, port=DEFAULT_PORT, state_dir=None):
    """Build (but do not start) a dashboard server bound to ``state_dir``."""
    handler = type(
        'BoundDashboardHandler', (DashboardHandler,), {'state_dir': Path(state_dir or '.')}
    )
    return ThreadingHTTPServer((host, port), handler)


def serve(host=DEFAULT_HOST, port=DEFAULT_PORT, state_dir=None):
    """Serve the dashboard until interrupted; return the process exit code."""
    try:
        httpd = make_server(host, port, state_dir)
    except (OSError, OverflowError) as exc:
        # A second --dashboard, a privileged port, or a port outside 0-65535
        # (OverflowError, which is not an OSError): report it, do not traceback.
        logger.error(f'Error: cannot serve on {host}:{port}: {exc}')
        return 1
    # flush: under systemd (or `--dashboard > log`) stdout is a pipe, and this
    # process never exits cleanly -- the URL would stay in the buffer forever.
    print(
        f'msi-psu-monitor dashboard: http://{host}:{httpd.server_port}/  (Ctrl-C to stop)',
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0
