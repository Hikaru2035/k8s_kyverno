"""Offline GitOps publication contracts; no external services."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
import sys
import yaml
from test_delivery import artifact, ROOT
sys.path.insert(0, str(ROOT/'jenkins/scripts'))
import policy_artifact


class GitOpsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def module(self, name):
        self.assertTrue((ROOT/'jenkins/scripts'/f'{name}.py').exists(), f'Missing {name} helper')
        return __import__(name)

    def approved(self):
        out = self.root/'evidence'
        path = artifact(out)
        receipt = policy_artifact.verify(path, 'development')
        receipt.update(source_job='policy-ci', source_build=21)
        (out/'policy-artifact').mkdir()
        (out/'policy-artifact/provenance.json').write_text(json.dumps(receipt))
        return out, path

    def test_profiles_exact_bytes_and_downgrade(self):
        m = self.module('gitops_policy')
        out, artifact_path = self.approved()
        target = self.root/'desired'
        for profile, groups, count in [('baseline',2,13), ('standard',3,27), ('restricted',4,29), ('baseline',2,13)]:
            with self.subTest(profile=profile):
                result = m.promote(out, target, 'development', profile, 'policy-ci', '21')
                files = sorted(target.glob('*/*.yaml'))
                self.assertEqual(len(files), count)
                self.assertEqual({p.parent.name for p in files}, set(policy_artifact.GROUPS[:groups]))
                for p in files:
                    self.assertEqual(p.read_bytes(), (artifact_path/'policies'/p.relative_to(target)).read_bytes())
                self.assertEqual(yaml.safe_load((target/'kustomization.yaml').read_text())['resources'],
                                 sorted(str(p.relative_to(target)) for p in files))
                self.assertEqual(result['policy_count'], count)
                self.assertEqual(result['approved_artifact_sha256'], policy_artifact.verify(artifact_path,'development')['artifact_sha256'])

    def test_invalid_artifact_or_identity_never_changes_target(self):
        m = self.module('gitops_policy')
        out, path = self.approved()
        target = self.root/'desired'; target.mkdir()
        (target/'keep').write_text('unchanged')
        for job, build, profile in [('wrong','21','baseline'),('policy-ci','','baseline'),('policy-ci','21','invalid')]:
            with self.assertRaises((ValueError, OSError)):
                m.promote(out,target,'development',profile,job,build)
        next((path/'policies').glob('*/*.yaml')).write_text('tampered')
        with self.assertRaises(ValueError): m.promote(out,target,'development','baseline','policy-ci','21')
        shutil.rmtree(path)
        with self.assertRaises((ValueError, OSError)): m.promote(out,target,'development','baseline','policy-ci','21')
        self.assertEqual(list(target.iterdir()), [target/'keep'])
        self.assertNotIn('k8s-security-framework', (ROOT/'jenkins/scripts/gitops_policy.py').read_text())

    def test_app_only_changes_intended_scalar_and_rejects_tags(self):
        m = self.module('gitops_app')
        source = ROOT/'gitops/applications/demo-app/deployment.yaml'
        target = self.root/'deployment.yaml'; shutil.copyfile(source,target)
        before = target.read_bytes()
        reference = self.root/'reference.txt'
        old = yaml.safe_load(before)['spec']['template']['spec']['containers'][0]['image']
        for value in ['harbor-public:30003/ksp-test/demo-app:21', 'elsewhere/app@sha256:'+'a'*64,
                      'harbor-public:30003/ksp-test/demo-app@sha256:bad', 'harbor-public:30003/ksp-test/demo-app@sha256:'+'0'*64]:
            reference.write_text(value+'\n')
            with self.assertRaises(ValueError): m.update(reference,target)
            self.assertEqual(target.read_bytes(),before)
        value = 'harbor-public:30003/ksp-test/demo-app@sha256:'+'a'*64
        reference.write_text(value+'\n')
        m.update(reference,target)
        self.assertEqual(target.read_bytes(),before.replace(old.encode(),value.encode()))
        m.update(reference,target)
        target.write_bytes(before.replace(b'name: app\n',b'name: missing\n'))
        with self.assertRaises(ValueError): m.update(reference,target)

    def test_pipeline_boundaries_and_argo(self):
        delivery = (ROOT/'Jenkinsfile.delivery').read_text()
        script = (ROOT/'jenkins/scripts/delivery.sh').read_text()
        for text in (delivery, script):
            for forbidden in ('kubectl','KUBECONFIG','deploy-policies','verify-policies','PolicyReport','clusterStep'):
                self.assertNotIn(forbidden,text)
        promotion = ROOT/'Jenkinsfile.policy-promote'
        self.assertTrue(promotion.exists())
        for p in [promotion, ROOT/'Jenkinsfile.ci', ROOT/'Jenkinsfile.delivery']:
            self.assertNotIn('ClusterPolicyReport',p.read_text())
            self.assertNotIn("delivery('reports')",p.read_text())
        for name,path in [('policy','gitops/policies/development'),('demo-app','gitops/applications/demo-app')]:
            doc = yaml.safe_load((ROOT/f'gitops/argocd/{name}-application.yaml').read_text())
            self.assertEqual(doc['spec']['source']['path'],path)
            self.assertEqual(doc['spec']['destination']['server'],'https://kubernetes.default.svc')
            self.assertEqual(doc['spec']['syncPolicy']['automated'],{'prune':True,'selfHeal':True})
        labels = yaml.safe_load((ROOT/'gitops/applications/demo-app/namespace.yaml').read_text())['metadata']['labels']
        self.assertEqual(labels['ksp.io/environment'],'dev')
        self.assertEqual(labels['ksp.io/profile'],'baseline')
        self.assertFalse((ROOT/'demo-app/k8s').exists())


class PublisherTests(unittest.TestCase):
    def setUp(self):
        import subprocess
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.remote = self.base/'remote.git'
        self.work = self.base/'work'
        self.command('init','--bare',str(self.remote))
        self.command('clone',str(self.remote),str(self.work))
        self.command('-C',str(self.work),'checkout','-b','cicd/jenkins')
        shutil.copytree(ROOT/'gitops',self.work/'gitops')
        self.command('-C',str(self.work),'add','.')
        self.command('-C',str(self.work),'-c','user.name=Test','-c','user.email=test@localhost','commit','-m','seed')
        self.command('-C',str(self.work),'push','origin','HEAD')
        self.evidence = self.base/'evidence'

    def command(self,*args):
        import subprocess
        return subprocess.check_output(['git',*args],stderr=subprocess.DEVNULL,text=True).strip()

    def update(self,work):
        p=work/'gitops/applications/demo-app/deployment.yaml'
        p.write_text(p.read_text().replace('0'*64,'a'*64))

    def test_scoped_publication_and_noop(self):
        import gitops_publish as p
        self.update(self.work)
        p.publish(self.work,'app','cicd/jenkins',self.evidence,None)
        receipt=json.loads((self.evidence/'publication.json').read_text())
        self.assertTrue(receipt['changed'])
        self.assertEqual(receipt['commit'],self.command('--git-dir',str(self.remote),'rev-parse','refs/heads/cicd/jenkins'))
        p.publish(self.work,'app','cicd/jenkins',self.evidence,None)
        self.assertFalse(json.loads((self.evidence/'publication.json').read_text())['changed'])
        (self.work/'unrelated').write_text('must not commit')
        with self.assertRaisesRegex(ValueError,'Unrelated'): p.publish(self.work,'app','cicd/jenkins',self.evidence,None)

    def test_concurrent_publication_fails_without_overwrite(self):
        import gitops_publish as p
        other=self.base/'other'
        self.command('clone','--branch','cicd/jenkins',str(self.remote),str(other))
        self.update(other)
        p.publish(other,'app','cicd/jenkins',self.evidence,None)
        remote_head=self.command('--git-dir',str(self.remote),'rev-parse','refs/heads/cicd/jenkins')
        self.update(self.work)
        with self.assertRaisesRegex(ValueError,'push failed'):
            # Distinct commit prevents identical commit hashes within one second.
            f=self.work/'gitops/applications/demo-app/deployment.yaml'
            f.write_text(f.read_text().replace('a'*64,'b'*64))
            p.publish(self.work,'app','cicd/jenkins',self.base/'failed',None)
        self.assertEqual(json.loads((self.base/'failed/publication.json').read_text())['status'],'failed')
        self.assertTrue((self.base/'failed/change.diff').is_file())
        self.assertEqual(remote_head,self.command('--git-dir',str(self.remote),'rev-parse','refs/heads/cicd/jenkins'))

    def test_credentials_are_environment_only_and_not_logged(self):
        import os
        from unittest.mock import patch
        import subprocess
        import gitops_publish as p
        with patch.dict(os.environ,{'GITOPS_USERNAME':'fixture-user','GITOPS_PASSWORD':'fixture-token','GIT_TRACE':'1'}):
            with p.credentials() as env:
                helper=Path(env['GIT_ASKPASS'])
                self.assertNotIn('fixture-token',helper.read_text())
                self.assertNotIn('GIT_TRACE',env)
                self.assertEqual(subprocess.check_output([str(helper),'Password'],env=env,text=True).strip(),'fixture-token')
            self.assertFalse(helper.exists())
        for url in ('https://user:token@example.com/repo','http://example.com/repo','https://example.com/repo?token=x'):
            with self.assertRaises(ValueError): p.prepare(self.base/'bad',url,'main',None)


class AdditionalBoundaries(unittest.TestCase):
    def test_sidecar_image_and_comments_are_unchanged(self):
        import gitops_app
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); deployment=root/'deployment.yaml'; reference=root/'reference.txt'
            original=(ROOT/'gitops/applications/demo-app/deployment.yaml').read_text()
            old='harbor-public:30003/ksp-test/demo-app@sha256:'+'0'*64
            original += f'      - name: sidecar\n        image: {old}\n'
            original += f'# Keep this example image unchanged: {old}\n'
            deployment.write_text(original)
            new='harbor-public:30003/ksp-test/demo-app@sha256:'+'c'*64
            reference.write_text(new)
            gitops_app.update(reference,deployment)
            self.assertEqual(deployment.read_text(),original.replace('        image: '+old,'        image: '+new,1))
            deployment.write_text(original.replace('  name: demo-app\n','  name: other\n',1))
            with self.assertRaises(ValueError): gitops_app.update(reference,deployment)

    def test_no_pipeline_collects_reports_or_embeds_secrets(self):
        import re
        files=[ROOT/p for p in ('Jenkinsfile.ci','Jenkinsfile.delivery','Jenkinsfile.policy-promote',
                               'jenkins/scripts/delivery.sh','jenkins/scripts/policy-promote.sh','jenkins/scripts/gitops_publish.py')]
        for path in files:
            text=path.read_text()
            for forbidden in ('PolicyReport','ClusterPolicyReport','delivery-evidence.sh','delivery-reports.py',
                              'BEGIN PRIVATE KEY','BEGIN OPENSSH PRIVATE KEY'):
                self.assertNotIn(forbidden,text,str(path))
            self.assertIsNone(re.search(r'https?://[^\s/]+:[^\s/]+@',text),str(path))
            self.assertIsNone(re.search(r'(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}',text),str(path))
        for name in ('Jenkinsfile.delivery','Jenkinsfile.policy-promote'):
            self.assertIn("credentialsId: 'gitops-git-credentials'",(ROOT/name).read_text())

    def test_initial_policies_match_real_local_approved_inventory(self):
        # Bootstrap provenance is honest, and initial Kustomization excludes higher groups.
        desired=ROOT/'gitops/policies/development'
        paths=yaml.safe_load((desired/'kustomization.yaml').read_text())['resources']
        self.assertEqual(len(paths),13)
        self.assertEqual({p.split('/')[0] for p in paths},{'common','baseline'})
        provenance=json.loads((desired/'provenance.json').read_text())
        self.assertEqual(provenance['policy_profile'],'baseline')
        self.assertFalse(provenance['jenkins_origin_verified'])
        approved=ROOT/'artifacts/approved-policies-development'
        if approved.is_dir():
            self.assertEqual(provenance['approved_artifact_sha256'],policy_artifact.verify(approved,'development')['artifact_sha256'])
            for path in paths: self.assertEqual((desired/path).read_bytes(),(approved/'policies'/path).read_bytes())
