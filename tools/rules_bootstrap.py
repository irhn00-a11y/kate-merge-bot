#!/usr/bin/env python3
"""Small pinned loader; canonical policy and runtime live in private office.
This file contains no repository-private rules or credentials.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen

def fetch_runtime(config):
    sha=config['runtime_commit']
    if config['central_repository']!='irhn00-a11y/office' or not re.fullmatch('[0-9a-f]{40}',sha):
        raise ValueError('invalid runtime source')
    expected=config['runtime_sha256']
    if not re.fullmatch('[0-9a-f]{64}',expected):
        raise ValueError('invalid runtime hash')
    endpoint=f'repos/irhn00-a11y/office/contents/tools/rules_runtime.py?ref={sha}'
    token=os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    if token:
        req=Request('https://api.github.com/'+endpoint,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','User-Agent':'ai-office-bootstrap'})
        with urlopen(req,timeout=15) as response: obj=json.load(response)
    else:
        p=subprocess.run(['gh','api',endpoint],capture_output=True,timeout=20)
        if p.returncode: raise OSError('runtime inaccessible')
        obj=json.loads(p.stdout)
    if obj.get('encoding')!='base64':raise ValueError('encoding')
    code=base64.b64decode(obj['content'])
    if hashlib.sha256(code).hexdigest()!=expected:raise ValueError('runtime hash mismatch')
    return code

def main():
    hook='--hook' in sys.argv
    try:
        root=Path(__file__).resolve().parents[1]
        config=json.loads((root/'.governance/entry.json').read_text())
        code=fetch_runtime(config)
        with tempfile.TemporaryDirectory(prefix='ai-office-rules-') as temp:
            runtime=Path(temp)/'rules_runtime.py';runtime.write_bytes(code)
            args=[sys.executable,str(runtime),'session','--repo',config['repository'],'--central-ref',config['central_ref'],*sys.argv[1:]]
            result=subprocess.run(args,timeout=110)
            return result.returncode
    except (OSError,ValueError,KeyError,subprocess.SubprocessError):
        msg='UNKNOWN: governance runtime/config unavailable or integrity mismatch. No rules-loaded claim. HOLD writes, merges, notifications and other risky actions; use authenticated connector to read required rules.'
        if hook:
            print(json.dumps({'hookSpecificOutput':{'hookEventName':'SessionStart','additionalContext':msg}}))
        else:print(msg,file=sys.stderr)
        return 0 if hook else 1

if __name__=='__main__':raise SystemExit(main())
