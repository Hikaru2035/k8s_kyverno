#!/usr/bin/env python3
"""Assemble this dependency-free demo with crane; no daemon, RUN or root writes."""
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import yaml


def application_layer(source, target):
    content=source.read_bytes()
    with tarfile.open(target,'w',format=tarfile.PAX_FORMAT) as tar:
        directory=tarfile.TarInfo('app'); directory.type=tarfile.DIRTYPE; directory.mode=0o755
        directory.uid=directory.gid=65532; tar.addfile(directory)
        entry=tarfile.TarInfo('app/app.py'); entry.size=len(content); entry.mode=0o444
        entry.uid=entry.gid=65532; tar.addfile(entry,io.BytesIO(content))
    return hashlib.sha256(content).hexdigest()


def build(root, out, tag):
    root,out=Path(root),Path(out);out.mkdir(parents=True,exist_ok=True)
    base=yaml.safe_load((root/'versions.yaml').read_text())['ci']['python']['image']
    # Resolve once, then download the immutable platform-specific base for assembly.
    sha=subprocess.check_output(['crane','digest','--platform=linux/amd64',base],text=True).strip()
    if not re.fullmatch('sha256:[0-9a-f]{64}',sha): raise ValueError('Invalid Python base digest')
    base_ref=base.split('@')[0]+'@'+sha
    with tempfile.TemporaryDirectory(prefix='demo-layer-') as temp:
        layer=Path(temp)/'app.tar'
        source_hash=application_layer(root/'demo-app/src/app.py',layer)
        subprocess.run(['crane','mutate','--platform=linux/amd64',base_ref,'--append',str(layer),
                        '--output',str(out/'image.tar'),'--tag',tag,'--user','65532:65532',
                        '--workdir','/app','--env','PYTHONDONTWRITEBYTECODE=1','--env','PYTHONUNBUFFERED=1',
                        '--cmd','python3,/app/app.py','--exposed-ports','8080'],check=True)
    # Confirm the produced runtime configuration before it reaches the scan/push stages.
    with tarfile.open(out/'image.tar') as archive:
        manifest=json.load(archive.extractfile('manifest.json'))
        if len(manifest)!=1: raise ValueError('Expected one demo image')
        config=json.load(archive.extractfile(manifest[0]['Config']))
    runtime=config['config']
    if (runtime.get('Cmd')!=['python3','/app/app.py'] or runtime.get('User')!='65532:65532'
            or runtime.get('WorkingDir')!='/app' or runtime.get('Entrypoint')):
        raise ValueError('Unexpected assembled image runtime configuration')
    (out/'build-metadata.json').write_text(json.dumps(dict(builder='crane-mutate-local-archive',base_image=base_ref,
        platform='linux/amd64',application_sha256=source_hash,healthcheck='Kubernetes readiness/liveness probes'),indent=2)+'\n')


if __name__=='__main__': build(*sys.argv[1:])
