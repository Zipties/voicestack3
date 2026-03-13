"""Subprocess wrapper for speaker verification. VRAM freed on exit.

Same isolation pattern as _gpu_worker.py — process exit guarantees
ALL GPU memory is reclaimed by the OS.
"""

import os
import sys
import json

# Add worker directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# PyTorch 2.6+ changed torch.load default to weights_only=True
# pyannote/speechbrain models use pickle-based checkpoints
import torch
_original_torch_load = torch.load
def _patched_torch_load(*args, **kwargs):
    kwargs["weights_only"] = False
    return _original_torch_load(*args, **kwargs)
torch.load = _patched_torch_load

from pipeline.verify import verify_speakers

if __name__ == "__main__":
    audio_path = sys.argv[1]
    threshold = float(sys.argv[2]) if len(sys.argv) > 2 else None
    min_dur = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0

    result = verify_speakers(audio_path, min_duration=min_dur, threshold=threshold)
    # Output JSON to stdout — parent reads the last line
    print(json.dumps(result), flush=True)
