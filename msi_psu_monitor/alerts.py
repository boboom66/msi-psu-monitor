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
    'opp': 'total power over-power (≥105% rated)',
    'otp': 'over-temperature (>OTP-5°C)',
    'fan': 'fan blocked, shutdown imminent',
}
for _pin in range(1, 13):
    ALERT_DESCRIPTIONS[f'ocp_pin{_pin}'] = f'12+4 pin {_pin} over-current'


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
                self._fired.discard(name)
        return fired

    @property
    def active_alerts(self):
        """Names of alerts currently in fired state."""
        return sorted(self._fired)
