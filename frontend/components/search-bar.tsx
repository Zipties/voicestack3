"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Search, Loader2, Filter, X } from "lucide-react";
import {
  searchTranscripts,
  fetchSpeakers,
  type SearchResult,
  type SearchResponse,
  type Speaker,
} from "@/lib/api";
import { getSpeakerColor } from "@/lib/store";
import { formatTime } from "@/lib/utils";

function HighlightText({ text, query }: { text: string; query: string }) {
  if (!query || query.length < 2) return <>{text}</>;
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const parts = text.split(new RegExp(`(${escaped})`, "gi"));
  return (
    <>
      {parts.map((part, i) =>
        part.toLowerCase() === query.toLowerCase() ? (
          <mark
            key={i}
            className="bg-vs-text-accent/20 text-vs-text-accent font-semibold rounded-sm px-0.5"
          >
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </>
  );
}

export function SearchBar() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [meta, setMeta] = useState<SearchResponse["meta"] | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const [hasSearched, setHasSearched] = useState(false);

  // Speaker filter
  const [speakers, setSpeakers] = useState<Speaker[]>([]);
  const [speakersLoaded, setSpeakersLoaded] = useState(false);
  const [showFilter, setShowFilter] = useState(false);
  const [selectedSpeaker, setSelectedSpeaker] = useState<string>("");

  const doSearch = useCallback(
    async (q: string, speaker?: string) => {
      if (q.length < 2) {
        setResults([]);
        setMeta(null);
        setIsOpen(false);
        setHasSearched(false);
        return;
      }

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setIsLoading(true);
      try {
        const data = await searchTranscripts(
          q,
          20,
          speaker || undefined,
          controller.signal
        );
        setResults(data.results);
        setMeta(data.meta);
        setIsOpen(true);
        setHasSearched(true);
        setSelectedIndex(-1);
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === "AbortError") return;
      } finally {
        if (!controller.signal.aborted) setIsLoading(false);
      }
    },
    []
  );

  const handleInputChange = useCallback(
    (value: string) => {
      setQuery(value);
      clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        doSearch(value, selectedSpeaker);
      }, 300);
    },
    [doSearch, selectedSpeaker]
  );

  // Global Cmd+K / Ctrl+K
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  // Click outside to close
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const navigateToResult = useCallback(
    (result: SearchResult) => {
      setIsOpen(false);
      inputRef.current?.blur();
      router.push(
        `/jobs/${result.job_id}?t=${result.start_time}&highlight=${result.segment_id}`
      );
    },
    [router]
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!isOpen || results.length === 0) {
      if (e.key === "Escape") {
        setIsOpen(false);
        inputRef.current?.blur();
      }
      return;
    }

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setSelectedIndex((prev) =>
          prev < results.length - 1 ? prev + 1 : 0
        );
        break;
      case "ArrowUp":
        e.preventDefault();
        setSelectedIndex((prev) =>
          prev > 0 ? prev - 1 : results.length - 1
        );
        break;
      case "Enter":
        e.preventDefault();
        if (selectedIndex >= 0 && selectedIndex < results.length) {
          navigateToResult(results[selectedIndex]);
        }
        break;
      case "Escape":
        e.preventDefault();
        setIsOpen(false);
        inputRef.current?.blur();
        break;
    }
  };

  const loadSpeakers = async () => {
    if (speakersLoaded) return;
    try {
      const data = await fetchSpeakers();
      setSpeakers(data);
      setSpeakersLoaded(true);
    } catch {
      // ignore
    }
  };

  const handleFilterToggle = () => {
    if (!showFilter) loadSpeakers();
    setShowFilter((prev) => !prev);
  };

  const handleSpeakerSelect = (speakerId: string) => {
    setSelectedSpeaker(speakerId);
    setShowFilter(false);
    if (query.length >= 2) {
      doSearch(query, speakerId);
    }
  };

  const clearSpeakerFilter = () => {
    setSelectedSpeaker("");
    if (query.length >= 2) {
      doSearch(query, "");
    }
  };

  const [isMac, setIsMac] = useState(false);
  useEffect(() => {
    setIsMac(navigator.userAgent.toLowerCase().includes("mac"));
  }, []);

  return (
    <div
      ref={dropdownRef}
      className="relative pl-14 md:pl-4 pr-4 py-3 border-b border-vs-border"
    >
      {/* Input row */}
      <div className="relative flex items-center gap-2">
        <div className="relative flex-1">
          <div className="absolute left-3 top-1/2 -translate-y-1/2 text-vs-text-muted">
            {isLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Search className="w-4 h-4" />
            )}
          </div>
          <input
            ref={inputRef}
            type="text"
            placeholder="Search transcripts..."
            value={query}
            onChange={(e) => handleInputChange(e.target.value)}
            onKeyDown={handleKeyDown}
            onFocus={() => {
              if (hasSearched && results.length > 0) setIsOpen(true);
            }}
            className="input w-full pl-10 pr-20"
          />
          <div className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-2">
            {selectedSpeaker && (
              <button
                onClick={clearSpeakerFilter}
                className="flex items-center gap-1 text-2xs bg-vs-text-accent/15 text-vs-text-accent rounded-md px-1.5 py-0.5"
              >
                <span className="max-w-[60px] truncate">
                  {speakers.find((s) => s.name === selectedSpeaker)?.name ||
                    selectedSpeaker}
                </span>
                <X className="w-3 h-3" />
              </button>
            )}
            <kbd className="hidden sm:inline-flex items-center gap-0.5 text-2xs text-vs-text-muted bg-vs-surface border border-vs-border rounded px-1.5 py-0.5 font-mono">
              {isMac ? "⌘" : "Ctrl+"}K
            </kbd>
          </div>
        </div>

        {/* Filter button */}
        <button
          onClick={handleFilterToggle}
          className={`p-2 rounded-lg border transition-colors duration-100 ${
            showFilter || selectedSpeaker
              ? "border-vs-text-accent/40 text-vs-text-accent bg-vs-text-accent/10"
              : "border-vs-border text-vs-text-muted hover:text-vs-text-secondary hover:bg-vs-hover"
          }`}
          title="Filter by speaker"
        >
          <Filter className="w-4 h-4" />
        </button>
      </div>

      {/* Speaker filter dropdown */}
      {showFilter && (
        <div className="absolute right-4 top-full mt-1 w-56 bg-vs-raised border border-vs-border rounded-xl shadow-lg z-50 py-1 max-h-60 overflow-y-auto animate-fade-in">
          <button
            onClick={() => handleSpeakerSelect("")}
            className={`w-full text-left px-3 py-2 text-sm hover:bg-vs-hover transition-colors ${
              !selectedSpeaker
                ? "text-vs-text-accent font-medium"
                : "text-vs-text-secondary"
            }`}
          >
            All speakers
          </button>
          {speakers.map((s) => (
            <button
              key={s.id}
              onClick={() => handleSpeakerSelect(s.name)}
              className={`w-full text-left px-3 py-2 text-sm hover:bg-vs-hover transition-colors flex items-center gap-2 ${
                selectedSpeaker === s.name
                  ? "text-vs-text-accent font-medium"
                  : "text-vs-text-secondary"
              }`}
            >
              <span
                className="w-2.5 h-2.5 rounded-full shrink-0"
                style={{ backgroundColor: getSpeakerColor(s.id) }}
              />
              <span className="truncate">{s.name}</span>
            </button>
          ))}
          {speakersLoaded && speakers.length === 0 && (
            <p className="px-3 py-2 text-sm text-vs-text-muted">
              No speakers found
            </p>
          )}
        </div>
      )}

      {/* Results dropdown */}
      {isOpen && hasSearched && (
        <div className="absolute left-0 right-0 top-full mt-0 bg-vs-raised border border-vs-border rounded-xl shadow-lg z-50 max-h-[60vh] overflow-y-auto animate-fade-in mx-4">
          {/* Semantic unavailable notice */}
          {meta && !meta.semantic_available && (
            <div className="px-3 py-1.5 text-xs text-vs-text-muted bg-vs-hover/50 rounded-t-xl border-b border-vs-border">
              Showing text matches only
            </div>
          )}

          {results.length === 0 ? (
            <div className="px-4 py-8 text-center text-vs-text-muted text-sm">
              No results for &ldquo;{query}&rdquo;
            </div>
          ) : (
            <div className="py-1">
              {results.map((result, i) => (
                <div
                  key={`${result.segment_id}-${i}`}
                  onClick={() => navigateToResult(result)}
                  className={`mx-1 px-3 py-2.5 rounded-lg cursor-pointer transition-colors duration-100 flex items-start gap-3 ${
                    i === selectedIndex
                      ? "bg-vs-hover"
                      : "hover:bg-vs-hover"
                  }`}
                >
                  {/* Speaker color dot */}
                  <span
                    className="w-2.5 h-2.5 rounded-full mt-1.5 shrink-0"
                    style={{
                      backgroundColor: result.speaker
                        ? getSpeakerColor(result.speaker)
                        : "#636879",
                    }}
                  />

                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-xs font-medium text-vs-text-primary">
                        {result.speaker || "Unknown"}
                      </span>
                    </div>
                    <p className="text-sm text-vs-text-secondary line-clamp-2 leading-relaxed">
                      <HighlightText text={result.text} query={query} />
                    </p>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-2xs text-vs-text-muted truncate max-w-[200px]">
                        {result.title || "Untitled"}
                      </span>
                      <span className="text-2xs text-vs-text-muted">
                        {formatTime(result.start_time)}
                      </span>
                    </div>
                  </div>

                  {/* Source badge */}
                  <span className="text-2xs text-vs-text-muted mt-1 shrink-0">
                    {result.source}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
