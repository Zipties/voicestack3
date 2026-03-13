"use client";

import { useEffect, useRef, useState } from "react";
import {
  Users,
  Shield,
  ShieldCheck,
  Merge,
  Loader2,
  Check,
  X,
  Trash2,
  ChevronDown,
  ChevronRight,
  FileAudio,
} from "lucide-react";
import {
  fetchSpeakers,
  updateSpeaker,
  mergeSpeakers,
  deleteSpeaker,
  fetchSpeakerEmbeddings,
  deleteSpeakerEmbedding,
  uploadSpeakerAvatar,
  type Speaker,
  type SpeakerEmbedding,
} from "@/lib/api";
import { getSpeakerColor } from "@/lib/store";
import { timeAgo, formatTime } from "@/lib/utils";
import SpeakerAvatar from "@/components/SpeakerAvatar";

export default function SpeakersPage() {
  const [speakers, setSpeakers] = useState<Speaker[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [mergeMode, setMergeMode] = useState(false);
  const [mergeSource, setMergeSource] = useState<string | null>(null);
  const [mergeTarget, setMergeTarget] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [embeddings, setEmbeddings] = useState<Record<string, SpeakerEmbedding[]>>({});
  const [loadingEmbeddings, setLoadingEmbeddings] = useState<string | null>(null);
  const [uploadingAvatarId, setUploadingAvatarId] = useState<string | null>(null);
  const [expandedRecordings, setExpandedRecordings] = useState<Set<string>>(new Set());
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadSpeakers = async () => {
    try {
      const data = await fetchSpeakers();
      setSpeakers(data);
    } catch (err) {
      console.error("Failed to load speakers:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSpeakers();
  }, []);

  const handleRename = async (id: string) => {
    if (!editName.trim()) return;
    try {
      await updateSpeaker(id, { name: editName.trim() });
      setEditingId(null);
      loadSpeakers();
    } catch (err) {
      console.error("Failed to rename:", err);
    }
  };

  const handleTrustToggle = async (speaker: Speaker) => {
    try {
      await updateSpeaker(speaker.id, { is_trusted: !speaker.is_trusted });
      loadSpeakers();
    } catch (err) {
      console.error("Failed to toggle trust:", err);
    }
  };

  const handleMerge = async () => {
    if (!mergeSource || !mergeTarget) return;
    try {
      await mergeSpeakers(mergeSource, mergeTarget);
      setMergeMode(false);
      setMergeSource(null);
      setMergeTarget(null);
      loadSpeakers();
    } catch (err) {
      console.error("Failed to merge:", err);
    }
  };

  const toggleEmbeddings = async (speakerId: string) => {
    if (expandedId === speakerId) {
      setExpandedId(null);
      return;
    }
    setExpandedId(speakerId);
    if (!embeddings[speakerId]) {
      setLoadingEmbeddings(speakerId);
      try {
        const data = await fetchSpeakerEmbeddings(speakerId);
        setEmbeddings((prev) => ({ ...prev, [speakerId]: data }));
      } catch (err) {
        console.error("Failed to load embeddings:", err);
      } finally {
        setLoadingEmbeddings(null);
      }
    }
  };

  const handleDeleteEmbedding = async (speakerId: string, embeddingId: string) => {
    try {
      await deleteSpeakerEmbedding(speakerId, embeddingId);
      setEmbeddings((prev) => ({
        ...prev,
        [speakerId]: prev[speakerId]?.filter((e) => e.id !== embeddingId) ?? [],
      }));
      loadSpeakers(); // refresh counts
    } catch (err) {
      console.error("Failed to delete embedding:", err);
    }
  };

  const handleDelete = async (id: string) => {
    setDeletingId(id);
    try {
      await deleteSpeaker(id);
      setSpeakers((prev) => prev.filter((s) => s.id !== id));
    } catch (err) {
      console.error("Failed to delete speaker:", err);
    } finally {
      setDeletingId(null);
      setConfirmDeleteId(null);
    }
  };

  const handleAvatarClick = (speakerId: string) => {
    setUploadingAvatarId(speakerId);
    fileInputRef.current?.click();
  };

  const handleAvatarFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !uploadingAvatarId) return;
    try {
      const result = await uploadSpeakerAvatar(uploadingAvatarId, file);
      setSpeakers((prev) =>
        prev.map((s) => (s.id === uploadingAvatarId ? { ...s, custom_avatar: result.custom_avatar } : s))
      );
    } catch (err) {
      console.error("Failed to upload avatar:", err);
    } finally {
      setUploadingAvatarId(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-6 h-6 text-vs-text-muted animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-6 pt-14 md:pt-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold">Speakers</h1>
        <div className="flex gap-2">
          {mergeMode ? (
            <>
              <button
                onClick={handleMerge}
                disabled={!mergeSource || !mergeTarget}
                className="btn-primary text-sm disabled:opacity-40"
              >
                <Merge className="w-4 h-4 mr-1 inline" />
                Merge Selected
              </button>
              <button
                onClick={() => {
                  setMergeMode(false);
                  setMergeSource(null);
                  setMergeTarget(null);
                }}
                className="btn-ghost text-sm"
              >
                Cancel
              </button>
            </>
          ) : (
            <button
              onClick={() => setMergeMode(true)}
              className="btn-ghost text-sm"
              disabled={speakers.length < 2}
            >
              <Merge className="w-4 h-4 mr-1 inline" />
              Merge Speakers
            </button>
          )}
        </div>
      </div>

      {mergeMode && (
        <div className="card p-3 mb-4 bg-vs-text-accent/5 border-vs-text-accent/20">
          <p className="text-xs text-vs-text-accent">
            Select a <strong>source</strong> speaker (will be deleted), then a{" "}
            <strong>target</strong> speaker (will keep all segments).
          </p>
        </div>
      )}

      {speakers.length === 0 ? (
        <div className="text-center py-20">
          <Users className="w-12 h-12 text-vs-text-muted mx-auto mb-3" />
          <p className="text-vs-text-secondary">No speakers detected yet</p>
          <p className="text-sm text-vs-text-muted mt-1">
            Upload and process a recording to detect speakers
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {speakers.map((speaker) => {
            const color = getSpeakerColor(speaker.id);
            const isEditing = editingId === speaker.id;
            const isSource = mergeSource === speaker.id;
            const isTarget = mergeTarget === speaker.id;

            return (
              <div
                key={speaker.id}
                className={`card px-4 py-3 animate-fade-in transition-all ${
                  mergeMode ? "cursor-pointer hover:bg-vs-hover/50" : ""
                } ${isSource ? "ring-2 ring-status-failed/50" : ""} ${
                  isTarget ? "ring-2 ring-status-completed/50" : ""
                }`}
                onClick={() => {
                  if (!mergeMode) return;
                  if (!mergeSource) {
                    setMergeSource(speaker.id);
                  } else if (mergeSource === speaker.id) {
                    setMergeSource(null);
                  } else if (!mergeTarget) {
                    setMergeTarget(speaker.id);
                  } else if (mergeTarget === speaker.id) {
                    setMergeTarget(null);
                  }
                }}
              >
                <div className="flex items-center gap-3">
                  {/* Avatar */}
                  <SpeakerAvatar
                    speakerId={speaker.id}
                    avatarId={speaker.avatar_id}
                    customAvatar={speaker.custom_avatar}
                    size={40}
                    onClick={mergeMode ? undefined : () => handleAvatarClick(speaker.id)}
                  />

                  {/* Name */}
                  <div className="flex-1 min-w-0">
                    {isEditing ? (
                      <div className="flex items-center gap-2">
                        <input
                          type="text"
                          value={editName}
                          onChange={(e) => setEditName(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") handleRename(speaker.id);
                            if (e.key === "Escape") setEditingId(null);
                          }}
                          className="input text-sm py-1 flex-1"
                          autoFocus
                        />
                        <button
                          onClick={() => handleRename(speaker.id)}
                          className="p-1 text-status-completed hover:bg-vs-hover rounded"
                        >
                          <Check className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => setEditingId(null)}
                          className="p-1 text-vs-text-muted hover:bg-vs-hover rounded"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={(e) => {
                          if (mergeMode) return;
                          e.stopPropagation();
                          setEditingId(speaker.id);
                          setEditName(speaker.name);
                        }}
                        className="text-sm font-medium hover:text-vs-text-accent transition-colors"
                        style={{ color }}
                      >
                        {speaker.name}
                      </button>
                    )}
                    <div className="flex items-center gap-3 mt-0.5 text-2xs text-vs-text-muted">
                      <span>{speaker.segment_count ?? 0} segments</span>
                      {!mergeMode && (speaker.embedding_count ?? 0) > 0 ? (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleEmbeddings(speaker.id);
                          }}
                          className="flex items-center gap-0.5 hover:text-vs-text-secondary transition-colors"
                        >
                          {expandedId === speaker.id ? (
                            <ChevronDown className="w-3 h-3" />
                          ) : (
                            <ChevronRight className="w-3 h-3" />
                          )}
                          {speaker.embedding_count} embeddings
                        </button>
                      ) : (
                        <span>{speaker.embedding_count ?? 0} embeddings</span>
                      )}
                      <span>{timeAgo(speaker.created_at)}</span>
                      {mergeMode && isSource && (
                        <span className="text-status-failed font-medium">
                          Source (will be deleted)
                        </span>
                      )}
                      {mergeMode && isTarget && (
                        <span className="text-status-completed font-medium">
                          Target (will keep segments)
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Trust badge + delete */}
                  {!mergeMode && (
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleTrustToggle(speaker);
                        }}
                        className={`p-1.5 rounded-lg transition-colors ${
                          speaker.is_trusted
                            ? "text-status-completed bg-status-completed/10"
                            : "text-vs-text-muted hover:text-vs-text-secondary hover:bg-vs-hover"
                        }`}
                        title={speaker.is_trusted ? "Recognized speaker" : "Mark as recognized"}
                      >
                        {speaker.is_trusted ? (
                          <ShieldCheck className="w-4 h-4" />
                        ) : (
                          <Shield className="w-4 h-4" />
                        )}
                      </button>
                      {confirmDeleteId === speaker.id ? (
                        <div className="flex items-center gap-1">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDelete(speaker.id);
                            }}
                            disabled={deletingId === speaker.id}
                            className="px-2 py-1 text-2xs font-medium bg-status-failed/15 text-status-failed rounded hover:bg-status-failed/25 transition-colors"
                          >
                            {deletingId === speaker.id ? <Loader2 className="w-3 h-3 animate-spin" /> : "Delete"}
                          </button>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setConfirmDeleteId(null);
                            }}
                            className="px-2 py-1 text-2xs text-vs-text-muted rounded hover:bg-vs-hover transition-colors"
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setConfirmDeleteId(speaker.id);
                          }}
                          className="p-1.5 rounded-lg text-vs-text-muted hover:text-status-failed hover:bg-status-failed/10 transition-colors"
                          title="Delete speaker"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  )}
                </div>

                {/* Embeddings panel */}
                {expandedId === speaker.id && (
                  <div className="mt-3 pt-3 border-t border-vs-border">
                    {loadingEmbeddings === speaker.id ? (
                      <div className="flex items-center justify-center py-4">
                        <Loader2 className="w-4 h-4 text-vs-text-muted animate-spin" />
                      </div>
                    ) : (() => {
                      const speakerEmbs = embeddings[speaker.id] ?? [];
                      if (speakerEmbs.length === 0) {
                        return <p className="text-2xs text-vs-text-muted py-2">No embeddings</p>;
                      }
                      // Group by transcript
                      const groups = new Map<string, { title: string; jobId: string | null; items: SpeakerEmbedding[] }>();
                      for (const emb of speakerEmbs) {
                        const key = emb.transcript_title || emb.job_id || "unknown";
                        if (!groups.has(key)) {
                          groups.set(key, { title: emb.transcript_title || "Untitled Recording", jobId: emb.job_id, items: [] });
                        }
                        groups.get(key)!.items.push(emb);
                      }
                      return (
                        <div className="space-y-1.5">
                          {Array.from(groups.values()).map((group) => {
                            const groupKey = `${speaker.id}:${group.title}:${group.jobId}`;
                            const isExpanded = expandedRecordings.has(groupKey);
                            return (
                              <div key={group.title + group.jobId}>
                                <div className="flex items-center gap-1.5 py-1 px-1 rounded hover:bg-vs-hover/30 transition-colors">
                                  <button
                                    className="p-0 shrink-0"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setExpandedRecordings((prev) => {
                                        const next = new Set(prev);
                                        if (next.has(groupKey)) next.delete(groupKey);
                                        else next.add(groupKey);
                                        return next;
                                      });
                                    }}
                                    title={isExpanded ? "Collapse samples" : "Expand samples"}
                                  >
                                    {isExpanded ? (
                                      <ChevronDown className="w-3 h-3 text-vs-text-muted" />
                                    ) : (
                                      <ChevronRight className="w-3 h-3 text-vs-text-muted" />
                                    )}
                                  </button>
                                  <FileAudio className="w-3 h-3 text-vs-text-muted shrink-0" />
                                  {group.jobId ? (
                                    <a
                                      href={`/jobs/${group.jobId}`}
                                      className="text-2xs font-medium text-vs-text-secondary hover:text-vs-text-accent transition-colors flex-1 truncate"
                                      onClick={(e) => e.stopPropagation()}
                                    >
                                      {group.title}
                                    </a>
                                  ) : (
                                    <span className="text-2xs font-medium text-vs-text-secondary flex-1 truncate">
                                      {group.title}
                                    </span>
                                  )}
                                  <span className="text-2xs text-vs-text-muted shrink-0">
                                    {group.items.length} sample{group.items.length !== 1 ? 's' : ''}
                                  </span>
                                </div>
                                {isExpanded && (
                                  <div className="space-y-1 ml-4 mt-1">
                                    {group.items.map((emb) => (
                                      <div
                                        key={emb.id}
                                        className="group/emb flex items-start gap-2 text-2xs py-1 px-2 rounded hover:bg-vs-hover/30"
                                      >
                                        {emb.segment ? (
                                          <>
                                            <span className="text-vs-text-muted shrink-0 tabular-nums">
                                              {formatTime(emb.segment.start_time)}
                                            </span>
                                            <span className="text-vs-text-secondary flex-1 line-clamp-1">
                                              {emb.segment.text}
                                            </span>
                                          </>
                                        ) : (
                                          <span className="text-vs-text-muted italic flex-1">
                                            Voice sample{emb.created_at ? ` · ${new Date(emb.created_at).toLocaleDateString()}` : ''}
                                          </span>
                                        )}
                                        <button
                                          onClick={(e) => {
                                            e.stopPropagation();
                                            handleDeleteEmbedding(speaker.id, emb.id);
                                          }}
                                          className="p-0.5 rounded text-vs-text-muted hover:text-status-failed opacity-0 group-hover/emb:opacity-100 transition-all shrink-0"
                                          title="Remove this voice sample"
                                        >
                                          <X className="w-3 h-3" />
                                        </button>
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      );
                    })()}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Hidden file input for avatar upload */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={handleAvatarFile}
      />
    </div>
  );
}
