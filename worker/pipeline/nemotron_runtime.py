"""Pinned Nemotron runtime; never import this into the WhisperX process."""
import argparse
import json
import os
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--audio', required=True)
    parser.add_argument('--device', default='cuda')
    args = parser.parse_args()
    # Keep stdout reserved for the JSON contract even if a library prints diagnostics.
    output = sys.stdout
    sys.stdout = sys.stderr
    import numpy as np
    import torch
    from transformers import AutoConfig, AutoModelForAudioFrameClassification, AutoProcessor
    torch.set_num_threads(8)
    model_path = os.getenv('NEMOTRON_MODEL_DIR', '/app/model_cache/nemotron')
    audio = np.load(args.audio, allow_pickle=False)
    if audio.ndim != 1:
        raise ValueError('Expected mono audio')
    processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)
    processor.streaming_modes['offline_chunked'] = (340, 40)
    processor.set_streaming_mode('offline_chunked')
    config = AutoConfig.from_pretrained(model_path, local_files_only=True)
    config.streaming_config.fifo_length = 40
    config.streaming_config.speaker_cache_update_period = 300
    model = AutoModelForAudioFrameClassification.from_pretrained(model_path, config=config, local_files_only=True, dtype=torch.float32).to(args.device).eval()
    cache = None
    logits = []
    position = 0
    frame_index = 0
    first = True
    with torch.inference_mode():
        while position < len(audio):
            size = processor.num_samples_first_audio_chunk if first else processor.num_samples_per_audio_chunk
            end = min(position+size, len(audio))
            last = end == len(audio)
            inputs = processor(audio[position:end], sampling_rate=16000, is_streaming=True, is_first_audio_chunk=first, is_last_audio_chunk=last, return_tensors='pt').to(args.device)
            result = model(**inputs, speaker_cache=cache)
            cache = result.speaker_cache
            logits.append(result.logits.cpu())
            if last:
                break
            frame_index += processor.num_mel_frames_per_step
            position = processor.audio_chunk_start(frame_index)
            first = False
    records = processor.extract_speaker_dict(torch.cat(logits, dim=1))[0] if logits else []
    segments = [{'start': float(s['Start']), 'end': float(s['End']), 'speaker': 'SPEAKER_'+str(s['Speaker'])} for s in records]
    output.write(json.dumps(segments))
    output.flush()

if __name__ == '__main__':
    main()
