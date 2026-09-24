#!/usr/bin/env python3
"""Isolated, scope-limited Git publication. Non-fast-forward pushes fail; never force."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlsplit
from policy_artifact import require

SCOPES = {'app':'gitops/applications/demo-app/deployment.yaml', 'policy':'gitops/policies/development'}


def git(root, *args, env=None):
    result = subprocess.run(['git','-C',str(root),*args],env=env,text=True,capture_output=True)
    # Never relay remote error text: it can contain credentials or HTTP headers.
    require(result.returncode == 0, f'Git {args[0]} failed; check access, branch, or concurrent publication')
    return result.stdout.strip()


@contextmanager
def credentials():
    require(os.environ.get('GITOPS_USERNAME') and os.environ.get('GITOPS_PASSWORD'), 'GitOps credentials required')
    with tempfile.TemporaryDirectory(prefix='gitops-auth-') as temp:
        askpass = Path(temp)/'askpass'
        askpass.write_text('#!/bin/sh\ncase "$1" in\n *Username*) printf "%s\\n" "$GITOPS_USERNAME" ;;\n *Password*) printf "%s\\n" "$GITOPS_PASSWORD" ;;\n *) exit 1 ;;\nesac\n')
        askpass.chmod(0o700)
        env = dict(os.environ,GIT_ASKPASS=str(askpass),GIT_TERMINAL_PROMPT='0',
                   GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='credential.helper',GIT_CONFIG_VALUE_0='')
        for key in list(env):
            if key.startswith(('GIT_TRACE','GIT_CURL_VERBOSE')): env.pop(key)
        yield env


def prepare(root, repo, branch, env):
    url = urlsplit(repo)
    require(url.scheme == 'https' and url.hostname and not url.username and not url.password
            and not url.query and not url.fragment, 'Use a credential-free HTTPS GitOps repository URL')
    require(not branch.startswith('-'), 'Invalid GitOps branch')
    git(Path.cwd(),'check-ref-format','--branch',branch)
    root = Path(root)
    require(not root.exists(), 'GitOps checkout must be fresh')
    git(Path.cwd(),'clone','--single-branch','--branch',branch,'--',repo,str(root),env=env)


def publish(root, mode, branch, evidence, env):
    root, evidence = Path(root), Path(evidence)
    scope = SCOPES[mode]
    require(git(root,'branch','--show-current') == branch, 'Unexpected GitOps branch')
    require(not git(root,'diff','--cached','--name-only'), 'Unexpected staged changes')
    changed = set(git(root,'diff','--name-only').splitlines()) | set(git(root,'ls-files','--others','--exclude-standard').splitlines())
    require(all(p == scope or (mode=='policy' and p.startswith(scope+'/')) for p in changed), 'Unrelated GitOps changes')
    require(not any(p.is_symlink() for p in (root/'gitops').rglob('*')), 'Symlink GitOps files')
    before = git(root,'rev-parse','HEAD')
    diff = git(root,'diff','--',scope)
    evidence.mkdir(parents=True,exist_ok=True)
    receipt = dict(before=before,branch=branch,scope=scope,changed=bool(changed),status='no-change')
    try:
        if changed:
            git(root,'add','--',scope)
            git(root,'diff','--cached','--check')
            diff = git(root,'diff','--cached','--',scope)
            git(root,'-c','user.name=Jenkins GitOps','-c','user.email=jenkins-gitops@localhost',
                'commit','-m',f'chore(gitops): publish {mode} desired state [skip ci]')
            receipt['commit'] = git(root,'rev-parse','HEAD')
            git(root,'push','origin',f'HEAD:refs/heads/{branch}',env=env)
            receipt['status'] = 'published'
        else:
            receipt['commit'] = before
    except (ValueError,OSError):
        receipt['status'] = 'failed'
        raise
    finally:
        (evidence/'change.diff').write_text(diff+'\n')
        (evidence/'publication.json').write_text(json.dumps(receipt,indent=2)+'\n')



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('prepare','publish'))
    parser.add_argument('mode',choices=SCOPES)
    parser.add_argument('evidence')
    args = parser.parse_args()
    try:
        root = Path(os.environ.get('GITOPS_CHECKOUT','.gitops-publish')).absolute()
        repo = os.environ.get('GITOPS_REPOSITORY','https://github.com/Hikaru2035/k8s_kyverno.git')
        branch = os.environ.get('GITOPS_BRANCH','cicd/jenkins')
        with credentials() as env:
            if args.command == 'prepare': prepare(root,repo,branch,env)
            else: publish(root,args.mode,branch,args.evidence,env)
    except (ValueError,OSError,KeyError) as error:
        raise SystemExit(f'GitOps publication rejected: {error}')
