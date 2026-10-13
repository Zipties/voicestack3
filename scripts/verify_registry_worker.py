"""Pull and exercise the actual registry worker without replacing the live one.

The test reads existing audio and speaker profiles; it creates no jobs,
transcripts, speakers or embeddings. Bootstrap DB configuration stays in
process environment, never command arguments or output.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess

CHECK = r'''import json,os,torch,importlib.metadata as meta
original_load=torch.load
def compatible(*args,**kwargs):
 kwargs.setdefault('weights_only',False)
 return original_load(*args,**kwargs)
torch.load=compatible
from pipeline.diarization import backend_name
assert backend_name()=='nemotron'
audio='/data/inputs/6392dabf-d398-4b2f-8706-a42ce677bd64_nemotron-default-validation.wav'
from whisper_model import transcribe_audio
transcription=transcribe_audio(audio)
assert transcription['segments']
from pipeline.transcription import align_and_diarize
aligned=align_and_diarize(audio,transcription,'registry-readonly-validation',do_align=True,do_diarize=True)
segments=aligned['segments']
assert segments and all(s.get('speaker') for s in segments)
assert any(s.get('words') for s in segments)
from pipeline.emotion import detect_emotions
emotions=detect_emotions(audio,segments,'registry-readonly-validation')
assert len(emotions)==len(segments) and any(e['confidence']>0 for e in emotions)
from pipeline.verify import verify_speakers
verification=verify_speakers(audio)
assert len(verification['speakers'])>=2 and verification['segments']
print('REGISTRY_CHECK_JSON '+json.dumps({'backend':backend_name(),'transcription_segments':len(transcription['segments']),'aligned_segments':len(segments),'emotion_results':len(emotions),'speaker_verification_count':len(verification['speakers']),'read_only_validation':True,'versions':{x:meta.version(x) for x in ('torch','whisperx','transformers','pyannote.audio','funasr','modelscope')}}))
'''

def main():
    parser=argparse.ArgumentParser()
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--digest')
    source.add_argument('--image',help='Optional local credential-free artifact preflight')
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    reference='ghcr.io/zipties/voicestack3-worker@'+args.digest if args.digest else args.image
    if args.digest:
        print('Pulling verified registry digest:',args.digest,flush=True)
        subprocess.run(['podman','pull',reference],check=True,timeout=1800)
    image=json.loads(subprocess.check_output(['podman','image','inspect',reference],text=True))[0]
    assert not any(any(n in e.split('=',1)[0].upper() for n in ('TOKEN','PASSWORD','SECRET','API_KEY')) for e in image['Config'].get('Env',[]))
    live=json.loads(subprocess.check_output(['podman','inspect','voicestack3_worker_1'],text=True))[0]
    live_env=dict(x.split('=',1) for x in live['Config']['Env'])
    env=dict(os.environ)
    env['DATABASE_URL']=live_env['DATABASE_URL']
    networks=list(live['NetworkSettings']['Networks'])
    assert networks
    command=['podman','run','--rm','--network',networks[0],'--device','nvidia.com/gpu=all','-v','voicestack3_data:/data:ro','-e','DATABASE_URL','-e','WHISPER_COMPUTE_TYPE=float16','-e','WHISPER_CACHE_DIR=/app/model_cache/whisper','-e','HF_HUB_OFFLINE=1','-e','TRANSFORMERS_OFFLINE=1','--entrypoint','python',reference,'-c',CHECK]
    result=subprocess.run(command,env=env,capture_output=True,text=True,timeout=900)
    if result.returncode:
        # Model diagnostics are local; redact configured DB credentials if present.
        message=(result.stdout[-3000:]+'\n'+result.stderr[-3000:]).replace(live_env['DATABASE_URL'],'[REDACTED_DATABASE_URL]')
        print(message)
        raise RuntimeError('Registry worker read-only compatibility test failed')
    records=[line[len('REGISTRY_CHECK_JSON '):] for line in result.stdout.splitlines() if line.startswith('REGISTRY_CHECK_JSON ')]
    assert records
    evidence=json.loads(records[-1])
    evidence.update(artifact_reference=reference,registry_digest_checked=bool(args.digest),image_id=image['Id'])
    path=Path(args.output)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(evidence,indent=2))
    print(json.dumps(evidence,indent=2),flush=True)
    # Keep the local pull alias aligned with GHCR. Live container remains intact.
    if args.digest:
        subprocess.run(['podman','tag',reference,'ghcr.io/zipties/voicestack3-worker:latest'],check=True)

if __name__=='__main__': main()
