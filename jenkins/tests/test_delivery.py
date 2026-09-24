"""Offline Delivery regression tests. Kubernetes/Jenkins/registry calls use fixtures."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'jenkins/scripts'))


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'jenkins/scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def artifact(base, env='development'):
    dest = base / ('approved-policies-' + env)
    shutil.copytree(ROOT / 'k8s-security-framework/tests/e2e_env' / env / 'policies', dest / 'policies')
    inventory = ''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+str(p.relative_to(dest/'policies'))+'\n'
                        for p in sorted((dest/'policies').rglob('*.yaml')))
    (dest/'policy-inventory.txt').write_text(inventory)
    counts = dict(expected_policies=29, accounted_policies=29, canonical_cases=383,
                  environment_regression_cases=0, executed=376, not_applicable=0, deferred=7, failed=0,
                  configuration_assertions=128, runtime_e2e_owned_by_delivery=18)
    meta = dict(git_commit='a'*40, environment=env, framework_version='0.1.0', policy_count=29,
                policy_inventory_sha256=hashlib.sha256(inventory.encode()).hexdigest(),
                test_evidence_sha256='b'*64, approval_mode='poc', **counts,
                deferred_policy='KSP-IMG-004', deferred_reason='external-registry-signature-verification-deferred-for-poc')
    (dest/'metadata.txt').write_text(''.join(f'{k}={v}\n' for k,v in meta.items()))
    (dest/'test-coverage-summary.txt').write_text(f'environment={env}\n'+''.join(f'{k}={v}\n' for k,v in counts.items()))
    return dest


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.path = artifact(self.base)

    def test_delivery_artifact_verifier_exists(self):
        self.assertTrue((ROOT/'jenkins/scripts/policy_artifact.py').is_file(), 'Delivery must verify archived artifacts')

    def test_environment_integrity_and_deferrals(self):
        import policy_artifact as a
        data = a.verify(self.path, 'development')
        self.assertEqual(data['policy_count'], 29)
        self.assertEqual(data['environment'], 'development')
        self.assertEqual(data['deferrals']['reason'], 'external-registry-signature-verification-deferred-for-poc')
        for env in ('staging','production','dev','../development'):
            with self.assertRaises(ValueError): a.verify(self.path, env)

    def test_changed_missing_extra_symlink_and_bad_metadata_fail(self):
        import policy_artifact as a
        for scenario in ('changed','missing','extra','symlink','metadata','aggregate','duplicate-key','extra-dir'):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temp:
                path=artifact(Path(temp)); policy=next((path/'policies').rglob('*.yaml'))
                if scenario=='changed': policy.write_bytes(policy.read_bytes()+b'\n')
                elif scenario=='missing': policy.unlink()
                elif scenario=='extra': (path/'policies/common/extra.yaml').write_bytes(policy.read_bytes())
                elif scenario=='symlink':
                    original=policy.read_bytes(); policy.unlink(); external=Path(temp)/'external'; external.write_bytes(original); policy.symlink_to(external)
                elif scenario=='metadata':
                    p=path/'metadata.txt'; p.write_text(p.read_text().replace('policy_count=29','policy_count=28'))
                elif scenario=='aggregate':
                    p=path/'policy-inventory.txt'; p.write_text(p.read_text()+'\n')
                elif scenario=='duplicate-key':
                    p=path/'metadata.txt'; p.write_text(p.read_text()+'environment=development\n')
                else: (path/'unapproved').mkdir()
                with self.assertRaises(ValueError): a.verify(path,'development')

    def test_authenticated_fetch_uses_successful_build_archives_only(self):
        import policy_artifact as a
        prefix='artifacts/approved-policies-development/'
        files={prefix+str(p.relative_to(self.path)):p.read_bytes() for p in self.path.rglob('*') if p.is_file()}
        info=dict(number=21,result='SUCCESS',building=False,artifacts=[dict(relativePath=p) for p in files])
        requests=[]
        def get(url):
            requests.append(url)
            if '/api/json?' in url: return json.dumps(info).encode()
            return files[url.split('/artifact/',1)[1]]
        out=self.base/'delivery'; out.mkdir()
        with patch.object(a, 'authenticated_get', side_effect=get):
            a.fetch(out, 'development', 'automated-tested', '21', 'https://jenkins.example/')
        self.assertTrue((out/'approved-policies-development/policies').is_dir())
        self.assertTrue(all('/job/automated-tested/21/' in u for u in requests))
        self.assertFalse(any('workspace' in u for u in requests))
        provenance=json.loads((out/'policy-artifact/provenance.json').read_text())
        self.assertEqual(provenance['source_build'],21)
        info['result']='FAILURE'
        with patch.object(a,'authenticated_get',side_effect=get), self.assertRaises(ValueError):
            a.fetch(self.base/'bad','development','automated-tested','21','https://jenkins.example/')

    def test_live_policy_identity_spec_and_real_readiness_shape(self):
        live=load('live-policies')
        paths=sorted((self.path/'policies').glob('*/*.yaml'))
        objects=[yaml.safe_load(p.read_text()) for p in paths]
        for obj in objects: obj['status']={'conditionStatus':{'ready':True}}
        live.check({'items':objects},paths)
        with self.assertRaises(ValueError): live.check({'items':objects[1:]},paths)
        bad=copy.deepcopy(objects); bad[0]['status']['conditionStatus']['ready']=False
        with self.assertRaises(ValueError): live.check({'items':bad},paths)
        bad=copy.deepcopy(objects); bad[0]['spec']['validationActions']=['Deny']
        with self.assertRaises(ValueError): live.check({'items':bad},paths)

    def test_only_demo_manifests_render_and_environment_label_is_selected(self):
        manifests=load('manifests')
        before={p:p.read_bytes() for p in (ROOT/'demo-app/k8s').glob('*.yaml')}
        for env,label in [('development','dev'),('staging','staging'),('production','production')]:
            target=self.base/env
            manifests.delivery('harbor-public:30003/ksp-test/demo-app@sha256:'+'a'*64,str(target),env)
            self.assertEqual({p.name for p in target.iterdir()}, {'namespace.yaml','deployment.yaml','service.yaml','networkpolicy.yaml','pod.yaml'})
            self.assertEqual(yaml.safe_load((target/'namespace.yaml').read_text())['metadata']['labels']['ksp.io/environment'],label)
        self.assertTrue(all(p.read_bytes()==content for p,content in before.items()))



class DeliveryFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        shutil.copytree(ROOT/'jenkins/scripts',self.root/'jenkins/scripts')
        shutil.copytree(ROOT/'demo-app',self.root/'demo-app')
        shutil.copyfile(ROOT/'versions.yaml',self.root/'versions.yaml')
        (self.root/'image-security/cosign').mkdir(parents=True)
        shutil.copyfile(ROOT/'image-security/cosign/cosign.pub',self.root/'image-security/cosign/cosign.pub')
        self.out=self.root/'artifacts/delivery/51'; self.out.mkdir(parents=True)
        self.artifact=artifact(self.out)
        import policy_artifact as a
        provenance=a.verify(self.artifact,'development'); provenance.update(source_job='automated-tested',source_build=21)
        (self.out/'policy-artifact').mkdir()
        (self.out/'policy-artifact/provenance.json').write_text(json.dumps(provenance))
        self.kube=self.root/'credential-kubeconfig'; self.kube.write_text('offline-fixture-only')
        self.bin=self.root/'bin'; self.bin.mkdir()
        fake=self.bin/'fake'
        fake.write_text(r'''#!/usr/bin/env python3
import io,json,os,sys,tarfile
from pathlib import Path
import yaml
root=Path(os.environ['TEST_ROOT']); name=Path(sys.argv[0]).name; args=sys.argv[1:]
with (root/'calls.jsonl').open('a') as f: f.write(json.dumps([name,*args])+'\n')
sha='sha256:'+'a'*64
ref='harbor-public:30003/ksp-test/demo-app@'+sha
if name=='kubectl':
 assert args[:2]==['--kubeconfig',str(root/'credential-kubeconfig')],args
 args=args[2:];args=[a for a in args if not a.startswith('--request-timeout=')]
 if args[:2]==['config','current-context']: print('existing-kubeadm');sys.exit()
 if args[:2]==['config','view']: print('https://existing-kubeadm:6443');sys.exit()
 if args[0]=='apply': print('resource configured');sys.exit(1 if os.environ.get('FAIL_APPLY') else 0)
 if args[0]=='create': print('apiVersion: v1\nkind: Pod\nmetadata: {name: demo-app-preflight}');sys.exit()
 if '-n' in args: i=args.index('-n');args=args[:i]+args[i+2:]
 if args[0] in ('rollout','wait'): print('ready');sys.exit()
 if args[1]=='crd':
  plural=args[2].split('.')[0]
  print(json.dumps({'spec':{'versions':[{'name':'v1','served':True,'schema':{'openAPIV3Schema':{'properties':{'status':{'properties':{'conditionStatus':{'properties':{'ready':{'type':'boolean'}}}}}}}}}]}}));sys.exit()
 if '.policies.kyverno.io' in args[1]:
  items=[]
  for p in (root/'artifacts/delivery/51/approved-policies-development/policies').glob('*/*.yaml'):
   obj=yaml.safe_load(p.read_text());obj['status']={'conditionStatus':{'ready':True}};items.append(obj)
  print(json.dumps({'items':items}));sys.exit()
 if args[1]=='namespace':
  if args[2]=='kube-system': print('cluster-uid');sys.exit()
  print(json.dumps({'kind':'Namespace','metadata':{'name':'ksp-demo'}}));sys.exit()
 deployment={'metadata':{'name':'demo-app','uid':'deployment-uid','generation':1,'labels':{'app.kubernetes.io/name':'demo-app'}},'spec':{'replicas':1},'status':{'observedGeneration':1,'availableReplicas':1,'updatedReplicas':1}}
 pod={'metadata':{'name':'demo-app-pod','uid':'pod-uid','labels':{'app.kubernetes.io/name':'demo-app'}},'spec':{'containers':[{'image':ref}]},'status':{'containerStatuses':[{'ready':True}],'conditions':[{'type':'Ready','status':'True'}]}}
 report={'metadata':{'name':'admission-report'},'scope':{'uid':'pod-uid'},'results':[{'policy':'approved-registry-allowlist','result':'fail'}]}
 value={'deployment':deployment,'deployments':{'items':[deployment]},'pods':{'items':[pod]},'service':{'metadata':{'name':'demo-app'}},'endpointslices':{'items':[{'endpoints':[{'conditions':{'ready':True},'addresses':['10.0.0.1']}]}]},'policyreports':{'items':[report]}}
 print(json.dumps(value.get(args[1],{'items':[]})));sys.exit()
if name=='crane':
 if args[0]=='digest': print(sha)
 elif args[0]=='manifest': print('{}')
 elif args[0]=='mutate':
  dest=Path(args[args.index('--output')+1]); layer=Path(args[args.index('--append')+1]).read_bytes()
  config=json.dumps({'config':{'Cmd':['python3','/app/app.py'],'User':'65532:65532','WorkingDir':'/app'}}).encode()
  manifest=json.dumps([{'Config':'config.json','RepoTags':['test'],'Layers':['layer.tar']}]).encode()
  with tarfile.open(dest,'w') as tar:
   for n,b in [('config.json',config),('manifest.json',manifest),('layer.tar',layer)]:
    h=tarfile.TarInfo(n);h.size=len(b);tar.addfile(h,io.BytesIO(b))
 sys.exit()
if name=='trivy': Path(args[args.index('--output')+1]).write_text('{}');sys.exit()
if name=='cosign':
 if args[0]=='public-key': print((root/'image-security/cosign/cosign.pub').read_text(),end='')
 else: print('{}')
 sys.exit()
raise SystemExit('Unexpected external tool')
''')
        fake.chmod(0o755)
        for name in ('kubectl','crane','trivy','cosign'): (self.bin/name).symlink_to(fake)
        self.env=dict(os.environ,PATH=str(self.bin)+':'+os.environ['PATH'],TEST_ROOT=str(self.root),
                      BUILD_ID='51',BUILD_NUMBER='51',POLICY_CI_JOB='automated-tested',POLICY_CI_BUILD='21',
                      POLICY_ENVIRONMENT='development',KUBECONFIG=str(self.kube),COSIGN_KEY=str(self.root/'fake-key'),COSIGN_PASSWORD='fixture')

    def run_stage(self,stage,success=True,**env):
        run=subprocess.run(['bash',str(self.root/'jenkins/scripts/delivery.sh'),stage],cwd=self.root,
                           env=dict(self.env,**env),capture_output=True,text=True)
        if success: self.assertEqual(run.returncode,0,stage+'\n'+run.stdout+'\n'+run.stderr)
        else: self.assertNotEqual(run.returncode,0)
        return run

    def test_complete_offline_flow_uses_artifact_kubeconfig_and_local_archive(self):
        for stage in ('security-scan','build','image-scan','push','digest','sign','verify','policy-verify',
                      'deploy-policies','verify-policies','render','admission','rollout','reports','health'):
            self.run_stage(stage)
        calls=[json.loads(line) for line in (self.root/'calls.jsonl').read_text().splitlines()]
        policy_applies=[c for c in calls if c[0]=='kubectl' and 'apply' in c and '/policies/' in ' '.join(c)]
        self.assertEqual(len(policy_applies),29)
        paths=[c[c.index('-f')+1] for c in policy_applies]
        self.assertTrue(all(p.startswith(str(self.artifact/'policies')) for p in paths))
        self.assertIn('/common/',paths[0])
        self.assertEqual(json.loads((self.out/'kyverno/approved-policies/identity-readiness.json').read_text())['actual_count'],29)
        summary=json.loads((self.out/'policy-report/summary.json').read_text())
        self.assertEqual(summary['enforcedFailures'],0)
        self.assertEqual(summary['results'][0]['validationActions'],['Audit','Warn'])
        self.assertEqual({p.name for p in (self.out/'deployment/rendered').iterdir()},
                         {'namespace.yaml','deployment.yaml','service.yaml','networkpolicy.yaml','pod.yaml'})
        self.assertTrue((self.out/'image/image.tar').is_file())
        mutate=next(c for c in calls if c[:2]==['crane','mutate'])
        self.assertIn('--output',mutate);self.assertIn('--append',mutate)
        self.assertFalse((self.root/'k8s-security-framework').exists())  # No Git-policy or renderer dependency.

    def test_changed_artifact_blocks_all_kubectl(self):
        p=next((self.artifact/'policies').rglob('*.yaml'));p.write_bytes(p.read_bytes()+b'\n')
        self.run_stage('deploy-policies',False)
        self.assertFalse((self.root/'calls.jsonl').exists())

    def test_kubeconfig_is_mandatory_and_apply_failure_stops(self):
        self.run_stage('deploy-policies',False,KUBECONFIG='')
        self.assertFalse((self.root/'calls.jsonl').exists())
        self.run_stage('deploy-policies',False,FAIL_APPLY='yes')
        calls=[json.loads(x) for x in (self.root/'calls.jsonl').read_text().splitlines()]
        self.assertEqual(sum('apply' in c for c in calls),1)

    def test_report_actions_and_absence_are_not_synthetic_compliance(self):
        module=load('delivery-reports')
        objects=[{'metadata':{'uid':'u','labels':{'app.kubernetes.io/name':'demo-app'}}}]
        reports=[{'metadata':{'name':'r'},'scope':{'uid':'u'},'results':[{'policy':'p','result':'fail'}]}]
        for actions,want in [(['Audit','Warn'],0),(['Deny'],1)]:
            policies=[{'metadata':{'name':'p'},'spec':{'validationActions':actions}}]
            self.assertEqual(module.summarize(objects,reports,policies)['enforcedFailures'],want)
        self.assertEqual(module.summarize(objects,[],[])['observation'],'not-observed-within-bounded-wait')

    def test_readiness_absent_only_when_crd_does_not_expose_it(self):
        live=load('live-policies')
        actual={'metadata':{},'status':{}}
        self.assertEqual(live.readiness(actual,{'properties':{}}),'not-exposed-by-crd')
        schema={'properties':{'status':{'properties':{'conditionStatus':{'properties':{'ready':{'type':'boolean'}}}}}}}
        with self.assertRaises(ValueError):live.readiness(actual,schema)

    def test_application_layer_is_deterministic_and_nonroot(self):
        import tarfile
        builder=load('build-demo-image')
        a=self.root/'a.tar';b=self.root/'b.tar'
        source=self.root/'demo-app/src/app.py'
        builder.application_layer(source,a);builder.application_layer(source,b)
        self.assertEqual(a.read_bytes(),b.read_bytes())
        with tarfile.open(a) as tar:
            self.assertEqual(tar.getmember('app/app.py').uid,65532)
            self.assertEqual(tar.extractfile('app/app.py').read(),source.read_bytes())

class VerificationBoundaryTests(unittest.TestCase):
    def test_additional_nondefault_live_fields_cannot_weaken_signature_checks(self):
        live=load('live-policies')
        with tempfile.TemporaryDirectory() as temp:
            path=artifact(Path(temp))
            policy=next((path/'policies').rglob('KSP-IMG-004-*.yaml'))
            desired=yaml.safe_load(policy.read_text())
            actual=copy.deepcopy(desired);actual['status']={'conditionStatus':{'ready':True}}
            config={'default':{},'properties':{key:{'default':True} for key in ('required','verifyDigest','mutateDigest')}}
            schema={'properties':{'spec':{'properties':{'validationConfigurations':config}},
                                  'status':{'properties':{'conditionStatus':{'properties':{'ready':{'type':'boolean'}}}}}}}
            crds={'ImageValidatingPolicy':{'spec':{'versions':[{'name':'v1','served':True,'schema':{'openAPIV3Schema':schema}}]}}}
            actual['spec']['validationConfigurations']={'required':True,'verifyDigest':True,'mutateDigest':True}
            live.check({'items':[actual]},[policy],crds)
            actual['spec']['validationConfigurations']['required']=False
            with self.assertRaises(ValueError):live.check({'items':[actual]},[policy],crds)


if __name__ == '__main__':
    unittest.main()
