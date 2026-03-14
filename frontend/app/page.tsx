"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Upload, FileAudio, Clock, AlertCircle, CheckCircle2, Loader2, Mic, Trash2, ScrollText } from "lucide-react";
import Link from "next/link";
import { fetchJobs, uploadAudio, deleteJob, subscribeToProgress, type Job, type JobProgress } from "@/lib/api";
import { formatBytes, formatTime, timeAgo } from "@/lib/utils";
import SpeakerAvatar from "@/components/SpeakerAvatar";

const STATUS_CONFIG: Record<string, { icon: typeof Loader2; color: string; label: string }> = {
  queued: { icon: Clock, color: "bg-status-queued/15 text-status-queued", label: "Queued" },
  processing: { icon: Loader2, color: "bg-status-processing/15 text-status-processing", label: "Processing" },
  completed: { icon: CheckCircle2, color: "bg-status-completed/15 text-status-completed", label: "Completed" },
  failed: { icon: AlertCircle, color: "bg-status-failed/15 text-status-failed", label: "Failed" },
};

export default function JobsPage() {
  const router = useRouter();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const [liveProgress, setLiveProgress] = useState<Record<string, JobProgress>>({});
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const loadJobs = useCallback(async () => {
    try {
      const data = await fetchJobs();
      setJobs(data);
    } catch (err) {
      console.error("Failed to load jobs:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadJobs();
    const interval = setInterval(loadJobs, 10000);
    return () => clearInterval(interval);
  }, [loadJobs]);

  // Subscribe to progress for active jobs
  useEffect(() => {
    const unsubs: (() => void)[] = [];
    for (const job of jobs) {
      if (job.status.toLowerCase() === "processing" || job.status.toLowerCase() === "queued") {
        const unsub = subscribeToProgress(
          job.id,
          (data) => setLiveProgress((prev) => ({ ...prev, [job.id]: data })),
          () => loadJobs()
        );
        unsubs.push(unsub);
      }
    }
    return () => unsubs.forEach((u) => u());
  }, [jobs, loadJobs]);

  const handleUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const file = files[0];
    setUploading(true);
    setUploadProgress(0);

    try {
      // Simulate progress (real upload doesn't give progress via fetch)
      const progressInterval = setInterval(() => {
        setUploadProgress((p) => Math.min(p + 10, 90));
      }, 200);

      const result = await uploadAudio(file);
      clearInterval(progressInterval);
      setUploadProgress(100);

      setTimeout(() => {
        setUploading(false);
        setUploadProgress(0);
        loadJobs();
      }, 500);
    } catch (err) {
      console.error("Upload failed:", err);
      setUploading(false);
      setUploadProgress(0);
    }
  };

  const handleDelete = async (jobId: string) => {
    setDeletingId(jobId);
    try {
      await deleteJob(jobId);
      setJobs((prev) => prev.filter((j) => j.id !== jobId));
    } catch (err) {
      console.error("Delete failed:", err);
    } finally {
      setDeletingId(null);
      setConfirmDeleteId(null);
    }
  };

  return (
    <div className="p-4 sm:p-6 pt-14 md:pt-6 max-w-4xl mx-auto w-full flex-1 overflow-auto">
      {/* Record / Upload Area - always visible */}
      <div
          className={`card mb-6 p-8 border-2 border-dashed transition-colors duration-150 ${
            dragOver
              ? "border-vs-text-accent bg-vs-text-accent/5"
              : "border-vs-border hover:border-vs-border-bright"
          }`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            handleUpload(e.dataTransfer.files);
          }}
        >
          {uploading ? (
            <div className="text-center">
              <Loader2 className="w-8 h-8 text-vs-text-accent mx-auto mb-3 animate-spin" />
              <p className="text-sm text-vs-text-secondary mb-3">Uploading...</p>
              <div className="w-64 mx-auto h-1.5 bg-vs-raised rounded-full overflow-hidden">
                <div
                  className="h-full bg-vs-text-accent rounded-full transition-all duration-300"
                  style={{ width: `${uploadProgress}%` }}
                />
              </div>
            </div>
          ) : (
            <div className="flex flex-col sm:flex-row items-center justify-center gap-6">
              {/* Record option */}
              <Link
                href="/record"
                className="flex flex-col items-center gap-2 p-4 rounded-xl hover:bg-white/5 transition-colors"
              >
                <div className="w-14 h-14 rounded-full bg-vs-text-accent flex items-center justify-center">
                  <Mic className="w-6 h-6 text-white" />
                </div>
                <span className="text-sm text-vs-text-secondary font-medium">Record</span>
              </Link>

              <div className="hidden sm:block w-px h-16 bg-vs-border" />
              <div className="sm:hidden h-px w-16 bg-vs-border" />

              {/* Upload option */}
              <label className="cursor-pointer flex flex-col items-center gap-2 p-4 rounded-xl hover:bg-white/5 transition-colors">
                <div className="w-14 h-14 rounded-full bg-vs-raised border border-vs-border flex items-center justify-center">
                  <Upload className="w-6 h-6 text-vs-text-muted" />
                </div>
                <span className="text-sm text-vs-text-secondary font-medium">Upload File</span>
                <p className="text-2xs text-vs-text-muted text-center">
                  Audio or video files
                </p>
                <input
                  type="file"
                  accept="audio/*,video/*"
                  className="hidden"
                  onChange={(e) => handleUpload(e.target.files)}
                />
              </label>
            </div>
          )}
        </div>

      {/* Jobs List */}
      {jobs.length > 0 && (
        <h2 className="text-sm font-semibold text-vs-text-secondary uppercase tracking-wider mb-3">
          Recordings
        </h2>
      )}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-6 h-6 text-vs-text-muted animate-spin" />
        </div>
      ) : jobs.length === 0 ? (
        <div className="text-center py-12">
          <p className="text-sm text-vs-text-muted">No recordings yet. Record or upload to get started.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {jobs.map((job) => {
            const live = liveProgress[job.id];
            const status = live?.status || job.status;
            const progress = live?.progress ?? job.progress;
            const stage = live?.stage || job.pipeline_stage;
            const statusKey = status.toLowerCase();
            const cfg = STATUS_CONFIG[statusKey] || STATUS_CONFIG.queued;
            const StatusIcon = cfg.icon;
            const isConfirming = confirmDeleteId === job.id;
            const isDeleting = deletingId === job.id;

            return (
              <div
                key={job.id}
                className="group card px-4 py-3 hover:bg-vs-hover/50 cursor-pointer transition-colors duration-100 animate-fade-in"
                onClick={() => {
                  if (isConfirming) return;
                  router.push(`/jobs/${job.id}`);
                }}
              >
                <div className="flex items-start gap-3 min-w-0">
                  {/* Speaker avatar stack or file icon */}
                  {job.speakers && job.speakers.length > 0 ? (
                    <div className="flex -space-x-2 shrink-0 mt-0.5">
                      {job.speakers.slice(0, 4).map((spk) => (
                        <SpeakerAvatar
                          key={spk.id}
                          speakerId={spk.id}
                          avatarId={spk.avatar_id}
                          customAvatar={spk.custom_avatar}
                          size={24}
                          className="ring-1 ring-vs-base"
                        />
                      ))}
                      {job.speakers.length > 4 && (
                        <div className="w-6 h-6 rounded-full bg-vs-raised ring-1 ring-vs-base flex items-center justify-center text-2xs text-vs-text-muted">
                          +{job.speakers.length - 4}
                        </div>
                      )}
                    </div>
                  ) : (
                    <FileAudio className="w-5 h-5 text-vs-text-muted shrink-0 mt-0.5" />
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-sm font-medium truncate min-w-0">
                        {job.title || job.asset?.filename || `Job ${job.id.slice(0, 8)}`}
                      </span>
                      <span className={`badge shrink-0 ${cfg.color}`}>
                        <StatusIcon
                          className={`w-3 h-3 mr-1 ${status === "PROCESSING" ? "animate-spin" : ""}`}
                        />
                        {cfg.label}
                      </span>
                      {job.has_summary && (
                        <span className="shrink-0 text-vs-text-accent" title="Summary generated">
                          <ScrollText className="w-3.5 h-3.5" />
                        </span>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 mt-1 text-2xs text-vs-text-muted">
                      {job.asset?.size_bytes && (
                        <span>{formatBytes(job.asset.size_bytes)}</span>
                      )}
                      {job.asset?.duration_seconds && (
                        <span>{formatTime(job.asset.duration_seconds)}</span>
                      )}
                      <span>{timeAgo(job.created_at)}</span>
                      {stage && statusKey === "processing" && (
                        <span className="text-status-processing">
                          {stage.replace(/_/g, " ").toLowerCase()}
                        </span>
                      )}
                    </div>
                    {(statusKey === "processing" || statusKey === "queued") && (
                      <div className="w-full max-w-40 h-1.5 bg-vs-raised rounded-full overflow-hidden mt-2">
                        <div
                          className="h-full bg-status-processing rounded-full transition-all duration-500"
                          style={{ width: `${progress}%` }}
                        />
                      </div>
                    )}
                    {job.error_message && statusKey === "failed" && (
                      <p className="text-2xs text-status-failed mt-1 line-clamp-2">
                        {job.error_message}
                      </p>
                    )}
                  </div>

                  {/* Delete button */}
                  {isConfirming ? (
                    <div className="flex items-center gap-1.5 shrink-0" onClick={(e) => e.stopPropagation()}>
                      <button
                        onClick={() => handleDelete(job.id)}
                        disabled={isDeleting}
                        className="px-2 py-1 text-2xs font-medium bg-status-failed/15 text-status-failed rounded hover:bg-status-failed/25 transition-colors"
                      >
                        {isDeleting ? <Loader2 className="w-3 h-3 animate-spin" /> : "Delete"}
                      </button>
                      <button
                        onClick={() => setConfirmDeleteId(null)}
                        className="px-2 py-1 text-2xs text-vs-text-muted rounded hover:bg-vs-hover transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setConfirmDeleteId(job.id);
                      }}
                      className="p-1.5 rounded-lg text-vs-text-muted hover:text-status-failed hover:bg-status-failed/10 transition-colors opacity-0 group-hover:opacity-100 shrink-0"
                      title="Delete recording"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
