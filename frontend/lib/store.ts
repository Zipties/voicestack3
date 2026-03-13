import { create } from "zustand";
import type { Transcript, Segment } from "./api";

// ─── Audio Player Store ──────────────────────────────────────────────────────

interface PlayerState {
  audioRef: HTMLAudioElement | null;
  isPlaying: boolean;
  currentTime: number;
  duration: number;
  playbackRate: number;
  setAudioRef: (ref: HTMLAudioElement | null) => void;
  setIsPlaying: (playing: boolean) => void;
  setCurrentTime: (time: number) => void;
  setDuration: (duration: number) => void;
  setPlaybackRate: (rate: number) => void;
  seekTo: (time: number) => void;
  togglePlay: () => void;
  skip: (seconds: number) => void;
}

export const usePlayerStore = create<PlayerState>((set, get) => ({
  audioRef: null,
  isPlaying: false,
  currentTime: 0,
  duration: 0,
  playbackRate: 1,
  setAudioRef: (ref) => set({ audioRef: ref }),
  setIsPlaying: (playing) => set({ isPlaying: playing }),
  setCurrentTime: (time) => set({ currentTime: time }),
  setDuration: (duration) => set({ duration }),
  setPlaybackRate: (rate) => {
    const audio = get().audioRef;
    if (audio) audio.playbackRate = rate;
    set({ playbackRate: rate });
  },
  seekTo: (time) => {
    const audio = get().audioRef;
    if (audio) {
      audio.currentTime = time;
      set({ currentTime: time });
    }
  },
  togglePlay: () => {
    const audio = get().audioRef;
    if (!audio) return;
    if (audio.paused) {
      audio.play().catch((e) => console.warn("[audio] togglePlay failed:", e));
      set({ isPlaying: true });
    } else {
      audio.pause();
      set({ isPlaying: false });
    }
  },
  skip: (seconds) => {
    const audio = get().audioRef;
    if (audio) {
      audio.currentTime = Math.max(0, Math.min(audio.duration, audio.currentTime + seconds));
    }
  },
}));

// ─── Transcript Store ────────────────────────────────────────────────────────

interface TranscriptState {
  transcript: Transcript | null;
  activeSegmentIdx: number;
  selectedSegmentId: string | null;
  setTranscript: (t: Transcript | null) => void;
  setActiveSegmentIdx: (idx: number) => void;
  setSelectedSegmentId: (id: string | null) => void;
  getActiveSegment: () => Segment | null;
}

export const useTranscriptStore = create<TranscriptState>((set, get) => ({
  transcript: null,
  activeSegmentIdx: -1,
  selectedSegmentId: null,
  setTranscript: (t) => set({ transcript: t }),
  setActiveSegmentIdx: (idx) => set({ activeSegmentIdx: idx }),
  setSelectedSegmentId: (id) => set({ selectedSegmentId: id }),
  getActiveSegment: () => {
    const { transcript, activeSegmentIdx } = get();
    if (!transcript || activeSegmentIdx < 0) return null;
    return transcript.segments[activeSegmentIdx] ?? null;
  },
}));

// ─── Speaker Colors ──────────────────────────────────────────────────────────

const SPEAKER_COLORS = [
  "#ff6b9d", "#51a3ff", "#4ecdc4", "#ffb347",
  "#95e86c", "#c17bf5", "#ff6b6b", "#45d0e8",
];

const colorCache = new Map<string, string>();

export function getSpeakerColor(speakerId: string): string {
  if (colorCache.has(speakerId)) return colorCache.get(speakerId)!;
  // Simple hash
  let hash = 0;
  for (let i = 0; i < speakerId.length; i++) {
    hash = ((hash << 5) - hash + speakerId.charCodeAt(i)) | 0;
  }
  const color = SPEAKER_COLORS[Math.abs(hash) % SPEAKER_COLORS.length];
  colorCache.set(speakerId, color);
  return color;
}

// ─── Speaker Avatars ────────────────────────────────────────────────────────

const AVATAR_COUNT = 100;

export function getSpeakerAvatarId(speakerId: string, avatarId: number | null): number {
  if (avatarId !== null && avatarId !== undefined) return avatarId;
  // Deterministic from speaker ID so it's stable
  let hash = 0;
  for (let i = 0; i < speakerId.length; i++) {
    hash = ((hash << 5) - hash + speakerId.charCodeAt(i)) | 0;
  }
  return Math.abs(hash) % AVATAR_COUNT;
}

export function getAvatarUrl(avatarId: number): string {
  return `/avatars/alien_${String(avatarId).padStart(3, "0")}.png`;
}

// ─── Emotion Helpers ─────────────────────────────────────────────────────────

export const EMOTION_COLORS: Record<string, string> = {
  happy: "#4ecdc4",
  sad: "#51a3ff",
  angry: "#ff6b6b",
  neutral: "#9ca3af",
  fearful: "#ffb347",
  surprised: "#c17bf5",
  disgusted: "#8b5e3c",
  other: "#6b7280",
  unknown: "#4b5563",
};

export function getEmotionClass(emotion: string | null): string {
  if (!emotion) return "emotion-unknown";
  return `emotion-${emotion}`;
}
