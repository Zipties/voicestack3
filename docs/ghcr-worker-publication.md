# VoiceStack3 GHCR worker publication

A worker rollout is not complete with a local-only image. The canonical CUDA worker is `ghcr.io/zipties/voicestack3-worker:latest` (linux/amd64); its immutable companion tag is `sha-<source-commit>`.

## Verified GHCR release

Publication completed through Actions run [38418424407](https://github.com/Zipties/voicestack3/actions/runs/38418424407). Both CUDA `latest` and `sha-e6d635443a83e53c9c9c225f7827f3dfb00e08ae` resolve to `sha256:ec1c219deaff735eb58ee7f0647d5294de874692fcd146db113d954e537a1075`. Remote default is Nemotron and the configuration contains no credential environment fields.

The actual registry digest was pulled and exercised read-only on the 90-second validation audio: transcription, 20 aligned/speaker-attributed segments, 20 emotion results and three verified speakers all passed. The published runtime retained Torch 2.8.0 / WhisperX 3.8.6 / Transformers 4.57.6; ModelScope resolved to 1.40.2 and its local-model loading was verified. No original job was reprocessed and no new database rows were created by registry validation. The local latest alias now matches the pulled release; the already-running worker was not restarted for publication.

Evidence: `nemotron-ghcr-publication.json` and `nemotron-ghcr-runtime-validation.json`. Repeat the runtime check with `scripts/verify_registry_worker.py --digest <verified-digest> --output <evidence-path>`. That helper passes bootstrap database configuration only through process environment and never puts credentials into command arguments or output.

## Scoped GitHub Actions path

`.github/workflows/publish-worker-latest.yml` is a manual, CUDA-worker-only workflow. It runs the diarization contract tests and builds/publishes the default worker using the workflow's `GITHUB_TOKEN` with `packages: write`. It does not rebuild backend/frontend/CPU packages and never passes the legacy `HF_TOKEN` secret.

The agents-vault `github-cli-agent-token` is provisioned for repo/workflow access, but its reported classic scopes do NOT include `write:packages`. It can push source and dispatch/monitor Actions; it cannot directly push to GHCR. Do not fall back to Cory's desktop GitHub or 1Password account.

From the project, inject `GH_TOKEN` through the scoped agents-vault wrapper and run:

```bash
python3 scripts/run_worker_publication.py --revision <remote-master-commit> --output /home/cory/.hermes/profiles/chad/tmp/vs3-ghcr-run.json
```

This dispatches the scoped workflow, persists the run handle during monitoring, and reads back the remote manifest/config after success. Move only the final successful evidence to `docs/nemotron-ghcr-publication.json`. Failure is not a published/verified release; follow the recorded run URL and failed step names.

Required readbacks:

- `latest` and `sha-<commit>` resolve to the same digest.
- Remote source-revision label matches the dispatched commit.
- Platform is linux/amd64 and `DIARIZATION_BACKEND=nemotron`.
- No token/password/secret/API-key environment fields exist in the published config.
- Pull/inspect and exercise the actual registry image's diarization/word-assignment contract before treating a freshly resolved dependency build as interchangeable with the previously qualified local image.

The main `build-images.yml` workflow remains available for normal source-triggered fleet builds. Gated fallback-model downloads use a transient BuildKit `hf_token` mount sourced from the NEW optional `HF_BUILD_TOKEN` secret, never an ARG or persistent ENV. That fresh secret is intentionally not assumed to exist. Default Nemotron needs no HF token; missing fallback auth simply skips gated model baking. A cached pyannote rollback can use `HF_HUB_OFFLINE=1`, or operators can provision an appropriate runtime credential separately.

## Credential containment finding

The prior public GHCR latest image and the old locally qualified image both had a nonempty `HF_TOKEN` environment field. No credential values were printed in diagnostics. The old public digest can remain retrievable even after replacing latest, so publication does not revoke that token. Rotation/revocation is a separate irreversible credential operation awaiting Cory's approval.

New builds must NOT consume the exposed legacy `HF_TOKEN` secret. The source build now uses optional secret mounts and no credential ENV. The scoped publication workflow supplies no Hugging Face secret at all.

A separate direct-publisher helper, `scripts/publish_worker_image.py`, exists for an explicitly provisioned package-write agent token. It scans a qualified image rootfs for credential literals, exports/imports to remove inherited credential-bearing history/config, tests offline inference, uses temporary registry auth, and verifies remote digest/config. It now checks classic package-write scope before doing the expensive export. The initial direct attempt failed on insufficient registry permissions; it did not complete publication. The resulting credential-free local `localhost/vs3-worker:nemotron-release` artifact passed offline inference and is retained, but is not proof of remote latest publication.

Do not publish the old credential-bearing image or its original inherited layers again. Do not delete prior public digests or revoke credentials without explicit approval. Temporary export/auth files are removed by the publisher's context manager; actual code/measurement evidence belongs in this repository.
