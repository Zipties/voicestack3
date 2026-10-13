"""Dispatch and verify the scoped GHCR latest workflow using agents-vault auth."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

BASE='https://api.github.com/repos/Zipties/voicestack3'
WORKFLOW='publish-worker-latest.yml'
IMAGE='ghcr.io/zipties/voicestack3-worker'

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--revision',required=True)
    p.add_argument('--output',required=True)
    args=p.parse_args()
    token=os.environ.pop('GH_TOKEN')
    def api(path,body=None):
        req=urllib.request.Request(BASE+path, data=json.dumps(body).encode() if body is not None else None, headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','Content-Type':'application/json','X-GitHub-Api-Version':'2022-11-28'})
        with urllib.request.urlopen(req,timeout=30) as response:
            data=response.read()
            return json.loads(data) if data else None
    def persist(data):
        path=Path(args.output)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(data,indent=2))
    assert api('/commits/master')['sha']==args.revision
    api('/actions/workflows/'+WORKFLOW+'/dispatches',{'ref':'master'})
    print('Dispatched scoped CUDA worker publication',flush=True)
    run=None
    for attempt in range(12):
        runs=api('/actions/workflows/'+WORKFLOW+'/runs?event=workflow_dispatch&per_page=10')['workflow_runs']
        matches=[x for x in runs if x['head_sha']==args.revision]
        if matches:
            run=matches[0]
            break
        time.sleep(10)
    if run is None: raise RuntimeError('Workflow dispatch did not produce a visible run')
    evidence={'workflow_run_id':run['id'],'workflow_url':run['html_url'],'source_revision':args.revision,'status':run['status'],'registry_image':IMAGE+':latest'}
    persist(evidence)
    print('Workflow:',run['html_url'],flush=True)
    previous=None
    deadline=time.monotonic()+7200
    while time.monotonic()<deadline:
        run=api('/actions/runs/'+str(run['id']))
        if run['status']!=previous:
            previous=run['status']
            print('Workflow status:',previous,flush=True)
        evidence.update(status=run['status'],conclusion=run['conclusion'])
        persist(evidence)
        if run['status']=='completed':
            if run['conclusion']!='success':
                jobs=api('/actions/runs/'+str(run['id'])+'/jobs')['jobs']
                evidence['failed_steps']=[{'job':j['name'],'step':s['name'],'conclusion':s['conclusion']} for j in jobs for s in j['steps'] if s.get('conclusion')=='failure']
                persist(evidence)
                raise RuntimeError('Publication workflow failed: '+json.dumps(evidence['failed_steps']))
            break
        time.sleep(30)
    else: raise TimeoutError('Publication workflow still running; persisted run ID supports recovery')
    def inspect(ref,config=False):
        command=['skopeo','inspect']+(['--config'] if config else [])+['docker://'+ref]
        return json.loads(subprocess.check_output(command,text=True,timeout=120))
    latest=inspect(IMAGE+':latest')
    pinned=inspect(IMAGE+':sha-'+args.revision)
    cfg=inspect(IMAGE+':latest',True)['config']
    assert latest['Digest']==pinned['Digest']
    assert cfg['Labels']['org.opencontainers.image.revision']==args.revision
    assert latest['Architecture']=='amd64' and latest['Os']=='linux'
    env=dict(e.split('=',1) for e in cfg.get('Env',[]))
    assert env['DIARIZATION_BACKEND']=='nemotron'
    assert not any(any(n in key.upper() for n in ('TOKEN','PASSWORD','SECRET','API_KEY')) for key in env)
    evidence.update(remote_manifest_digest=latest['Digest'],immutable_image=IMAGE+':sha-'+args.revision,remote_config_credential_free=True,remote_default_backend=env['DIARIZATION_BACKEND'],platform='linux/amd64')
    persist(evidence)
    print(json.dumps(evidence,indent=2),flush=True)

if __name__=='__main__': main()
