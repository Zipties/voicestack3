"use client";

import { useState, useEffect, useRef } from "react";
import { ChevronDown, Check, Users, User } from "lucide-react";
import {
  fetchSpeakers,
  updateSpeaker,
  reassignSegmentSpeaker,
  mergeSpeakers,
  type Speaker,
} from "@/lib/api";
import { getSpeakerColor } from "@/lib/store";
import SpeakerAvatar from "@/components/SpeakerAvatar";

interface SpeakerLabelProps {
  speaker: { id: string; name: string; avatar_id?: number | null; custom_avatar?: string | null } | null;
  segmentId: string;
  onSpeakerChanged?: () => void;
}

export function SpeakerLabel({ speaker, segmentId, onSpeakerChanged }: SpeakerLabelProps) {
  const [open, setOpen] = useState(false);
  const [speakers, setSpeakers] = useState<Speaker[]>([]);
  const [renaming, setRenaming] = useState(false);
  const [newName, setNewName] = useState("");
  const [confirmTarget, setConfirmTarget] = useState<Speaker | null>(null);
  const [filter, setFilter] = useState("");
  const dropdownRef = useRef<HTMLDivElement>(null);
  const filterRef = useRef<HTMLInputElement>(null);

  const color = speaker ? getSpeakerColor(speaker.id) : "#6b7280";
  const name = speaker?.name || "Unknown";

  useEffect(() => {
    if (open) {
      fetchSpeakers().then(setSpeakers).catch(console.error);
      setFilter("");
    }
  }, [open]);

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false);
        setRenaming(false);
        setConfirmTarget(null);
      }
    };
    if (open) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const handleRename = async () => {
    if (!speaker || !newName.trim()) return;
    try {
      await updateSpeaker(speaker.id, { name: newName.trim() });
      setRenaming(false);
      setOpen(false);
      onSpeakerChanged?.();
    } catch (err) {
      console.error("Failed to rename speaker:", err);
    }
  };

  const handleSingleReassign = async (target: Speaker) => {
    try {
      await reassignSegmentSpeaker(segmentId, target.id);
      setOpen(false);
      setConfirmTarget(null);
      onSpeakerChanged?.();
    } catch (err) {
      console.error("Failed to reassign segment:", err);
    }
  };

  const handleMergeAll = async (target: Speaker) => {
    if (!speaker) return;
    try {
      await mergeSpeakers(speaker.id, target.id);
      setOpen(false);
      setConfirmTarget(null);
      onSpeakerChanged?.();
    } catch (err) {
      console.error("Failed to merge speakers:", err);
    }
  };

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={(e) => {
          e.stopPropagation();
          setOpen(!open);
          setConfirmTarget(null);
        }}
        className="flex items-center gap-1.5 px-1.5 py-0.5 rounded-md hover:bg-vs-hover transition-colors text-xs font-medium shrink-0"
        style={{ color }}
      >
        {speaker ? (
          <SpeakerAvatar
            speakerId={speaker.id}
            avatarId={speaker.avatar_id ?? null}
            customAvatar={speaker.custom_avatar}
            size={20}
          />
        ) : (
          <span
            className="w-2 h-2 rounded-full shrink-0"
            style={{ backgroundColor: color }}
          />
        )}
        {name}
        <ChevronDown className="w-3 h-3 opacity-50" />
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 w-64 bg-vs-raised border border-vs-border rounded-lg shadow-xl z-40 animate-fade-in overflow-hidden">
          {/* Confirmation step */}
          {confirmTarget && speaker ? (
            <div className="p-2 space-y-1">
              <p className="text-2xs text-vs-text-muted px-1 pb-1">
                Reassign <strong className="text-vs-text-primary">{name}</strong> to{" "}
                <strong style={{ color: getSpeakerColor(confirmTarget.id) }}>
                  {confirmTarget.name}
                </strong>
              </p>
              <button
                onClick={() => handleSingleReassign(confirmTarget)}
                className="w-full px-3 py-2 flex items-center gap-2 text-xs hover:bg-vs-hover transition-colors rounded-md"
              >
                <User className="w-3.5 h-3.5 text-vs-text-muted" />
                <span>Just this segment</span>
              </button>
              <button
                onClick={() => handleMergeAll(confirmTarget)}
                className="w-full px-3 py-2 flex items-center gap-2 text-xs hover:bg-vs-hover transition-colors rounded-md"
              >
                <Users className="w-3.5 h-3.5 text-vs-text-accent" />
                <span>
                  All "{name}" segments everywhere
                </span>
              </button>
              <button
                onClick={() => setConfirmTarget(null)}
                className="w-full px-2 py-1 text-2xs text-vs-text-muted hover:text-vs-text-secondary transition-colors"
              >
                Cancel
              </button>
            </div>
          ) : (
            <>
              {/* Rename option */}
              {speaker && !renaming && (
                <button
                  onClick={() => {
                    setRenaming(true);
                    setNewName(speaker.name);
                  }}
                  className="w-full px-3 py-2 text-left text-xs text-vs-text-secondary hover:bg-vs-hover transition-colors border-b border-vs-border"
                >
                  Rename "{name}"
                </button>
              )}

              {renaming && (
                <div className="p-2 border-b border-vs-border">
                  <input
                    type="text"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") handleRename();
                      if (e.key === "Escape") setRenaming(false);
                    }}
                    className="input w-full text-xs"
                    placeholder="New name..."
                    autoFocus
                  />
                </div>
              )}

              {/* Filter + Speaker list */}
              {!renaming && speakers.length > 3 && (
                <div className="px-2 pt-2 pb-1">
                  <input
                    ref={filterRef}
                    type="text"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                    className="input w-full text-xs"
                    placeholder="Filter speakers..."
                    autoFocus={!speaker}
                  />
                </div>
              )}
              <div className="max-h-48 overflow-y-auto py-1">
                {speakers.filter((s) => !filter || s.name.toLowerCase().includes(filter.toLowerCase())).map((s) => (
                  <button
                    key={s.id}
                    onClick={() => {
                      if (!speaker || speaker.id === s.id) {
                        setOpen(false);
                        return;
                      }
                      setConfirmTarget(s);
                    }}
                    className="w-full px-3 py-1.5 flex items-center gap-2 text-xs hover:bg-vs-hover transition-colors"
                  >
                    <SpeakerAvatar
                      speakerId={s.id}
                      avatarId={s.avatar_id}
                      customAvatar={s.custom_avatar}
                      size={18}
                    />
                    <span className="flex-1 text-left text-vs-text-primary">{s.name}</span>
                    {speaker?.id === s.id && (
                      <Check className="w-3 h-3 text-vs-text-accent" />
                    )}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
