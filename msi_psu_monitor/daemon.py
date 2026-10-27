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
import signal
import sys
import time
from pathlib import Path

from msi_psu_monitor import __version__
from msi_psu_monitor import monitor
from msi_psu_monitor import state as stats
from msi_psu_monitor.alerts import AlertEngine
from msi_psu_monitor.config import ConfigError, load_config
from msi_psu_monitor.protocol import DeviceBusyError

logger = logging.getLogger('msi_psu.daemon')

#: Same exit-code contract as the CLI (monitor.EXIT_*): 0 ok, 1 error.
EXIT_OK = 0
EXIT_ERROR = 1

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
        # A deliberately slow cadence is not a "long gap": the guard exists for
        # suspend/outage, so it must never be shorter than the expected interval.
        self.state_gap_s = max(stats.MAX_SAMPLE_GAP_S, self.sample_interval * 2)
        self.alert_log = bool(cfg.get('alert_log', True))
        self.live_snapshot = bool(cfg.get('live_snapshot', True))
        self.fan_mode = cfg.get('fan_mode') or None
        self.fan_duty = cfg.get('fan_duty')
        self.fan_zero_fan = cfg.get('fan_zero_fan')
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
        #: Why the last discovery found nothing (filled by the default _discover).
        self.discovery_available = []
        self.discovery_blocked = []
        self._discovery_note = None
        #: Reason of the read failure the current textfile was written for, so a
        #: broken read rewrites ``msi_psu_up 0`` once instead of every second.
        self.prom_failure = None
        self.last_failure = None
        self._next_prom = 0.0
        self._next_history = 0.0
        self._next_prune = 0.0
        self._next_discovery = 0.0
        # OCP block (C0h thresholds + C1h state) for the prometheus file.
        # ocp_available stays None until a PSU is open and its variant is known.
        self.ocp_available = None
        self.ocp_config = None
        self.ocp_state = None
        self.ocp_multirail = None

    # ---- device lifecycle ------------------------------------------------

    def _discover(self):
        """Return the hidraw path to use, honouring the optional serial filter."""
        path, available, blocked = monitor.resolve_device(self.cfg.get('serial'))
        # Keep the reason a miss had none of the three shapes: no device at all,
        # a serial that is not attached, or devices that all refused to open.
        self.discovery_available = list(available)
        self.discovery_blocked = list(blocked)
        return path

    def _note_discovery_miss(self):
        """Explain a discovery miss once, instead of failing silently forever.

        ``resolve_device`` already knows why nothing matched, but the daemon used
        to reduce all three cases to a debug line every five seconds: a typo in
        ``[monitor] serial`` left the service running and logging nothing an
        operator would ever see. The message is emitted once per distinct reason
        (a replaced/rejected device changes the text, a repeated miss does not).
        """
        serial = self.cfg.get('serial')
        if serial and self.discovery_available:
            note = (
                f'No PSU with serial {serial!r} is attached; seen: '
                f'{", ".join(self.discovery_available)}. '
                f'Retrying every {DISCOVERY_RETRY_S:g}s.'
            )
        elif self.discovery_blocked:
            note = (
                'Could not open any MSI PSU device (permission, or another process '
                f'holds it). Run as root, or install the udev rule. Retrying every '
                f'{DISCOVERY_RETRY_S:g}s.'
            )
        elif serial:
            note = f'No PSU with serial {serial!r} is attached yet; retrying.'
        else:
            return
        if note == self._discovery_note:
            return
        self._discovery_note = note
        logger.warning(note)

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
            try:
                self.device_path = self.select_device()
            except Exception as exc:
                # Discovery touches sysfs/glob/open: a single bad uevent
                # (non-UTF-8 bytes, a vanishing hidraw node) must throttle like
                # any other discovery miss, never kill the resident daemon.
                logger.warning(f'Device discovery failed: {exc}')
                self.device_path = None
                self._next_discovery = self.clock() + DISCOVERY_RETRY_S
                return None
            if self.device_path is None:
                self._note_discovery_miss()
                logger.debug('No MSI PSU found yet; retrying shortly.')
                return None
        psu = None
        try:
            psu = self.psu_factory(self.device_path)
            psu.open()
            psu.init()
        except (OSError, DeviceBusyError) as exc:
            # open() succeeded but init() failed: the fd is live, so close it
            # before dropping the object. Without this a persistent init failure
            # leaks one descriptor per discovery attempt.
            if psu is not None:
                try:
                    psu.close()
                except Exception:  # pragma: no cover - best effort on a dying device
                    pass
            logger.warning(f'Cannot open {self.device_path}: {exc}')
            # Forget the path so the retry goes through the discovery throttle
            # above: keeping it made the next tick reopen (and warn) every second.
            self.device_path = None
            self._next_discovery = self.clock() + DISCOVERY_RETRY_S
            return None
        except Exception as exc:
            # A malformed device object/parser bug must not kill the daemon.
            if psu is not None:
                try:
                    psu.close()
                except Exception:  # pragma: no cover - best effort
                    pass
            logger.warning(f'Unexpected error while opening {self.device_path}: {exc}')
            self.device_path = None
            self._next_discovery = self.clock() + DISCOVERY_RETRY_S
            return None
        self.psu = psu
        self._discovery_note = None
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
        if psu is None or (self.fan_mode is None and self.fan_zero_fan is None):
            return False
        restored = []
        if self.fan_zero_fan is not None:
            try:
                zero = monitor.apply_zero_fan_setting(psu, self.fan_zero_fan)
            except Exception as exc:  # pragma: no cover - defensive against odd devices
                logger.warning(f'Zero Fan profile restore failed: {exc}')
                zero = None
            if zero is None:
                logger.warning('The PSU refused the configured Zero Fan setting; leaving it as is.')
            else:
                restored.append(f'Zero Fan {"on" if zero else "off"}')
        if self.fan_mode is not None:
            try:
                applied = monitor.apply_fan_setting(psu, self.fan_mode, self.fan_duty)
            except Exception as exc:  # pragma: no cover - defensive against odd devices
                logger.warning(f'Fan profile restore failed: {exc}')
                applied = None
            if applied is None:
                logger.warning('The PSU refused the configured fan profile; leaving it as is.')
            else:
                mode, duty = applied
                restored.append(f'{mode}' + ('' if duty is None else f' duty {duty}%'))
        if not restored:
            return False
        logger.info(
            f'Restored the configured fan profile: {", ".join(restored)} '
            f'(product={getattr(psu, "product", "")!r} fw={getattr(psu, "fw_revision", "")!r})'
        )
        return True

    def _drop_psu(self):
        if self.psu is None:
            return
        try:
            self.psu.close()
        except Exception:  # pragma: no cover - best effort on a dying device
            pass
        self.psu = None
        # The replacement may be a different model, so forget the OCP block
        # instead of exporting the previous PSU's thresholds.
        self.ocp_available = None
        self.ocp_config = None
        self.ocp_state = None
        self.ocp_multirail = None

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
        except Exception as exc:
            # A malformed payload/parser bug must not kill the resident daemon:
            # count it as a failed read so the rescan/restart path can recover.
            logger.warning(f'Unexpected error while reading the PSU: {exc}')
            return self._read_failed(f'unexpected read error: {exc}')
        if not isinstance(sensors, dict):
            # The contract is a dict; None/list would turn the membership tests
            # below into a TypeError and kill the loop before the rescan.
            return self._read_failed(f'get_sensors returned {type(sensors).__name__}, not a dict')
        if 'error' in sensors:
            return self._read_failed(str(sensors['error']))
        if not monitor.has_readings(sensors):
            return self._read_failed(
                sensors.get('payload_error') or 'no sensor payload (0xE0 read failed)'
            )
        self.failures = 0

        sensors.update(monitor.read_fan_fields(psu))
        # [monitor] no_alerts: documented as "skip the E1h alert poll entirely
        # (same as --no-alerts)", and honoured here the way the CLI honours it --
        # no poll, and no status/alerts/threshold keys, so no Status line, no
        # alert metrics and no alert log lines. It used to be ignored by the
        # daemon, i.e. a documented switch that did nothing in normal mode.
        if not self.cfg.get('no_alerts'):
            fired = []
            try:
                fired = monitor.attach_alerts(psu, self.engine, sensors, self.cfg)
            except Exception as exc:  # pragma: no cover - defensive against odd devices
                logger.debug(f'Alert poll failed: {exc}')
            # take_cleared() must run even when the log is disabled, or the
            # engine's recovery buffer would grow for the life of the daemon.
            self._record_alerts(fired, self.engine.take_cleared())
        try:
            monitor.apply_stats(
                sensors, self.state, max_gap_s=self.state_gap_s, ts=self.wall_clock()
            )
        except Exception as exc:
            # A malformed reading must not kill the resident daemon either.
            logger.warning(f'Unexpected error while enriching the sample: {exc}')
            return self._read_failed(f'sample enrichment error: {exc}')
        if self.live_snapshot:
            stats.write_live_snapshot(self.state_dir, sensors, ts=self.wall_clock())
        self.samples += 1
        return sensors

    def _record_alerts(self, fired, cleared):
        """Append alert edges and recoveries to the durable alert log.

        MSI Center keeps AlertLog_MM_dd_yyyy.log (5 MiB cap); this is the same
        idea in the state directory. A failed write is logged by the state helper
        and never interrupts monitoring.
        """
        if not self.alert_log or (not fired and not cleared):
            return
        try:
            for alert in fired:
                stats.append_alert_log(
                    self.state_dir, monitor.format_alert_line(alert), ts=self.wall_clock()
                )
            for alert in cleared:
                stats.append_alert_log(
                    self.state_dir,
                    f'RECOVERED {monitor.format_alert_line(alert)}',
                    ts=self.wall_clock(),
                )
        except Exception as exc:  # pragma: no cover - alert logging is best effort
            # A full disk or an unwritable state directory must not turn an alert
            # poll into a monitoring failure; the state helper already logs the
            # specific write error.
            logger.warning(f'Cannot write the alert log: {exc}')

    def _read_failed(self, reason):
        """Count one failed read and rescan after ``RESCAN_AFTER_FAILURES``."""
        self.last_failure = reason
        self.failures += 1
        logger.error(f'Read failed ({self.failures}/{RESCAN_AFTER_FAILURES}): {reason}')
        if self.failures >= RESCAN_AFTER_FAILURES:
            self.failures = 0
            self._rediscover()
        return None

    def refresh_ocp(self):
        """Read the C0h/C1h OCP block for the prometheus file.

        Only the MPG TS models answer 0xC0 with the 8-byte 12V-2x6 OCP
        configuration and 0xC1 with its 42-byte state; on the MEG units 0xC1 is
        the 26-byte black box, so reading it there would export a different
        register as if it were OCP. Nothing is cached: the C1h state is a rolling
        5 s average, and the 30 s prometheus cadence is the right refresh rate
        (two extra reads per write, each bounded by the HID timeout). A failed
        read clears the block and warns rather than leaving the previous values
        behind.
        """
        psu = self.psu
        if psu is None:
            return
        self.ocp_available = bool(getattr(psu, 'supports_ocp_config', False))
        if not self.ocp_available:
            self.ocp_config = None
            self.ocp_state = None
            self.ocp_multirail = self._read_multirail(psu)
            return
        self.ocp_multirail = None  # only the MEG P models answer that 0xC0 read
        try:
            config = psu.read_ocp_thresholds()
        except Exception as exc:  # pragma: no cover - defensive against odd devices
            logger.warning(f'OCP configuration read failed: {exc}')
            config = None
        self.ocp_config = config
        self.ocp_state = None
        if config is None:
            logger.warning(
                'The PSU did not answer the 0xC0 OCP configuration read (or returned an invalid enable byte).'
            )
            return
        reader = getattr(psu, 'read_ocp_state', None)
        if reader is None:
            self.ocp_state = None
            return
        try:
            self.ocp_state = reader()
        except Exception as exc:  # pragma: no cover - the state block is a bonus
            logger.warning(f'OCP state read failed: {exc}')
            self.ocp_state = None

    def _read_multirail(self, psu):
        """Read the 1-byte 0xC0 multirail flag (MEG P models only).

        The other half of the same overloaded address: these models report
        whether per-rail OCP protection is active instead of the 12V-2x6
        thresholds. ``None`` means "this model does not answer that read".
        """
        reader = getattr(psu, 'read_multirail_ocp', None)
        if reader is None or not getattr(psu, 'supports_multirail_ocp', False):
            return None
        try:
            return reader()
        except Exception as exc:  # pragma: no cover - defensive against odd devices
            logger.warning(f'Multirail OCP read failed: {exc}')
            return None

    def write_prometheus(self, sensors, output=None):
        """Atomically replace the textfile collector output."""
        target = Path(output) if output else self.prom_path
        if target is None:
            return None
        body = [monitor.format_prometheus(sensors)]
        # Re-read on every prometheus write: the 0xC1h state is a rolling 5 s
        # average, so caching it once per session would export stale currents as
        # if they were live.
        self.refresh_ocp()
        if self.ocp_config is not None:
            body.append(
                monitor.format_ocp_prometheus(
                    self.ocp_config, self.ocp_state, sensors.get('product')
                )
            )
        elif self.ocp_available is not None:
            body.append(monitor.format_ocp_availability_prometheus(self.ocp_available))
            if self.ocp_multirail is not None:
                body.append(
                    monitor.format_multirail_prometheus(self.ocp_multirail, sensors.get('product'))
                )
        stats.atomic_write_text(target, '\n'.join(body) + '\n')
        self.prom_failure = None
        return target

    def write_prometheus_failure(self, reason, output=None):
        """Overwrite the textfile with ``msi_psu_up 0`` after a failed read.

        ``write_prometheus`` only runs when a sample succeeded, so an unplugged
        PSU used to leave the last healthy file on disk: node_exporter re-exports
        the unchanged ``msi_psu_up 1`` and the last wattage on every scrape, and
        the dashboard shows a PSU that was removed an hour ago as current. The
        same reason is written once (not once per second) so a PSU that stays
        away does not rewrite the file every tick.
        """
        target = Path(output) if output else self.prom_path
        if target is None or self.prom_failure == reason:
            return None
        stats.atomic_write_text(target, monitor.format_prometheus({'error': reason}) + '\n')
        self.prom_failure = reason
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
            # The textfile must not keep claiming the last reading is live.
            try:
                self.write_prometheus_failure(self.last_failure or 'no reading')
            except OSError as exc:
                logger.error(f'Cannot write {self.prom_path}: {exc}')
            except Exception as exc:  # pragma: no cover - defensive against odd paths
                # e.g. an embedded NUL in the configured path raises ValueError,
                # not OSError; the sample loop must still survive it.
                logger.error(f'Unexpected error while writing {self.prom_path}: {exc}')
            return not self.stopping

        if now >= self._next_prom:
            try:
                self.write_prometheus(sensors)
            except OSError as exc:
                logger.error(f'Cannot write {self.prom_path}: {exc}')
            except Exception as exc:
                logger.error(f'Unexpected error while writing {self.prom_path}: {exc}')
            self._next_prom = now + self.prom_interval

        if now >= self._next_history:
            try:
                self.record_history(sensors)
            except OSError as exc:
                logger.error(f'Cannot write history: {exc}')
            except Exception as exc:
                logger.error(f'Unexpected error while writing history: {exc}')
            self._next_history = now + self.history_interval

        if now >= self._next_prune:
            # Housekeeping must never be able to kill the resident daemon: a
            # state directory whose permissions changed under it (or a file
            # system that refuses readdir) raised straight out of tick(), so a
            # PSU that had been monitored for an hour crashed on the first prune
            # and systemd restarted it into the same wall every hour.
            try:
                stats.prune_history(self.state_dir, days=self.retention_days)
                stats.prune_alert_logs(self.state_dir, days=self.retention_days)
            except OSError as exc:
                logger.warning(f'Cannot prune old files in {self.state_dir}: {exc}')
            except Exception as exc:  # pragma: no cover - defensive against odd paths
                logger.warning(f'Unexpected error while pruning {self.state_dir}: {exc}')
            self._next_prune = now + PRUNE_INTERVAL_S

        return not self.stopping

    def run(self, iterations=None):
        """Sample until SIGTERM/SIGINT, or for a bounded number of loop passes."""
        self._install_signal_handlers()
        logger.info(
            f'msi-psu-monitor daemon {__version__} started '
            f'(state: {self.state_dir}, prom: {self.prom_path or "disabled"})'
        )
        if self.cfg.get('no_alerts'):
            # Say it once at start-up: with the poll off there is no Status line
            # and no alert metric at all, which is not the same as "all normal".
            logger.info('Alert polling disabled by config ([monitor] no_alerts).')
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
        return EXIT_OK


