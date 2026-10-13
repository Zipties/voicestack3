"""Exercise live VS3 with ONE new 90-second test job; never reprocess the original."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
import wave
import requests

SOURCE_JOB = 'a00a8584-6ec2-42ec-a0d7-4b920037c2e5'
SOURCE = Path('/home/cory/.local/share/containers/storage/volumes/voicestack3_data/_data/artifacts')/SOURCE_JOB/'audio_16k_mono.wav'
API = 'http://localhost:8000'

def get(path):
    with urllib.request.urlopen(API+path, timeout=20) as response:
        return json.load(response)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='vs3-nemotron-validation-') as folder:
        clip=Path(folder)/'nemotron-default-validation.wav'
        with wave.open(str(SOURCE)) as original, wave.open(str(clip),'wb') as target:
            target.setparams(original.getparams())
            target.writeframes(original.readframes(90*original.getframerate()))
        settings=get('/api/settings')
        assert all(settings.get(k) for k in ['pipeline_alignment','pipeline_diarization','pipeline_emotion','pipeline_speaker_matching'])
        assert settings.get('auto_summary') == 'off', 'Avoid triggering remote summary calls during this test'
        with clip.open('rb') as file:
            response=requests.post(API+'/api/jobs/',files={'file':(clip.name,file,'audio/wav')},timeout=30)
            response.raise_for_status()
            job=response.json()['job_id']
        print('Validation job:',job,flush=True)
        stages=[]
        deadline=time.monotonic()+900
        while time.monotonic()<deadline:
            state=get('/api/jobs/'+job)
            stage=state.get('pipeline_stage')
            if not stages or stage!=stages[-1]:
                stages.append(stage)
                print(state['status'],stage,flush=True)
            if state['status'].upper() in ['FAILED','ERROR','CANCELLED']:
                raise RuntimeError(state.get('error_message'))
            if state['status'].upper()=='COMPLETED':
                break
            time.sleep(2)
        else: raise TimeoutError('Validation job did not complete: '+job)
        transcript=get('/api/transcripts/by-job/'+job)
        segments=transcript['segments']
        assert transcript['raw_text'].strip() and segments
        timed=sum(bool(s.get('word_timings')) for s in segments)
        attributed=sum(bool(s.get('speaker')) for s in segments)
        emotions=sum(bool(s.get('emotion')) for s in segments)
        assert timed>0 and attributed>0 and emotions>0
        speakers={s['speaker']['id'] for s in segments if s.get('speaker')}
        assert len(speakers)>=2
        log=subprocess.check_output(['podman','exec','voicestack3_redis_1','redis-cli','--raw','LRANGE','job:'+job+':log_history','0','-1'],text=True)
        assert '[diarization] backend=nemotron' in log
        result={'job_id':job,'source_job':SOURCE_JOB,'status':state['status'],'stages_observed':stages,'segments':len(segments),'segments_with_word_timings':timed,'segments_with_speaker':attributed,'segments_with_emotion':emotions,'speaker_id_count':len(speakers),'nemotron_log_verified':True,'transcript_top_level_keys':sorted(transcript),'segment_keys':sorted(segments[0]),'test_clip_seconds':90,'note':'One new validation job retained. Original job and transcript untouched.'}
        Path(args.output).parent.mkdir(parents=True,exist_ok=True)
        Path(args.output).write_text(json.dumps(result,indent=2))
        print(json.dumps(result,indent=2))

if __name__=='__main__': main()
