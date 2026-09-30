#!/usr/bin/env python3
"""Apply/verify archived policies only, using the supplied kubeadm kubeconfig."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import yaml
from policy_artifact import GROUPS, KINDS, require, verify


def normalized(value):
    if isinstance(value,list): return [normalized(x) for x in value]
    if isinstance(value,dict):
        return {k:normalized(v) for k,v in value.items()
                if not (k=='matchPolicy' and v=='Equivalent') and not (k=='scope' and v=='*')
                and not (k in ('namespaceSelector','objectSelector') and not v)}
    return value


def defaulted(value, schema):
    value=copy.deepcopy(value)
    if isinstance(value,dict):
        for key, prop in schema.get('properties',{}).items():
            if key not in value and 'default' in prop: value[key]=copy.deepcopy(prop['default'])
            if key in value: value[key]=defaulted(value[key],prop)
    elif isinstance(value,list): value=[defaulted(v,schema.get('items',{})) for v in value]
    return value


def schema_for(crds, desired):
    crd=crds[desired['kind']]
    return next(v['schema']['openAPIV3Schema'] for v in crd['spec']['versions']
                if v['name']==desired['apiVersion'].split('/')[1] and v.get('served'))


def readiness(actual, schema=None):
    status=actual.get('status',{})
    props=(schema or {}).get('properties',{}).get('status',{}).get('properties',{})
    nested=props.get('conditionStatus',{}).get('properties',{})
    if schema is not None and not ('ready' in nested or 'ready' in props or 'conditions' in props):
        return 'not-exposed-by-crd'
    if 'ready' in nested or (schema is None and 'conditionStatus' in status):
        require(status.get('conditionStatus',{}).get('ready') is True, 'Policy not Ready')
    elif 'ready' in props:
        require(status.get('ready') is True, 'Policy not Ready')
    else:
        require(any(c.get('type')=='Ready' and c.get('status')=='True' for c in status.get('conditions',[])), 'Policy not Ready')
    generation=actual['metadata'].get('generation',0)
    for container in (status,status.get('conditionStatus',{})):
        if 'observedGeneration' in container:
            require(container['observedGeneration']>=generation,'Readiness is stale')
        for condition in container.get('conditions',[]):
            if 'observedGeneration' in condition:
                require(condition['observedGeneration']>=generation,'Readiness condition is stale')
    return 'Ready'


def check(live, paths, crds=None):
    items=live['items']
    indexed={(x['kind'],x['metadata']['name']):x for x in items}
    require(len(indexed)==len(items),'Duplicate live identity')
    wanted={}; evidence=[]
    for path in paths:
        desired=yaml.safe_load(path.read_text()); key=(desired['kind'],desired['metadata']['name'])
        require(key not in wanted,'Duplicate expected policy'); wanted[key]=desired
        actual=indexed.get(key)
        require(actual is not None,f'Missing policy: {key}')
        require(actual['apiVersion']==desired['apiVersion'],f'Policy API mismatch: {key}')
        schema=schema_for(crds,desired) if crds is not None else None
        spec_schema=(schema or {}).get('properties',{}).get('spec',{})
        require(normalized(defaulted(actual['spec'],spec_schema))==
                normalized(defaulted(desired['spec'],spec_schema)),f'Policy drift: {key} spec')
        for field in ('labels','annotations'):
            for name,value in desired['metadata'].get(field,{}).items():
                require(actual['metadata'].get(field,{}).get(name)==value,f'Policy metadata drift: {key}/{name}')
        if desired['kind'] in ('ValidatingPolicy','ImageValidatingPolicy'):
            require(actual['spec'].get('evaluation',{}).get('admission',{}).get('enabled') is not False,f'Admission disabled: {key}')
        require(actual['spec'].get('failurePolicy','Fail')==desired['spec'].get('failurePolicy','Fail'),f'Failure policy drift: {key}')
        evidence.append(dict(kind=key[0],name=key[1],readiness=readiness(actual,schema)))
    extra=[key for key,x in indexed.items() if key not in wanted and
           x['metadata'].get('labels',{}).get('policies.ksp.io/id','').startswith('ksp-')]
    require(not extra,f'Unexpected framework policies: {extra}')
    require(wanted,'Empty approved policy inventory')
    result=dict(expected_count=len(wanted),actual_count=len(evidence),policies=evidence,
                other_cluster_policies=[list(k) for k in indexed if k not in wanted])
    print(json.dumps(result,indent=2))
    return result


def kubectl(*args):
    kubeconfig=os.environ.get('KUBECONFIG','')
    require(kubeconfig and Path(kubeconfig).is_file(),'Jenkins kubeconfig credential required')
    return subprocess.run(['kubectl','--kubeconfig',kubeconfig,'--request-timeout=30s',*args],
                          text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=40)


def cluster(command, artifact, evidence, env):
    artifact,evidence=Path(artifact),Path(evidence)
    verify(artifact,env)  # before any kubectl, with no Git/source-policy fallback
    evidence.mkdir(parents=True,exist_ok=True)
    paths=[p for group in GROUPS for p in sorted((artifact/'policies'/group).glob('*.yaml'))]
    if command=='apply':
        with (evidence/'apply.txt').open('w') as log:
            for path in paths:
                result=kubectl('apply','-f',str(path))
                log.write(str(path)+'\n'+result.stdout+result.stderr); log.flush()
                require(result.returncode==0,f'Policy apply failed: {path.name}; see apply.txt')
        verify(artifact,env)
        return
    crds={}
    for kind,plural in KINDS.items():
        result=kubectl('get','crd',plural+'.policies.kyverno.io','-o','json')
        (evidence/(plural+'-crd.error.txt')).write_text(result.stderr)
        require(result.returncode==0,f'Cannot discover readiness schema: {kind}')
        crds[kind]=json.loads(result.stdout)
    (evidence/'crds.json').write_text(json.dumps(crds,indent=2)+'\n')
    resource_types=','.join(plural+'.policies.kyverno.io' for plural in KINDS.values())
    last=''
    for attempt in range(1,7):
        result=kubectl('get',resource_types,'-o','json')
        (evidence/f'live-{attempt}.json').write_text(result.stdout)
        (evidence/f'live-{attempt}.error.txt').write_text(result.stderr)
        require(result.returncode==0,'Cannot read deployed policies')
        try:
            report=check(json.loads(result.stdout),paths,crds)
            (evidence/'identity-readiness.json').write_text(json.dumps(report,indent=2)+'\n')
            verify(artifact,env)
            return
        except ValueError as error:
            last=str(error); (evidence/'verification-errors.txt').write_text(last+'\n')
            if attempt<6: time.sleep(5)
    raise ValueError(last)


if __name__=='__main__':
    try: cluster(*sys.argv[1:])
    except (ValueError,OSError,KeyError,StopIteration,subprocess.TimeoutExpired) as error:
        raise SystemExit(str(error))
