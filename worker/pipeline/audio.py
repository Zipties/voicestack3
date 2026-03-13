"""Audio processing: normalize to 16kHz mono WAV + Opus archival."""

import os
import json
import subprocess
from pathlib import Path


def get_audio_info(file_path: str) -> dict:
    """Get audio metadata via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", file_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")

    info = json.loads(result.stdout)
    audio_stream = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "audio"),
        None
    )
    if not audio_stream:
        raise RuntimeError("No audio stream found in file")

    return {
        "duration": float(info.get("format", {}).get("duration", 0)),
        "sample_rate": int(audio_stream.get("sample_rate", 0)),
        "channels": int(audio_stream.get("channels", 0)),
        "codec": audio_stream.get("codec_name", "unknown"),
    }


def has_video_stream(file_path: str) -> bool:
    """Check if a file contains a video stream (i.e., it's a video file)."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", file_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return False
    try:
        info = json.loads(result.stdout)
        return any(s.get("codec_type") == "video" for s in info.get("streams", []))
    except (json.JSONDecodeError, ValueError):
        return False


def normalize_audio(input_path: str, output_path: str) -> dict:
    """Convert to 16kHz mono WAV for ML pipeline (WhisperX, speaker embeddings).

    Uses two-pass loudnorm to avoid pumping/breathing artifacts.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Pass 1: Analyze loudness stats
    analyze_cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-ar", "16000", "-ac", "1",
        "-f", "null", "/dev/null"
    ]
    result = subprocess.run(analyze_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg loudnorm analysis failed: {result.stderr}")

    # Parse loudnorm stats from stderr (ffmpeg outputs filter info there)
    stats = _parse_loudnorm_stats(result.stderr)

    if stats:
        # Pass 2: Apply measured correction (no guessing = no artifacts)
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-af", (
                f"loudnorm=I=-16:TP=-1.5:LRA=11:linear=true"
                f":measured_I={stats['input_i']}"
                f":measured_TP={stats['input_tp']}"
                f":measured_LRA={stats['input_lra']}"
                f":measured_thresh={stats['input_thresh']}"
            ),
            "-ar", "16000", "-ac", "1",
            output_path
        ]
    else:
        # Fallback: simple resampling without loudnorm if stats parse fails
        print("[audio] Warning: loudnorm stats parse failed, using simple conversion")
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-ar", "16000", "-ac", "1",
            output_path
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg normalization failed: {result.stderr}")

    return get_audio_info(output_path)


def _parse_loudnorm_stats(stderr: str) -> dict | None:
    """Extract loudnorm JSON stats from ffmpeg stderr output."""
    # ffmpeg prints the JSON block at the end of stderr
    try:
        # Find the JSON block that loudnorm outputs
        idx = stderr.rfind('{')
        if idx == -1:
            return None
        json_str = stderr[idx:]
        # Find matching closing brace
        depth = 0
        end = idx
        for i, c in enumerate(json_str):
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        stats = json.loads(json_str[:end])
        # Validate required keys exist
        required = ['input_i', 'input_tp', 'input_lra', 'input_thresh']
        if all(k in stats for k in required):
            return stats
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def create_playback_audio(input_path: str, output_path: str) -> dict:
    """Create high-quality playback audio (48kHz AAC in M4A container).

    M4A (MP4) with faststart moov atom provides accurate browser seeking
    and universal codec support (including Safari/iOS). OGG/WebM Opus
    had seeking drift and Safari compatibility issues respectively.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-c:a", "aac", "-b:a", "128k",
        "-ar", "48000", "-ac", "1",
        "-movflags", "+faststart",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg playback encode failed: {result.stderr}")

    return get_audio_info(output_path)


def create_opus_archive(input_path: str, job_id: str) -> str:
    """Create Opus archive for long-term storage (24kbps VBR)."""
    archive_dir = Path("/data/archival")
    archive_dir.mkdir(parents=True, exist_ok=True)

    archive_path = str(archive_dir / f"{job_id}.opus")
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-c:a", "libopus", "-b:a", "24k", "-vbr", "on",
        archive_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Opus archive failed: {result.stderr}")

    return archive_path


def process_audio(input_path: str, job_id: str) -> tuple[str, str]:
    """Full audio processing: normalize for ML + create playback + archive.

    For video inputs: extracts audio, then deletes the original video file
    to avoid storing full video files long-term.

    Returns (wav_path, opus_path).
    """
    artifacts_dir = Path("/data/artifacts") / job_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    is_video = has_video_stream(input_path)
    if is_video:
        print(f"[audio] Video file detected, will extract audio and discard video", flush=True)

    # ML pipeline file: 16kHz mono WAV (for WhisperX, speaker embeddings, emotion)
    wav_path = str(artifacts_dir / "audio_16k_mono.wav")
    normalize_audio(input_path, wav_path)

    # Playback file: 48kHz AAC in M4A (universal browser support + accurate seeking)
    playback_path = str(artifacts_dir / "audio_playback.m4a")
    create_playback_audio(input_path, playback_path)

    # Archival: low-bitrate Opus for long-term storage
    opus_path = create_opus_archive(input_path, job_id)

    # For video files: delete the original to save storage.
    # Audio has been extracted into wav, playback m4a, and opus archive.
    if is_video:
        try:
            input_size = Path(input_path).stat().st_size
            Path(input_path).unlink()
            print(f"[audio] Deleted video source ({input_size / 1048576:.1f} MB): {input_path}", flush=True)
        except OSError as e:
            print(f"[audio] Warning: could not delete video source: {e}", flush=True)

    return wav_path, opus_path
