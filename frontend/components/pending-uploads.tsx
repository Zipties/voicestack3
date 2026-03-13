"use client";

import { useState, useEffect, useCallback } from "react";
import { CloudUpload, Loader2, WifiOff } from "lucide-react";
import { getAllPending, removePending, type PendingRecording } from "@/lib/offline-store";
import { uploadAudio } from "@/lib/api";

export function PendingUploads() {
  const [pending, setPending] = useState<PendingRecording[]>([]);
  const [flushing, setFlushing] = useState(false);
  const [online, setOnline] = useState(
    typeof navigator !== "undefined" ? navigator.onLine : true
  );

  const refresh = useCallback(async () => {
    try {
      const items = await getAllPending();
      setPending(items);
    } catch {
      // IndexedDB unavailable
    }
  }, []);

  // Poll for pending items (catches saves from recorder + background sync removals)
  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 3000);
    return () => clearInterval(interval);
  }, [refresh]);

  // Track online/offline status
  useEffect(() => {
    const goOnline = () => setOnline(true);
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);

  // Auto-flush when coming back online
  useEffect(() => {
    if (online && pending.length > 0 && !flushing) {
      flush();
    }
  }, [online]); // eslint-disable-line react-hooks/exhaustive-deps

  async function flush() {
    if (flushing) return;
    setFlushing(true);

    try {
      const items = await getAllPending();
      for (const rec of items) {
        try {
          const file = new File([rec.blob], rec.filename, { type: rec.mimeType });
          await uploadAudio(file);
          await removePending(rec.id);
        } catch {
          // Will retry on next flush
          break; // Stop on first failure (probably still offline)
        }
      }
    } finally {
      setFlushing(false);
      await refresh();
    }
  }

  if (pending.length === 0) return null;

  return (
    <button
      onClick={online ? flush : undefined}
      disabled={!online || flushing}
      className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors text-amber-400 hover:bg-vs-hover disabled:opacity-60 disabled:cursor-default"
    >
      {flushing ? (
        <Loader2 className="w-4 h-4 animate-spin" />
      ) : online ? (
        <CloudUpload className="w-4 h-4" />
      ) : (
        <WifiOff className="w-4 h-4" />
      )}
      <span>
        {flushing
          ? "Uploading..."
          : `${pending.length} pending`}
      </span>
    </button>
  );
}
