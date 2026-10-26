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

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: the stdlib module arrives in 3.11
    import tomli as tomllib

#: Every shipped module, including the console-script entry point. ``__init__``
#: is absent because importing any ``msi_psu_monitor.<module>`` imports it first.
SHIPPED_MODULES = (
    '__main__',
    'alerts',
    'config',
    'daemon',
    'dashboard',
    'demo',
    'menu',
    'monitor',
    'protocol',
    'state',
    'termdash',
)

PROBE = """
import importlib
import sys

before = set(sys.modules)
for module in __MODULES__:
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
    # -I ignores PYTHONPATH and, since 3.11, keeps the cwd off sys.path, so the
    # checkout is injected in the child: this must test the tree, not whatever
    # happens to be pip-installed in the environment running pytest.
    probe = f'import sys; sys.path.insert(0, {str(root)!r})' + PROBE.replace(
        '__MODULES__', repr(SHIPPED_MODULES)
    )
    result = subprocess.run(
        [sys.executable, '-I', '-c', probe],
        cwd=root,
        capture_output=True,
        text=True,
        env={'PATH': '/usr/bin:/bin'},
    )
    # -I is not what proves the promise (-S would be needed to hide
    # site-packages, and the .deb does install into site-packages anyway): the
    # leak check is. Anything our modules import from outside the stdlib lands
    # in `foreign`, so a new runtime dependency cannot slip in unnoticed.
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_probe_covers_every_shipped_module():
    """A module missing from the tuple is a hole the stdlib-only promise leaks through.

    The tuple used to be hand-written and omitted ``__main__`` (the console-script
    entry point), while the docs claimed "every module" was imported. Tying the
    tuple to the directory means a new module cannot be forgotten.
    """
    root = pathlib.Path(__file__).resolve().parents[1]
    shipped = {path.stem for path in (root / 'msi_psu_monitor').glob('*.py')}
    assert set(SHIPPED_MODULES) == shipped - {'__init__'}


def test_pyproject_declares_no_runtime_dependencies():
    """A stray dependency would silently enter every `.deb` install."""
    root = pathlib.Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / 'pyproject.toml').read_text())['project']
    assert project.get('dependencies', []) == []
