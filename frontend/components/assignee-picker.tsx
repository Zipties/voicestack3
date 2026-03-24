"use client";

import { useState, useEffect, useRef } from "react";
import { ChevronDown, UserPlus } from "lucide-react";
import { getSpeakerColor } from "@/lib/store";
import SpeakerAvatar from "@/components/SpeakerAvatar";

interface SpeakerInfo {
  id: string;
  name: string;
  avatar_id: number | null;
  custom_avatar: string | null;
}

interface AssigneePickerProps {
  assignee: string | null;
  speakers: SpeakerInfo[];
  onChange: (name: string | null) => void;
}

export function AssigneePicker({ assignee, speakers, onChange }: AssigneePickerProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    if (open) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const matched = assignee
    ? speakers.find((s) => s.name.toLowerCase() === assignee.toLowerCase())
    : null;

  const color = matched ? getSpeakerColor(matched.id) : "#6b7280";

  return (
    <div className="relative shrink-0" ref={ref}>
      <button
        onClick={(e) => {
          e.stopPropagation();
          setOpen(!open);
        }}
        className="flex items-center gap-1 px-1.5 py-0.5 rounded-md hover:bg-vs-hover transition-colors text-xs font-medium"
        style={{ color: matched ? color : undefined }}
      >
        {matched ? (
          <>
            <SpeakerAvatar
              speakerId={matched.id}
              avatarId={matched.avatar_id}
              customAvatar={matched.custom_avatar}
              size={18}
            />
            <span>{matched.name}</span>
          </>
        ) : (
          <span className="text-vs-text-muted flex items-center gap-1">
            <UserPlus className="w-3 h-3" />
            {assignee || "Assign"}
          </span>
        )}
        <ChevronDown className="w-3 h-3 opacity-40" />
      </button>

      {open && (
        <div className="absolute top-full right-0 mt-1 w-48 bg-vs-raised border border-vs-border rounded-lg shadow-xl z-40 animate-fade-in overflow-hidden">
          {/* Unassign option */}
          {assignee && (
            <button
              onClick={() => {
                onChange(null);
                setOpen(false);
              }}
              className="w-full px-3 py-1.5 text-left text-xs text-vs-text-muted hover:bg-vs-hover transition-colors border-b border-vs-border"
            >
              Unassign
            </button>
          )}
          <div className="max-h-48 overflow-y-auto py-1">
            {speakers.map((s) => {
              const isSelected = matched?.id === s.id;
              return (
                <button
                  key={s.id}
                  onClick={() => {
                    onChange(s.name);
                    setOpen(false);
                  }}
                  className={`w-full px-3 py-1.5 flex items-center gap-2 text-xs hover:bg-vs-hover transition-colors ${
                    isSelected ? "bg-vs-hover/50" : ""
                  }`}
                >
                  <SpeakerAvatar
                    speakerId={s.id}
                    avatarId={s.avatar_id}
                    customAvatar={s.custom_avatar}
                    size={18}
                  />
                  <span
                    className="flex-1 text-left font-medium"
                    style={{ color: getSpeakerColor(s.id) }}
                  >
                    {s.name}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
