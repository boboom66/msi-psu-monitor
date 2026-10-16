#!/usr/bin/env python3
"""Resident MSI PSU monitor daemon (stdlib only, Python 3.10+).

One process owns the PSU hidraw device and samples it on a fixed cadence
(D-02), replacing the old systemd timer that re-scanned every minute:

* every ``sample_interval`` (1 s): read sensors, evaluate the E1h alerts and
  the per-pin software mirror; alerts go to stderr so journald picks them up;
* every ``prom_interval`` (30 s): atomically replace the node_exporter
  textfile (``.tmp`` + ``os.replace``), so scrapers never see a partial file;
* every ``history_interval`` (60 s): append one CSV line to
  ``daily-YYYYMMDD.log`` and persist the cumulative state;
* every hour: drop history files and daily buckets older than
  ``retention_days`` (30).

Five consecutive read failures trigger a rescan for the device, matching MSI
Center's recovery behaviour when the PSU drops off the bus.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path

from msi_psu_monitor import __version__
from msi_psu_monitor import monitor
from msi_psu_monitor import state as stats
from msi_psu_monitor.alerts import AlertEngine
from msi_psu_monitor.config import load_config
from msi_psu_monitor.protocol import DeviceBusyError

logger = logging.getLogger('msi_psu.daemon')

RESCAN_AFTER_FAILURES = 5
DISCOVERY_RETRY_S = 5.0
PRUNE_INTERVAL_S = 3600.0


class MonitorDaemon:
    """Sample loop with injectable device factory, clock and sleep (testable)."""

    def __init__(
        self,
        cfg,
        psu_factory=None,
        select_device=None,
        clock=time.monotonic,
        wall_clock=time.time,
    ):
        self.cfg = cfg
        self.state_dir = Path(cfg.get('state_dir') or stats.default_state_dir())
        self.prom_path = Path(cfg['prom_path']) if cfg.get('prom_path') else None
        self.sample_interval = float(cfg.get('sample_interval') or 1.0)
        self.prom_interval = float(cfg.get('prom_interval') or 30.0)
        self.history_interval = float(cfg.get('history_interval') or 60.0)
        self.retention_days = int(cfg.get('retention_days') or stats.RETENTION_DAYS)
        self.fan_mode = cfg.get('fan_mode') or None
        self.fan_duty = cfg.get('fan_duty')
        self.psu_factory = psu_factory or self._open_default
        self.select_device = select_device or self._discover
        self.clock = clock
        self.wall_clock = wall_clock

        self.state = stats.MonitorState.load(stats.state_path(self.state_dir))
        self.engine = AlertEngine(consecutive_required=int(cfg.get('consecutive_required') or 1))
        self.psu = None
        self.device_path = None
        self.failures = 0
        self.samples = 0
        self.stopping = False
        self._next_prom = 0.0
        self._next_history = 0.0
        self._next_prune = 0.0
        self._next_discovery = 0.0

    # ---- device lifecycle ------------------------------------------------

    def _discover(self):
        """Return the hidraw path to use, honouring the optional serial filter."""
        path, _ = monitor.resolve_device(self.cfg.get('serial'))
        return path

    def _open_default(self, path):
        return monitor.open_psu(path)

    def _ensure_psu(self):
        """Return an open PSU, discovering and re-opening it as needed."""
        if self.psu is not None:
            return self.psu
        if self.device_path is None:
            now = self.clock()
            if now < self._next_discovery:
                return None
            self._next_discovery = now + DISCOVERY_RETRY_S
            self.device_path = self.select_device()
            if self.device_path is None:
                logger.debug('No MSI PSU found yet; retrying shortly.')
                return None
        try:
            psu = self.psu_factory(self.device_path)
            psu.open()
            psu.init()
        except (OSError, DeviceBusyError) as exc:
            logger.warning(f'Cannot open {self.device_path}: {exc}')
            self._next_discovery = self.clock() + DISCOVERY_RETRY_S
            return None
        self.psu = psu
        logger.info(f'Opened {self.device_path}: {getattr(psu, "product", "unknown")}')
        self.restore_fan_profile(psu)
        return psu

    def restore_fan_profile(self, psu=None):
        """Re-apply the configured fan profile after (re)opening the PSU.

        The PSU keeps 41h across a suspend but not across AC loss, and MSI Center
        re-asserts its profile whenever it takes the device over again -- this is
        that behaviour. Opt-in through ``[fan] mode`` in the config file; with no
        mode configured the daemon never writes to the PSU.

        A refusal is logged, never fatal: monitoring must survive a PSU that
        rejects the write (an older firmware, or a fan already at that setting).
        """
        psu = psu or self.psu
        if psu is None or self.fan_mode is None:
            return False
        try:
            applied = monitor.apply_fan_setting(psu, self.fan_mode, self.fan_duty)
        except Exception as exc:  # pragma: no cover - defensive against odd devices
            logger.warning(f'Fan profile restore failed: {exc}')
            return False
        if applied is None:
            logger.warning('The PSU refused the configured fan profile; leaving it as is.')
            return False
        mode, duty = applied
        detail = f'{mode}' + ('' if duty is None else f' duty {duty}%')
        logger.info(f'Restored the configured fan profile: {detail}')
        return True

    def _drop_psu(self):
        if self.psu is None:
            return
        try:
            self.psu.close()
        except Exception:  # pragma: no cover - best effort on a dying device
            pass
        self.psu = None

    def _rediscover(self):
        self._drop_psu()
        self.device_path = None
        self._next_discovery = 0.0
        logger.warning(
            f'{RESCAN_AFTER_FAILURES} consecutive read failures; rescanning for the PSU.'
        )

    # ---- sampling --------------------------------------------------------

    def sample(self):
        """Read and enrich one sample; return None when the PSU did not answer."""
        psu = self._ensure_psu()
        if psu is None:
            return None

        try:
            sensors = psu.get_sensors()
        except OSError as exc:
            # An unplugged PSU raises ENODEV out of a read; that is a failure to
            # count towards the rescan, never a reason to die.
            return self._read_failed(str(exc))
        if 'error' in sensors:
            return self._read_failed(str(sensors['error']))
        if not monitor.has_readings(sensors):
            return self._read_failed('no sensor payload (0xE0 read failed)')
        self.failures = 0

        sensors.update(monitor.read_fan_fields(psu))
        active, have_data = [], False
        try:
            _, active, have_data = monitor.collect_alerts(psu, self.engine, sensors)
        except Exception as exc:  # pragma: no cover - defensive against odd devices
            logger.debug(f'Alert poll failed: {exc}')
        sensors['alerts'] = active
        sensors['status'] = monitor.status_from(active, have_data)
        monitor.apply_stats(sensors, self.state)
        self.samples += 1
        return sensors

    def _read_failed(self, reason):
        """Count one failed read and rescan after ``RESCAN_AFTER_FAILURES``."""
        self.failures += 1
        logger.error(f'Read failed ({self.failures}/{RESCAN_AFTER_FAILURES}): {reason}')
        if self.failures >= RESCAN_AFTER_FAILURES:
            self.failures = 0
            self._rediscover()
        return None

    def write_prometheus(self, sensors, output=None):
        """Atomically replace the textfile collector output."""
        target = Path(output) if output else self.prom_path
        if target is None:
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + '.tmp')
        tmp.write_text(monitor.format_prometheus(sensors) + '\n')
        os.replace(tmp, target)
        return target

    def record_history(self, sensors):
        """Append today's CSV line and persist the cumulative state."""
        stats.append_history(self.state_dir, sensors, ts=self.wall_clock())
        self.state.prune(days=self.retention_days)
        self.state.save(stats.state_path(self.state_dir))

    # ---- main loop -------------------------------------------------------

    def _install_signal_handlers(self):
        def handler(signum, _frame):
            logger.info(f'Received signal {signum}; shutting down.')
            self.stopping = True

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):  # pragma: no cover - non-main thread
                pass

    def tick(self):
        """Run one sampling iteration; return False to stop the loop."""
        now = self.clock()
        sensors = self.sample()
        if sensors is None:
            return not self.stopping

        if now >= self._next_prom:
            try:
                self.write_prometheus(sensors)
            except OSError as exc:
                logger.error(f'Cannot write {self.prom_path}: {exc}')
            self._next_prom = now + self.prom_interval

        if now >= self._next_history:
            try:
                self.record_history(sensors)
            except OSError as exc:
                logger.error(f'Cannot write history: {exc}')
            self._next_history = now + self.history_interval

        if now >= self._next_prune:
            stats.prune_history(self.state_dir, days=self.retention_days)
            self._next_prune = now + PRUNE_INTERVAL_S

        return not self.stopping

    def run(self, iterations=None):
        """Sample until SIGTERM/SIGINT (or ``iterations`` samples, for tests)."""
        self._install_signal_handlers()
        logger.info(
            f'msi-psu-monitor daemon {__version__} started '
            f'(state: {self.state_dir}, prom: {self.prom_path or "disabled"})'
        )
        try:
            while self.tick():
                if iterations is not None:
                    iterations -= 1
                    if iterations <= 0:
                        break
                time.sleep(self.sample_interval)
        finally:
            self._drop_psu()
            try:
                self.state.save(stats.state_path(self.state_dir))
            except OSError as exc:  # pragma: no cover - read-only state dir
                logger.error(f'Cannot persist state: {exc}')
            logger.info(f'Stopped after {self.samples} samples.')
        return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog='msi-psu-monitor-daemon',
        description='Resident MSI PSU monitor (1s alerts, 30s prometheus, 60s history).',
    )
    parser.add_argument('--config', type=str, default=None, help='Explicit config file')
    parser.add_argument('--state-dir', type=str, default=None, help='Override the state directory')
    parser.add_argument('--prom-path', type=str, default=None, help='Override the prometheus path')
    parser.add_argument(
        '--iterations',
        type=int,
        default=None,
        metavar='N',
        help='Stop after N samples instead of running forever (smoke tests)',
    )
    parser.add_argument(
        '--verbose', '-v', action='store_true', help='Verbose diagnostics on stderr'
    )
    parser.add_argument('--quiet', '-q', action='store_true', help='Errors only on stderr')
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    if args.state_dir:
        cfg['state_dir'] = args.state_dir
    if args.prom_path:
        cfg['prom_path'] = args.prom_path

    monitor.setup_logging(
        verbose=args.verbose or cfg['verbose'],
        quiet=args.quiet or cfg['quiet'],
    )
    daemon = MonitorDaemon(cfg)
    try:
        return daemon.run(iterations=args.iterations)
    except KeyboardInterrupt:  # pragma: no cover - SIGINT before handlers are up
        return 0


if __name__ == '__main__':
    sys.exit(main())
