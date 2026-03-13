"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import {
  MessageSquare,
  Send,
  Loader2,
  ChevronDown,
  X,
  User,
  RotateCcw,
} from "lucide-react";
import {
  fetchChatAgents,
  chatWithTranscript,
  type ChatAgent,
} from "@/lib/api";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  agent?: string;
}

interface ChatSidebarProps {
  transcriptId: string;
  isOpen: boolean;
  onClose: () => void;
}

// ─── localStorage helpers ────────────────────────────────────────────────────

const AGENT_KEY = "vs3-chat-agent";
const HISTORY_PREFIX = "vs3-chat-history:";
const SESSION_PREFIX = "vs3-chat-session:";

function storageKey(transcriptId: string, agentId: string, prefix: string) {
  return `${prefix}${transcriptId}:${agentId}`;
}

function loadSelectedAgent(): string {
  if (typeof window === "undefined") return "main";
  return localStorage.getItem(AGENT_KEY) || "main";
}

function saveSelectedAgent(agentId: string) {
  localStorage.setItem(AGENT_KEY, agentId);
}

function loadHistory(transcriptId: string, agentId: string): ChatMessage[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(storageKey(transcriptId, agentId, HISTORY_PREFIX));
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveHistory(transcriptId: string, agentId: string, messages: ChatMessage[]) {
  localStorage.setItem(
    storageKey(transcriptId, agentId, HISTORY_PREFIX),
    JSON.stringify(messages)
  );
}

function loadSessionId(transcriptId: string, agentId: string): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(storageKey(transcriptId, agentId, SESSION_PREFIX));
}

function saveSessionId(transcriptId: string, agentId: string, sessionId: string) {
  localStorage.setItem(
    storageKey(transcriptId, agentId, SESSION_PREFIX),
    sessionId
  );
}

function clearChat(transcriptId: string, agentId: string) {
  localStorage.removeItem(storageKey(transcriptId, agentId, HISTORY_PREFIX));
  localStorage.removeItem(storageKey(transcriptId, agentId, SESSION_PREFIX));
}

// ─── Agent colors ────────────────────────────────────────────────────────────

const AGENT_COLORS: Record<string, string> = {
  main: "#51A3FF",
  kira: "#FF6B9D",
  cindy: "#C17BF5",
  tyrell: "#4ECDC4",
};

function getAgentColor(id: string): string {
  return AGENT_COLORS[id] || "#FFB347";
}

// ─── Component ───────────────────────────────────────────────────────────────

