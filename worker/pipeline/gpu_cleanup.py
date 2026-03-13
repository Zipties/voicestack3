"""GPU memory management between pipeline stages."""

import gc


def cleanup_gpu():
    """Force GPU memory cleanup. Call between model stages."""
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except ImportError:
        pass


def log_gpu_memory(stage: str):
    """Log current GPU memory usage for debugging."""
    try:
        import torch
        if torch.cuda.is_available():
            allocated = torch.cuda.memory_allocated() / 1024**3
            reserved = torch.cuda.memory_reserved() / 1024**3
            print(f"[GPU] {stage}: {allocated:.1f}GB allocated, {reserved:.1f}GB reserved")
    except ImportError:
        pass
