"""Non-speech event detection via BEATs (Microsoft AudioSet classifier).

Runs BEATs fine-tuned on AudioSet as a second-pass analyzer on audio segments
to detect non-speech events like laughter, crying, coughing, applause, etc.

BEATs classifies audio into 527 AudioSet categories with per-class probabilities
(multi-label sigmoid output). We filter for paralinguistic events only.

Replaces SenseVoice which only emitted <|Speech|> tags and never detected events.
"""

import os

# Checkpoint path - auto-downloaded on first use
BEATS_CHECKPOINT = os.getenv(
    "BEATS_CHECKPOINT",
    "/app/model_cache/beats/BEATs_iter3_plus_AS2M_finetuned_on_AS2M_cpt2.pt",
)

# HuggingFace mirror (original OneDrive links expired)
_BEATS_HF_REPO = "WeiChihChen/BEATs_iter3_plus_AS2M_finetuned_on_AS2M_cpt2"
_BEATS_HF_FILE = "BEATs_iter3_plus_AS2M_finetuned_on_AS2M_cpt2.pt"


def _ensure_checkpoint():
    """Download BEATs checkpoint from HuggingFace if not present."""
    if os.path.exists(BEATS_CHECKPOINT):
        return
    os.makedirs(os.path.dirname(BEATS_CHECKPOINT), exist_ok=True)
    print("[beats] Downloading checkpoint from HuggingFace...", flush=True)

    from huggingface_hub import hf_hub_download
    dl_dir = os.path.dirname(BEATS_CHECKPOINT)
    path = hf_hub_download(
        repo_id=_BEATS_HF_REPO,
        filename=_BEATS_HF_FILE,
        local_dir=dl_dir,
    )
    # HF filename differs from our expected name - rename
    downloaded = os.path.join(dl_dir, _BEATS_HF_FILE)
    if os.path.exists(downloaded) and downloaded != BEATS_CHECKPOINT:
        os.rename(downloaded, BEATS_CHECKPOINT)
    size_mb = os.path.getsize(BEATS_CHECKPOINT) / (1024 * 1024)
    print(f"[beats] Downloaded checkpoint ({size_mb:.0f} MB)", flush=True)


# Minimum probability to consider a class detected
EVENT_THRESHOLD = float(os.getenv("BEATS_EVENT_THRESHOLD", "0.25"))

# AudioSet MID → (canonical_event_name, display_name)
# Verified against actual BEATs iter3+ AS2M finetuned cpt2 checkpoint (2026-02-12)
# MIDs from: http://storage.googleapis.com/us_audioset/youtube_corpus/v1/csv/class_labels_indices.csv
_MID_TO_EVENT = {
    # === Human non-speech vocalizations ===
    "/m/01j3sz":  ("LAUGHTER", "Laughter"),                      # idx 472
    "/m/07sq110": ("BELLY_LAUGH", "Belly laugh"),                # idx 245
    "/t/dd00001": ("BABY_LAUGHTER", "Baby laughter"),            # idx 473
    "/m/07r660_": ("GIGGLE", "Giggle"),                          # idx 244
    "/m/07s04w4": ("SNICKER", "Snicker"),                        # idx 155
    "/m/07rgt08": ("CHUCKLE", "Chuckle, chortle"),               # idx 242
    "/m/0463cq4": ("CRYING", "Crying, sobbing"),                 # idx 498
    "/t/dd00002": ("BABY_CRY", "Baby cry, infant cry"),          # idx 395
    "/m/07qz6j3": ("WHIMPER", "Whimper"),                        # idx 81
    "/m/07plz5l": ("SIGH", "Sigh"),                              # idx 62
    "/m/07s0dtb": ("GASP", "Gasp"),                              # idx 466
    "/m/01b_21":  ("COUGH", "Cough"),                            # idx 156
    "/m/01hsr_":  ("SNEEZE", "Sneeze"),                          # idx 213
    "/m/01d3sd":  ("SNORING", "Snoring"),                        # idx 477
    "/m/0dl9sf8": ("THROAT_CLEARING", "Throat clearing"),        # idx 141
    "/m/02p3nc":  ("HICCUP", "Hiccup"),                          # idx 506
    "/m/03q5_w":  ("BURPING", "Burping, eructation"),            # idx 122
    "/m/0lyf6":   ("BREATHING", "Breathing"),                    # idx 310
    "/m/07mzm6":  ("WHEEZE", "Wheeze"),                          # idx 285
    "/m/07q0yl5": ("SNORT", "Snort"),                            # idx 170
    "/m/07s2xch": ("GROAN", "Groan"),                            # idx 410
    "/m/07r4k75": ("GRUNT", "Grunt"),                            # idx 323
    "/m/03qc9zr": ("SCREAMING", "Screaming"),                    # idx 34
    "/m/07p6fty": ("SHOUT", "Shout"),                            # idx 344
    "/m/01w250":  ("WHISTLING", "Whistling"),                    # idx 393
    "/m/02rtxlg": ("WHISPERING", "Whispering"),                  # idx 413
    "/m/07sr1lc": ("YELL", "Yell"),                              # idx 50
    "/m/04gy_2":  ("BATTLE_CRY", "Battle cry"),                  # idx 334
    "/m/07qw_06": ("WAIL", "Wail, moan"),                        # idx 431
    "/m/07ppn3j": ("SNIFF", "Sniff"),                            # idx 526
    # === Audience / crowd ===
    "/m/028ght":  ("APPLAUSE", "Applause"),                      # idx 483
    "/m/0l15bq":  ("CLAPPING", "Clapping"),                      # idx 449
    "/m/053hz1":  ("CHEERING", "Cheering"),                      # idx 485
    "/m/03qtwd":  ("CROWD", "Crowd"),                            # idx 198
    "/m/07qfr4h": ("SPEECH_NOISE", "Hubbub, speech noise"),      # idx 199
    # === Singing ===
    "/m/015lz1":  ("SINGING", "Singing"),                        # idx 49
    "/m/02fxyj":  ("HUMMING", "Humming"),                        # idx 430
    # === Environmental (useful context) ===
    "/m/04rlf":   ("MUSIC", "Music"),                            # idx 2
    "/m/0bt9lr":  ("DOG", "Dog"),                                # idx 149
    "/m/01yrx":   ("CAT", "Cat"),                                # idx 335
    "/m/015p6":   ("BIRD", "Bird"),                              # idx 171
    "/m/07pp_mv": ("ALARM", "Alarm"),                            # idx 316
    "/m/07cx4":   ("TELEPHONE", "Telephone"),                    # idx 144
    "/m/03wwcy":  ("DOORBELL", "Doorbell"),                      # idx 474
    "/m/07r4wb8": ("KNOCK", "Knock"),                            # idx 173
    "/m/039jq":   ("GLASS", "Glass"),                            # idx 399
    "/m/02dgv":   ("DOOR", "Door"),                              # idx 68
}


