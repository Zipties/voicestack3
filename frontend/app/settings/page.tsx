"use client";

import { useState, useEffect } from "react";
import {
  Settings,
  Save,
  Loader2,
  CheckCircle,
  XCircle,
  Zap,
  Database,
  Brain,
  FileText,
  FolderOpen,
  ChevronDown,
  ChevronRight,
  RotateCcw,
  Eye,
  Play,
  RefreshCw,
  Mic,
} from "lucide-react";
import {
  fetchSettings,
  saveSettings,
  fetchAvailableModels,
  testLlmConnection,
  testQdrantConnection,
  fetchWatcherStatus,
  triggerWatcherScan,
  type AppSettings,
  type WatcherStatus,
} from "@/lib/api";

type LlmProvider = AppSettings["llm_provider"];

interface ModelOption {
  id: string;
}

interface TestResult {
  status: "ok" | "error" | "testing";
  message: string;
}

export default function SettingsPage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [llmTest, setLlmTest] = useState<TestResult | null>(null);
  const [qdrantTest, setQdrantTest] = useState<TestResult | null>(null);
  const [watcherStatus, setWatcherStatus] = useState<WatcherStatus | null>(null);
  const [scanning, setScanning] = useState(false);
  const [availableModels, setAvailableModels] = useState<ModelOption[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);

  // Form state
  const [provider, setProvider] = useState<LlmProvider>("none");
  const [openaiBaseUrl, setOpenaiBaseUrl] = useState("https://api.openai.com/v1");
  const [openaiApiKey, setOpenaiApiKey] = useState("");
  const [openaiModel, setOpenaiModel] = useState("gpt-4o-mini");
  const [analyzePrompt, setAnalyzePrompt] = useState("");
  const [showPromptEditor, setShowPromptEditor] = useState(false);
  const [qdrantEnabled, setQdrantEnabled] = useState(false);
  const [qdrantUrl, setQdrantUrl] = useState("");
  const [qdrantApiKey, setQdrantApiKey] = useState("");
  const [qdrantCollection, setQdrantCollection] = useState("vs3-transcripts-bge");
  const [embedUrl, setEmbedUrl] = useState("");
  const [embedApiKey, setEmbedApiKey] = useState("");
  // Pipeline stages
  const [pipeAlignment, _setPipeAlignment] = useState(true);
  const [pipeDiarization, _setPipeDiarization] = useState(true);
  const [pipeEmotion, setPipeEmotion] = useState(true);
  const [pipeSpeakers, _setPipeSpeakers] = useState(true);
  const [autoSummary, setAutoSummary] = useState<"off" | "all" | "known_speakers_only">("off");
  const [defaultPrompt, setDefaultPrompt] = useState("");

  // Node dependency enforcement:
  // alignment ← diarization ← speaker matching
  const setPipeAlignment = (v: boolean) => {
    _setPipeAlignment(v);
    if (!v) { _setPipeDiarization(false); _setPipeSpeakers(false); }
  };
  const setPipeDiarization = (v: boolean) => {
    _setPipeDiarization(v);
    if (v) _setPipeAlignment(true);       // need alignment for diarization
    if (!v) _setPipeSpeakers(false);      // speakers need diarization
  };
  const setPipeSpeakers = (v: boolean) => {
    _setPipeSpeakers(v);
    if (v) { _setPipeAlignment(true); _setPipeDiarization(true); }
  };

  const [openclawGatewayUrl, setOpenclawGatewayUrl] = useState("");
  const [openclawGatewayToken, setOpenclawGatewayToken] = useState("");
  const [openclawSummaryAgent, setOpenclawSummaryAgent] = useState("");
  const [openclawChatAgent, setOpenclawChatAgent] = useState("");

  const [whisperModel, setWhisperModel] = useState("large-v3");
  const [whisperPersistent, setWhisperPersistent] = useState(true);
  const [whisperPrompt, setWhisperPrompt] = useState("");
  const [whisperIdleTimeout, setWhisperIdleTimeout] = useState(1800);
  const [showWhisperPrompt, setShowWhisperPrompt] = useState(false);

  const [watcherEnabled, setWatcherEnabled] = useState(false);
  const [watcherPath, setWatcherPath] = useState("");
  const [watcherExtensions, setWatcherExtensions] = useState(".m4a,.mp3,.wav,.ogg,.flac,.opus,.mp4,.webm");
  const [watcherMinSize, setWatcherMinSize] = useState(10);
  const [watcherCooldown, setWatcherCooldown] = useState(120);
  const [watcherInterval, setWatcherInterval] = useState(30);

  useEffect(() => {
    fetchSettings()
      .then((s) => {
        setProvider(s.llm_provider);
        setOpenaiBaseUrl(s.openai_base_url || "https://api.openai.com/v1");
        setOpenaiApiKey(s.openai_api_key || "");
        setOpenaiModel(s.openai_model || "gpt-4o-mini");
        setAnalyzePrompt(s.llm_analyze_prompt || "");
        setDefaultPrompt((s as any).default_analyze_prompt || "");
        setQdrantEnabled(s.qdrant_enabled);
        setQdrantUrl(s.qdrant_url || "");
        setQdrantApiKey(s.qdrant_api_key || "");
        setQdrantCollection(s.qdrant_collection || "vs3-transcripts-bge");
        setEmbedUrl(s.embed_url || "");
        setEmbedApiKey(s.embed_api_key || "");
        setPipeAlignment(s.pipeline_alignment ?? true);
        setPipeDiarization(s.pipeline_diarization ?? true);
        setPipeEmotion(s.pipeline_emotion ?? true);
        setPipeSpeakers(s.pipeline_speaker_matching ?? true);
        setAutoSummary(s.auto_summary ?? "off");
        setOpenclawGatewayUrl(s.openclaw_gateway_url || "");
        setOpenclawGatewayToken(s.openclaw_gateway_token || "");
        setOpenclawSummaryAgent(s.openclaw_summary_agent || "");
        setOpenclawChatAgent(s.openclaw_chat_agent || "");
        setWhisperModel(s.whisper_model || "large-v3");
        setWhisperPersistent(s.whisper_persistent ?? true);
        setWhisperPrompt(s.whisper_prompt || "");
        setWhisperIdleTimeout(s.whisper_idle_timeout ?? 1800);
        setWatcherEnabled(s.file_watcher_enabled ?? false);
        setWatcherPath(s.file_watcher_path || "");
        setWatcherExtensions(s.file_watcher_extensions || ".m4a,.mp3,.wav,.ogg,.flac,.opus,.mp4,.webm");
        setWatcherMinSize(s.file_watcher_min_size_kb ?? 10);
        setWatcherCooldown(s.file_watcher_cooldown_seconds ?? 120);
        setWatcherInterval(s.file_watcher_poll_interval_seconds ?? 30);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
    fetchWatcherStatus().then(setWatcherStatus).catch(() => {});
  }, []);

  // Fetch available models when provider is openai_key and we have a key + URL
  useEffect(() => {
    if (provider === "openai_key") {
      loadModels();
    } else {
      setAvailableModels([]);
    }
  }, [provider]);

  const loadModels = async () => {
    setModelsLoading(true);
    try {
      const models = await fetchAvailableModels();
      setAvailableModels(models.map((m) => ({ id: m.id })));
    } catch {
      setAvailableModels([]);
    } finally {
      setModelsLoading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const data: Partial<AppSettings> = {
        llm_provider: provider,
        openai_base_url: openaiBaseUrl,
        openai_model: openaiModel,
        llm_analyze_prompt: analyzePrompt,
        pipeline_alignment: pipeAlignment,
        pipeline_diarization: pipeDiarization,
        pipeline_emotion: pipeEmotion,
        pipeline_speaker_matching: pipeSpeakers,
        auto_summary: autoSummary,
        openclaw_gateway_url: openclawGatewayUrl,
        openclaw_gateway_token: openclawGatewayToken,
        openclaw_summary_agent: openclawSummaryAgent,
        openclaw_chat_agent: openclawChatAgent,
        qdrant_enabled: qdrantEnabled,
        qdrant_url: qdrantUrl,
        qdrant_collection: qdrantCollection,
        embed_url: embedUrl,

        whisper_model: whisperModel,
        whisper_persistent: whisperPersistent,
        whisper_idle_timeout: whisperIdleTimeout,
        whisper_prompt: whisperPrompt,
        file_watcher_enabled: watcherEnabled,
        file_watcher_path: watcherPath,
        file_watcher_extensions: watcherExtensions,
        file_watcher_min_size_kb: watcherMinSize,
        file_watcher_cooldown_seconds: watcherCooldown,
        file_watcher_poll_interval_seconds: watcherInterval,
      };
      if (openaiApiKey && !openaiApiKey.startsWith("***")) {
        data.openai_api_key = openaiApiKey;
      }
      if (qdrantApiKey && !qdrantApiKey.startsWith("***")) {
        data.qdrant_api_key = qdrantApiKey;
      }
      if (embedApiKey && !embedApiKey.startsWith("***")) {
        data.embed_api_key = embedApiKey;
      }
      await saveSettings(data);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleTestLlm = async () => {
    setLlmTest({ status: "testing", message: "Testing..." });
    try {
      const result = await testLlmConnection();
      setLlmTest(result as TestResult);
    } catch (e: any) {
      setLlmTest({ status: "error", message: e.message });
    }
  };

  const handleTestQdrant = async () => {
    setQdrantTest({ status: "testing", message: "Testing..." });
    try {
      const result = await testQdrantConnection();
      setQdrantTest(result as TestResult);
    } catch (e: any) {
      setQdrantTest({ status: "error", message: e.message });
    }
  };

  const handleScanNow = async () => {
    setScanning(true);
    try {
      const result = await triggerWatcherScan();
      const status = await fetchWatcherStatus();
      setWatcherStatus(status);
      if (result.count > 0) {
        setSaved(true);
        setTimeout(() => setSaved(false), 3000);
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setScanning(false);
    }
  };

  if (loading) {
    return (
      <div className="p-6 pt-14 md:pt-6 max-w-3xl mx-auto">
        <div className="flex items-center gap-2 text-vs-text-secondary">
          <Loader2 className="w-5 h-5 animate-spin" />
          Loading settings...
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 pt-14 md:pt-6 max-w-3xl mx-auto overflow-y-auto h-full">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold">Settings</h1>
        <button
          onClick={handleSave}
          disabled={saving}
          className="btn-primary flex items-center gap-2"
        >
          {saving ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : saved ? (
            <CheckCircle className="w-4 h-4" />
          ) : (
            <Save className="w-4 h-4" />
          )}
          {saved ? "Saved" : "Save"}
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* ── LLM Provider ── */}
      <section className="card p-6 mb-4">
        <div className="flex items-center gap-2 mb-4">
          <Brain className="w-5 h-5 text-vs-text-accent" />
          <h2 className="text-lg font-medium">LLM Provider</h2>
        </div>
        <p className="text-sm text-vs-text-secondary mb-4">
          Used for generating titles, summaries, tags, and action items from transcripts.
        </p>

        <div className="space-y-3">
          {/* OpenAI API Key */}
          <label className="flex items-start gap-3 p-3 rounded-lg border border-vs-border hover:border-vs-border-bright cursor-pointer transition-colors">
            <input
              type="radio"
              name="llm_provider"
              value="openai_key"
              checked={provider === "openai_key"}
              onChange={() => setProvider("openai_key")}
              className="mt-1 accent-vs-text-accent"
            />
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <svg className="w-4 h-4 text-amber-400" viewBox="0 0 24 24" fill="currentColor">
                  {/* ChatGPT-style robot face */}
                  <path d="M12 2a8 8 0 0 0-8 8v1a2 2 0 0 0-2 2v2a2 2 0 0 0 2 2h1a7 7 0 0 0 14 0h1a2 2 0 0 0 2-2v-2a2 2 0 0 0-2-2v-1a8 8 0 0 0-8-8Zm-3 9.5a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3Zm6 0a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3Zm-6.5 5.5a4.5 4.5 0 0 0 9 0" fillRule="evenodd"/>
                </svg>
                <span className="font-medium">OpenAI-Compatible API Key</span>
              </div>
              <p className="text-sm text-vs-text-muted mt-1">
                Any OpenAI-compatible endpoint (OpenAI, Ollama, LM Studio, etc.)
              </p>
              {provider === "openai_key" && (
                <div className="mt-3 space-y-3">
                  <div>
                    <label className="block text-sm text-vs-text-secondary mb-1">Endpoint URL</label>
                    <input
                      type="text"
                      value={openaiBaseUrl}
                      onChange={(e) => setOpenaiBaseUrl(e.target.value)}
                      className="input w-full"
                      placeholder="https://api.openai.com/v1"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-vs-text-secondary mb-1">API Key</label>
                    <input
                      type="password"
                      value={openaiApiKey}
                      onChange={(e) => setOpenaiApiKey(e.target.value)}
                      className="input w-full"
                      placeholder="sk-..."
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-vs-text-secondary mb-1">Model</label>
                    <div className="flex items-center gap-2">
                      {availableModels.length > 0 ? (
                        <select
                          value={openaiModel}
                          onChange={(e) => setOpenaiModel(e.target.value)}
                          className="input w-64"
                        >
                          {!availableModels.some((m) => m.id === openaiModel) && (
                            <option value={openaiModel}>{openaiModel}</option>
                          )}
                          {availableModels.map((m) => (
                            <option key={m.id} value={m.id}>
                              {m.id}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          type="text"
                          value={openaiModel}
                          onChange={(e) => setOpenaiModel(e.target.value)}
                          className="input w-64"
                          placeholder="gpt-4o-mini"
                        />
                      )}
                      <button
                        type="button"
                        onClick={loadModels}
                        disabled={modelsLoading}
                        className="btn-ghost text-xs px-2 py-1"
                        title="Fetch available models from API"
                      >
                        {modelsLoading ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <RefreshCw className="w-3.5 h-3.5" />
                        )}
                      </button>
                    </div>
                    <p className="text-xs text-vs-text-muted mt-1">
                      {availableModels.length > 0
                        ? `${availableModels.length} models available`
                        : "Save your API key first, then click refresh to load models"}
                    </p>
                  </div>
                </div>
              )}
            </div>
          </label>

          {/* OpenClaw Proxy */}
          <label className="flex items-start gap-3 p-3 rounded-lg border border-vs-border hover:border-vs-border-bright cursor-pointer transition-colors">
            <input
              type="radio"
              name="llm_provider"
              value="openclaw"
              checked={provider === "openclaw"}
              onChange={() => setProvider("openclaw")}
              className="mt-1 accent-vs-text-accent"
            />
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <svg className="w-4 h-4 text-purple-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  {/* Lobster claw icon for OpenClaw */}
                  <path d="M9 2C6 2 4 5 4 8c0 2 1 3.5 2.5 4.5L4 17l2 2 3-3c.5.2 1 .3 1.5.3" />
                  <path d="M15 2c3 0 5 3 5 6 0 2-1 3.5-2.5 4.5L20 17l-2 2-3-3c-.5.2-1 .3-1.5.3" />
                  <path d="M12 13v8" />
                  <circle cx="12" cy="22" r="1" fill="currentColor" />
                </svg>
                <span className="font-medium">OpenClaw Proxy</span>
              </div>
              <p className="text-sm text-vs-text-muted mt-1">
                Connect to an OpenClaw gateway for multi-agent chat and summarization.
                Requires the openclaw-proxy sidecar container.
              </p>
              {provider === "openclaw" && (
                <div className="mt-3 space-y-3">
                  <div>
                    <label className="block text-sm text-vs-text-secondary mb-1">Gateway URL</label>
                    <input
                      type="text"
                      value={openclawGatewayUrl}
                      onChange={(e) => setOpenclawGatewayUrl(e.target.value)}
                      className="input w-full"
                      placeholder="wss://your-gateway.example.com"
                    />
                    <p className="text-xs text-vs-text-muted mt-1">
                      Your OpenClaw gateway WebSocket URL (from <code>openclaw wizard</code>)
                    </p>
                  </div>
                  <div>
                    <label className="block text-sm text-vs-text-secondary mb-1">Gateway Token</label>
                    <input
                      type="password"
                      value={openclawGatewayToken}
                      onChange={(e) => setOpenclawGatewayToken(e.target.value)}
                      className="input w-full"
                      placeholder="Your gateway authentication token"
                    />
                    <p className="text-xs text-vs-text-muted mt-1">
                      Authentication token for your gateway connection
                    </p>
                  </div>
                  <div>
                    <label className="block text-sm text-vs-text-secondary mb-1">Summary Agent</label>
                    <input
                      type="text"
                      value={openclawSummaryAgent}
                      onChange={(e) => setOpenclawSummaryAgent(e.target.value)}
                      className="input w-full"
                      placeholder="e.g. summarizer"
                    />
                    <p className="text-xs text-vs-text-muted mt-1">
                      Agent ID used for auto-generating titles, summaries, and tags
                    </p>
                  </div>
                  <div>
                    <label className="block text-sm text-vs-text-secondary mb-1">Chat Agent</label>
                    <input
                      type="text"
                      value={openclawChatAgent}
                      onChange={(e) => setOpenclawChatAgent(e.target.value)}
                      className="input w-full"
                      placeholder="e.g. assistant"
                    />
                    <p className="text-xs text-vs-text-muted mt-1">
                      Default agent for the chat sidebar (can switch between agents in chat)
                    </p>
                  </div>
                </div>
              )}
            </div>
          </label>

          {/* Disabled */}
          <label className="flex items-start gap-3 p-3 rounded-lg border border-vs-border hover:border-vs-border-bright cursor-pointer transition-colors">
            <input
              type="radio"
              name="llm_provider"
              value="none"
              checked={provider === "none"}
              onChange={() => setProvider("none")}
              className="mt-1 accent-vs-text-accent"
            />
            <div className="flex-1">
              <span className="font-medium text-vs-text-secondary">Disabled</span>
              <p className="text-sm text-vs-text-muted mt-1">
                Transcription works, but no auto-titles, summaries, or tags.
              </p>
            </div>
          </label>
        </div>

        {/* Analysis Prompt */}
        {provider !== "none" && (
          <div className="mt-4 border-t border-vs-border pt-4">
            <button
              type="button"
              onClick={() => setShowPromptEditor(!showPromptEditor)}
              className="flex items-center gap-2 text-sm text-vs-text-secondary hover:text-vs-text-primary transition-colors"
            >
              {showPromptEditor ? (
                <ChevronDown className="w-3.5 h-3.5" />
              ) : (
                <ChevronRight className="w-3.5 h-3.5" />
              )}
              <FileText className="w-3.5 h-3.5" />
              Customize Analysis Prompt
            </button>
            {showPromptEditor && (
              <div className="mt-3">
                <p className="text-xs text-vs-text-muted mb-2">
                  Customize how the LLM analyzes your transcripts. This prompt tells it what
                  title formats, tags, and outline styles to use. Leave blank for the default.
                </p>
                <textarea
                  value={analyzePrompt || defaultPrompt}
                  onChange={(e) => setAnalyzePrompt(e.target.value)}
                  className="input w-full h-48 text-xs font-mono resize-y"
                  placeholder="Analysis prompt — the transcript text is appended automatically."
                />
                <div className="flex items-center gap-2 mt-2">
                  <button
                    type="button"
                    onClick={() => setAnalyzePrompt("")}
                    className="btn-ghost text-xs flex items-center gap-1"
                  >
                    <RotateCcw className="w-3 h-3" />
                    Reset to Default
                  </button>
                  <span className="text-2xs text-vs-text-muted">
                    {analyzePrompt ? "Using custom prompt" : "Using default prompt"}
                  </span>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Test LLM button */}
        {provider !== "none" && (
          <div className="mt-4 flex items-center gap-3">
            <button
              onClick={handleTestLlm}
              className="btn-ghost text-sm flex items-center gap-2"
            >
              <Zap className="w-3.5 h-3.5" />
              Test Connection
            </button>
            {llmTest && (
              <span
                className={`text-sm flex items-center gap-1.5 ${
                  llmTest.status === "ok"
                    ? "text-emerald-400"
                    : llmTest.status === "error"
                    ? "text-red-400"
                    : "text-vs-text-muted"
                }`}
              >
                {llmTest.status === "testing" ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : llmTest.status === "ok" ? (
                  <CheckCircle className="w-3.5 h-3.5" />
                ) : (
                  <XCircle className="w-3.5 h-3.5" />
                )}
                {llmTest.message}
              </span>
            )}
          </div>
        )}
      </section>

      {/* ── Whisper Model ── */}
      <section className="card p-6 mb-4">
        <div className="flex items-center gap-2 mb-4">
          <Mic className="w-5 h-5 text-vs-text-accent" />
          <h2 className="text-lg font-medium">Whisper Model</h2>
        </div>
        <p className="text-sm text-vs-text-secondary mb-4">
          Configure the Whisper speech-to-text model used for transcription.
        </p>

        <div className="space-y-4">
          {/* Model Selector */}
          <div>
            <label className="block text-sm text-vs-text-secondary mb-1">Model</label>
            <select
              value={whisperModel}
              onChange={(e) => setWhisperModel(e.target.value)}
              className="input w-full"
            >
              <option value="tiny">Tiny (~39 MB) — Fastest, lowest accuracy</option>
              <option value="base">Base (~139 MB) — Fast, basic accuracy</option>
              <option value="small">Small (~461 MB) — Good balance</option>
              <option value="medium">Medium (~1.5 GB) — High accuracy</option>
              <option value="large-v2">Large v2 (~2.9 GB) — Very high accuracy</option>
              <option value="large-v3">Large v3 (~3 GB) — Best accuracy</option>
              <option value="large-v3-turbo">Large v3 Turbo (~1.6 GB) — Near-best accuracy, 4x faster</option>
              <option value="distil-large-v3">Distil Large v3 (~1.5 GB) — Fast, high accuracy</option>
            </select>
            <p className="text-2xs text-vs-text-muted mt-1">
              Changing the model requires downloading it on first use. Larger models are more accurate but use more memory and are slower on CPU.
            </p>
          </div>

          {/* Persistent Mode Toggle */}
          <div className="flex items-center justify-between">
            <div className="flex-1 mr-4">
              <h3 className="text-sm font-medium">Persistent Mode</h3>
              <p className="text-2xs text-vs-text-muted mt-1">
                {whisperPersistent
                  ? "Model stays loaded in memory for fast transcription and API access (port 9000). Uses more RAM but much faster for multiple files."
                  : "Model loads per job and unloads after. Saves memory but slower. API endpoint disabled."}
              </p>
            </div>
            <button
              onClick={() => setWhisperPersistent(!whisperPersistent)}
              className={`relative w-11 h-6 rounded-full transition-colors shrink-0 ${
                whisperPersistent ? "bg-vs-text-accent" : "bg-vs-border"
              }`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${
                  whisperPersistent ? "translate-x-5" : ""
                }`}
              />
            </button>
          </div>

          {/* Idle Auto-Unload */}
          {whisperPersistent && (
            <div className="flex items-center justify-between">
              <div className="flex-1 mr-4">
                <h3 className="text-sm font-medium">Idle Auto-Unload</h3>
                <p className="text-2xs text-vs-text-muted mt-1">
                  {whisperIdleTimeout > 0
                    ? `Unload model after ${whisperIdleTimeout >= 60 ? `${Math.floor(whisperIdleTimeout / 60)} min` : `${whisperIdleTimeout}s`} of inactivity to free VRAM. First request after unload takes ~4s to reload.`
                    : "Model stays loaded permanently. Uses ~4 GB VRAM at all times."}
                </p>
              </div>
              <select
                value={whisperIdleTimeout}
                onChange={(e) => setWhisperIdleTimeout(Number(e.target.value))}
                className="input w-32 text-sm"
              >
                <option value={0}>Never</option>
                <option value={300}>5 min</option>
                <option value={600}>10 min</option>
                <option value={1800}>30 min</option>
                <option value={3600}>1 hour</option>
                <option value={7200}>2 hours</option>
              </select>
            </div>
          )}

          {/* Transcription Prompt (collapsible) */}
          <div className="border-t border-vs-border pt-4">
            <button
              type="button"
              onClick={() => setShowWhisperPrompt(!showWhisperPrompt)}
              className="flex items-center gap-2 text-sm text-vs-text-secondary hover:text-vs-text-primary transition-colors"
            >
              {showWhisperPrompt ? (
                <ChevronDown className="w-3.5 h-3.5" />
              ) : (
                <ChevronRight className="w-3.5 h-3.5" />
              )}
              <FileText className="w-3.5 h-3.5" />
              Transcription Prompt
            </button>
            {showWhisperPrompt && (
              <div className="mt-3">
                <p className="text-xs text-vs-text-muted mb-2">
                  Help Whisper recognize domain-specific words, names, and terms. Add custom spellings, technical vocabulary, or proper nouns.
                </p>
                <textarea
                  value={whisperPrompt}
                  onChange={(e) => setWhisperPrompt(e.target.value)}
                  className="input w-full h-32 text-xs font-mono resize-y"
                  placeholder="e.g. Technical terms: Kubernetes, PostgreSQL, Terraform. Names: Dr. Sarah Chen, John McAllister."
                />
                <div className="flex items-center gap-2 mt-2">
                  <button
                    type="button"
                    onClick={() => setWhisperPrompt("")}
                    className="btn-ghost text-xs flex items-center gap-1"
                  >
                    <RotateCcw className="w-3 h-3" />
                    Reset to Default
                  </button>
                  <span className="text-2xs text-vs-text-muted">
                    {whisperPrompt ? "Using custom prompt" : "No prompt set"}
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* ── Processing Pipeline ── */}
      <section className="card p-6 mb-4">
        <div className="flex items-center gap-2 mb-4">
          <Settings className="w-5 h-5 text-vs-text-accent" />
          <h2 className="text-lg font-medium">Processing Pipeline</h2>
        </div>
        <p className="text-sm text-vs-text-secondary mb-5">
          Toggle pipeline stages for new recordings. Transcription always runs.
        </p>

        {/* Pipeline flow visualization */}
        <div className="flex items-center gap-1 flex-wrap mb-6">
          {/* Transcription - always on */}
          <div className="flex items-center gap-1">
            <div className="px-3 py-2 rounded-lg bg-vs-text-accent/15 border border-vs-text-accent/30 text-vs-text-accent text-xs font-medium">
              Transcription
            </div>
            <ChevronRight className="w-4 h-4 text-vs-text-muted shrink-0" />
          </div>

          {/* Alignment */}
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPipeAlignment(!pipeAlignment)}
              className={`px-3 py-2 rounded-lg border text-xs font-medium transition-all ${
                pipeAlignment
                  ? "bg-emerald-500/15 border-emerald-500/30 text-emerald-400"
                  : "bg-vs-hover/30 border-vs-border text-vs-text-muted line-through"
              }`}
            >
              Alignment
            </button>
            <ChevronRight className="w-4 h-4 text-vs-text-muted shrink-0" />
          </div>

          {/* Diarization */}
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPipeDiarization(!pipeDiarization)}
              className={`px-3 py-2 rounded-lg border text-xs font-medium transition-all ${
                pipeDiarization
                  ? "bg-emerald-500/15 border-emerald-500/30 text-emerald-400"
                  : "bg-vs-hover/30 border-vs-border text-vs-text-muted line-through"
              }`}
            >
              Diarization
            </button>
            <ChevronRight className="w-4 h-4 text-vs-text-muted shrink-0" />
          </div>

          {/* Emotion */}
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPipeEmotion(!pipeEmotion)}
              className={`px-3 py-2 rounded-lg border text-xs font-medium transition-all ${
                pipeEmotion
                  ? "bg-emerald-500/15 border-emerald-500/30 text-emerald-400"
                  : "bg-vs-hover/30 border-vs-border text-vs-text-muted line-through"
              }`}
            >
              Emotion
            </button>
            <ChevronRight className="w-4 h-4 text-vs-text-muted shrink-0" />
          </div>

          {/* Speaker Matching */}
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPipeSpeakers(!pipeSpeakers)}
              className={`px-3 py-2 rounded-lg border text-xs font-medium transition-all ${
                pipeSpeakers
                  ? "bg-emerald-500/15 border-emerald-500/30 text-emerald-400"
                  : "bg-vs-hover/30 border-vs-border text-vs-text-muted line-through"
              }`}
            >
              Speaker Matching
            </button>
          </div>
        </div>

        <p className="text-2xs text-vs-text-muted mb-1">
          Click a stage to toggle it. Dependent stages auto-toggle together.
        </p>

        {/* Auto-Summary */}
        <div className="mt-5 pt-5 border-t border-vs-border">
          <div className="flex items-center gap-2 mb-3">
            <FileText className="w-4 h-4 text-vs-text-accent" />
            <h3 className="text-sm font-medium">Auto-Summary</h3>
          </div>
          <p className="text-sm text-vs-text-secondary mb-3">
            Automatically generate a summary after processing completes. Requires an LLM provider.
          </p>
          <div className="space-y-2">
            <label className="flex items-center gap-3 p-2.5 rounded-lg border border-vs-border hover:border-vs-border-bright cursor-pointer transition-colors">
              <input
                type="radio"
                name="auto_summary"
                value="off"
                checked={autoSummary === "off"}
                onChange={() => setAutoSummary("off")}
                className="accent-vs-text-accent"
              />
              <span className="text-sm">Off</span>
            </label>
            <label className="flex items-center gap-3 p-2.5 rounded-lg border border-vs-border hover:border-vs-border-bright cursor-pointer transition-colors">
              <input
                type="radio"
                name="auto_summary"
                value="all"
                checked={autoSummary === "all"}
                onChange={() => setAutoSummary("all")}
                className="accent-vs-text-accent"
              />
              <span className="text-sm">All recordings</span>
            </label>
            <label className="flex items-center gap-3 p-2.5 rounded-lg border border-vs-border hover:border-vs-border-bright cursor-pointer transition-colors">
              <input
                type="radio"
                name="auto_summary"
                value="known_speakers_only"
                checked={autoSummary === "known_speakers_only"}
                onChange={() => setAutoSummary("known_speakers_only")}
                className="accent-vs-text-accent"
              />
              <div>
                <span className="text-sm">Only recognized speakers</span>
                <p className="text-2xs text-vs-text-muted mt-0.5">
                  Only auto-summarize when all detected speakers are recognized.
                </p>
              </div>
            </label>
          </div>
          {autoSummary !== "off" && provider === "none" && (
            <p className="text-2xs text-amber-400 mt-2">
              Auto-summary requires an LLM provider to be configured above.
            </p>
          )}
        </div>
      </section>

      {/* ── Semantic Search ── */}
      <section className="card p-6 mb-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Database className="w-5 h-5 text-vs-text-accent" />
            <h2 className="text-lg font-medium">Semantic Search</h2>
          </div>
          <button
            onClick={() => setQdrantEnabled(!qdrantEnabled)}
            className={`relative w-11 h-6 rounded-full transition-colors ${
              qdrantEnabled ? "bg-vs-text-accent" : "bg-vs-border"
            }`}
          >
            <span
              className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${
                qdrantEnabled ? "translate-x-5" : ""
              }`}
            />
          </button>
        </div>
        <p className="text-sm text-vs-text-secondary mb-4">
          Index transcripts in Qdrant for natural language search across recordings.
        </p>

        {qdrantEnabled && (
          <div className="space-y-3">
            <div>
              <label className="block text-sm text-vs-text-secondary mb-1">Qdrant URL</label>
              <input
                type="text"
                value={qdrantUrl}
                onChange={(e) => setQdrantUrl(e.target.value)}
                className="input w-full"
                placeholder="http://localhost:6333"
              />
            </div>
            <div>
              <label className="block text-sm text-vs-text-secondary mb-1">Qdrant API Key</label>
              <input
                type="password"
                value={qdrantApiKey}
                onChange={(e) => setQdrantApiKey(e.target.value)}
                className="input w-full"
                placeholder="Optional — required for Qdrant Cloud"
              />
            </div>
            <div>
              <label className="block text-sm text-vs-text-secondary mb-1">Collection Name</label>
              <input
                type="text"
                value={qdrantCollection}
                onChange={(e) => setQdrantCollection(e.target.value)}
                className="input w-full"
                placeholder="vs3-transcripts-bge"
              />
              <p className="text-2xs text-vs-text-muted mt-1">
                Qdrant collection to store transcript embeddings in.
              </p>
            </div>
            <div>
              <label className="block text-sm text-vs-text-secondary mb-1">Embedding API URL</label>
              <input
                type="text"
                value={embedUrl}
                onChange={(e) => setEmbedUrl(e.target.value)}
                className="input w-full"
                placeholder="http://localhost:7997/embeddings"
              />
            </div>
            <div>
              <label className="block text-sm text-vs-text-secondary mb-1">Embedding API Key</label>
              <input
                type="password"
                value={embedApiKey}
                onChange={(e) => setEmbedApiKey(e.target.value)}
                className="input w-full"
                placeholder="Optional"
              />
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={handleTestQdrant}
                className="btn-ghost text-sm flex items-center gap-2"
              >
                <Zap className="w-3.5 h-3.5" />
                Test Connection
              </button>
              {qdrantTest && (
                <span
                  className={`text-sm flex items-center gap-1.5 ${
                    qdrantTest.status === "ok"
                      ? "text-emerald-400"
                      : qdrantTest.status === "error"
                      ? "text-red-400"
                      : "text-vs-text-muted"
                  }`}
                >
                  {qdrantTest.status === "testing" ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : qdrantTest.status === "ok" ? (
                    <CheckCircle className="w-3.5 h-3.5" />
                  ) : (
                    <XCircle className="w-3.5 h-3.5" />
                  )}
                  {qdrantTest.message}
                </span>
              )}
            </div>
          </div>
        )}
      </section>

      {/* ── File Watcher ── */}
      <section className="card p-6 mb-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <FolderOpen className="w-5 h-5 text-vs-text-accent" />
            <h2 className="text-lg font-medium">File Watcher</h2>
          </div>
          <button
            onClick={() => setWatcherEnabled(!watcherEnabled)}
            className={`relative w-11 h-6 rounded-full transition-colors ${
              watcherEnabled ? "bg-vs-text-accent" : "bg-vs-border"
            }`}
          >
            <span
              className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${
                watcherEnabled ? "translate-x-5" : ""
              }`}
            />
          </button>
        </div>
        <p className="text-sm text-vs-text-secondary mb-4">
          Automatically process audio files dropped into a watched directory.
        </p>

        {watcherEnabled && (
          <div className="space-y-3">
            <div>
              <label className="block text-sm text-vs-text-secondary mb-1">Watch Directory</label>
              <input
                type="text"
                value={watcherPath}
                onChange={(e) => setWatcherPath(e.target.value)}
                className="input w-full"
                placeholder="~/VoiceStack Dropbox"
              />
            </div>
            <div>
              <label className="block text-sm text-vs-text-secondary mb-1">File Extensions</label>
              <input
                type="text"
                value={watcherExtensions}
                onChange={(e) => setWatcherExtensions(e.target.value)}
                className="input w-full"
                placeholder=".m4a,.mp3,.wav,.ogg,.flac"
              />
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="block text-sm text-vs-text-secondary mb-1">Min Size (KB)</label>
                <input
                  type="number"
                  value={watcherMinSize}
                  onChange={(e) => setWatcherMinSize(Number(e.target.value))}
                  className="input w-full"
                  min={0}
                />
              </div>
              <div>
                <label className="block text-sm text-vs-text-secondary mb-1">Cooldown (sec)</label>
                <input
                  type="number"
                  value={watcherCooldown}
                  onChange={(e) => setWatcherCooldown(Number(e.target.value))}
                  className="input w-full"
                  min={0}
                />
              </div>
              <div>
                <label className="block text-sm text-vs-text-secondary mb-1">Poll Interval (sec)</label>
                <input
                  type="number"
                  value={watcherInterval}
                  onChange={(e) => setWatcherInterval(Number(e.target.value))}
                  className="input w-full"
                  min={5}
                />
              </div>
            </div>

            {/* Watcher status */}
            {watcherStatus && (
              <div className="flex items-center gap-4 text-sm text-vs-text-muted pt-2">
                <span className="flex items-center gap-1.5">
                  <Eye className="w-3.5 h-3.5" />
                  {watcherStatus.files_processed} files processed
                </span>
                {watcherStatus.last_scan && (
                  <span>
                    Last scan: {new Date(watcherStatus.last_scan).toLocaleTimeString()}
                  </span>
                )}
              </div>
            )}

            <div className="flex items-center gap-3">
              <button
                onClick={handleScanNow}
                disabled={scanning}
                className="btn-ghost text-sm flex items-center gap-2"
              >
                {scanning ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Play className="w-3.5 h-3.5" />
                )}
                Scan Now
              </button>
            </div>
          </div>
        )}
      </section>

      {/* Footer note */}
      <p className="text-2xs text-vs-text-muted text-center pb-6">
        Settings are stored in the database. Environment variables are used as fallback.
      </p>
    </div>
  );
}
