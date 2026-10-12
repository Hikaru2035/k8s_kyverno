#!/usr/bin/env python3
"""Remove historical checked-in evidence only in a fresh Jenkins job checkout."""
import os
from pathlib import Path
import shutil
import sys

root = Path.cwd().resolve()
if root != Path(os.environ['WORKSPACE']).resolve() or not os.environ.get('JENKINS_URL'):
    raise SystemExit('Only run inside a fresh Jenkins workspace after checkout')
if sys.argv[1] == 'framework':
    names = ['validate', 'check-policy', 'cli-unit', 'rendered-policy-test',
             'integration-kind', 'report', 'e2e']
else:
    names = ['delivery']
for name in names:
    path = root / 'artifacts' / name
    if path.is_symlink():
        raise SystemExit(f'Refusing symlink {path}')
    if path.exists():
        shutil.rmtree(path)
