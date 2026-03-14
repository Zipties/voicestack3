"use client";

import { useState, useEffect, useRef } from "react";
import { Square, ChevronDown, Mic, X, Loader2, WifiOff, Check } from "lucide-react";
import { uploadAudio } from "@/lib/api";
import { savePending, type PendingRecording } from "@/lib/offline-store";

type RecordingState = "starting" | "recording" | "uploading" | "saved-offline";

interface RecorderProps {
  onRecordingComplete?: (jobId: string) => void;
  onClose?: () => void;
}

export function Recorder({ onRecordingComplete, onClose }: RecorderProps) {
  const [state, setState] = useState<RecordingState>("starting");
  const [elapsed, setElapsed] = useState(0);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedDevice, setSelectedDevice] = useState<string>("");
  const [showDevices, setShowDevices] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const [stealthMode, setStealthMode] = useState(false);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const silentAudioRef = useRef<HTMLAudioElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animationRef = useRef<number>(0);
  const timerRef = useRef<ReturnType<typeof setInterval>>();
  const startTimeRef = useRef<number>(0);
  const positionIntervalRef = useRef<ReturnType<typeof setInterval>>();
  const wakeLockRef = useRef<WakeLockSentinel | null>(null);
  const lastTapRef = useRef<number>(0);

  // Size canvas properly for retina
  function sizeCanvas() {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    if (rect.width === 0) return;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    const ctx = canvas.getContext("2d");
    if (ctx) ctx.scale(dpr, dpr);
  }

  // Wake Lock: keep screen on during recording
  async function acquireWakeLock() {
    try {
      if ("wakeLock" in navigator) {
        wakeLockRef.current = await navigator.wakeLock.request("screen");
      }
    } catch {
      // Wake lock can fail if page not visible, battery saver, etc. Non-fatal.
    }
  }

  async function releaseWakeLock() {
    if (wakeLockRef.current) {
      await wakeLockRef.current.release();
      wakeLockRef.current = null;
    }
  }

  // Media Session: show recording widget on iOS/Android lock screen.
  // iOS REQUIRES an actual <audio> element playing (not just AudioContext).
  // We play a static silent WAV from our own origin so iOS associates the
  // media session with this PWA (blob: URLs cause navigation issues on tap).
  async function setupMediaSession() {
    if (!("mediaSession" in navigator)) return;

    // Register action handlers BEFORE playback (iOS requirement)
    navigator.mediaSession.setActionHandler("pause", () => { handleStop(); });
    try { navigator.mediaSession.setActionHandler("stop", () => { handleStop(); }); } catch { /* not all browsers */ }

    // Play silent audio loop from same origin - iOS needs a real <audio> element
    const audio = new Audio("/silence.wav");
    audio.loop = true;
    silentAudioRef.current = audio;

    try {
      await audio.play();
    } catch {
      // Autoplay blocked - non-fatal, lock screen just won't show
    }

    // Set metadata AFTER play starts (critical for iOS - ignored if set before)
    navigator.mediaSession.metadata = new MediaMetadata({
      title: "Recording...",
      artist: "VoiceStack",
      album: "Live Recording",
      artwork: [
        { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
        { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
      ],
    });
    navigator.mediaSession.playbackState = "playing";

    // Update position state so the lock screen shows elapsed time
    updateMediaSessionPosition();
    positionIntervalRef.current = setInterval(updateMediaSessionPosition, 1000);
  }

  function updateMediaSessionPosition() {
    if (!("mediaSession" in navigator) || !("setPositionState" in navigator.mediaSession)) return;
    const elapsed = Math.floor((Date.now() - startTimeRef.current) / 1000);
    try {
      navigator.mediaSession.setPositionState({
        duration: elapsed + 3600, // fake long duration so it doesn't "end"
        playbackRate: 1,
        position: elapsed,
      });
    } catch {
      // iOS can be finicky with position state
    }
  }

  function teardownMediaSession() {
    if (positionIntervalRef.current) {
      clearInterval(positionIntervalRef.current);
      positionIntervalRef.current = undefined;
    }
    // Stop silent audio element
    if (silentAudioRef.current) {
      silentAudioRef.current.pause();
      silentAudioRef.current.src = "";
      silentAudioRef.current = null;
    }
    if (!("mediaSession" in navigator)) return;
    navigator.mediaSession.playbackState = "none";
    navigator.mediaSession.setActionHandler("pause", null);
    try { navigator.mediaSession.setActionHandler("stop", null); } catch { /* */ }
    navigator.mediaSession.metadata = null;
  }

  // Re-acquire wake lock when page becomes visible again (iOS releases on tab switch)
  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === "visible" && state === "recording") {
        acquireWakeLock();
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, [state]);

  // Double-tap stealth mode - document-level native listener to bypass React's passive touch events.
  // Must be on document because the stealth overlay is position:fixed z-200 and intercepts all touches.
  useEffect(() => {
    const handler = (e: TouchEvent) => {
      // Don't trigger on buttons
      const target = e.target as HTMLElement;
      if (target.closest("button") || target.closest("select")) return;

      const now = Date.now();
      if (now - lastTapRef.current < 500) {
        e.preventDefault(); // Actually blocks double-tap-to-zoom (non-passive listener)
        setStealthMode((prev) => !prev);
        lastTapRef.current = 0;
      } else {
        lastTapRef.current = now;
      }
    };

    // { passive: false } is critical - React touch handlers are passive by default
    // and cannot preventDefault. This native listener CAN.
    document.addEventListener("touchstart", handler, { passive: false });
    return () => document.removeEventListener("touchstart", handler);
  }, []);

  // Start waveform animation loop
  function startWaveform(analyser: AnalyserNode) {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const bufferLength = analyser.fftSize;
    const dataArray = new Float32Array(bufferLength);

    const draw = () => {
      animationRef.current = requestAnimationFrame(draw);
      analyser.getFloatTimeDomainData(dataArray);

      const rect = canvas.getBoundingClientRect();
      const width = rect.width;
      const height = rect.height;

      ctx.clearRect(0, 0, width, height);
      ctx.shadowColor = "#7c8dff";
      ctx.shadowBlur = 12;
      ctx.beginPath();
      ctx.lineWidth = 2.5;
      ctx.strokeStyle = "#7c8dff";

      const sliceWidth = width / bufferLength;
      let x = 0;

      for (let i = 0; i < bufferLength; i++) {
        const amplified = dataArray[i] * 4;
        const y = (amplified + 1) / 2 * height;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
        x += sliceWidth;
      }

      ctx.stroke();
      ctx.shadowBlur = 0;
    };

    draw();
  }

  async function startRecording(deviceId?: string) {
    setState("starting");
    setError(null);
    chunksRef.current = [];

    try {
      const constraints: MediaStreamConstraints = {
        audio: {
          deviceId: deviceId ? { exact: deviceId } : undefined,
          // Disable echo cancellation and noise suppression (cause artifacts,
          // server-side pipeline handles normalization). Keep AGC enabled so
          // recordings have usable levels across different mics/devices.
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: true,
          sampleRate: 48000,
          channelCount: 1,
        },
      };

      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      streamRef.current = stream;

      // Enumerate devices now that we have permission
      const all = await navigator.mediaDevices.enumerateDevices();
      const audioInputs = all.filter((d) => d.kind === "audioinput");
      setDevices(audioInputs);
      if (audioInputs.length > 0 && !deviceId) {
        setSelectedDevice(audioInputs[0].deviceId);
      }

      // Set up audio analysis for waveform
      const audioCtx = new AudioContext({ sampleRate: 48000 });
      audioCtxRef.current = audioCtx;
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.8;
      source.connect(analyser);
      analyserRef.current = analyser;

      // Pick best supported format
      const mimeTypes = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/mp4",
        "audio/ogg;codecs=opus",
      ];
      const mimeType = mimeTypes.find((m) => MediaRecorder.isTypeSupported(m)) || "";

      const recorder = new MediaRecorder(stream, {
        mimeType: mimeType || undefined,
        audioBitsPerSecond: 128000,
      });

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          chunksRef.current.push(e.data);
        }
      };

      mediaRecorderRef.current = recorder;
      recorder.start(); // No timeslice! Single continuous blob avoids WebM chunk-boundary stuttering

      startTimeRef.current = Date.now();
      setState("recording");
      setElapsed(0);

      // Keep screen awake during recording
      await acquireWakeLock();

      // Show recording on lock screen (Now Playing widget)
      setupMediaSession();

      timerRef.current = setInterval(() => {
        const secs = Math.floor((Date.now() - startTimeRef.current) / 1000);
        setElapsed(secs);
        // Update lock screen title with elapsed time
        if ("mediaSession" in navigator && navigator.mediaSession.metadata) {
          const h = Math.floor(secs / 3600);
          const m = Math.floor((secs % 3600) / 60);
          const s = secs % 60;
          const ts = h > 0
            ? `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`
            : `${m}:${s.toString().padStart(2, "0")}`;
          navigator.mediaSession.metadata.title = `Recording ${ts}`;
        }
      }, 200);

      // Size canvas and start waveform
      sizeCanvas();
      if (animationRef.current) cancelAnimationFrame(animationRef.current);
      startWaveform(analyser);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Unknown error";
      console.error("Recording failed:", err);
      if (message.includes("NotAllowed") || message.includes("Permission")) {
        setError("Microphone access denied. Check your browser settings.");
      } else {
        setError(`Recording failed: ${message}`);
      }
    }
  }

  // Auto-start recording on mount - no deps, runs once
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    startRecording();
  }, []);

  // Handle window resize
  useEffect(() => {
    const handleResize = () => sizeCanvas();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const stopRecording = async () => {
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === "inactive") return;

    if (timerRef.current) clearInterval(timerRef.current);
    if (animationRef.current) cancelAnimationFrame(animationRef.current);

    await releaseWakeLock();
    teardownMediaSession();
    setStealthMode(false);

    return new Promise<void>((resolve) => {
      recorder.onstop = () => {
        streamRef.current?.getTracks().forEach((t) => t.stop());
        audioCtxRef.current?.close();
        resolve();
      };
      recorder.stop();
    });
  };

  const handleStop = async () => {
    await stopRecording();

    if (chunksRef.current.length === 0) {
      setError("No audio data captured.");
      setState("starting");
      return;
    }

    const mimeType = mediaRecorderRef.current?.mimeType || "audio/webm";
    const blob = new Blob(chunksRef.current, { type: mimeType });

    const ext = mimeType.includes("mp4")
      ? "m4a"
      : mimeType.includes("ogg")
      ? "ogg"
      : "webm";
    const filename = `recording-${new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-")}.${ext}`;
    const file = new File([blob], filename, { type: mimeType });

    // Save to IndexedDB immediately so the recording is never lost
    const pendingId = `rec-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const pendingRec: PendingRecording = {
      id: pendingId,
      blob,
      filename,
      mimeType,
      createdAt: Date.now(),
      attempts: 0,
    };

    try {
      await savePending(pendingRec);
    } catch (e) {
      console.warn("IndexedDB save failed, uploading directly:", e);
    }

    setState("uploading");
    setUploadProgress(0);

    try {
      const progressInterval = setInterval(() => {
        setUploadProgress((p) => Math.min(p + 8, 90));
      }, 200);

      const result = await uploadAudio(file);
      clearInterval(progressInterval);
      setUploadProgress(100);

      // Upload succeeded - remove from IndexedDB
      const { removePending } = await import("@/lib/offline-store");
      await removePending(pendingId).catch(() => {});

      setTimeout(() => {
        onRecordingComplete?.(result.job_id);
      }, 400);
    } catch (err) {
      console.error("Upload failed, recording saved offline:", err);
      setState("saved-offline");

      // Request background sync if available
      if ("serviceWorker" in navigator && "SyncManager" in window) {
        const reg = await navigator.serviceWorker.ready;
        try {
          await (reg as any).sync.register("upload-pending");
        } catch {
          // Background sync not supported or denied
        }
      }
    }
  };

  const handleClose = async () => {
    if (state === "recording") await stopRecording();
    onClose?.();
  };

  const formatElapsed = (s: number) => {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    if (h > 0) {
      return `${h}:${m.toString().padStart(2, "0")}:${sec.toString().padStart(2, "0")}`;
    }
    return `${m}:${sec.toString().padStart(2, "0")}`;
  };

  return (
    <div
      className="fixed inset-0 z-[100] bg-[#08090d] flex flex-col items-center justify-between safe-area-inset touch-manipulation"
      onDoubleClick={(e) => {
        // Desktop fallback only
        const target = e.target as HTMLElement;
        if (target.closest("button") || target.closest("select")) return;
        setStealthMode((prev) => !prev);
      }}
    >
      {/* Stealth mode: black overlay, recording continues underneath.
          Document-level touchstart listener handles double-tap through the overlay. */}
      {stealthMode && (
        <div className="fixed inset-0 z-[200] bg-black touch-manipulation" />
      )}

      {/* Top bar */}
      <div className="w-full flex items-center justify-between px-4 pt-4 pb-2">
        <button
          onClick={handleClose}
          className="p-2 text-vs-text-muted hover:text-vs-text-primary transition-colors"
        >
          <X className="w-5 h-5" />
        </button>

        {/* Mic selector - show during recording if multiple devices */}
        {state === "recording" && devices.length > 1 && (
          <div className="relative">
            <button
              onClick={() => setShowDevices(!showDevices)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 text-xs text-vs-text-secondary hover:bg-white/10 transition-colors"
            >
              <Mic className="w-3 h-3" />
              <span className="max-w-[140px] truncate">
                {devices.find((d) => d.deviceId === selectedDevice)?.label || "Microphone"}
              </span>
              <ChevronDown className="w-3 h-3 opacity-50" />
            </button>
            {showDevices && (
              <div className="absolute right-0 top-full mt-1 w-64 bg-vs-raised border border-vs-border rounded-lg shadow-xl overflow-hidden animate-fade-in z-10">
                {devices.map((device) => (
                  <button
                    key={device.deviceId}
                    onClick={async () => {
                      setSelectedDevice(device.deviceId);
                      setShowDevices(false);
                      // Restart recording with new device
                      await stopRecording();
                      startRecording(device.deviceId);
                    }}
                    className={`w-full px-3 py-2 text-left text-xs transition-colors ${
                      device.deviceId === selectedDevice
                        ? "bg-vs-text-accent/10 text-vs-text-accent"
                        : "text-vs-text-secondary hover:bg-vs-hover"
                    }`}
                  >
                    {device.label || `Microphone ${device.deviceId.slice(0, 8)}`}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {state === "recording" && (
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
            <span className="text-xs text-red-400 font-mono">{formatElapsed(elapsed)}</span>
          </div>
        )}

        {state === "uploading" && (
          <span className="text-xs text-vs-text-muted">Uploading...</span>
        )}

        {state === "saved-offline" && (
          <div className="flex items-center gap-1.5">
            <WifiOff className="w-3.5 h-3.5 text-amber-400" />
            <span className="text-xs text-amber-400">Offline</span>
          </div>
        )}

        {state === "starting" && (
          <span className="text-xs text-vs-text-muted">Starting mic...</span>
        )}
      </div>

      {/* Center: Waveform */}
      <div className="flex-1 flex flex-col items-center justify-center w-full px-6 gap-6">
        {error && (
          <div className="px-4 py-2 bg-red-500/10 border border-red-500/20 rounded-lg">
            <p className="text-xs text-red-400">{error}</p>
          </div>
        )}

        <canvas
          ref={canvasRef}
          className="w-full max-w-lg"
          style={{ height: "120px" }}
        />

        {state === "starting" && !error && (
          <Loader2 className="w-6 h-6 text-vs-text-muted animate-spin" />
        )}

        {state === "recording" && (
          <p className="text-xs text-vs-text-muted animate-pulse">Tap stop when finished</p>
        )}

        {state === "uploading" && (
          <div className="w-48">
            <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
              <div
                className="h-full bg-vs-text-accent rounded-full transition-all duration-300"
                style={{ width: `${uploadProgress}%` }}
              />
            </div>
          </div>
        )}

        {state === "saved-offline" && (
          <div className="flex flex-col items-center gap-3">
            <div className="w-16 h-16 rounded-full bg-amber-500/10 border border-amber-500/20 flex items-center justify-center">
              <Check className="w-8 h-8 text-amber-400" />
            </div>
            <p className="text-sm text-vs-text-primary font-medium">Recording saved</p>
            <p className="text-xs text-vs-text-muted text-center max-w-[240px]">
              You appear to be offline. Your recording is saved locally and will upload automatically when you reconnect.
            </p>
          </div>
        )}
      </div>

      {/* Bottom: Stop button (or uploading spinner) */}
      <div className="w-full flex flex-col items-center gap-3 pb-8 px-6">
        {state === "recording" && (
          <button
            onClick={handleStop}
            className="w-20 h-20 rounded-full bg-red-500 flex items-center justify-center shadow-lg shadow-red-500/20 hover:bg-red-600 active:scale-95 transition-all"
          >
            <Square className="w-7 h-7 text-white fill-white" />
          </button>
        )}

        {state === "uploading" && (
          <div className="w-20 h-20 rounded-full bg-vs-raised flex items-center justify-center">
            <Loader2 className="w-8 h-8 text-vs-text-accent animate-spin" />
          </div>
        )}

        {state === "starting" && !error && (
          <div className="w-20 h-20 rounded-full bg-vs-raised/50 flex items-center justify-center">
            <Mic className="w-8 h-8 text-vs-text-muted animate-pulse" />
          </div>
        )}

        {state === "saved-offline" && (
          <button
            onClick={() => onClose?.()}
            className="btn-primary flex items-center gap-2"
          >
            <Check className="w-4 h-4" />
            Done
          </button>
        )}

        {error && (
          <button
            onClick={() => {
              setError(null);
              startRecording();
            }}
            className="btn-primary flex items-center gap-2"
          >
            <Mic className="w-4 h-4" />
            Try Again
          </button>
        )}
      </div>
    </div>
  );
}
