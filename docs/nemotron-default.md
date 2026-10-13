# Nemotron is the VoiceStack3 default diarizer

Deployed locally on 2026-10-13 after Cory approved promotion of the isolated A/B candidate.

## Compatibility and architecture

`pipeline.diarization` is the shared contract for persistent transcription, legacy one-shot transcription, and read-only speaker verification. It returns either standard `{start, end, speaker}` records or a DataFrame with those columns, preserving WhisperX word assignment and downstream ECAPA-TDNN/pgvector speaker matching. Existing speaker identities, transcript schema, emotion processing, alignment, and stored recordings are unchanged. Nemotron's generic labels are not treated as real names.

Default: `DIARIZATION_BACKEND=nemotron`. Set `DIARIZATION_BACKEND=pyannote` for an explicit Community-1 rollback. Invalid names and runtime failures fail visibly; they do not silently substitute models. Pyannote remains installed and its cached offline inference was tested in the candidate image.

The main worker keeps WhisperX 3.8.6, Transformers 4.57.6 and its deployed dependencies. Nemotron runs through `/opt/nemotron/bin/python` in a separate virtualenv and subprocess/CUDA context. That environment alone contains Transformers source commit `d0deac8f876f3b89bf03aa513f4823e364084e8c` and NumPy 2.3.5. Model revision `f667ed73aee57d40cc39428eb768b4fd87a0a29e` is baked at `/app/model_cache/nemotron`; inference is local-files-only and requires no HF token. The 340+40 frame offline-style chunk configuration retains speaker cache across the entire file. Eight speakers is a model capacity limit; recordings with more speakers need the explicit pyannote backend.

Subprocess scratch audio uses a temporary directory that is cleaned on success or failure. Exiting the Nemotron process frees its GPU context. `NEMOTRON_PYTHON`, `NEMOTRON_MODEL_DIR` and `DIARIZATION_TIMEOUT` are administrator overrides.

## Deployment and rollback

Initial deployed worker image ID: `f75c4d848c1435baa555425bbd9f109294ab6129c7e90d503f5fa319cf90bc75` (still running after publication, retained as `localhost/vs3-worker:nemotron-candidate`). Publication subsequently completed through the scoped GitHub Actions workflow: GHCR `latest` and the immutable source tag resolve to `sha256:ec1c219deaff735eb58ee7f0647d5294de874692fcd146db113d954e537a1075`. The pulled release image ID is `a45755032b019169dad7e7814ad56df65d941c0b2ce238885ec157f0b8453ccc`, and the local latest alias now points to it. See `ghcr-worker-publication.md` and the two GHCR evidence JSON files. Publication did not restart the already-qualified running worker.

The rollback image is retained as `localhost/vs3-worker:pre-nemotron-20261013` (ID `f9951aeea6043f91a13c8e7d98a6a7c79d8dd416ece54b62b3561c6993413f2d`). Only the idle worker was recreated during the initial rollout using the existing `podman-compose.yml` + `compose.gpu.yml` manager. Database, backend, frontend and Redis were not recreated. Remote pulls of latest now receive the verified Nemotron release.

The legacy local images contain the previously exposed HF token. Never republish them or use that credential for new authentication. For a cached offline rollback, override `HF_TOKEN` to empty and set `HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1`; gated downloads instead require a separately provisioned replacement credential after approved rotation.

`worker/Containerfile` includes the isolated runtime and pinned model for future normal builds. The first promotion deliberately used `worker/Containerfile.nemotron`, layering onto the exact previous image rather than re-resolving WhisperX/emotion/embedding dependencies. For that derivative build, prepare a temporary context with the five changed pipeline files and the pinned model snapshot as `nemotron-model/`; no models or scratch output belong in the Git tree.

To roll back the image, while the worker queue and in-progress registry are idle:

1. Tag `localhost/vs3-worker:pre-nemotron-20261013` back to `ghcr.io/zipties/voicestack3-worker:latest`.
2. From `/home/cory/proj/voicestack3`, run `podman-compose -f podman-compose.yml -f compose.gpu.yml up -d --no-deps --force-recreate worker`.
3. Verify worker image identity, `/health` on port 9000 and a real transcription. Capture compose output privately rather than pasting rendered environment/secrets into chat.

For backend-only rollback, a worker environment override `DIARIZATION_BACKEND=pyannote` selects the retained adapter without removing Nemotron. Recreate only the worker after changing its owning compose environment. No rollback deletes recordings or changes database schema.

## Verified acceptance

- Eight unit tests: default/rollback selection, invalid backend, mono input, empty audio, DataFrame schema, scratch cleanup, child failure propagation, invalid segment bounds.
- Full existing 24m49.8s recording run through the image adapter with networking disabled: 567 activity segments, seven generic speakers, successful WhisperX segment/word assignment.
- Candidate main interpreter remained on WhisperX 3.8.6 / Transformers 4.57.6; isolated interpreter reported Transformers 5.19.0.dev0.
- Explicit pyannote rollback inference passed offline in the same candidate image.
- Live worker image and effective `backend_name()` read back as expected; worker API healthy after normal startup.
- ONE new 90-second validation job, `6392dabf-d398-4b2f-8706-a42ce677bd64`, completed through the actual queue and persistence path. All 20 transcript segments have word timings, speaker attribution and emotion; three speaker identities were returned. Redis pipeline log explicitly records `backend=nemotron`. Existing jobs were not reprocessed.
- Read-only speaker verification API returned HTTP 200, three speakers and 31 activity segments with the existing dialogue/timeline response schema.
- Auto-summary was already off and remained off. No remote LLM call or third-party communication was used for validation.

See `nemotron-default-validation.json` for the machine-readable job evidence and `scripts/verify_nemotron_deployment.py` for the reproducible live test (it deliberately creates one new test job each invocation).

The preceding benchmark is in `/home/cory/proj/vs3-diarization-bench/README.md`: roughly 12.7x faster warm diarization and lower sampled VRAM on one recording. Those stage timings do not promise a 12.7x end-to-end speedup, and stored-label agreement is not human-ground-truth accuracy. Cory authorized promotion with that limitation understood.

## Source/worktree hygiene

Implementation was isolated on `feat/nemotron-default` in `/home/cory/proj/voicestack3-nemotron`, because the production worktree already contained unrelated backend/frontend/config changes. Only task-owned worker files, tests, verification script and this documentation are committed. Unrelated changes in the original worktree are preserved, never stashed or included in the rollout.
