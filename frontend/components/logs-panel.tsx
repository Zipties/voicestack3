"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp, Terminal } from "lucide-react";
import { subscribeToLogs } from "@/lib/api";

export function LogsPanel({ jobId }: { jobId: string }) {
  const [logs, setLogs] = useState<string[]>([]);
  const [expanded, setExpanded] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const autoScroll = useRef(true);

  useEffect(() => {
    const unsub = subscribeToLogs(jobId, (line) => {
      setLogs((prev) => {
        const next = [...prev, line];
        // Keep last 500 lines
        return next.length > 500 ? next.slice(-500) : next;
      });
    });
    return unsub;
  }, [jobId]);

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (autoScroll.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  const handleScroll = () => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    // Disable auto-scroll if user scrolled up
    autoScroll.current = scrollHeight - scrollTop - clientHeight < 40;
  };

  const lineColor = (line: string) => {
    if (line.includes("FAILED") || line.includes("Error") || line.includes("error"))
      return "text-red-400";
    if (line.includes("COMPLETED")) return "text-green-400";
    if (line.includes("DETECTED")) return "text-amber-400";
    if (line.includes("MATCHED")) return "text-emerald-400";
    if (line.includes("[VRAM]") || line.includes("[GPU]")) return "text-purple-400";
    if (line.startsWith("===")) return "text-vs-text-muted";
    return "text-vs-text-secondary";
  };

  return (
    <div className="border-t border-vs-border bg-vs-surface">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-4 py-2 text-xs font-medium text-vs-text-muted hover:text-vs-text-primary transition-colors"
      >
        <Terminal className="w-3.5 h-3.5" />
        <span>Pipeline Logs</span>
        {logs.length > 0 && (
          <span className="text-2xs bg-vs-hover rounded px-1.5 py-0.5">
            {logs.length}
          </span>
        )}
        <span className="flex-1" />
        {expanded ? (
          <ChevronDown className="w-3.5 h-3.5" />
        ) : (
          <ChevronUp className="w-3.5 h-3.5" />
        )}
      </button>

      {/* Log content */}
      {expanded && (
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="h-48 overflow-auto px-4 pb-3 font-mono text-2xs leading-relaxed select-text"
        >
          {logs.length === 0 ? (
            <p className="text-vs-text-muted italic py-2">
              Waiting for pipeline logs...
            </p>
          ) : (
            logs.map((line, i) => (
              <div key={i} className={lineColor(line)}>
                {line}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
