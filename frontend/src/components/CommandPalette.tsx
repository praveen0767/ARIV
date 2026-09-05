"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { Search, X, Loader2, Bot, ChevronRight, Terminal } from "lucide-react";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  steps?: string[];
  timestamp: Date;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

const SUGGESTED = [
  "Why did the latest payment fail?",
  "Can any open cases be recovered?",
  "What is the current policy status?",
  "Show recent recovery actions.",
  "How much incremental revenue has ARIV generated?",
  "Which failure category is most common?",
];

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [steps, setSteps] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, steps]);

  const handleSubmit = useCallback(async () => {
    if (!query.trim() || loading) return;
    const userQuery = query.trim();
    setQuery("");

    const userMsg: Message = {
      id: Date.now().toString(),
      role: "user",
      content: userQuery,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);
    setSteps([]);

    try {
      const response = await fetch("/api/proxy/v1/agent/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: userQuery }),
      });

      if (!response.ok || !response.body) {
        throw new Error(`Error ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let currentSteps: string[] = [];
      let finalContent = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim();
          if (!raw || raw === "[DONE]") continue;
          try {
            const event = JSON.parse(raw);
            if (event.type === "step") {
              currentSteps = [...currentSteps, event.text];
              setSteps([...currentSteps]);
            } else if (event.type === "content") {
              finalContent += event.text;
            }
          } catch {
            // ignore parse errors
          }
        }
      }

      const assistantMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: finalContent || "I couldn't retrieve data from the backend. Please ensure the backend is running.",
        steps: currentSteps,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err: any) {
      const errMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: `Error: ${err.message}. Please check backend connectivity.`,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errMsg]);
    } finally {
      setLoading(false);
      setSteps([]);
    }
  }, [query, loading]);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        if (!open) onClose(); // toggle handled by parent
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose, open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[10vh]">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="relative w-full max-w-2xl bg-white border border-slate-200 rounded-xl shadow-2xl overflow-hidden flex flex-col max-h-[75vh]">
        {/* Header */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-200 bg-slate-50">
          <Bot className="w-5 h-5 text-blue-600 flex-shrink-0" />
          <span className="text-sm font-semibold text-slate-700">ASK ARIV</span>
          <span className="text-xs text-slate-400 ml-1">— Revenue Recovery AI</span>
          <button
            onClick={onClose}
            className="ml-auto text-slate-400 hover:text-slate-700 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Conversation */}
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto p-4 space-y-4 min-h-0"
        >
          {messages.length === 0 ? (
            <div className="space-y-3">
              <p className="text-sm text-slate-500 text-center pt-2">
                Ask ARIV anything about payment failures, recovery actions, or system state.
              </p>
              <div className="grid grid-cols-1 gap-2 mt-4">
                {SUGGESTED.map((s) => (
                  <button
                    key={s}
                    onClick={() => setQuery(s)}
                    className="text-left text-sm text-slate-600 hover:text-blue-700 hover:bg-blue-50 px-3 py-2 rounded-lg transition-colors flex items-center gap-2 border border-slate-100"
                  >
                    <ChevronRight className="w-3 h-3 text-slate-400 flex-shrink-0" />
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((msg) => (
              <div key={msg.id} className={msg.role === "user" ? "flex justify-end" : "flex justify-start"}>
                {msg.role === "assistant" && (
                  <div className="flex items-start gap-3 max-w-full">
                    <div className="w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center flex-shrink-0 mt-0.5">
                      <Bot className="w-4 h-4 text-white" />
                    </div>
                    <div className="space-y-2 max-w-[calc(100%-2.5rem)]">
                      {msg.steps && msg.steps.length > 0 && (
                        <div className="space-y-1">
                          {msg.steps.map((step, i) => (
                            <div key={i} className="flex items-center gap-1.5 text-xs text-slate-400">
                              <span className="text-emerald-500">✓</span>
                              {step}
                            </div>
                          ))}
                        </div>
                      )}
                      <div className="bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5">
                        <pre className="text-sm text-slate-800 whitespace-pre-wrap font-sans leading-relaxed">
                          {msg.content}
                        </pre>
                      </div>
                    </div>
                  </div>
                )}
                {msg.role === "user" && (
                  <div className="bg-blue-600 text-white rounded-lg px-3 py-2 max-w-[80%]">
                    <p className="text-sm">{msg.content}</p>
                  </div>
                )}
              </div>
            ))
          )}

          {/* Loading steps */}
          {loading && (
            <div className="flex items-start gap-3">
              <div className="w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center flex-shrink-0 mt-0.5">
                <Bot className="w-4 h-4 text-white" />
              </div>
              <div className="space-y-1.5">
                {steps.map((step, i) => (
                  <div key={i} className="flex items-center gap-1.5 text-xs text-slate-400">
                    <span className="text-emerald-500">✓</span>
                    {step}
                  </div>
                ))}
                <div className="flex items-center gap-2 text-xs text-slate-400">
                  <Loader2 className="w-3 h-3 animate-spin text-blue-500" />
                  Investigating…
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Input */}
        <div className="border-t border-slate-200 p-3 bg-white">
          <div className="flex items-center gap-2 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 focus-within:ring-2 focus-within:ring-blue-500/20 focus-within:border-blue-400 transition-all">
            <Terminal className="w-4 h-4 text-slate-400 flex-shrink-0" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSubmit();
                }
              }}
              placeholder="Ask ARIV about any payment, case, or recovery action…"
              className="flex-1 bg-transparent text-sm text-slate-800 placeholder:text-slate-400 outline-none"
              disabled={loading}
            />
            {loading ? (
              <Loader2 className="w-4 h-4 animate-spin text-blue-500 flex-shrink-0" />
            ) : (
              <kbd className="text-xs text-slate-400 font-mono bg-slate-200 px-1.5 py-0.5 rounded border border-slate-300">↵</kbd>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