def _positive_iterations(text):
    """argparse type: --iterations 0/negative would silently run one sample."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f'invalid iteration count: {text!r}') from None
    if value < 1:
        raise argparse.ArgumentTypeError('--iterations must be at least 1')
    return value


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
        type=_positive_iterations,
        default=None,
        metavar='N',
        help='Stop after N sample-loop passes instead of running forever '
        '(failed reads still count; smoke tests)',
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
    # An unset $DIR is not "use the default": silently ignoring it left the
    # daemon writing to the packaged state directory instead of the one the
    # caller named. --config "" behaves the same way, so it is a usage error
    # here too instead of a ConfigError one exit code later.
    if args.config is not None and not args.config:
        parser.error('--config requires a path')
    if args.state_dir is not None and not args.state_dir:
        parser.error('--state-dir requires a path')
    if args.prom_path is not None and not args.prom_path:
        parser.error('--prom-path requires a path')
    try:
        # Provisional level so load_config()'s own warnings honour --quiet;
        # reconfigured below after the file's verbose/quiet are merged.
        monitor.setup_logging(verbose=args.verbose, quiet=args.quiet)
        cfg = load_config(args.config)
    except ConfigError as exc:
        # A traceback here reaches the journal as 400 lines of stack and systemd
        # restarts the unit every RestartSec forever. The CLI reports the same
        # thing as one line, so do that (logging is not configured yet).
        print(f'Error: {exc}', file=sys.stderr)
        return EXIT_ERROR
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
        return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
