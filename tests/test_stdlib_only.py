"""The runtime must stay standard-library only.

`dependencies = []` in pyproject.toml is a declaration; this test is the proof.
It imports every shipped module in a fresh subprocess and fails if anything
outside the standard library (or the package itself) shows up in ``sys.modules``.
A subprocess is required because pytest has already imported third-party code
into this process.
"""

import pathlib
import subprocess
import sys
import tomllib

PROBE = """
import importlib
import sys

before = set(sys.modules)
for module in (
    'protocol',
    'alerts',
    'config',
    'state',
    'monitor',
    'daemon',
    'dashboard',
    'demo',
):
    importlib.import_module('msi_psu_monitor.' + module)

added = {name.split('.')[0] for name in set(sys.modules) - before}
foreign = sorted(
    name
    for name in added
    if name not in sys.stdlib_module_names
    and not name.startswith(('msi_psu_monitor', '_'))
)
if foreign:
    sys.exit('third-party import leaked in: ' + ', '.join(foreign))
"""


def test_shipped_modules_import_without_third_party_packages():
    root = pathlib.Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, '-I', '-c', PROBE],
        cwd=root,
        capture_output=True,
        text=True,
        env={'PYTHONPATH': str(root), 'PATH': '/usr/bin:/bin'},
    )
    # -I ignores site-packages, which is exactly the environment a `.deb`
    # install runs in: python3 + our modules, nothing else.
    assert result.returncode == 0, result.stdout + result.stderr


def test_pyproject_declares_no_runtime_dependencies():
    """A stray dependency would silently enter every `.deb` install."""
    root = pathlib.Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / 'pyproject.toml').read_text())['project']
    assert project.get('dependencies', []) == []
