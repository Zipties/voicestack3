"""Stable diarization contract for transcription and speaker verification.

Nemotron dependencies execute in an isolated interpreter and CUDA context.
Set DIARIZATION_BACKEND=pyannote for explicit rollback; failures never silently
change the model used to label a recording.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import numpy as np


def backend_name():
    backend = os.getenv('DIARIZATION_BACKEND', 'nemotron').lower()
    if backend not in ('nemotron', 'pyannote'):
        raise ValueError('DIARIZATION_BACKEND must be nemotron or pyannote')
    return backend


def diarize_segments(audio, device='cuda'):
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim != 1:
        raise ValueError('Diarization requires mono 16kHz audio')
    if not len(audio):
        return []
    backend = backend_name()
    print(f'[diarization] backend={backend} device={device}', flush=True)
    if backend == 'pyannote':
        from whisperx.diarize import DiarizationPipeline
        token = os.getenv('HF_TOKEN')
        if not token and os.getenv('HF_HUB_OFFLINE', '0') != '1':
            raise RuntimeError('HF_TOKEN required for pyannote diarization')
        model = DiarizationPipeline(token=token or True, device=device)
        try:
            result = model(audio)
            return [{'start': float(row.start), 'end': float(row.end), 'speaker': str(row.speaker)} for row in result.itertuples()]
        finally:
            del model
    python = os.getenv('NEMOTRON_PYTHON', '/opt/nemotron/bin/python')
    runtime = Path(__file__).with_name('nemotron_runtime.py')
    with tempfile.TemporaryDirectory(prefix='vs3-diarization-') as folder:
        input_path = Path(folder)/'audio.npy'
        np.save(input_path, audio, allow_pickle=False)
        result = subprocess.run([python, str(runtime), '--audio', str(input_path), '--device', device], capture_output=True, text=True, timeout=int(os.getenv('DIARIZATION_TIMEOUT', '1800')))
        if result.returncode:
            raise RuntimeError('Nemotron diarization failed: ' + result.stderr[-2000:])
        segments = json.loads(result.stdout)
    for segment in segments:
        if not (0 <= segment['start'] < segment['end'] <= len(audio)/16000 + .2):
            raise RuntimeError('Invalid Nemotron segment bounds')
        if not isinstance(segment['speaker'], str):
            raise RuntimeError('Invalid Nemotron speaker label')
    return segments


def diarize_dataframe(audio, device='cuda'):
    import pandas as pd
    return pd.DataFrame(diarize_segments(audio, device), columns=['start', 'end', 'speaker'])
