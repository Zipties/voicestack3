"use client";

import { getSpeakerColor, getSpeakerAvatarId, getAvatarUrl } from "@/lib/store";

interface SpeakerAvatarProps {
  speakerId: string;
  avatarId: number | null;
  customAvatar?: string | null;
  size?: number;
  onClick?: () => void;
  className?: string;
}

/**
 * Speaker avatar that blends into the UI with a color-tinted overlay.
 * Uses CSS mask + mix-blend-mode so the avatar dissolves into the card
 * and picks up the speaker's assigned color as a wash.
 */
export default function SpeakerAvatar({
  speakerId,
  avatarId,
  customAvatar,
  size = 48,
  onClick,
  className = "",
}: SpeakerAvatarProps) {
  const color = getSpeakerColor(speakerId);
  const resolvedId = getSpeakerAvatarId(speakerId, avatarId);
  const url = customAvatar || getAvatarUrl(resolvedId);

  return (
    <div
      className={`relative shrink-0 overflow-hidden rounded-full ${onClick ? "cursor-pointer" : ""} ${className}`}
      style={{ width: size, height: size }}
      onClick={onClick}
    >
      {/* Base image with radial fade into surrounding UI */}
      <img
        src={url}
        alt=""
        className="absolute inset-0 w-full h-full object-cover"
        style={{
          maskImage: "radial-gradient(circle, black 50%, transparent 85%)",
          WebkitMaskImage: "radial-gradient(circle, black 50%, transparent 85%)",
        }}
        draggable={false}
      />
    </div>
  );
}