export function ChatSidebar({ transcriptId, isOpen, onClose }: ChatSidebarProps) {
  const [agents, setAgents] = useState<ChatAgent[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string>(loadSelectedAgent);
  const [showAgentPicker, setShowAgentPicker] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Load agents list
  useEffect(() => {
    fetchChatAgents()
      .then((list) => {
        setAgents(list);
        const saved = loadSelectedAgent();
        if (list.length > 0 && !list.find((a) => a.id === saved)) {
          setSelectedAgent(list[0].id);
          saveSelectedAgent(list[0].id);
        }
      })
      .catch((err) => console.error("Failed to load agents:", err));
  }, []);

  // Load history + session when transcript or agent changes
  useEffect(() => {
    const history = loadHistory(transcriptId, selectedAgent);
    const session = loadSessionId(transcriptId, selectedAgent);
    setMessages(history);
    setSessionId(session);
  }, [transcriptId, selectedAgent]);

  // Persist messages whenever they change
  const persistMessages = useCallback(
    (msgs: ChatMessage[]) => {
      saveHistory(transcriptId, selectedAgent, msgs);
    },
    [transcriptId, selectedAgent]
  );

  useEffect(() => {
    if (messages.length > 0) {
      persistMessages(messages);
    }
  }, [messages, persistMessages]);

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input when sidebar opens
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [isOpen]);

  // Auto-resize textarea
  useEffect(() => {
    const el = inputRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 120) + "px";
    }
  }, [input]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || sending) return;

    setInput("");
    const userMsg: ChatMessage = { role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    setSending(true);

    try {
      const result = await chatWithTranscript(
        transcriptId,
        text,
        selectedAgent,
        sessionId ?? undefined
      );
      // Persist the session ID for this transcript+agent
      setSessionId(result.session_id);
      saveSessionId(transcriptId, selectedAgent, result.session_id);

      const assistantMsg: ChatMessage = {
        role: "assistant",
        content: result.response,
        agent: result.agent,
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Failed to get a response. The agent may be unavailable." },
      ]);
      console.error("Chat error:", err);
    } finally {
      setSending(false);
    }
  };

  const handleNewSession = () => {
    clearChat(transcriptId, selectedAgent);
    setMessages([]);
    setSessionId(null);
  };

  const handleAgentSwitch = (agentId: string) => {
    if (agentId !== selectedAgent) {
      setSelectedAgent(agentId);
      saveSelectedAgent(agentId);
      // History/session for the new agent will be loaded by the useEffect above
    }
    setShowAgentPicker(false);
  };

  const currentAgent = agents.find((a) => a.id === selectedAgent);
  const agentColor = getAgentColor(selectedAgent);

  if (!isOpen) return null;

  return (
    <div className="w-[340px] border-l border-vs-border flex flex-col bg-vs-surface shrink-0 min-h-0">
      {/* Header */}
      <div className="px-4 py-3 border-b border-vs-border flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <MessageSquare className="w-4 h-4 text-vs-text-accent shrink-0" />
          <span className="text-sm font-medium truncate">Agent Chat</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={handleNewSession}
            className="p-1.5 text-vs-text-muted hover:text-vs-text-secondary hover:bg-vs-hover rounded"
            title="Clear conversation"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={onClose}
            className="p-1.5 text-vs-text-muted hover:text-vs-text-secondary hover:bg-vs-hover rounded"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Agent Picker */}
      <div className="px-3 py-2 border-b border-vs-border shrink-0">
        <button
          onClick={() => setShowAgentPicker(!showAgentPicker)}
          className="w-full flex items-center justify-between px-2.5 py-2 rounded-lg bg-vs-raised hover:bg-vs-hover text-sm transition-colors"
        >
          <div className="flex items-center gap-2.5">
            <div
              className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold text-white shrink-0"
              style={{ backgroundColor: agentColor }}
            >
              {(currentAgent?.name || selectedAgent)[0].toUpperCase()}
            </div>
            <div className="text-left">
              <div className="text-xs font-medium text-vs-text-primary">
                {currentAgent?.name || selectedAgent}
              </div>
              <div className="text-[10px] text-vs-text-muted truncate max-w-[200px]">
                {currentAgent?.description || ""}
              </div>
            </div>
          </div>
          <ChevronDown
            className={`w-3.5 h-3.5 text-vs-text-muted transition-transform shrink-0 ${
              showAgentPicker ? "rotate-180" : ""
            }`}
          />
        </button>
        {showAgentPicker && (
          <div className="mt-1.5 space-y-0.5 max-h-60 overflow-auto">
            {agents.map((agent) => {
              const color = getAgentColor(agent.id);
              const hasHistory = loadHistory(transcriptId, agent.id).length > 0;
              return (
                <button
                  key={agent.id}
                  onClick={() => handleAgentSwitch(agent.id)}
                  className={`w-full text-left px-2.5 py-2 rounded-lg text-xs transition-colors flex items-center gap-2.5 ${
                    agent.id === selectedAgent
                      ? "bg-vs-text-accent/10"
                      : "hover:bg-vs-hover"
                  }`}
                >
                  <div
                    className="w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold text-white shrink-0"
                    style={{ backgroundColor: color }}
                  >
                    {agent.name[0].toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span
                        className={`font-medium ${
                          agent.id === selectedAgent
                            ? "text-vs-text-accent"
                            : "text-vs-text-secondary"
                        }`}
                      >
                        {agent.name}
                      </span>
                      {hasHistory && (
                        <span className="w-1.5 h-1.5 rounded-full bg-vs-text-accent shrink-0" />
                      )}
                    </div>
                    <div className="text-[10px] text-vs-text-muted mt-0.5">
                      {agent.description}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-auto px-3 py-3 space-y-3 min-h-0">
        {messages.length === 0 && (
          <div className="text-center py-8">
            <div
              className="w-12 h-12 rounded-full flex items-center justify-center text-lg font-bold text-white mx-auto mb-3"
              style={{ backgroundColor: agentColor }}
            >
              {(currentAgent?.name || "?")[0].toUpperCase()}
            </div>
            <p className="text-xs text-vs-text-muted mb-1">
              Chat with <span className="text-vs-text-secondary font-medium">{currentAgent?.name || selectedAgent}</span>
            </p>
            <p className="text-[10px] text-vs-text-muted">
              Transcript context is shared automatically
            </p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex gap-2 ${msg.role === "user" ? "justify-end" : ""}`}
          >
            {msg.role === "assistant" && (
              <div
                className="w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold text-white shrink-0 mt-1"
                style={{ backgroundColor: agentColor }}
              >
                {(currentAgent?.name || "A")[0].toUpperCase()}
              </div>
            )}
            <div
              className={`max-w-[85%] rounded-lg px-3 py-2 text-xs leading-relaxed ${
                msg.role === "user"
                  ? "bg-vs-text-accent/15 text-vs-text-primary"
                  : "bg-vs-raised text-vs-text-secondary"
              }`}
            >
              {msg.content.split("\n").map((line, li) => (
                <p key={li} className={li > 0 ? "mt-1.5" : ""}>
                  {line}
                </p>
              ))}
            </div>
            {msg.role === "user" && (
              <User className="w-4 h-4 text-vs-text-muted shrink-0 mt-1" />
            )}
          </div>
        ))}
        {sending && (
          <div className="flex gap-2">
            <div
              className="w-5 h-5 rounded-full flex items-center justify-center shrink-0 mt-1"
              style={{ backgroundColor: agentColor }}
            >
              <Loader2 className="w-3 h-3 text-white animate-spin" />
            </div>
            <div className="bg-vs-raised rounded-lg px-3 py-2">
              <span className="text-[10px] text-vs-text-muted">
                {currentAgent?.name || "Agent"} is thinking...
              </span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="px-3 py-3 border-t border-vs-border shrink-0 bg-vs-surface">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder={`Message ${currentAgent?.name || "agent"}...`}
            rows={1}
            className="flex-1 min-w-0 bg-vs-raised border border-vs-border rounded-lg px-3 py-2 text-xs text-vs-text-primary placeholder:text-vs-text-muted focus:outline-none focus:ring-2 focus:ring-vs-text-accent/40 focus:border-vs-text-accent/60 transition-colors resize-none"
            disabled={sending}
            style={{ maxHeight: "120px" }}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || sending}
            className="p-2 rounded-lg bg-vs-text-accent text-white disabled:opacity-30 hover:bg-vs-text-accent/80 transition-colors shrink-0"
          >
            <Send className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}
