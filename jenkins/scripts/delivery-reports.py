#!/usr/bin/env python3
"""Bounded report observation; Audit/Warn findings are evidence, not denials."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import yaml
from policy_artifact import require, verify


def summarize(objects, reports, policies):
    uids={x['metadata']['uid'] for x in objects if x['metadata'].get('labels',{}).get('app.kubernetes.io/name')=='demo-app'}
    actions={p['metadata']['name']:p['spec'].get('validationActions',[]) for p in policies}
    related=[]
    for report in reports:
        for result in report.get('results',[]):
            refs=result.get('resources',[])+[report.get('scope',{})]
            if any(ref.get('uid') in uids for ref in refs):
                policy=result.get('policy','').rsplit('/',1)[-1]
                related.append(dict(result, report=report['metadata']['name'],
                    approvedPolicy=policy in actions, validationActions=actions.get(policy,[])))
    denied=[r for r in related if r.get('result') in ('fail','error') and 'Deny' in r['validationActions']]
    return dict(applicationUIDs=sorted(uids),results=related,enforcedFailures=len(denied),
        observation='observed' if related else 'not-observed-within-bounded-wait',
        note='Reports are asynchronous. Missing results do not prove compliance. Audit/Warn findings are not admission denials; Policy CI signature deferrals remain in provenance.')


def collect(out, artifact, env):
    out,artifact=Path(out),Path(artifact); verify(artifact,env)
    kubeconfig=os.environ.get('KUBECONFIG','')
    require(kubeconfig and Path(kubeconfig).is_file(),'Jenkins kubeconfig credential required')
    for part in ('deployment','policy-report'): (out/part).mkdir(parents=True,exist_ok=True)
    def get(args,path):
        result=subprocess.run(['kubectl','--kubeconfig',kubeconfig,'--request-timeout=15s',*args,'-o','json'],
                              text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20)
        path.write_text(result.stdout); path.with_suffix('.error.txt').write_text(result.stderr)
        if result.returncode: return None
        return json.loads(result.stdout)
    objects=[]; errors=[]
    for kind in ('deployments','replicasets','pods','services','endpointslices','events'):
        data=get(['-n','ksp-demo','get',kind],out/'deployment'/f'{kind}.json')
        if data is None: errors.append(kind)
        elif kind in ('deployments','replicasets','pods'): objects.extend(data['items'])
    policies=[yaml.safe_load(p.read_text()) for p in (artifact/'policies').glob('*/*.yaml')]
    summary=None
    for attempt in range(1,7):
        reports=[]
        for name,args in (('namespaced',['-n','ksp-demo','get','policyreports']),('cluster',['get','clusterpolicyreports'])):
            path=out/'policy-report'/f'{name}-{attempt}.json'; data=get(args,path)
            (out/'policy-report'/f'{name}.json').write_bytes(path.read_bytes())
            if data is None: errors.append(name)
            else: reports.extend(data['items'])
        summary=summarize(objects,reports,policies); summary['attempts']=attempt
        if errors or summary['results'] or attempt==6: break
        time.sleep(5)
    summary['collectionErrors']=errors
    (out/'policy-report/summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    status=int(bool(errors or summary['enforcedFailures']))
    (out/'policy-report/collection-status.txt').write_text(str(status)+'\n')
    require(not status,'PolicyReport collection/enforced policy findings failed; see summary.json')


if __name__=='__main__':
    try: collect(*sys.argv[1:])
    except (ValueError,OSError,KeyError,subprocess.TimeoutExpired) as error: raise SystemExit(str(error))
