const API_URL = process.env.NEXT_PUBLIC_API_URL || "";
// SSE endpoints need to bypass Next.js rewrite proxy (it buffers streaming responses).
// In production behind Traefik/nginx, the reverse proxy handles SSE correctly (same origin).
// For local Docker Compose, connect directly to the backend on port 8000.
function getSSEUrl(): string {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (typeof window === "undefined") return "";
  // If the page is served on port 3000 (Next.js), SSE goes direct to backend on 8000
  const loc = window.location;
  if (loc.port === "3000") return `${loc.protocol}//${loc.hostname}:8000`;
  return ""; // Behind reverse proxy — same origin works
}
const SSE_URL = getSSEUrl();

// ─── Types ───────────────────────────────────────────────────────────────────

export interface JobSpeaker {
  id: string;
  name: string;
  avatar_id: number | null;
  custom_avatar: string | null;
}

export interface Job {
  id: string;
  status: "QUEUED" | "PROCESSING" | "COMPLETED" | "FAILED";
  progress: number;
  pipeline_stage: string | null;
  error_message: string | null;
  title: string | null;
  has_summary: boolean;
  created_at: string | null;
  updated_at: string | null;
  speakers?: JobSpeaker[];
  asset?: {
    filename: string;
    mimetype: string | null;
    size_bytes: number | null;
    duration_seconds: number | null;
  } | null;
}

export interface WordTiming {
  word: string;
  start: number;
  end: number;
  score: number;
}

export interface Speaker {
  id: string;
  name: string;
  is_trusted: boolean;
  match_confidence: number | null;
  avatar_id: number | null;
  custom_avatar: string | null;
  embedding_count?: number;
  segment_count?: number;
  created_at: string | null;
}

export interface Segment {
  id: string;
  start_time: number;
  end_time: number;
  text: string;
  word_timings: WordTiming[] | null;
  speaker: { id: string; name: string; avatar_id: number | null; custom_avatar: string | null } | null;
  original_speaker_label: string | null;
  emotion: string | null;
  emotion_confidence: number | null;
  speech_events: string[];
}

export interface Tag {
  id: string;
  tag: string;
  source: string;
}

export interface Transcript {
  id: string;
  job_id: string;
  raw_text: string;
  title: string | null;
  summary: string | null;
  language: string | null;
  segments: Segment[];
  tags: Tag[];
  created_at: string | null;
}

export interface ActionItem {
  text: string;
  checked: boolean;
}

export interface Overview {
  title: string;
  summary: string;
  action_items: (string | ActionItem)[];
  outline: { heading: string; content: string }[];
}

export interface JobProgress {
  status: string;
  progress: number;
  stage: string | null;
}

// ─── API Calls ───────────────────────────────────────────────────────────────

export async function fetchJobs(limit = 50): Promise<Job[]> {
  const res = await fetch(`${API_URL}/api/jobs/?limit=${limit}`);
  if (!res.ok) throw new Error(`Failed to fetch jobs: ${res.status}`);
  return res.json();
}

export async function fetchJob(jobId: string): Promise<Job> {
  const res = await fetch(`${API_URL}/api/jobs/${jobId}`);
  if (!res.ok) throw new Error(`Failed to fetch job: ${res.status}`);
  return res.json();
}

export async function uploadAudio(file: File): Promise<{ job_id: string; status: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_URL}/api/jobs/`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`Failed to upload: ${res.status}`);
  return res.json();
}

export async function reprocessJob(jobId: string): Promise<{ job_id: string; status: string }> {
  const res = await fetch(`${API_URL}/api/jobs/${jobId}/reprocess`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to reprocess: ${res.status}`);
  return res.json();
}

export async function deleteJob(jobId: string): Promise<{ deleted: boolean }> {
  const res = await fetch(`${API_URL}/api/jobs/${jobId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Failed to delete: ${res.status}`);
  return res.json();
}

export async function fetchTranscriptByJob(jobId: string): Promise<Transcript> {
  const res = await fetch(`${API_URL}/api/transcripts/by-job/${jobId}`);
  if (!res.ok) throw new Error(`Failed to fetch transcript: ${res.status}`);
  return res.json();
}

export async function fetchTranscript(transcriptId: string): Promise<Transcript> {
  const res = await fetch(`${API_URL}/api/transcripts/${transcriptId}`);
  if (!res.ok) throw new Error(`Failed to fetch transcript: ${res.status}`);
  return res.json();
}

export async function fetchSpeakers(): Promise<Speaker[]> {
  const res = await fetch(`${API_URL}/api/speakers/`);
  if (!res.ok) throw new Error(`Failed to fetch speakers: ${res.status}`);
  return res.json();
}

