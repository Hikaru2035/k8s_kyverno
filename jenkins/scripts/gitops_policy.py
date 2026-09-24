#!/usr/bin/env python3
"""Promote cumulative profiles exclusively from a verified Jenkins archive receipt."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import tempfile
from policy_artifact import GROUPS, check, require, verify

PROFILES = ('baseline','standard','restricted')


def copy_profile(artifact, destination, environment, profile, provenance):
    """Shared exact-byte copier; bootstrap may supply explicitly unverified origin metadata."""
    require(environment == 'development', 'This GitOps PoC targets development only')
    require(profile in PROFILES, 'Invalid POLICY_PROFILE')
    artifact, destination = Path(artifact), Path(destination)
    verified = verify(artifact,environment)
    require(not any(p.is_symlink() for p in (destination,*destination.parents)), 'Symlink destination')
    require(not destination.exists() or destination.is_dir(), 'Expected destination directory')
    if destination.exists():
        require(not any(p.is_symlink() for p in destination.rglob('*')), 'Symlink desired state')
        require(all(p.name in (*GROUPS,'kustomization.yaml','provenance.json') for p in destination.iterdir()),
                'Unexpected desired-state entry; refusing deletion')
    groups = GROUPS[:GROUPS.index(profile)+1]
    contents = {f'{g}/{p.name}':p.read_bytes() for g in groups for p in sorted((artifact/'policies'/g).glob('*.yaml'))}
    require(all(any(name.startswith(g+'/') for name in contents) for g in groups), 'Empty selected policy group')
    metadata = dict(provenance, policy_environment=environment, policy_profile=profile,
                    approved_artifact_sha256=verified['artifact_sha256'], source_commit=verified['policy_git_commit'],
                    promotion_timestamp=datetime.now(timezone.utc).isoformat(), policy_count=len(contents),
                    approval_mode=verified['approval_mode'], deferrals=verified['deferrals'])
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.policy-stage-',dir=destination.parent) as tmp:
        staged = Path(tmp)/'desired'; staged.mkdir()
        for relative, content in contents.items():
            target = staged/relative; target.parent.mkdir(exist_ok=True)
            target.write_bytes(content)
            require(target.read_bytes() == (artifact/'policies'/relative).read_bytes(), 'Copied policy bytes differ')
        require(verify(artifact,environment) == verified, 'Artifact changed during promotion')
        (staged/'kustomization.yaml').write_text('apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n' +
                                              ''.join(f'  - {name}\n' for name in sorted(contents)))
        (staged/'provenance.json').write_text(json.dumps(metadata,indent=2,sort_keys=True)+'\n')
        if destination.exists(): shutil.rmtree(destination)
        staged.rename(destination)
    for relative, content in contents.items():
        require((destination/relative).read_bytes() == content, 'Final policy bytes differ')
    return metadata


def promote(out, destination, environment, profile, job, build):
    require(re.fullmatch('[1-9][0-9]*',build), 'Explicit POLICY_CI_BUILD required')
    prior = check(out,environment,job,build)
    result = copy_profile(Path(out)/f'approved-policies-{environment}',destination,environment,profile,
                        dict(policy_ci_job=job,policy_ci_build=int(build),source_build_url=prior.get('source_build_url'),
                             origin='successful-jenkins-archive'))
    require(check(out,environment,job,build) == prior, 'Retrieval receipt changed during promotion')
    return result


if __name__ == '__main__':
    import os
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out'); parser.add_argument('destination')
    args = parser.parse_args()
    try:
        print(json.dumps(promote(args.out,args.destination,os.environ['POLICY_ENVIRONMENT'],
                                 os.environ['POLICY_PROFILE'],os.environ['POLICY_CI_JOB'],os.environ['POLICY_CI_BUILD']),indent=2))
    except (ValueError,OSError,KeyError) as error:
        raise SystemExit(f'Promotion rejected: {error}')
