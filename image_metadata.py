"""Validate the HA version and publication policy before any image is pushed."""
import json
import os
from pathlib import Path
import re
import yaml


def metadata(config, event, ref, repository, release_tag='', request_publish='false'):
    version = config['version']
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?', version):
        raise ValueError('App version must be a valid versioned container tag')
    if set(config['arch']) != {'amd64', 'aarch64'}:
        raise ValueError('Expected amd64 and aarch64')
    if set(config['options']) != set(config['schema']):
        raise ValueError('App options/schema mismatch')
    if config['image'] != 'ghcr.io/holsteiner-kiel/ha-kuma-discovery':
        raise ValueError('Unexpected image repository')
    if event == 'release' and release_tag not in (version, 'v' + version):
        raise ValueError('Release tag does not match config.yaml version')
    bootstrap = event == 'push' and ref == 'refs/heads/ci/prebuilt-ghcr-images' and version == '1.5.2'
    manual = event == 'workflow_dispatch' and request_publish == 'true' and ref == 'refs/heads/main'
    publish = repository == 'holsteiner-kiel/ha-kuma-discovery' and (bootstrap or manual or event == 'release')
    return version, publish


if __name__ == '__main__':
    config = yaml.safe_load(Path('ha_kuma_discovery/config.yaml').read_text())
    version, publish = metadata(config, os.environ['EVENT'], os.environ['GITHUB_REF'],
                                os.environ['GITHUB_REPOSITORY'], os.environ.get('RELEASE_TAG', ''),
                                os.environ.get('REQUEST_PUBLISH', 'false'))
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
        output.write(f'version={version}\npublish={str(publish).lower()}\n')
    print(json.dumps({'version': version, 'publish': publish}))
