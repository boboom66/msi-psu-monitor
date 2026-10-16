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
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from msi_psu_monitor import state as stats

logger = logging.getLogger('msi_psu.dashboard')

DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 8899
ROW_LIMIT = 20000

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
 canvas { width: 100%; height: 120px; display: block; }
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
  rows.forEach((r, i) => { const v = num(r[key]); if (v !== null) pts.push([i, v]); });
  return pts;
}

function draw(canvas, all, showAxis) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 320, h = 120;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  const pad = 26;
  let lo = Infinity, hi = -Infinity;
  all.forEach(s => s.pts.forEach(p => { if (p[1] < lo) lo = p[1]; if (p[1] > hi) hi = p[1]; }));
  if (!Number.isFinite(lo)) { ctx.fillStyle = '#7c8794'; ctx.fillText('no data', 8, 20); return []; }
  if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
  const span = rows.length > 1 ? rows.length - 1 : 1;
  const x = i => pad + (i / span) * (w - pad - 6);
  const y = v => h - 16 - ((v - lo) / (hi - lo)) * (h - 28);

  ctx.strokeStyle = '#262d36'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(pad, 4); ctx.lineTo(pad, h - 16); ctx.lineTo(w - 6, h - 16); ctx.stroke();

  if (showAxis) {
    ctx.fillStyle = '#7c8794'; ctx.font = '10px sans-serif';
    ctx.fillText(hi.toFixed(hi >= 100 ? 0 : 2), 2, 12);
    ctx.fillText(lo.toFixed(lo >= 100 ? 0 : 2), 2, h - 18);
  }

  all.forEach(s => {
    ctx.strokeStyle = s.color; ctx.lineWidth = 1.6; ctx.beginPath();
    s.pts.forEach((p, k) => { const px = x(p[0]), py = y(p[1]); k ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
    ctx.stroke();
  });
  return [lo, hi];
}

function render() {
  CHARTS.forEach(c => {
    const canvas = document.getElementById('cv-' + c.id);
    const all = c.keys.map(([k, color]) => ({color, pts: series(k)}));
    const range2 = draw(canvas, all, true);
    const last = all.map(s => s.pts.length ? s.pts[s.pts.length - 1][1] : null);
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
  const w = canvas.clientWidth || 640, h = 150;
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

function okJson(response) {
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function load() {
  const info = document.getElementById('info');
  try {
    const [hist, st] = await Promise.all([
      fetch(`/api/history?from=${range}`).then(okJson),
      fetch('/api/state').then(okJson),
    ]);
    rows = hist.rows.slice(-ROW_LIMIT);
    daily = st.daily || {};
    info.textContent =
      `${st.product || 'MSI PSU'} \\u00b7 samples ${st.count} \\u00b7 avg ${st.power_avg.toFixed(2)} W ` +
      `\\u00b7 avg eff ${st.efficiency_avg.toFixed(2)} % \\u00b7 total ${st.total_energy_kwh.toFixed(3)} kWh`;
  } catch (err) {
    // A failed poll has to be visible: leaving the previous numbers on screen
    // without a word is how a dead daemon keeps looking healthy.
    info.textContent = `Data may be stale (${err})`;
  }
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
}


def render_page():
    """Return the dashboard HTML with every ``__PLACEHOLDER__`` substituted."""
    page = PAGE
    for name, value in PAGE_SUBSTITUTIONS.items():
        page = page.replace(name, value)
    return page


def _history_payload(state_dir, from_spec):
    """Return the JSON payload for ``/api/history``."""
    window = stats.parse_from(from_spec) if from_spec and from_spec != 'all' else None
    since = None if window is None else time.time() - window
    rows = list(stats.iter_history(state_dir, since_ts=since))
    return {'from': from_spec or 'all', 'count': len(rows), 'rows': rows}


def _state_payload(state_dir):
    """Return the JSON payload for ``/api/state``."""
    monitor_state = stats.MonitorState.load(stats.state_path(state_dir))
    return {
        'product': monitor_state.product,
        'serial': monitor_state.serial,
        'count': monitor_state.count,
        'power_avg': monitor_state.power_avg,
        'efficiency_avg': monitor_state.efficiency_avg,
        'total_energy_kwh': monitor_state.total_energy_kwh,
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
        return parse_qs(urlparse(self.path).query)

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
        route = urlparse(self.path).path
        try:
            if route in ('/', '/index.html'):
                page = render_page()
                return 200, page, 'text/html; charset=utf-8', ()
            if route == '/api/history':
                payload = _history_payload(self.state_dir, self._from_spec())
                return 200, json.dumps(payload), 'application/json', ()
            if route == '/api/state':
                payload = _state_payload(self.state_dir)
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
    except OSError as exc:
        # A second --dashboard, or a privileged port: report it, do not traceback.
        logger.error(f'Error: cannot serve on {host}:{port}: {exc}')
        return 1
    print(f'msi-psu-monitor dashboard: http://{host}:{httpd.server_port}/  (Ctrl-C to stop)')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0
