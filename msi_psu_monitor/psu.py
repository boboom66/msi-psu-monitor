"""``psu`` console command: the interactive menu unless arguments are given.

``psu``            -> the menu (same as ``msi-psu-monitor menu``)
``psu --once``     -> the normal CLI, arguments passed through unchanged
"""

import sys

from msi_psu_monitor import monitor


def main():
    """Open the menu when called with no arguments; otherwise pass through."""
    if len(sys.argv) == 1:
        sys.argv.append('menu')
    monitor.main()


if __name__ == '__main__':
    main()
