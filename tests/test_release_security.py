"""Release-security invariants: SBOM, support/security docs, incident runbook."""

import hashlib
import json
import subprocess
import sys

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _version():
    text = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
    for line in text.splitlines():
        if line.startswith('version = '):
            return line.split('"', 1)[1].split('"', 1)[0]
    raise AssertionError('no project version')


def test_security_and_support_documents_exist_and_name_the_current_line():
    security = (ROOT / 'SECURITY.md').read_text(encoding='utf-8')
    support = (ROOT / 'docs/support.md').read_text(encoding='utf-8')
    version = _version()
    assert 'Supported versions' in security
    assert 'Reporting a vulnerability' in security
    assert 'SBOM' in security and 'SHA256SUMS' in security
    major_minor = '.'.join(version.split('.')[:2]) + '.x'
    assert major_minor in support
    assert 'Update channel' in support
    assert 'glibc 2.35' in support


def test_the_incident_runbook_preserves_evidence_and_has_a_release_path():
    text = (ROOT / 'docs/incident-response.md').read_text(encoding='utf-8')
    for command in ('systemctl stop', 'sha256sum', 'journalctl', 'gh release delete'):
        assert command in text
    assert 'Preserve the evidence' in text or 'preserve the evidence' in text


def test_the_release_workflow_generates_and_publishes_an_sbom():
    text = (ROOT / '.github/workflows/release.yml').read_text(encoding='utf-8')
    assert 'scripts/build_sbom.py' in text
    assert 'SBOM-${{ matrix.arch }}.json' in text
    assert 'dist/SBOM-*.json' in text
    assert (
        'sha256sum msi-psu-monitor_*.tar.gz msi-psu-monitor_*_amd64.deb '
        'msi-psu-monitor_*_arm64.deb SBOM-*.json'
    ) in text


def test_the_sbom_generator_emits_cyclonedx_with_artifact_hashes(tmp_path):
    dist = tmp_path / 'dist'
    dist.mkdir()
    artifact = dist / 'msi-psu-monitor_1.0.0_linux_x86_64.tar.gz'
    artifact.write_bytes(b'payload')
    output = tmp_path / 'SBOM.json'
    subprocess.run(
        [
            sys.executable,
            str(ROOT / 'scripts/build_sbom.py'),
            '--dist',
            str(dist),
            '--output',
            str(output),
            '--arch',
            'x86_64',
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    bom = json.loads(output.read_text(encoding='utf-8'))
    assert bom['bomFormat'] == 'CycloneDX'
    assert bom['specVersion'] == '1.5'
    assert bom['metadata']['component']['version'] == _version()
    files = [c for c in bom['components'] if c['type'] == 'file']
    assert files == [
        {
            'type': 'file',
            'name': artifact.name,
            'hashes': [{'alg': 'SHA-256', 'content': hashlib.sha256(b'payload').hexdigest()}],
        }
    ]
    names = {c['name'] for c in bom['components']}
    assert {'CPython', 'PyInstaller', 'OpenSSL', 'zlib'} <= names


def test_the_sbom_generator_is_stdlib_only():
    text = (ROOT / 'scripts/build_sbom.py').read_text(encoding='utf-8')
    for forbidden in ('import requests', 'import tomli', 'from tomli'):
        assert forbidden not in text


def test_ci_and_release_run_the_quality_gates():
    """A release tag must not publish code that skipped the normal gates."""
    ci = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
    release = (ROOT / '.github/workflows/release.yml').read_text(encoding='utf-8')
    assert 'coverage report --fail-under=90' in ci
    for command in (
        'ruff check .',
        'ruff format --check .',
        'mypy msi_psu_monitor/',
        'bash scripts/smoke.sh',
    ):
        assert command in release, command
