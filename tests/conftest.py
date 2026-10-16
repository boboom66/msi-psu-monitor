"""Pytest bootstrap: make the repo root importable and keep tests out of $HOME."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Point every test at a throwaway state directory.

    Autouse and suite-wide on purpose. ``monitor.main()`` and ``daemon.main()``
    both resolve the state directory through ``state.default_state_dir()``, which
    falls back to ``/var/lib/msi-psu-monitor`` (writable under sudo) or
    ``~/.local/state/msi-psu-monitor``. A test that drives a full CLI run without
    this override *writes and prunes the user's real statistics*, and the leak is
    invisible to the suite because nothing asserts on that directory. Isolating
    here means a new test module cannot forget to do it.
    """
    monkeypatch.setenv('MSI_PSU_STATE_DIR', str(tmp_path))
    return tmp_path
