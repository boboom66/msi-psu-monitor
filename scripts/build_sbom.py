#!/usr/bin/env python3
"""Generate a CycloneDX 1.5 SBOM for the release artifacts (stdlib only).

The release is a PyInstaller freeze, so the SBOM must name both the project and
the components inside the binary (CPython, PyInstaller, OpenSSL, zlib, bzip2,
liblzma) and must hash every artifact it ships. Run it after the artifacts are
built and before SHA256SUMS is generated.
"""

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import ssl
import sys
import uuid
import zlib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def project_version():
    """Read [project] version without requiring tomllib (3.11+)."""
    text = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit('cannot read [project] version from pyproject.toml')
    return match.group(1)


def pyinstaller_version():
    """The pin lives in the build dependency group, not in the runtime metadata."""
    text = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
    match = re.search(r'pyinstaller\s*==\s*([0-9][^\s,]*)', text)
    if match:
        return match.group(1)
    try:
        return importlib.metadata.version('pyinstaller')
    except importlib.metadata.PackageNotFoundError:
        return 'unknown'


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _component(name, version, license_id, kind='library', description=''):
    component = {
        'type': kind,
        'name': name,
        'version': version,
        'licenses': [{'license': {'id': license_id}}],
    }
    if description:
        component['description'] = description
    return component


def build(dist_dir, arch=None):
    version = project_version()
    components = [
        _component(
            'CPython',
            platform.python_version(),
            'PSF-2.0',
            'framework',
            'Python runtime embedded by PyInstaller',
        ),
        _component(
            'PyInstaller',
            pyinstaller_version(),
            'GPL-2.0-or-later WITH Bootloader-exception',
            'application',
            'Bootloader used to freeze the one-file binaries',
        ),
        _component(
            'OpenSSL',
            ssl.OPENSSL_VERSION.split()[1] if ' ' in ssl.OPENSSL_VERSION else 'unknown',
            'Apache-2.0',
            'library',
            'TLS/crypto library bundled by PyInstaller',
        ),
        _component('zlib', zlib.ZLIB_VERSION, 'Zlib', 'library', 'Compression library'),
        _component('bzip2', 'unknown', 'bzip2-1.0.6', 'library', 'Optional compression module'),
        _component('xz/liblzma', 'unknown', '0BSD', 'library', 'Optional compression module'),
    ]

    artifacts = []
    if dist_dir.is_dir():
        for path in sorted(dist_dir.iterdir()):
            if path.is_file() and path.name.endswith(('.tar.gz', '.deb')):
                artifacts.append(
                    {
                        'type': 'file',
                        'name': path.name,
                        'hashes': [{'alg': 'SHA-256', 'content': _sha256(path)}],
                    }
                )
    components.extend(artifacts)

    suffix = arch or 'all'
    bom = {
        'bomFormat': 'CycloneDX',
        'specVersion': '1.5',
        'serialNumber': 'urn:uuid:'
        + str(uuid.uuid5(uuid.NAMESPACE_URL, f'msi-psu-monitor-{version}-{suffix}')),
        'version': 1,
        'metadata': {
            'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'tools': [{'vendor': 'msi-psu-monitor', 'name': 'build_sbom.py', 'version': '1'}],
            'component': {
                'type': 'application',
                'name': 'msi-psu-monitor',
                'version': version,
                'licenses': [{'license': {'id': 'MIT'}}],
            },
        },
        'components': components,
    }
    return bom


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--dist', default='dist', type=Path, help='directory with release artifacts'
    )
    parser.add_argument('--output', required=True, type=Path, help='SBOM JSON path')
    parser.add_argument('--arch', default=None, help='x86_64/arm64 suffix for the serial number')
    args = parser.parse_args(argv)
    bom = build(args.dist, args.arch)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bom, indent=2) + '\n', encoding='utf-8')
    print(f'wrote {args.output} ({len(bom["components"])} components)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
