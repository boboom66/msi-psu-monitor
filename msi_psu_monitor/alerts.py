"""Edge-triggered alert engine for MSI PSU E1h status bits."""

from dataclasses import dataclass, field

SEVERITY_WARNING = 'warning'
SEVERITY_CRITICAL = 'critical'

# The fan alert means the PSU shuts down ~10 s after it is sent (REV6 E1h),
# so it is the only critical level; all protection trips are warnings.
CRITICAL_ALERTS = frozenset({'fan'})

ALERT_DESCRIPTIONS = {
    'ocp_12v': '12V rail over-current (≥105% rated)',
    'ocp_5v': '5V rail over-current (≥105% rated)',
    'ocp_3v3': '3.3V rail over-current (≥105% rated)',
    'ovp_12v': '12V rail over-voltage',
    'ovp_5v': '5V rail over-voltage',
    'ovp_3v3': '3.3V rail over-voltage',
    'uvp_12v': '12V rail under-voltage',
    'uvp_5v': '5V rail under-voltage',
    'uvp_3v3': '3.3V rail under-voltage',
    'opp': 'total power over-power (≥105% rated)',
    'otp': 'over-temperature (>OTP-5°C)',
    'fan': 'fan blocked, shutdown imminent',
    'ac': 'AC input lost, running on hold-up',
}
for _rail in range(1, 6):
    ALERT_DESCRIPTIONS[f'ocp_12v{_rail}'] = f'12V{_rail} rail over-current'
for _pin in range(1, 13):
    ALERT_DESCRIPTIONS[f'ocp_pin{_pin}'] = f'12+4 pin {_pin} over-current'

# Software mirror of the PSU's own 12V-2x6 thresholds (REV6 C0h factory
# defaults, frozen 2026-10-16): one pin over 12 A, or a spread wider than
# 5 A between the pins of the same connector, counts as an alert even
# before the PSU's own (5 s averaged, 20 s debounced) trip fires.
PIN_OCP_THRESHOLD_A = 12.0
PIN_IMBALANCE_THRESHOLD_A = 5.0
IMBALANCE_ALERT = 'pin_imbalance'
ALERT_DESCRIPTIONS[IMBALANCE_ALERT] = '12V-2x6 pin current difference (>5A)'


def severity_of(name):
    """Return the severity level for an alert name."""
    return SEVERITY_CRITICAL if name in CRITICAL_ALERTS else SEVERITY_WARNING


@dataclass
class Alert:
    """A single fired alert."""

    name: str
    severity: str = field(default=SEVERITY_WARNING)
    description: str = field(default='')


def describe(name):
    """Human-readable description for an alert name."""
    return ALERT_DESCRIPTIONS.get(name, name)


def format_alert_line(alert):
    """Single-line console rendering: ALERT [severity] name: description."""
    return f'ALERT [{alert.severity}] {alert.name}: {alert.description}'


class AlertEngine:
    """Convert raw E1h bitmaps into edge-triggered alerts.

    An alert fires only after `consecutive_required` successive polls
    report it active (debounce against single-sample flakiness; 12+4
    readings are 5-second averages per REV6). Recovery clears on the
    first OK poll so shutdown-imminent states never linger.
    """

    def __init__(self, consecutive_required=2):
        if consecutive_required < 1:
            raise ValueError('consecutive_required must be >= 1')
        self.consecutive_required = consecutive_required
        self._streaks = {}
        self._fired = set()
        #: Recoveries since the last take_cleared(); retain() is a model swap,
        #: not a recovery, so it stays out of this list.
        self._cleared = []

    def update(self, active):
        """Feed one E1h poll result; return newly fired alerts.

        Args:
            active: Dict mapping alert name to bool (True = active).

        Returns:
            List of Alert objects fired by this poll (possibly empty).
        """
        fired = []
        for name, is_active in active.items():
            if is_active:
                streak = self._streaks.get(name, 0) + 1
                self._streaks[name] = streak
                if streak >= self.consecutive_required and name not in self._fired:
                    self._fired.add(name)
                    fired.append(
                        Alert(name=name, severity=severity_of(name), description=describe(name))
                    )
            else:
                self._streaks.pop(name, None)
                if name in self._fired:
                    self._fired.discard(name)
                    self._cleared.append(
                        Alert(name=name, severity=severity_of(name), description=describe(name))
                    )
        return fired

    def retain(self, names):
        """Forget alerts (and streaks) this device cannot report any more.

        A name only leaves the fired set when a poll reports it ``False``, so an
        alert inherited from a previously attached model outlives the device that
        could produce it: ``ocp_pin1`` latched on an Ai1600TS is not in the MEG
        Ai1300P's index array, so it is never reported again and the daemon exports
        ``msi_psu_alert{alert="ocp_pin1"} 1`` (and a status line naming it) forever.

        Callers pass the names the current device can report -- and only when they
        actually read the E1h bitmap, because an unanswered read says nothing
        about which names the device has (see ``monitor.collect_alerts``).

        Args:
            names: Alert names that stay in the engine.
        """
        known = set(names)
        self._fired &= known
        for name in [name for name in self._streaks if name not in known]:
            del self._streaks[name]

    def take_cleared(self):
        """Return alerts that recovered since the last call, and reset the list."""
        cleared, self._cleared = self._cleared, []
        return cleared

    @property
    def active_alerts(self):
        """Names of alerts currently in fired state."""
        return sorted(self._fired)


def evaluate_pin_alerts(pins):
    """Map per-pin currents (A) to ``name -> bool``, mirroring C0h thresholds.

    Imbalance is evaluated per 6-pin connector when all 12 pins are present,
    because each 12V-2x6 connector is protected independently.
    """
    if not pins:
        return {}
    try:
        values = [float(value) for value in pins]
    except (TypeError, ValueError):
        return {}
    active = {
        f'ocp_pin{index}': value >= PIN_OCP_THRESHOLD_A
        for index, value in enumerate(values, start=1)
    }
    groups = [values[0:6], values[6:12]] if len(values) == 12 else [values]
    spread = 0.0
    for group in groups:
        if group:
            spread = max(spread, max(group) - min(group))
    active[IMBALANCE_ALERT] = spread > PIN_IMBALANCE_THRESHOLD_A
    return active
