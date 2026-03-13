# VoiceStack3

Self-hosted audio intelligence. Upload audio, get transcripts with speaker identification, emotion detection, and AI-powered summaries.

![License](https://img.shields.io/badge/license-MIT%20%2B%20Commons%20Clause-blue)

## Features

- **Transcription** — WhisperX large-v3 with word-level timestamps
- **Speaker Diarization** — pyannote 3.1 identifies who spoke when
- **Speaker Recognition** — ECAPA-TDNN voice fingerprinting. Name a speaker once, recognized forever
- **Emotion Detection** — emotion2vec+ detects sentiment per segment
- **AI Summaries** — Auto-generate titles, summaries, action items, and outlines via any OpenAI-compatible API or [OpenClaw](https://github.com/anthropics/openclaw) agents
- **Semantic Search** — Optional Qdrant integration for searching across all transcripts
- **File Watcher** — Drop audio files in a folder, auto-processed
- **Speaker Verification** — Lightweight endpoint for identifying speakers without full pipeline

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) or [Podman](https://podman.io/)

That's it. All ML models are bundled in the Docker images.

### macOS (Apple Silicon or Intel)

```bash
git clone https://github.com/Zipties/voicestack3.git
cd voicestack3
cp .env.example .env
docker compose up -d
```

The default `.env.example` is pre-configured for CPU mode. Open [http://localhost:3000](http://localhost:3000).

Processing speed: ~2-3x audio length (a 5 min recording takes ~10-15 min).

### Linux with NVIDIA GPU

```bash
git clone https://github.com/Zipties/voicestack3.git
cd voicestack3
cp .env.example .env
```

Edit `.env`:
```bash
WORKER_TAG=latest
WHISPER_COMPUTE_TYPE=float16
```

Then:
```bash
docker compose -f docker-compose.yml -f compose.gpu.yml up -d
```

Requires [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html). Processing speed: faster-than-realtime on RTX 3060+.

### Linux without GPU

Same as macOS — use the defaults in `.env.example` (CPU mode).

### First Run

First startup pulls images (~8GB for CPU, ~15GB for GPU). Models are pre-bundled — no HuggingFace account or manual downloads needed.

Upload an audio file and the pipeline runs automatically: transcription, alignment, diarization, emotion detection, speaker matching.

### Optional Setup

| Feature | How to Enable |
|---------|--------------|
| **AI Summaries** | Settings > LLM Provider > add OpenAI API key (or Ollama, LM Studio, etc.) |
| **OpenClaw Agents** | Set `OPENCLAW_GATEWAY_URL` and `OPENCLAW_GATEWAY_TOKEN` in `.env`, run with `--profile openclaw` |
| **Semantic Search** | Point `QDRANT_URL` and `EMBED_URL` at a Qdrant + embedding server |

## Architecture

```
┌──────────┐    ┌──────────┐    ┌──────────┐
│ Frontend │───>│ Backend  │───>│  Worker  │
│ Next.js  │    │ FastAPI  │    │ WhisperX │
│ :3000    │    │ :8000    │    │ GPU/CPU  │
└──────────┘    └──────────┘    └──────────┘
                     │               │
                ┌────┴────┐    ┌────┴────┐
                │ Postgres│    │  Redis  │
                │ pgvector│    │  (RQ)   │
                └─────────┘    └─────────┘
```

### Pipeline Stages

1. Audio normalization (ffmpeg → 16kHz mono WAV)
2. Transcription (WhisperX large-v3)
3. Word alignment (wav2vec2)
4. Speaker diarization (pyannote 3.1)
5. Emotion detection (emotion2vec+ large)
6. Speaker embedding + matching (ECAPA-TDNN → pgvector)
7. Persist to database
8. Export files (.txt, .srt, .vtt, .json)
9. LLM metadata (optional)

## Configuration

All config via `.env` or the Settings page in the UI.

| Variable | CPU Default | GPU Default | Description |
|----------|-------------|-------------|-------------|
| `WORKER_TAG` | `cpu` | `latest` | Docker image tag for the worker |
| `WHISPER_MODEL` | `large-v3` | `large-v3` | WhisperX model |
| `WHISPER_COMPUTE_TYPE` | `int8` | `float16` | Quantization (int8 for CPU, float16 for GPU) |
| `WHISPER_BATCH_SIZE` | `16` | `16` | Lower = less memory usage |
| `SPEAKER_MATCH_THRESHOLD` | `0.45` | `0.45` | Speaker matching strictness (lower = stricter) |
| `API_TOKEN` | `changeme` | `changeme` | API authentication token |

## OpenClaw Integration (Optional)

[OpenClaw](https://github.com/anthropics/openclaw) users can connect their agents for transcript summarization and chat.

1. Add to `.env`:
   ```bash
   OPENCLAW_GATEWAY_URL=wss://your-gateway.example.com
   OPENCLAW_GATEWAY_TOKEN=your-token-here
   ```

2. Start with the openclaw profile:
   ```bash
   docker compose --profile openclaw up -d
   ```

3. Go to Settings > LLM Provider > OpenClaw and select your summary/chat agents.

The proxy connects directly to your OpenClaw gateway over WSS — no CLI installation needed.

## Development

```bash
# Uses docker-compose.dev.yml — mounts source code for hot reload
docker compose -f docker-compose.dev.yml up
```

## License

MIT + Commons Clause. Free for personal use. Contact me for commercial licensing.