def detect_events(audio_path: str, segments: list, job_id: str) -> list[dict]:
    """Run BEATs on each segment to detect non-speech events.

    Args:
        audio_path: Path to 16kHz mono WAV
        segments: WhisperX segments with start/end times
        job_id: For logging

    Returns list of dicts:
        [{"segment_idx": 0, "events": ["LAUGHTER", "SIGH"]}, ...]
    """
    import torch
    import librosa
    from pipeline.gpu_cleanup import cleanup_gpu, log_gpu_memory
    from pipeline.beats import BEATs, BEATsConfig

    print(f"[beats] Loading model for {len(segments)} segments...", flush=True)
    log_gpu_memory("before_beats")

    _ensure_checkpoint()
    device = "cuda" if torch.cuda.is_available() else "cpu"

    # Load fine-tuned BEATs checkpoint
    checkpoint = torch.load(BEATS_CHECKPOINT, map_location=device, weights_only=False)
    cfg = BEATsConfig(checkpoint["cfg"])
    model = BEATs(cfg)
    model.load_state_dict(checkpoint["model"])
    model.to(device)
    model.eval()

    # Build class_idx → event mapping
    # checkpoint label_dict: {class_idx: AudioSet_MID}
    label_dict = checkpoint.get("label_dict", {})
    idx_to_event = {}
    for class_idx, mid in label_dict.items():
        if mid in _MID_TO_EVENT:
            event_name, display_name = _MID_TO_EVENT[mid]
            idx_to_event[class_idx] = (event_name, display_name)

    print(f"[beats] Model loaded ({sum(p.numel() for p in model.parameters()) / 1e6:.1f}M params), "
          f"{len(label_dict)} classes, {len(idx_to_event)} target events, device={device}", flush=True)

    # Load full audio once
    audio, sr = librosa.load(audio_path, sr=16000)

    results = []
    for idx, seg in enumerate(segments):
        start_sample = int(seg["start"] * sr)
        end_sample = int(seg["end"] * sr)
        segment_audio = audio[start_sample:end_sample]

        # Skip very short segments (< 0.5s)
        if len(segment_audio) < sr * 0.5:
            results.append({"segment_idx": idx, "events": []})
            continue

        try:
            # BEATs expects (batch, samples) float tensor
            waveform = torch.tensor(segment_audio, dtype=torch.float32).unsqueeze(0).to(device)
            padding_mask = torch.zeros(1, waveform.shape[1], dtype=torch.bool).to(device)

            with torch.no_grad():
                probs, _ = model.extract_features(waveform, padding_mask=padding_mask)

            # probs shape: (1, 527) - sigmoid probabilities per AudioSet class
            probs = probs.squeeze(0).cpu()

            # Find target events above threshold
            events = []
            all_probs = []
            for class_idx, (event_name, display_name) in idx_to_event.items():
                prob = probs[class_idx].item()
                all_probs.append((event_name, prob))
                if prob >= EVENT_THRESHOLD:
                    events.append(event_name)

            results.append({
                "segment_idx": idx,
                "events": events,
            })

            # Always log top 3 candidates per segment for debugging
            top3 = sorted(all_probs, key=lambda x: -x[1])[:3]
            top3_str = ", ".join(f"{e}={p:.3f}" for e, p in top3)
            if events:
                detected = ", ".join(f"{e}={p:.2f}" for e, p in sorted(all_probs, key=lambda x: -x[1]) if p >= EVENT_THRESHOLD)
                print(f"[beats]   seg {idx} DETECTED: [{detected}] (top3: {top3_str})", flush=True)
            else:
                print(f"[beats]   seg {idx} top3: {top3_str}", flush=True)

        except Exception as e:
            print(f"[beats] Warning: segment {idx} failed: {e}", flush=True)
            results.append({"segment_idx": idx, "events": []})

    event_count = sum(len(r["events"]) for r in results)
    print(f"[beats] Detected {event_count} events across {len(results)} segments", flush=True)

    del model, checkpoint
    cleanup_gpu()
    log_gpu_memory("after_beats")

    return results
