"""Publish the qualified worker without inherited credential-bearing metadata.

GH_TOKEN must be injected by the agents-vault wrapper. No secret values are
printed, put in arguments, or retained. Temporary registry auth is removed.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import urllib.request
import uuid

REGISTRY_IMAGE = 'ghcr.io/zipties/voicestack3-worker'
SECRET_NAMES = ('TOKEN','PASSWORD','SECRET','API_KEY')

SCAN = r'''import os,stat,json
secrets=[v.encode() for k,v in os.environ.items() if any(n in k.upper() for n in ('TOKEN','PASSWORD','SECRET','API_KEY')) and len(v)>8]
if not secrets: raise RuntimeError('Expected source image credential for literal scan')
hits=[];count=0
for root,dirs,files in os.walk('/',topdown=True):
 if root=='/': dirs[:]=[d for d in dirs if d not in ('proc','sys','dev','data')]
 for name in files:
  path=os.path.join(root,name)
  try:
   if not stat.S_ISREG(os.stat(path,follow_symlinks=False).st_mode): continue
   count+=1
   with open(path,'rb') as f:
    tail=b''
    while True:
     chunk=f.read(2**20)
     if not chunk: break
     payload=tail+chunk
     if any(secret in payload for secret in secrets): hits.append(path);break
     tail=payload[-max(map(len,secrets)):]
  except (PermissionError,FileNotFoundError): continue
print(json.dumps({'regular_files_scanned':count,'credential_literal_paths':hits}))
if hits: raise SystemExit(2)
'''

def call(argv, **kwargs):
    r=subprocess.run(argv,text=True,capture_output=True,**kwargs)
    if r.returncode:
        raise RuntimeError('Command failed: '+argv[0]+' '+argv[1]+' (exit '+str(r.returncode)+')')
    return r.stdout

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source',default='localhost/vs3-worker:nemotron-candidate')
    p.add_argument('--revision',required=True)
    p.add_argument('--output',required=True)
    args=p.parse_args()
    token=os.environ.pop('GH_TOKEN')
    req=urllib.request.Request('https://api.github.com/user',headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(req,timeout=30) as r:
        reported_scopes=r.headers.get('X-OAuth-Scopes')
        username=json.load(r)['login']
    if reported_scopes is not None and 'write:packages' not in [x.strip() for x in reported_scopes.split(',')]:
        raise RuntimeError('Agent token lacks write:packages; publish through GitHub Actions instead')
    print('Authenticated GitHub publisher:',username,flush=True)
    original=json.loads(call(['podman','image','inspect',args.source]))[0]
    cfg=original['Config']
    stripped=[e.split('=',1)[0] for e in cfg.get('Env',[]) if any(n in e.split('=',1)[0].upper() for n in SECRET_NAMES)]
    print('Dropping credential ENV names:',stripped,flush=True)
    scan=json.loads(call(['podman','run','--rm','--network','none','--entrypoint','python',args.source,'-c',SCAN]))
    print('Credential-literal rootfs scan:',scan,flush=True)
    changes=[]
    for e in cfg.get('Env',[]):
        if not any(n in e.split('=',1)[0].upper() for n in SECRET_NAMES):
            changes+=['--change','ENV '+e.split('=',1)[0]+'='+json.dumps(e.split('=',1)[1])]
    for field,instruction in [('WorkingDir','WORKDIR'),('User','USER')]:
        if cfg.get(field): changes+=['--change',instruction+' '+cfg[field]]
    for field in ['Entrypoint','Cmd']:
        if cfg.get(field): changes+=['--change',field.upper()+' '+json.dumps(cfg[field])]
    for port in cfg.get('ExposedPorts',{}): changes+=['--change','EXPOSE '+port]
    for volume in cfg.get('Volumes',{}): changes+=['--change','VOLUME '+json.dumps([volume])]
    changes+=['--change','LABEL org.opencontainers.image.source=https://github.com/Zipties/voicestack3','--change','LABEL org.opencontainers.image.revision='+args.revision]
    name='vs3-release-'+uuid.uuid4().hex[:12]
    release='localhost/vs3-worker:nemotron-release'
    temp_root=Path('/home/cory/.hermes/profiles/chad/tmp')
    with tempfile.TemporaryDirectory(prefix='vs3-ghcr-',dir=temp_root) as folder:
        auth=Path(folder)/'auth.json'
        tar=Path(folder)/'rootfs.tar'
        try:
            call(['podman','create','--name',name,args.source])
            print('Exporting qualified rootfs; import discards inherited image history/config.',flush=True)
            call(['podman','export','--output',str(tar),name])
            call(['podman','import','--arch','amd64','--os','linux',*changes,str(tar),release])
        finally:
            subprocess.run(['podman','rm',name],capture_output=True)
        safe=json.loads(call(['podman','image','inspect',release]))[0]
        assert not any(any(n in e.split('=',1)[0].upper() for n in SECRET_NAMES) for e in safe['Config'].get('Env',[]))
        assert safe['Config']['Entrypoint']==cfg['Entrypoint']
        assert not safe.get('History') or len(safe['History'])<=1
        # Read-only offline inference proves the serialized artifact's runtime.
        check=call(['podman','run','--rm','--network','none','--device','nvidia.com/gpu=all','-v','voicestack3_data:/data:ro','--entrypoint','python',release,'-c',"import numpy as np,wave; from pipeline.diarization import diarize_dataframe,backend_name; p='/data/artifacts/a00a8584-6ec2-42ec-a0d7-4b920037c2e5/audio_16k_mono.wav'; w=wave.open(p); a=np.frombuffer(w.readframes(30*16000),dtype='<i2').astype(np.float32)/32768; w.close(); f=diarize_dataframe(a); assert len(f)>0; print('RELEASE_CHECK',backend_name(),len(f))"])
        print(check.strip(),flush=True)
        call(['podman','login','--authfile',str(auth),'--username',username,'--password-stdin','ghcr.io'],input=token)
        os.chmod(auth,0o600)
        print('Pushing credential-free worker release to GHCR latest…',flush=True)
        digest_path=Path(folder)/'digest'
        call(['podman','push','--authfile',str(auth),'--digestfile',str(digest_path),release,'docker://'+REGISTRY_IMAGE+':latest'],timeout=3600)
        pushed=digest_path.read_text().strip()
        remote=json.loads(call(['skopeo','inspect','--authfile',str(auth),'--config','docker://'+REGISTRY_IMAGE+':latest']))
        assert not any(any(n in e.split('=',1)[0].upper() for n in SECRET_NAMES) for e in remote['config'].get('Env',[]))
        assert remote['config']['Labels']['org.opencontainers.image.revision']==args.revision
        verified=json.loads(call(['skopeo','inspect','--authfile',str(auth),'docker://'+REGISTRY_IMAGE+':latest']))['Digest']
        assert pushed==verified,(pushed,verified)
        evidence={'registry_image':REGISTRY_IMAGE+':latest','remote_manifest_digest':pushed,'source_image_id':original['Id'],'release_image_id':safe['Id'],'source_revision':args.revision,'removed_environment_names':stripped,'rootfs_secret_scan':scan,'offline_release_inference_passed':True,'remote_config_credential_free':True,'note':'Export/import discarded credential-bearing inherited history. Source live container was not modified.'}
        Path(args.output).parent.mkdir(parents=True,exist_ok=True)
        Path(args.output).write_text(json.dumps(evidence,indent=2))
        print(json.dumps(evidence,indent=2),flush=True)

if __name__=='__main__': main()
