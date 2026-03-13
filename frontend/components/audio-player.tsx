"use client";

import { useEffect, useRef } from "react";
import { Play, Pause, SkipBack, SkipForward } from "lucide-react";
import { usePlayerStore } from "@/lib/store";
import { formatTime } from "@/lib/utils";

interface AudioPlayerProps {
  src: string;
}

const SPEED_OPTIONS = [0.5, 0.75, 1, 1.25, 1.5, 2];

export function AudioPlayer({ src }: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const {
    isPlaying,
    currentTime,
    duration,
    playbackRate,
    setAudioRef,
    setIsPlaying,
    setCurrentTime,
    setDuration,
    setPlaybackRate,
    togglePlay,
    skip,
  } = usePlayerStore();

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    setAudioRef(audio);

    const onTimeUpdate = () => setCurrentTime(audio.currentTime);
    const onDurationChange = () => setDuration(audio.duration);
    const onPlay = () => setIsPlaying(true);
    const onPause = () => setIsPlaying(false);
    const onEnded = () => setIsPlaying(false);

    const onError = () => {
      const e = audio.error;
      console.error("[audio] Error:", e?.code, e?.message, "src:", audio.src, "networkState:", audio.networkState, "readyState:", audio.readyState);
    };
    const onCanPlay = () => console.log("[audio] canplay - readyState:", audio.readyState, "duration:", audio.duration);
    const onLoadStart = () => console.log("[audio] loadstart - src:", audio.src);
    const onStalled = () => console.warn("[audio] stalled - networkState:", audio.networkState, "readyState:", audio.readyState);

    audio.addEventListener("timeupdate", onTimeUpdate);
    audio.addEventListener("durationchange", onDurationChange);
    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);
    audio.addEventListener("ended", onEnded);
    audio.addEventListener("error", onError);
    audio.addEventListener("canplay", onCanPlay);
    audio.addEventListener("loadstart", onLoadStart);
    audio.addEventListener("stalled", onStalled);

    return () => {
      audio.removeEventListener("timeupdate", onTimeUpdate);
      audio.removeEventListener("durationchange", onDurationChange);
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
      audio.removeEventListener("ended", onEnded);
      audio.removeEventListener("error", onError);
      audio.removeEventListener("canplay", onCanPlay);
      audio.removeEventListener("loadstart", onLoadStart);
      audio.removeEventListener("stalled", onStalled);
      setAudioRef(null);
    };
  }, [setAudioRef, setIsPlaying, setCurrentTime, setDuration]);

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0;

  const handleSeek = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const fraction = (e.clientX - rect.left) / rect.width;
    const audio = audioRef.current;
    if (audio && duration > 0) {
      audio.currentTime = fraction * duration;
    }
  };

  return (
    <div className="shrink-0 bg-vs-surface border-t border-vs-border px-6 py-3">
      <audio ref={audioRef} src={src} preload="auto" />

      {/* Progress bar */}
      <div
        className="w-full h-1 bg-vs-raised rounded-full mb-3 cursor-pointer group"
        onClick={handleSeek}
      >
        <div
          className="h-full bg-vs-text-accent rounded-full relative transition-all duration-75"
          style={{ width: `${progress}%` }}
        >
          <div className="absolute right-0 top-1/2 -translate-y-1/2 w-3 h-3 bg-vs-text-accent rounded-full opacity-0 group-hover:opacity-100 transition-opacity" />
        </div>
      </div>

      <div className="flex items-center gap-4">
        {/* Controls */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => skip(-15)}
            className="p-1.5 text-vs-text-secondary hover:text-vs-text-primary transition-colors"
            title="Back 15s"
          >
            <SkipBack className="w-4 h-4" />
          </button>
          <button
            onClick={togglePlay}
            className="p-2 bg-vs-text-accent rounded-full text-white hover:bg-vs-text-accent/90 transition-colors"
          >
            {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4 ml-0.5" />}
          </button>
          <button
            onClick={() => skip(15)}
            className="p-1.5 text-vs-text-secondary hover:text-vs-text-primary transition-colors"
            title="Forward 15s"
          >
            <SkipForward className="w-4 h-4" />
          </button>
        </div>

        {/* Time */}
        <span className="text-xs font-mono text-vs-text-secondary min-w-[90px]">
          {formatTime(currentTime)} / {formatTime(duration)}
        </span>

        <div className="flex-1" />

        {/* Speed */}
        <div className="flex items-center gap-1">
          {SPEED_OPTIONS.map((speed) => (
            <button
              key={speed}
              onClick={() => setPlaybackRate(speed)}
              className={`px-2 py-0.5 rounded text-xs transition-colors ${
                playbackRate === speed
                  ? "bg-vs-text-accent/15 text-vs-text-accent font-medium"
                  : "text-vs-text-muted hover:text-vs-text-secondary"
              }`}
            >
              {speed}x
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
