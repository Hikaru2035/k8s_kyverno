#!/usr/bin/env python3
"""Fetch only successful Jenkins archives and verify the approved policy contract."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import urllib.parse
import urllib.request
import yaml

ENVIRONMENTS = {'development': 'dev', 'staging': 'staging', 'production': 'production'}
GROUPS = ('common', 'baseline', 'standard', 'restricted')
KINDS = {'ValidatingPolicy': 'validatingpolicies', 'ImageValidatingPolicy': 'imagevalidatingpolicies',
         'MutatingPolicy': 'mutatingpolicies', 'GeneratingPolicy': 'generatingpolicies'}
DEFERRED_REASON = 'external-registry-signature-verification-deferred-for-poc'


def require(ok, message):
    if not ok: raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fields(path):
    result = {}
    for line in path.read_text().splitlines():
        key, separator, value = line.partition('=')
        require(separator and key and value and key not in result, f'Invalid/duplicate metadata field in {path.name}')
        result[key] = value
    return result


def verify(path, env):
    path = Path(path)
    require(env in ENVIRONMENTS, 'Invalid POLICY_ENVIRONMENT')
    require(path.name == f'approved-policies-{env}' and path.is_dir(), 'Artifact/environment path mismatch')
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'Symlink artifact path')
    entries = list(path.rglob('*'))
    require(not any(p.is_symlink() or not (p.is_dir() or p.is_file()) for p in entries), 'Symlink/nonregular artifact entry')
    meta = fields(path/'metadata.txt')
    require(meta.get('environment') == env, 'Artifact environment mismatch')
    require(meta.get('approval_mode') == 'poc', 'Unsupported approval mode')
    require(re.fullmatch('[0-9a-f]{40,64}', meta.get('git_commit','')), 'Invalid policy git commit')
    require(re.fullmatch('[A-Za-z0-9][A-Za-z0-9.+_-]*',meta.get('framework_version','')), 'Invalid framework version')
    for key in ('policy_inventory_sha256', 'test_evidence_sha256'):
        require(re.fullmatch('[0-9a-f]{64}',meta.get(key,'')), f'Invalid {key}')
    inventory = (path/'policy-inventory.txt').read_bytes()
    require(digest(inventory) == meta['policy_inventory_sha256'], 'Inventory aggregate hash mismatch')
    expected, identities, documents = {}, set(), []
    for line in inventory.decode().splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  ((?:common|baseline|standard|restricted)/[A-Za-z0-9_.-]+\.yaml)', line)
        require(match is not None, 'Invalid policy inventory entry')
        sha, relative = match.groups()
        require(relative not in expected, 'Duplicate inventory path')
        expected[relative] = sha
    require(inventory == ''.join(f'{h}  {p}\n' for p,h in sorted(expected.items())).encode(), 'Inventory must be canonical and sorted')
    required = {'metadata.txt','policy-inventory.txt','test-coverage-summary.txt'} | {'policies/'+p for p in expected}
    require({str(p.relative_to(path)) for p in entries if p.is_file()} == required, 'Missing or unexpected artifact files')
    require({str(p.relative_to(path)) for p in entries if p.is_dir()} == {'policies'} | {'policies/'+g for g in GROUPS}, 'Unexpected/missing artifact directories')
    for relative, sha in expected.items():
        content = (path/'policies'/relative).read_bytes()
        require(digest(content) == sha, f'Policy hash mismatch: {relative}')
        policy = yaml.safe_load(content)
        require(policy['apiVersion'] == 'policies.kyverno.io/v1' and policy['kind'] in KINDS, 'Unsupported policy resource')
        md = policy['metadata']; name = md['name']
        require(re.fullmatch('[a-z0-9][a-z0-9.-]*',name) and not md.get('namespace'), 'Invalid cluster policy identity')
        require(md.get('annotations',{}).get('policies.ksp.io/runtime-environment') == env, 'Rendered policy environment mismatch')
        identity = (policy['apiVersion'],policy['kind'],name)
        require(identity not in identities, 'Duplicate policy identity')
        identities.add(identity); documents.append(policy)
    count = len(expected)
    require(count > 0 and meta.get('policy_count') == str(count), 'Policy count mismatch')
    summary = fields(path/'test-coverage-summary.txt')
    require(summary.get('environment') == env, 'Coverage environment mismatch')
    numeric = ('expected_policies','accounted_policies','canonical_cases','environment_regression_cases',
               'executed','not_applicable','deferred','failed','configuration_assertions','runtime_e2e_owned_by_delivery')
    counts = {}
    for key in numeric:
        require(re.fullmatch('[0-9]+',meta.get(key,'')) and summary.get(key) == meta[key], f'Coverage mismatch: {key}')
        counts[key] = int(meta[key])
    require(counts['expected_policies'] == counts['accounted_policies'] == count, 'Unaccounted policies')
    require(counts['failed'] == 0 and counts['executed'] > 0 and counts['configuration_assertions'] >= count, 'Unapproved coverage')
    require(counts['canonical_cases']+counts['environment_regression_cases'] == counts['executed']+counts['not_applicable']+counts['deferred'], 'Case accounting mismatch')
    if counts['deferred']:
        require(meta.get('deferred_policy') == 'KSP-IMG-004' and meta.get('deferred_reason') == DEFERRED_REASON, 'Unapproved deferral')
        require(any(d['metadata'].get('labels',{}).get('policies.ksp.io/id') == 'ksp-img-004' for d in documents), 'Deferred policy absent')
    if counts['not_applicable']:
        require(meta.get('not_applicable_reason') == 'admission-mutation-disabled-for-environment', 'Unapproved non-applicable reason')
        require(any(d['metadata'].get('labels',{}).get('policies.ksp.io/id') == 'ksp-pod-012'
                    and d['spec'].get('evaluation',{}).get('admission',{}).get('enabled') is False for d in documents), 'Disabled mutation policy absent')
    artifact_hash = digest(''.join(f'{digest((path/p).read_bytes())}  {p}\n' for p in sorted(required)).encode())
    return dict(environment=env, policy_git_commit=meta['git_commit'], framework_version=meta['framework_version'],
                policy_count=count, policy_inventory_sha256=meta['policy_inventory_sha256'], artifact_sha256=artifact_hash,
                approval_mode=meta['approval_mode'], coverage=counts,
                deferrals=dict(count=counts['deferred'], policy=meta.get('deferred_policy'), reason=meta.get('deferred_reason')),
                policies=[dict(apiVersion=a,kind=k,name=n) for a,k,n in sorted(identities)])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Jenkins redirected artifact access; configure its canonical JENKINS_URL')


def authenticated_get(url):
    user, token = os.environ['JENKINS_ARTIFACT_USER'], os.environ['JENKINS_ARTIFACT_TOKEN']
    auth = base64.b64encode((user+':'+token).encode()).decode()
    request = urllib.request.Request(url, headers={'Authorization':'Basic '+auth})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
        require(response.status == 200, 'Jenkins artifact request failed')
        data = response.read(16*1024*1024+1)
        require(len(data) <= 16*1024*1024, 'Jenkins response exceeds PoC size limit')
        return data


def fetch(out, env, job, build, base_url):
    require(env in ENVIRONMENTS, 'Invalid POLICY_ENVIRONMENT')
    require(re.fullmatch('[1-9][0-9]*',build), 'POLICY_CI_BUILD must be an explicit build number')
    parts = job.split('/')
    require(all(re.fullmatch('[A-Za-z0-9][A-Za-z0-9_. -]*',p) for p in parts), 'Invalid POLICY_CI_JOB')
    url = urllib.parse.urlsplit(base_url)
    require(url.scheme in ('http','https') and url.netloc and not url.username and not url.password and not url.query and not url.fragment,
            'Invalid JENKINS_URL')
    build_url = base_url.rstrip('/')+'/'+'/'.join('job/'+urllib.parse.quote(p,safe='') for p in parts)+'/'+build+'/'
    api = build_url+'api/json?tree=number,result,building,artifacts%5BrelativePath%5D'
    info = json.loads(authenticated_get(api))
    require(info.get('number') == int(build) and info.get('result') == 'SUCCESS' and info.get('building') is False,
            'Policy CI build must be completed SUCCESS')
    name = f'approved-policies-{env}'
    prefixes = (f'artifacts/{name}/', f'{name}/')
    available = [a['relativePath'] for a in info['artifacts']]
    chosen = [p for p in prefixes if any(a.startswith(p) for a in available)]
    require(len(chosen) == 1, 'Requested environment artifact missing or ambiguous')
    prefix = chosen[0]; paths = [p for p in available if p.startswith(prefix)]
    require(0 < len(paths) <= 1024 and len(paths) == len(set(paths)), 'Invalid archive file inventory')
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    require(not (out/name).exists(), 'Artifact destination already exists')
    with tempfile.TemporaryDirectory(prefix='.download-',dir=out) as temp:
        staged = Path(temp)/name; staged.mkdir()
        for entry in paths:
            relative = entry[len(prefix):]; p = PurePosixPath(relative)
            require(not p.is_absolute() and all(x not in ('','.','..') for x in relative.split('/')) and '\\' not in relative,
                    'Unsafe archived artifact path')
            target = staged/relative; target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(authenticated_get(build_url+'artifact/'+urllib.parse.quote(entry,safe='/')))
        provenance = verify(staged,env)
        provenance.update(source_job=job, source_build=int(build), source_build_url=build_url, source_archive_prefix=prefix)
        staged.rename(out/name)
    evidence = out/'policy-artifact'; evidence.mkdir(exist_ok=True)
    (evidence/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    print(json.dumps(provenance,indent=2))


def check(out, env, job, build):
    out = Path(out)
    prior = json.loads((out/'policy-artifact/provenance.json').read_text())
    require(prior['source_job'] == job and str(prior['source_build']) == build, 'Policy CI source identity changed')
    current = verify(out/f'approved-policies-{env}',env)
    require(all(prior.get(k) == v for k,v in current.items()), 'Artifact changed after retrieval')
    return prior


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('fetch','check'))
    parser.add_argument('out')
    args=parser.parse_args()
    try:
        values=(args.out, os.environ['POLICY_ENVIRONMENT'], os.environ['POLICY_CI_JOB'], os.environ['POLICY_CI_BUILD'])
        if args.command=='fetch': fetch(*values,os.environ['JENKINS_URL'])
        else: print(json.dumps(check(*values),indent=2))
    except (ValueError, OSError, KeyError, yaml.YAMLError) as error:
        raise SystemExit(f'Approved artifact rejected: {error}')
