"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  Sparkles,
  Loader2,
  MessageSquare,
  Clock,
  AlertCircle,
  CheckCircle2,
  RotateCcw,
  Trash2,
  Pencil,
  Plus,
  X,
  Check,
} from "lucide-react";
import Link from "next/link";
import {
  fetchJob,
  fetchTranscriptByJob,
  subscribeToProgress,
  generateOverview,
  resummarize,
  toggleActionItem,
  updateOverview,
  fetchIndexStatus,
  reprocessJob,
  deleteJob,
  updateTranscriptTitle,
  audioUrl,
  type Job,
  type Transcript,
  type Segment,
  type Overview,
  type ActionItem,
  type JobProgress,
} from "@/lib/api";
import { usePlayerStore, useTranscriptStore, getSpeakerColor } from "@/lib/store";
import { formatTime } from "@/lib/utils";
import { AudioPlayer } from "@/components/audio-player";
import { EmotionBadge } from "@/components/emotion-badge";
import { SpeakerLabel } from "@/components/speaker-label";
import { ChatSidebar } from "@/components/chat-sidebar";
import { LogsPanel } from "@/components/logs-panel";
import { AssigneePicker } from "@/components/assignee-picker";

type Tab = "transcript" | "summary";

export default function JobDetailPage() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const jobId = params.id as string;
  const highlightSegmentId = searchParams.get("highlight");
  const seekTime = searchParams.get("t");

  const [job, setJob] = useState<Job | null>(null);
  const [tab, setTab] = useState<Tab>("transcript");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [generatingOverview, setGeneratingOverview] = useState(false);
  const [loading, setLoading] = useState(true);
  const [chatOpen, setChatOpen] = useState(false);
  const [liveProgress, setLiveProgress] = useState<JobProgress | null>(null);
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [indexStatus, setIndexStatus] = useState<string>("unknown");
  const titleInputRef = useRef<HTMLInputElement>(null);

  const { currentTime, seekTo, setIsPlaying } = usePlayerStore();
  const { transcript, setTranscript, activeSegmentIdx, setActiveSegmentIdx } =
    useTranscriptStore();

  const segmentRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  // Load job + transcript
  useEffect(() => {
    async function load() {
      try {
        const jobData = await fetchJob(jobId);
        setJob(jobData);

        // Only try to load transcript if job is completed
        const status = jobData.status.toLowerCase();
        if (status === "completed") {
          try {
            const transcriptData = await fetchTranscriptByJob(jobId);
            setTranscript(transcriptData);

            if (transcriptData.summary) {
              try {
                const parsed = JSON.parse(transcriptData.summary);
                setOverview(parsed);
              } catch {
                setOverview({
                  title: transcriptData.title || "",
                  summary: transcriptData.summary,
                  action_items: [],
                  outline: [],
                });
              }
            }
          } catch {
            // Transcript may not exist yet even if job says completed
          }
        }
      } catch (err) {
        console.error("Failed to load:", err);
      } finally {
        setLoading(false);
      }
    }
    load();
    return () => setTranscript(null);
  }, [jobId, setTranscript]);

  // Poll Qdrant index status
  useEffect(() => {
    if (!transcript) return;
    let cancelled = false;

    const check = async () => {
      const result = await fetchIndexStatus(transcript.id);
      if (!cancelled) {
        setIndexStatus(result.status);
        // Keep polling while indexing
        if (result.status === "indexing" || result.status === "stale") {
          setTimeout(check, 2000);
        }
      }
    };
    check();
    return () => { cancelled = true; };
  }, [transcript?.id, overview]);

  // Subscribe to SSE progress if job is not completed
  useEffect(() => {
    if (!job) return;
    const status = job.status.toLowerCase();
    if (status === "completed" || status === "failed") return;

    const unsub = subscribeToProgress(
      jobId,
      (data) => {
        setLiveProgress(data);
      },
      async () => {
        // Job finished - reload job and transcript
        try {
          const jobData = await fetchJob(jobId);
          setJob(jobData);
          if (jobData.status.toLowerCase() === "completed") {
            const transcriptData = await fetchTranscriptByJob(jobId);
            setTranscript(transcriptData);
            setLiveProgress(null);

            if (transcriptData.summary) {
              try {
                setOverview(JSON.parse(transcriptData.summary));
              } catch {
                setOverview({
                  title: transcriptData.title || "",
                  summary: transcriptData.summary,
                  action_items: [],
                  outline: [],
                });
              }
            }
          }
        } catch (err) {
          console.error("Failed to reload after completion:", err);
        }
      }
    );

    return unsub;
  }, [job, jobId, setTranscript]);

  // Track active segment based on playback time
  useEffect(() => {
    if (!transcript) return;
    const idx = transcript.segments.findIndex(
      (seg) => currentTime >= seg.start_time && currentTime < seg.end_time
    );
    if (idx !== -1 && idx !== activeSegmentIdx) {
      setActiveSegmentIdx(idx);
    }
  }, [currentTime, transcript, activeSegmentIdx, setActiveSegmentIdx]);

  // Auto-scroll to active segment
  useEffect(() => {
    if (activeSegmentIdx >= 0) {
      const el = segmentRefs.current.get(activeSegmentIdx);
      el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [activeSegmentIdx]);

  // Deep-link: highlight segment and seek audio from search results
  const [highlightedIdx, setHighlightedIdx] = useState<number | null>(null);
  useEffect(() => {
    if (!transcript || !highlightSegmentId) return;
    const idx = transcript.segments.findIndex(
      (seg) => seg.id === highlightSegmentId
    );
    if (idx === -1) return;

    // Scroll to segment
    const el = segmentRefs.current.get(idx);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      setHighlightedIdx(idx);
      // Remove highlight after 2s
      const timer = setTimeout(() => setHighlightedIdx(null), 2000);
      return () => clearTimeout(timer);
    }
  }, [transcript, highlightSegmentId]);

  // Seek audio to timestamp from search deep-link
  useEffect(() => {
    if (!seekTime || !transcript) return;
    const t = parseFloat(seekTime);
    if (!isNaN(t)) {
      usePlayerStore.getState().seekTo(t);
    }
  }, [seekTime, transcript]);

  const handleSegmentClick = (seg: Segment, idx: number) => {
    const audio = usePlayerStore.getState().audioRef;
    if (!audio) return;

    // Pause first to avoid AbortError from play() during seek
    audio.pause();

    // Always wait for seeked event before playing.
    // Setting currentTime is async — playing before seek completes
    // causes AbortError or plays from the wrong position.
    const playAfterSeek = () => {
      audio.play().catch((e) => console.warn("[audio] play after seek failed:", e));
    };
    audio.addEventListener("seeked", playAfterSeek, { once: true });

    audio.currentTime = seg.start_time;
    usePlayerStore.getState().setCurrentTime(seg.start_time);
    setIsPlaying(true);
  };

  const handleGenerateOverview = async () => {
    if (!transcript) return;
    setGeneratingOverview(true);
    try {
      const result = await generateOverview(transcript.id);
      setOverview(result);
    } catch (err) {
      console.error("Failed to generate overview:", err);
    } finally {
      setGeneratingOverview(false);
    }
  };

  const reloadTranscript = async () => {
    try {
      const data = await fetchTranscriptByJob(jobId);
      setTranscript(data);
    } catch (err) {
      console.error("Failed to reload transcript:", err);
    }
  };

  const [resummarizing, setResummarizing] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const handleDelete = async () => {
    if (!job) return;
    setDeleting(true);
    try {
      await deleteJob(jobId);
      router.push("/");
    } catch (err) {
      console.error("Failed to delete:", err);
      setDeleting(false);
      setConfirmDelete(false);
    }
  };

  const handleResummarize = async () => {
    if (!transcript) return;
    setResummarizing(true);
    try {
      const result = await resummarize(transcript.id);
      setOverview(result);
    } catch (err) {
      console.error("Failed to resummarize:", err);
    } finally {
      setResummarizing(false);
    }
  };

  const handleReprocess = async () => {
    if (!job) return;
    setReprocessing(true);
    try {
      await reprocessJob(jobId);
      setTranscript(null);
      setOverview(null);
      setLiveProgress(null);
      setJob({ ...job, status: "QUEUED", progress: 0, pipeline_stage: null, error_message: null });
    } catch (err) {
      console.error("Failed to reprocess:", err);
    } finally {
      setReprocessing(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center flex-1">
        <Loader2 className="w-6 h-6 text-vs-text-muted animate-spin" />
      </div>
    );
  }

  // Job is still processing - show progress screen
  if (!transcript && job) {
    const status = liveProgress?.status?.toLowerCase() || job.status.toLowerCase();
    const progress = liveProgress?.progress ?? job.progress ?? 0;
    const stage = liveProgress?.stage || job.pipeline_stage;

    return (
      <div className="flex flex-col flex-1 min-h-0">
        <div className="border-b border-vs-border px-6 py-4 pt-14 md:pt-4 shrink-0">
          <div className="flex items-center gap-3">
            <Link
              href="/"
              className="text-vs-text-muted hover:text-vs-text-primary transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
            </Link>
            <h1 className="text-lg font-semibold truncate flex-1">
              {job.asset?.filename || `Recording`}
            </h1>
          </div>
        </div>

        <div className="flex-1 flex flex-col items-center justify-center gap-6 px-6">
          {status === "failed" ? (
            <>
              <AlertCircle className="w-12 h-12 text-status-failed" />
              <div className="text-center">
                <p className="text-vs-text-primary font-medium mb-1">Processing Failed</p>
                <p className="text-sm text-vs-text-muted max-w-md">
                  {job.error_message || "An error occurred during processing."}
                </p>
              </div>
              <div className="flex gap-3">
                <button
                  onClick={handleReprocess}
                  disabled={reprocessing}
                  className="btn-primary flex items-center gap-2"
                >
                  {reprocessing ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <RotateCcw className="w-4 h-4" />
                  )}
                  Reprocess
                </button>
                <Link href="/" className="btn-ghost">
                  Back to Recordings
                </Link>
              </div>
            </>
          ) : (
            <>
              {status === "queued" ? (
                <Clock className="w-12 h-12 text-status-queued animate-pulse" />
              ) : (
                <Loader2 className="w-12 h-12 text-vs-text-accent animate-spin" />
              )}

              <div className="text-center">
                <p className="text-vs-text-primary font-medium mb-1">
                  {status === "queued" ? "Queued for Processing" : "Processing Recording"}
                </p>
                {stage && (
                  <p className="text-sm text-vs-text-accent mb-3">
                    {stage.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase())}
                  </p>
                )}
                <p className="text-xs text-vs-text-muted">
                  This page will update automatically when ready
                </p>
              </div>

              {/* Progress bar */}
              <div className="w-64">
                <div className="h-2 bg-vs-raised rounded-full overflow-hidden">
                  <div
                    className="h-full bg-vs-text-accent rounded-full transition-all duration-700 ease-out"
                    style={{ width: `${progress}%` }}
                  />
                </div>
                <p className="text-2xs text-vs-text-muted text-center mt-2">
                  {Math.round(progress)}%
                </p>
              </div>
            </>
          )}
        </div>

        {/* Logs Panel - pinned to bottom */}
        {status !== "failed" && (
          <LogsPanel jobId={jobId} />
        )}
      </div>
    );
  }

  // No job at all
  if (!job) {
    return (
      <div className="p-6 pt-14 md:pt-6 flex-1">
        <Link href="/" className="btn-ghost inline-flex items-center gap-2 mb-4">
          <ArrowLeft className="w-4 h-4" /> Back
        </Link>
        <p className="text-vs-text-secondary">Recording not found.</p>
      </div>
    );
  }

  const transcriptSpeakers = (() => {
    if (!transcript) return [];
    const seen = new Map<string, typeof transcript.segments[0]["speaker"]>();
    for (const seg of transcript.segments) {
      if (seg.speaker && !seen.has(seg.speaker.id)) {
        seen.set(seg.speaker.id, seg.speaker);
      }
    }
    return Array.from(seen.values()).filter(Boolean) as {
      id: string; name: string; avatar_id: number | null; custom_avatar: string | null;
    }[];
  })();

  const title =
    overview?.title || transcript!.title || job.asset?.filename || "Untitled Recording";

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Top section: content + sidebar side by side */}
      <div className="flex flex-1 min-h-0">
        {/* Main content */}
        <div className="flex flex-col flex-1 min-w-0 min-h-0">
          {/* Header */}
          <div className="border-b border-vs-border px-6 py-4 pt-14 md:pt-4 shrink-0">
            <div className="flex items-center gap-3 mb-3">
              <Link
                href="/"
                className="text-vs-text-muted hover:text-vs-text-primary transition-colors"
              >
                <ArrowLeft className="w-4 h-4" />
              </Link>
              {editingTitle ? (
                <input
                  ref={titleInputRef}
                  type="text"
                  value={titleDraft}
                  onChange={(e) => setTitleDraft(e.target.value)}
                  onBlur={async () => {
                    const trimmed = titleDraft.trim();
                    if (trimmed && trimmed !== title && transcript) {
                      try {
                        await updateTranscriptTitle(transcript.id, trimmed);
                        setTranscript({ ...transcript, title: trimmed });
                      } catch {}
                    }
                    setEditingTitle(false);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                    if (e.key === "Escape") setEditingTitle(false);
                  }}
                  className="text-lg font-semibold flex-1 bg-transparent border-b border-vs-text-accent outline-none"
                  autoFocus
                />
              ) : (
                <h1
                  className="text-lg font-semibold truncate flex-1 cursor-pointer hover:text-vs-text-accent transition-colors"
                  onClick={() => {
                    if (transcript) {
                      setTitleDraft(title);
                      setEditingTitle(true);
                    }
                  }}
                  title="Click to rename"
                >
                  {title}
                </h1>
              )}
              {/* Qdrant index status indicator */}
              {indexStatus !== "unknown" && indexStatus !== "disabled" && (
                <div
                  className="relative group"
                  title={
                    indexStatus === "indexed" ? "Indexed in Qdrant" :
                    indexStatus === "indexing" ? "Indexing..." :
                    indexStatus === "stale" ? "Index out of date" :
                    indexStatus === "failed" ? "Index failed" : "Not indexed"
                  }
                >
                  <div className={`w-2.5 h-2.5 rounded-full transition-colors ${
                    indexStatus === "indexed" ? "bg-status-completed" :
                    indexStatus === "indexing" ? "bg-vs-text-accent animate-pulse" :
                    indexStatus === "stale" ? "bg-yellow-500" :
                    indexStatus === "failed" ? "bg-status-failed" : "bg-vs-text-muted"
                  }`} />
                </div>
              )}
              <button
                onClick={handleReprocess}
                disabled={reprocessing}
                className="p-2 rounded-lg text-vs-text-muted hover:text-vs-text-primary hover:bg-vs-hover transition-colors"
                title="Reprocess with latest pipeline"
              >
                {reprocessing ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <RotateCcw className="w-4 h-4" />
                )}
              </button>
              {confirmDelete ? (
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={handleDelete}
                    disabled={deleting}
                    className="px-2.5 py-1 text-xs font-medium bg-status-failed/15 text-status-failed rounded hover:bg-status-failed/25 transition-colors"
                  >
                    {deleting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : "Delete"}
                  </button>
                  <button
                    onClick={() => setConfirmDelete(false)}
                    className="px-2.5 py-1 text-xs text-vs-text-muted rounded hover:bg-vs-hover transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setConfirmDelete(true)}
                  className="p-2 rounded-lg text-vs-text-muted hover:text-status-failed hover:bg-status-failed/10 transition-colors"
                  title="Delete recording"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              )}
              <button
                onClick={() => setChatOpen(!chatOpen)}
                className={`p-2 rounded-lg transition-colors ${
                  chatOpen
                    ? "bg-vs-text-accent/15 text-vs-text-accent"
                    : "text-vs-text-muted hover:text-vs-text-primary hover:bg-vs-hover"
                }`}
                title="AI Chat"
              >
                <MessageSquare className="w-4 h-4" />
              </button>
            </div>

            {/* Tabs */}
            <div className="flex gap-1">
              {(["summary", "transcript"] as Tab[]).map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                    tab === t
                      ? "bg-vs-hover text-vs-text-primary"
                      : "text-vs-text-secondary hover:text-vs-text-primary"
                  }`}
                >
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                </button>
              ))}
            </div>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-auto min-h-0">
            {tab === "transcript" ? (
              <TranscriptTab
                segments={transcript!.segments}
                activeIdx={activeSegmentIdx}
                currentTime={currentTime}
                onSegmentClick={handleSegmentClick}
                onSpeakerChanged={reloadTranscript}
                segmentRefs={segmentRefs}
                highlightedIdx={highlightedIdx}
              />
            ) : (
              <SummaryTab
                overview={overview}
                generating={generatingOverview}
                onGenerate={handleGenerateOverview}
                transcriptId={transcript!.id}
                onOverviewUpdate={setOverview}
                resummarizing={resummarizing}
                onResummarize={handleResummarize}
                speakers={transcriptSpeakers}
              />
            )}
          </div>
        </div>

        {/* Chat Sidebar */}
        <ChatSidebar
          transcriptId={transcript!.id}
          isOpen={chatOpen}
          onClose={() => setChatOpen(false)}
        />
      </div>

      {/* Audio Player - spans full width below content+sidebar */}
      <AudioPlayer src={audioUrl(jobId)} />
    </div>
  );
}

// ─── Transcript Tab ──────────────────────────────────────────────────────────

function TranscriptTab({
  segments,
  activeIdx,
  currentTime,
  onSegmentClick,
  onSpeakerChanged,
  segmentRefs,
  highlightedIdx,
}: {
  segments: Segment[];
  activeIdx: number;
  currentTime: number;
  onSegmentClick: (seg: Segment, idx: number) => void;
  onSpeakerChanged: () => void;
  segmentRefs: React.MutableRefObject<Map<number, HTMLDivElement>>;
  highlightedIdx: number | null;
}) {
  return (
    <div className="px-4 py-4 space-y-0.5">
      {segments.map((seg, idx) => {
        const isActive = idx === activeIdx;

        return (
          <div
            key={seg.id}
            ref={(el) => {
              if (el) segmentRefs.current.set(idx, el);
            }}
            className={`segment-row ${isActive ? "active" : ""} ${highlightedIdx === idx ? "ring-2 ring-vs-text-accent/40 transition-shadow duration-500" : ""}`}
            onClick={() => onSegmentClick(seg, idx)}
          >
            {/* Speaker */}
            <SpeakerLabel
              speaker={seg.speaker}
              segmentId={seg.id}
              onSpeakerChanged={onSpeakerChanged}
            />

            {/* Timestamp */}
            <span className="text-2xs font-mono text-vs-text-muted shrink-0 pt-0.5 w-12 text-right">
              {formatTime(seg.start_time)}
            </span>

            {/* Text with word highlighting + speech events */}
            <div className="flex-1 min-w-0">
              <p className="text-sm leading-relaxed">
                {seg.word_timings && seg.word_timings.length > 0 ? (
                  seg.word_timings.map((w, wi) => {
                    const isWordActive =
                      isActive && currentTime >= w.start && currentTime < w.end;
                    return (
                      <span
                        key={wi}
                        className={
                          isWordActive
                            ? "bg-vs-text-accent/20 text-vs-text-accent rounded px-0.5 transition-colors duration-75"
                            : ""
                        }
                      >
                        {w.word}{" "}
                      </span>
                    );
                  })
                ) : (
                  <span>{seg.text}</span>
                )}
                {seg.speech_events?.length > 0 && (
                  <>
                    {" "}
                    {seg.speech_events.map((evt, ei) => (
                      <span
                        key={ei}
                        className="text-vs-text-muted italic text-xs"
                      >
                        [{evt.toLowerCase().replace(/_/g, " ")}]
                        {ei < seg.speech_events.length - 1 ? " " : ""}
                      </span>
                    ))}
                  </>
                )}
              </p>
            </div>

            {/* Emotion */}
            <EmotionBadge
              emotion={seg.emotion}
              confidence={seg.emotion_confidence}
            />
          </div>
        );
      })}
    </div>
  );
}

// ─── Summary Tab ─────────────────────────────────────────────────────────────

function SummaryTab({
  overview,
  generating,
  onGenerate,
  transcriptId,
  onOverviewUpdate,
  resummarizing,
  onResummarize,
  speakers,
}: {
  overview: Overview | null;
  generating: boolean;
  onGenerate: () => void;
  transcriptId: string | null;
  onOverviewUpdate: (overview: Overview) => void;
  resummarizing: boolean;
  onResummarize: () => void;
  speakers: { id: string; name: string; avatar_id: number | null; custom_avatar: string | null }[];
}) {
  if (!overview && !generating) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <Sparkles className="w-10 h-10 text-vs-text-muted mb-4" />
        <p className="text-vs-text-secondary mb-2">No overview generated yet</p>
        <button onClick={onGenerate} className="btn-primary flex items-center gap-2">
          <Sparkles className="w-4 h-4" />
          Generate Overview
        </button>
      </div>
    );
  }

  if (generating) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <Loader2 className="w-8 h-8 text-vs-text-accent animate-spin mb-4" />
        <p className="text-vs-text-secondary">Generating overview...</p>
      </div>
    );
  }

  const [editing, setEditing] = useState(false);
  const [editSummary, setEditSummary] = useState("");
  const [editItems, setEditItems] = useState<{ text: string; checked: boolean; assignee?: string | null }[]>([]);
  const [editOutline, setEditOutline] = useState<{ heading: string; content: string }[]>([]);
  const [saving, setSaving] = useState(false);

  const startEditing = () => {
    if (!overview) return;
    setEditSummary(overview.summary || "");
    setEditItems(
      overview.action_items.map((item) =>
        typeof item === "string"
          ? { text: item, checked: false, assignee: null }
          : { text: item.text, checked: item.checked, assignee: item.assignee || null }
      )
    );
    setEditOutline(overview.outline.map((o) => ({ heading: o.heading, content: o.content })));
    setEditing(true);
  };

  const saveEdits = async () => {
    if (!transcriptId) return;
    setSaving(true);
    try {
      const result = await updateOverview(transcriptId, {
        summary: editSummary,
        action_items: editItems,
        outline: editOutline,
      });
      onOverviewUpdate(result);
      setEditing(false);
    } catch (err) {
      console.error("Failed to save overview:", err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="px-6 py-6 max-w-3xl space-y-8">
      {/* Edit toggle */}
      <div className="flex justify-end">
        {editing ? (
          <div className="flex items-center gap-2">
            <button
              onClick={() => setEditing(false)}
              className="px-3 py-1 text-xs text-vs-text-muted hover:text-vs-text-secondary rounded transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={saveEdits}
              disabled={saving}
              className="px-3 py-1 text-xs font-medium bg-vs-text-accent/15 text-vs-text-accent rounded hover:bg-vs-text-accent/25 transition-colors flex items-center gap-1.5"
            >
              {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
              Save
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <button
              onClick={onResummarize}
              disabled={resummarizing}
              className="px-3 py-1 text-xs text-vs-text-muted hover:text-vs-text-accent rounded hover:bg-vs-hover transition-colors flex items-center gap-1.5"
              title="Delete vectors and regenerate summary from scratch"
            >
              {resummarizing ? <Loader2 className="w-3 h-3 animate-spin" /> : <RotateCcw className="w-3 h-3" />}
              Resummarize
            </button>
            <button
              onClick={startEditing}
              className="px-3 py-1 text-xs text-vs-text-muted hover:text-vs-text-secondary rounded hover:bg-vs-hover transition-colors flex items-center gap-1.5"
            >
              <Pencil className="w-3 h-3" />
              Edit
            </button>
          </div>
        )}
      </div>

      {/* Summary */}
      {(overview?.summary || editing) && (
        <section>
          <h2 className="text-sm font-semibold text-vs-text-secondary uppercase tracking-wider mb-3">
            Summary
          </h2>
          {editing ? (
            <textarea
              value={editSummary}
              onChange={(e) => setEditSummary(e.target.value)}
              className="input w-full text-sm leading-relaxed min-h-[80px] resize-y"
            />
          ) : (
            <p className="text-sm text-vs-text-primary leading-relaxed">
              {overview!.summary}
            </p>
          )}
        </section>
      )}

      {/* Action Items */}
      {((overview?.action_items && overview.action_items.length > 0) || editing) && (
        <section>
          <h2 className="text-sm font-semibold text-vs-text-secondary uppercase tracking-wider mb-3">
            Action Items
          </h2>
          {editing ? (
            <div className="space-y-2">
              {editItems.map((item, i) => (
                <div key={i} className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    checked={item.checked}
                    onChange={() => {
                      const next = [...editItems];
                      next[i] = { ...next[i], checked: !next[i].checked };
                      setEditItems(next);
                    }}
                    className="mt-1.5 rounded border-vs-border bg-vs-raised cursor-pointer"
                  />
                  <input
                    type="text"
                    value={item.text}
                    onChange={(e) => {
                      const next = [...editItems];
                      next[i] = { ...next[i], text: e.target.value };
                      setEditItems(next);
                    }}
                    className="input flex-1 text-sm"
                  />
                  <input
                    type="text"
                    value={item.assignee || ""}
                    onChange={(e) => {
                      const next = [...editItems];
                      next[i] = { ...next[i], assignee: e.target.value || null };
                      setEditItems(next);
                    }}
                    placeholder="Assignee"
                    className="input w-28 text-sm text-vs-text-secondary"
                  />
                  <button
                    onClick={() => setEditItems(editItems.filter((_, j) => j !== i))}
                    className="p-1 text-vs-text-muted hover:text-status-failed transition-colors shrink-0 mt-0.5"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))}
              <button
                onClick={() => setEditItems([...editItems, { text: "", checked: false, assignee: null }])}
                className="flex items-center gap-1.5 text-xs text-vs-text-muted hover:text-vs-text-accent transition-colors mt-1"
              >
                <Plus className="w-3 h-3" />
                Add item
              </button>
            </div>
          ) : (
            <ul className="space-y-2">
              {overview!.action_items.map((item, i) => {
                const text = typeof item === "string" ? item : item.text;
                const checked = typeof item === "string" ? false : item.checked;
                const assignee = typeof item === "string" ? null : item.assignee;
                return (
                  <li key={i} className="flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={async () => {
                        if (!transcriptId || !overview) return;
                        try {
                          const result = await toggleActionItem(transcriptId, i);
                          const updated = { ...overview };
                          updated.action_items = [...overview.action_items];
                          updated.action_items[i] = result.item;
                          onOverviewUpdate(updated);
                        } catch (err) {
                          console.error("Failed to toggle:", err);
                        }
                      }}
                      className="mt-1 rounded border-vs-border bg-vs-raised cursor-pointer"
                    />
                    <span
                      className={`flex-1 ${
                        checked
                          ? "text-vs-text-muted line-through"
                          : "text-vs-text-primary"
                      } transition-colors`}
                    >
                      {text}
                    </span>
                    <AssigneePicker
                      assignee={assignee || null}
                      speakers={speakers}
                      onChange={async (name) => {
                        if (!transcriptId || !overview) return;
                        const updatedItems = overview.action_items.map((it, j) => {
                          const obj = typeof it === "string" ? { text: it, checked: false, assignee: null } : { ...it };
                          if (j === i) obj.assignee = name;
                          return obj;
                        });
                        try {
                          const result = await updateOverview(transcriptId, {
                            action_items: updatedItems.map((it) => ({
                              text: typeof it === "string" ? it : it.text,
                              checked: typeof it === "string" ? false : it.checked,
                              assignee: typeof it === "string" ? null : it.assignee,
                            })),
                          });
                          onOverviewUpdate(result);
                        } catch (err) {
                          console.error("Failed to update assignee:", err);
                        }
                      }}
                    />
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      )}

      {/* Outline */}
      {((overview?.outline && overview.outline.length > 0) || editing) && (
        <section>
          <h2 className="text-sm font-semibold text-vs-text-secondary uppercase tracking-wider mb-3">
            Outline
          </h2>
          {editing ? (
            <div className="space-y-4">
              {editOutline.map((item, i) => (
                <div key={i} className="space-y-1 pl-3 border-l-2 border-vs-border">
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      value={item.heading}
                      onChange={(e) => {
                        const next = [...editOutline];
                        next[i] = { ...next[i], heading: e.target.value };
                        setEditOutline(next);
                      }}
                      className="input flex-1 text-sm font-medium"
                      placeholder="Section heading"
                    />
                    <button
                      onClick={() => setEditOutline(editOutline.filter((_, j) => j !== i))}
                      className="p-1 text-vs-text-muted hover:text-status-failed transition-colors shrink-0"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  <textarea
                    value={item.content}
                    onChange={(e) => {
                      const next = [...editOutline];
                      next[i] = { ...next[i], content: e.target.value };
                      setEditOutline(next);
                    }}
                    className="input w-full text-xs resize-y min-h-[40px]"
                    placeholder="Section content"
                  />
                </div>
              ))}
              <button
                onClick={() => setEditOutline([...editOutline, { heading: "", content: "" }])}
                className="flex items-center gap-1.5 text-xs text-vs-text-muted hover:text-vs-text-accent transition-colors"
              >
                <Plus className="w-3 h-3" />
                Add section
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              {overview!.outline.map((item, i) => (
                <div key={i}>
                  <h3 className="text-sm font-medium text-vs-text-primary">
                    {item.heading}
                  </h3>
                  <p className="text-xs text-vs-text-secondary mt-0.5">
                    {item.content}
                  </p>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