export async function updateSpeaker(
  id: string,
  update: { name?: string; is_trusted?: boolean; avatar_id?: number }
): Promise<Speaker> {
  const res = await fetch(`${API_URL}/api/speakers/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
  });
  if (!res.ok) throw new Error(`Failed to update speaker: ${res.status}`);
  return res.json();
}

export interface SpeakerEmbedding {
  id: string;
  segment: {
    id: string;
    text: string;
    start_time: number;
    end_time: number;
  } | null;
  job_id: string | null;
  transcript_title: string | null;
  created_at: string | null;
}

export async function fetchSpeakerEmbeddings(speakerId: string): Promise<SpeakerEmbedding[]> {
  const res = await fetch(`${API_URL}/api/speakers/${speakerId}/embeddings`);
  if (!res.ok) throw new Error(`Failed to fetch embeddings: ${res.status}`);
  return res.json();
}

export async function deleteSpeakerEmbedding(
  speakerId: string,
  embeddingId: string
): Promise<{ deleted: boolean }> {
  const res = await fetch(`${API_URL}/api/speakers/${speakerId}/embeddings/${embeddingId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`Failed to delete embedding: ${res.status}`);
  return res.json();
}

export async function deleteSpeaker(id: string): Promise<{ deleted: boolean }> {
  const res = await fetch(`${API_URL}/api/speakers/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Failed to delete speaker: ${res.status}`);
  return res.json();
}

export async function uploadSpeakerAvatar(speakerId: string, file: File): Promise<{ id: string; custom_avatar: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_URL}/api/speakers/${speakerId}/avatar`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`Failed to upload avatar: ${res.status}`);
  return res.json();
}

export async function mergeSpeakers(
  sourceId: string,
  targetId: string
): Promise<{ merged: boolean; target_id: string; target_name: string }> {
  const res = await fetch(`${API_URL}/api/speakers/merge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_id: sourceId, target_id: targetId }),
  });
  if (!res.ok) throw new Error(`Failed to merge speakers: ${res.status}`);
  return res.json();
}

