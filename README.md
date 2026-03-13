# VoiceStack3

Self-hosted audio intelligence. Upload audio, get transcripts with speaker identification, emotion detection, and AI-powered summaries.

![License](https://img.shields.io/badge/license-MIT%20%2B%20Commons%20Clause-blue)

## Features

- **Transcription** — WhisperX large-v2 with word-level timestamps
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
- NVIDIA GPU with [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) (recommended, CPU mode also works)

### Run

```bash
git clone https://github.com/Zipties/voicestack3.git
cd voicestack3
cp .env.example .env    # Edit if needed
docker compose up -d    # or: podman compose up -d
```

Open [http://localhost:3000](http://localhost:3000)

For NVIDIA GPU acceleration:

```bash
docker compose -f docker-compose.yml -f compose.gpu.yml up -d
```

### First Run

Models are baked into the Docker images — no downloads needed. First startup pulls ~15GB of images (one time).

The only optional setup:
1. **LLM for summaries** — Go to Settings, add an OpenAI API key (or any compatible endpoint like Ollama)
2. **OpenClaw agents** — For multi-agent chat, enable the OpenClaw proxy sidecar (see below)
3. **Qdrant for search** — Enable in Settings if you have a Qdrant instance

## Architecture

```
┌──────────┐    ┌──────────┐    ┌──────────┐
│ Frontend │───▶│ Backend  │───▶│  Worker  │
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
2. Transcription (WhisperX large-v2)
3. Word alignment (wav2vec2)
4. Speaker diarization (pyannote 3.1)
5. Emotion detection (emotion2vec+ large)
6. Speaker embedding + matching (ECAPA-TDNN → pgvector)
7. Persist to database
8. Export files (.txt, .srt, .vtt, .json)
9. LLM metadata (optional)

## Configuration

All config is in `.env` or the Settings page in the UI. Key options:

| Variable | Default | Description |
|----------|---------|-------------|
| `PLATFORM` | `cuda` | `cuda` for NVIDIA GPU, `cpu` for CPU-only |
| `WHISPER_MODEL` | `large-v2` | WhisperX model size |
| `WHISPER_COMPUTE_TYPE` | `float16` | `float16` for GPU, `int8` for CPU |
| `WHISPER_BATCH_SIZE` | `16` | Lower for less VRAM usage |
| `SPEAKER_MATCH_THRESHOLD` | `0.3` | Speaker matching strictness (lower = stricter) |

## OpenClaw Integration (Optional)

[OpenClaw](https://github.com/anthropics/openclaw) users can connect their agents for summarization and chat. Start the proxy sidecar:

```bash
# Add --profile openclaw to enable the proxy container
docker compose --profile openclaw up -d
```

Then go to Settings > LLM Provider > OpenClaw Proxy and configure your agent IDs.

The proxy reads your `~/.openclaw/openclaw.json` config and makes your agents available to VoiceStack3 for transcript analysis and chat.

## CPU Mode

Works on any machine (including Apple Silicon via Rosetta). Set `PLATFORM=cpu` in `.env`. Processing is ~2-3x audio length instead of faster-than-realtime on GPU.

## Development

```bash
# Backend + Worker mount source code for hot reload
docker compose up
# Frontend runs in dev mode with hot reload
```

## License

MIT + Commons Clause. Free for personal use. Contact me for commercial licensing.
