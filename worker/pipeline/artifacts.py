"""Generate output files: .txt, .srt, .vtt, .json artifacts."""

import json
from pathlib import Path


def _format_timestamp_srt(seconds: float) -> str:
    """Format seconds as SRT timestamp: HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _format_timestamp_vtt(seconds: float) -> str:
    """Format seconds as VTT timestamp: HH:MM:SS.mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def generate_artifacts(
    job_id: str,
    segments: list,
    speaker_map: dict,
    emotions: list[dict],
    events: list[dict],
    language: str,
    speaker_names: dict[str, str] | None = None,
) -> dict[str, str]:
    """Generate .txt, .srt, .vtt, .json output files.

    Args:
        speaker_names: Maps raw labels to display names, e.g. {"SPEAKER_00": "Nicole"}

    Returns dict of {format: file_path}.
    """
    if speaker_names is None:
        speaker_names = {}
    artifacts_dir = Path("/data/artifacts") / job_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    paths = {}

    # Plain text (with emotion + event annotations)
    txt_path = artifacts_dir / "transcript.txt"
    emotion_lookup_txt = {e["segment_idx"]: e for e in emotions}
    event_lookup_txt = {e["segment_idx"]: e.get("events", []) for e in events}
    lines = []
    for idx, seg in enumerate(segments):
        raw_label = seg.get("speaker", "Unknown")
        speaker = speaker_names.get(raw_label, raw_label)
        seg_text = seg.get("text", "").strip()
        if seg_text:
            emo = emotion_lookup_txt.get(idx, {}).get("emotion", "")
            evts = event_lookup_txt.get(idx, [])
            tags = []
            if emo and emo not in ("unknown", "neutral"):
                tags.append(emo)
            tags.extend(e.lower() for e in evts)
            tag_str = f" [{', '.join(tags)}]" if tags else ""
            lines.append(f"[{speaker}{tag_str}] {seg_text}")
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    paths["txt"] = str(txt_path)

    # SRT
    srt_path = artifacts_dir / "transcript.srt"
    srt_lines = []
    for idx, seg in enumerate(segments, 1):
        text = seg.get("text", "").strip()
        if not text:
            continue
        start = _format_timestamp_srt(seg.get("start", 0))
        end = _format_timestamp_srt(seg.get("end", 0))
        raw_label = seg.get("speaker", "")
        speaker = speaker_names.get(raw_label, raw_label) if raw_label else ""
        prefix = f"[{speaker}] " if speaker else ""
        srt_lines.append(f"{idx}\n{start} --> {end}\n{prefix}{text}\n")
    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")
    paths["srt"] = str(srt_path)

    # VTT
    vtt_path = artifacts_dir / "transcript.vtt"
    vtt_lines = ["WEBVTT\n"]
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        start = _format_timestamp_vtt(seg.get("start", 0))
        end = _format_timestamp_vtt(seg.get("end", 0))
        raw_label = seg.get("speaker", "")
        speaker = speaker_names.get(raw_label, raw_label) if raw_label else ""
        prefix = f"<v {speaker}>" if speaker else ""
        vtt_lines.append(f"{start} --> {end}\n{prefix}{text}\n")
    vtt_path.write_text("\n".join(vtt_lines), encoding="utf-8")
    paths["vtt"] = str(vtt_path)

    # JSON (full structured output)
    json_path = artifacts_dir / "transcript.json"
    emotion_lookup = {e["segment_idx"]: e for e in emotions}
    event_lookup = {e["segment_idx"]: e.get("events", []) for e in events}
    json_data = {
        "job_id": job_id,
        "language": language,
        "segments": [
            {
                "index": idx,
                "start": seg.get("start", 0),
                "end": seg.get("end", 0),
                "text": seg.get("text", "").strip(),
                "speaker": speaker_names.get(seg.get("speaker", ""), seg.get("speaker")),
                "emotion": emotion_lookup.get(idx, {}).get("emotion", "unknown"),
                "emotion_confidence": emotion_lookup.get(idx, {}).get("confidence", 0.0),
                "speech_events": event_lookup.get(idx, []),
                "words": seg.get("words", []),
            }
            for idx, seg in enumerate(segments)
        ],
    }
    json_path.write_text(json.dumps(json_data, indent=2, ensure_ascii=False), encoding="utf-8")
    paths["json"] = str(json_path)

    print(f"[artifacts] Generated: {', '.join(paths.keys())}")
    return paths