export async function reassignSegmentSpeaker(
  segmentId: string,
  speakerId: string
): Promise<{ segment_id: string; speaker_id: string; speaker_name: string }> {
  const res = await fetch(`${API_URL}/api/speakers/segments/${segmentId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ speaker_id: speakerId }),
  });
  if (!res.ok) throw new Error(`Failed to reassign segment: ${res.status}`);
  return res.json();
}

export async function updateTranscriptTitle(
  transcriptId: string,
  title: string
): Promise<{ id: string; title: string }> {
  const res = await fetch(`${API_URL}/api/transcripts/${transcriptId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error(`Failed to update title: ${res.status}`);
  return res.json();
}

export async function generateOverview(transcriptId: string): Promise<Overview> {
  const res = await fetch(`${API_URL}/api/transcripts/${transcriptId}/generate-overview`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Failed to generate overview: ${res.status}`);
  return res.json();
}

export async function toggleActionItem(
  transcriptId: string,
  itemIndex: number
): Promise<{ index: number; item: ActionItem }> {
  const res = await fetch(
    `${API_URL}/api/transcripts/${transcriptId}/action-items/${itemIndex}`,
    { method: "PATCH" }
  );
  if (!res.ok) throw new Error(`Failed to toggle action item: ${res.status}`);
  return res.json();
}

export async function fetchIndexStatus(
  transcriptId: string
): Promise<{ status: string; points?: number; error?: string; ts?: string }> {
  const res = await fetch(`${API_URL}/api/transcripts/${transcriptId}/index-status`);
  if (!res.ok) return { status: "unknown" };
  return res.json();
}

export async function updateOverview(
  transcriptId: string,
  data: {
    summary?: string;
    action_items?: { text: string; checked: boolean }[];
    outline?: { heading: string; content: string }[];
  }
): Promise<Overview> {
  const res = await fetch(`${API_URL}/api/transcripts/${transcriptId}/overview`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Failed to update overview: ${res.status}`);
  return res.json();
}

// ─── Settings ────────────────────────────────────────────────────────────────

export interface AppSettings {
  llm_provider: "openclaw" | "openai_key" | "none";
  openai_base_url: string;
  openai_api_key: string;
  openai_model: string;
  llm_analyze_prompt: string;
  // OpenClaw proxy
  openclaw_gateway_url: string;
  openclaw_gateway_token: string;
  openclaw_summary_agent: string;
  openclaw_chat_agent: string;
  qdrant_enabled: boolean;
  qdrant_url: string;
  qdrant_api_key: string;
  qdrant_collection: string;
  embed_url: string;
  embed_api_key: string;
  // Whisper model
  whisper_model: string;
  whisper_persistent: boolean;
  whisper_prompt: string;
  // Pipeline stages
  pipeline_alignment: boolean;
  pipeline_diarization: boolean;
  pipeline_emotion: boolean;
  pipeline_speaker_matching: boolean;
  // Auto-summary
  auto_summary: "off" | "all" | "known_speakers_only";
  // File watcher
  file_watcher_enabled: boolean;
  file_watcher_path: string;
  file_watcher_extensions: string;
  file_watcher_min_size_kb: number;
  file_watcher_cooldown_seconds: number;
  file_watcher_poll_interval_seconds: number;
}

export interface WatcherStatus {
  enabled: boolean;
  path: string;
  files_processed: number;
  last_scan: string | null;
  thread_alive: boolean;
}

export async function fetchSettings(): Promise<AppSettings> {
  const res = await fetch(`${API_URL}/api/settings`);
  if (!res.ok) throw new Error(`Failed to fetch settings: ${res.status}`);
  return res.json();
}

export async function saveSettings(
  data: Partial<AppSettings>
): Promise<AppSettings> {
  const res = await fetch(`${API_URL}/api/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Failed to save settings: ${res.status}`);
  return res.json();
}

export async function fetchAvailableModels(): Promise<
  { id: string; owned_by: string }[]
> {
  const res = await fetch(`${API_URL}/api/settings/models`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.models || [];
}

export async function testLlmConnection(): Promise<{
  status: string;
  message: string;
}> {
  const res = await fetch(`${API_URL}/api/settings/test-llm`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Test failed: ${res.status}`);
  return res.json();
}

export async function testQdrantConnection(): Promise<{
  status: string;
  message: string;
}> {
  const res = await fetch(`${API_URL}/api/settings/test-qdrant`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Test failed: ${res.status}`);
  return res.json();
}

export async function fetchWatcherStatus(): Promise<WatcherStatus> {
  const res = await fetch(`${API_URL}/api/settings/watcher/status`);
  if (!res.ok) throw new Error(`Failed to fetch watcher status: ${res.status}`);
  return res.json();
}

export async function triggerWatcherScan(): Promise<{
  scanned: boolean;
  ingested: { file: string; job_id: string }[];
  count: number;
}> {
  const res = await fetch(`${API_URL}/api/settings/watcher/scan`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Scan failed: ${res.status}`);
  return res.json();
}


// ─── Helpers ─────────────────────────────────────────────────────────────────

export interface ChatAgent {
  id: string;
  name: string;
  description: string;
  model: string;
  category: string;
}

export interface ChatResponse {
  response: string;
  session_id: string;
  agent: string;
}

export async function fetchChatAgents(): Promise<ChatAgent[]> {
  const res = await fetch(`${API_URL}/api/transcripts/agents/available`);
  if (!res.ok) throw new Error(`Failed to fetch agents: ${res.status}`);
  return res.json();
}

export async function chatWithTranscript(
  transcriptId: string,
  message: string,
  agent: string = "main",
  sessionId?: string
): Promise<ChatResponse> {
  const res = await fetch(`${API_URL}/api/transcripts/${transcriptId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      agent,
      session_id: sessionId,
    }),
  });
  if (!res.ok) throw new Error(`Chat failed: ${res.status}`);
  return res.json();
}

export function audioUrl(jobId: string): string {
  // Use M4A endpoint for accurate seeking + universal browser support.
  // Cache-bust to avoid stale cached responses from format migrations.
  return `${API_URL}/api/audio/${jobId}/m4a?v=2`;
}

export function subscribeToLogs(
  jobId: string,
  onLog: (line: string) => void,
): () => void {
  const es = new EventSource(`${SSE_URL}/api/jobs/${jobId}/logs`);
  let errorCount = 0;

  es.onmessage = (event) => {
    errorCount = 0;
    try {
      const data = JSON.parse(event.data);
      if (data.line) onLog(data.line);
    } catch {
      // ignore
    }
  };

  // Let EventSource auto-reconnect on transient errors.
  // Only close after sustained failures (server gone).
  es.onerror = () => {
    errorCount++;
    if (errorCount > 5) es.close();
  };

  return () => es.close();
}

export function subscribeToProgress(
  jobId: string,
  onProgress: (data: JobProgress) => void,
  onDone?: () => void
): () => void {
  const es = new EventSource(`${SSE_URL}/api/jobs/${jobId}/progress`);
  let errorCount = 0;

  es.onmessage = (event) => {
    errorCount = 0;
    try {
      const data: JobProgress = JSON.parse(event.data);
      onProgress(data);
      if (data.status.toLowerCase() === "completed" || data.status.toLowerCase() === "failed") {
        es.close();
        onDone?.();
      }
    } catch {
      // ignore parse errors
    }
  };

  es.onerror = () => {
    errorCount++;
    if (errorCount > 5) {
      es.close();
      onDone?.();
    }
  };

  return () => es.close();
}
