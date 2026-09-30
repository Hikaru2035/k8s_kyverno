#!/usr/bin/env python3
"""Same authenticated /v2/ gate as GitLab, with system TLS verification."""
import base64
import os
import urllib.request

auth = base64.b64encode((os.environ['HARBOR_USERNAME'] + ':' + os.environ['HARBOR_PASSWORD']).encode()).decode()
request = urllib.request.Request('https://harbor-public:30003/v2/', headers={'Authorization': 'Basic ' + auth})
with urllib.request.urlopen(request, timeout=30) as response:
    print('Harbor HTTP status:', response.status)
    if response.status != 200:
        raise SystemExit(1)
