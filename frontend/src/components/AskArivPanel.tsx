"use client";

import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { createPortal } from "react-dom";
import { usePathname, useRouter } from "next/navigation";
import {
  Bot,
  X,
  ChevronRight,
  Loader2,
  Terminal,
  Sparkles,
  MessageSquare,
  Minimize2,
  Maximize2,
  ArrowUp,
  Copy,
  Check,
  ShieldAlert,
  ArrowRight,
  Activity,
  Layers,
  ExternalLink,
} from "lucide-react";
import { useAriv } from "@/context/ArivContext";
import { useLiveStatus, formatLastUpdated } from "@/hooks/use-live-status";
import { activityStore, ActivityEvent } from "@/components/ActivityToast";

interface NavigationLink {
  label: string;
  href: string;
  is_external?: boolean;
  isExternal?: boolean;
}

interface MessageMeta {
  case_id?: string;
  payment_link_url?: string;
  action_type?: string;
  status?: string;
  can_recover?: boolean;
  links?: NavigationLink[];
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  steps?: string[];
  meta?: MessageMeta;
  recommendation?: {
    action: string;
    status?: string;
    recoverability?: string;
    policy?: string;
    autonomy?: string;
    paymentUrl?: string;
  };
  timestamp: Date;
}

export function AskArivPanel() {
  const { isOpen, closeAriv, initialQuery, clearInitialQuery } = useAriv();
  const [mounted, setMounted] = useState(false);
  const [query, setQuery] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [steps, setSteps] = useState<string[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [latestActivity, setLatestActivity] = useState<ActivityEvent | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pathname = usePathname();
  const router = useRouter();
  const { liveState, lastUpdated } = useLiveStatus();

  // Mount detection for React portal
  useEffect(() => {
    setMounted(true);
  }, []);

  // Subscribe to live activity stream
  useEffect(() => {
    const unsub = activityStore.subscribe((events) => {
      if (events.length > 0) {
        setLatestActivity(events[0]);
      }
    });
    return unsub;
  }, []);

  // Derive page-aware context chip (Requirement 7)
  const pageContext = useMemo(() => {
    if (!pathname) return { label: "Command Center", route: "/" };
    if (pathname === "/") return { label: "Command Center", route: "/" };
    if (pathname.startsWith("/cases/")) {
      const id = pathname.split("/")[2] || "";
      return { label: `Case ${id ? id.slice(0, 8) + "..." : "Detail"}`, route: pathname, caseId: id };
    }
    if (pathname.startsWith("/cases")) return { label: "Recovery Operations", route: "/cases" };
    if (pathname.startsWith("/impact")) return { label: "Recovery Impact", route: "/impact" };
    if (pathname.startsWith("/demo")) return { label: "Live Demo", route: "/demo" };
    if (pathname.startsWith("/system")) return { label: "System Health", route: "/system" };
    if (pathname.startsWith("/settings")) return { label: "Settings", route: "/settings" };
    return { label: "Recovery Workspace", route: pathname };
  }, [pathname]);

  // Quick Action Prompts (Context-Aware)
  const quickActions = useMemo(() => {
    const isCaseDetail = Boolean((pageContext as any).caseId);

    if (isCaseDetail) {
      return [
        {
          label: "WHAT'S HAPPENING WITH THIS CASE?",
          query: "What's happening with this case?",
        },
        {
          label: "WHY DID ARIV CHOOSE THIS ACTION?",
          query: "Why did ARIV choose this action?",
        },
        {
          label: "WAS PAYMENT RECOVERED?",
          query: "Was the payment actually recovered?",
        },
        {
          label: "WHERE IS THE PAYMENT LINK?",
          query: "Where is the payment link?",
        },
        {
          label: "SHOW LATEST ACTIVITY",
          query: "Show me the latest activity.",
        },
        {
          label: "RECOVER THIS CASE",
          query: "Recover this case.",
        },
      ];
    }

    return [
      {
        label: "WHAT IS HAPPENING RIGHT NOW?",
        query: "What is happening right now?",
      },
      {
        label: "SHOW PAYMENTS WAITING FOR RECOVERY",
        query: "Show me payments waiting for recovery.",
      },
      {
        label: "HOW MUCH WAS RECOVERED?",
        query: "How much did we recover?",
      },
      {
        label: "IS ARIV HEALTHY?",
        query: "Is ARIV healthy?",
      },
      {
        label: "WHY IS REVENUE AT RISK?",
        query: "How much revenue is at risk right now?",
      },
      {
        label: "SIMULATE RECOVERY PREVIEW",
        query: "How would you recover this case?",
      },
    ];
  }, [pageContext]);

  // Auto-focus input and handle escape key
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 80);
      const handleKeyDown = (e: KeyboardEvent) => {
        if (e.key === "Escape") {
          closeAriv();
        }
      };
      window.addEventListener("keydown", handleKeyDown);
      return () => window.removeEventListener("keydown", handleKeyDown);
    }
  }, [isOpen, closeAriv]);

  // Scroll to bottom on updates
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, steps, loading]);

  // Helper to parse recommendation card from agent content (Requirement 12)
  const extractRecommendation = (text: string) => {
    const upper = text.toUpperCase();

    // Check if there is a real payment link URL in the text
    const urlMatch = text.match(/https:\/\/rzp\.io\/[^\s\)\],]+/i);
    const paymentUrl = urlMatch ? urlMatch[0] : undefined;

    if (upper.includes("GENERATE_PAYMENT_LINK") || paymentUrl) {
      return {
        action: "GENERATE_PAYMENT_LINK",
        status: upper.includes("WAITING FOR CUSTOMER PAYMENT") ? "WAITING_FOR_PAYMENT" : "EXECUTED",
        recoverability: "HIGH",
        policy: "APPROVED",
        autonomy: "FULL_AUTO",
        paymentUrl,
      };
    }
    if (upper.includes("RETRY_WITH_BACKOFF") || upper.includes("SCHEDULE_RETRY")) {
      return {
        action: "SCHEDULE_RETRY",
        status: "SCHEDULED",
        recoverability: "MEDIUM",
        policy: "APPROVED",
        autonomy: "FULL_AUTO",
      };
    }
    if (upper.includes("POLICY_REJECTION") || upper.includes("BLOCKED") || upper.includes("STOP_RECOVERY")) {
      return {
        action: upper.includes("STOP_RECOVERY") ? "STOP_RECOVERY" : "SUPPRESS_DISPATCH",
        status: "STOPPED",
        recoverability: "LOW",
        policy: "SAFETY_FIREWALL_BLOCKED",
        autonomy: "POLICY_ENFORCED",
      };
    }
    return undefined;
  };

  // SSE Query Execution (Requirement 11)
  const submitQuery = useCallback(
    async (userQuery: string) => {
      if (!userQuery.trim() || loading) return;
      setQuery("");

      const userMsg: Message = {
        id: Date.now().toString(),
        role: "user",
        content: userQuery.trim(),
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userMsg]);
      setLoading(true);
      setSteps(["Investigating workspace state..."]);

      try {
        const response = await fetch("/api/proxy/v1/agent/query", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            query: userQuery.trim(),
            current_route: pageContext.route,
            case_id: (pageContext as any).caseId || undefined,
          }),
        });

        if (!response.ok || !response.body) {
          throw new Error(`HTTP ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let currentSteps: string[] = ["Context loaded", "Recovery telemetry loaded"];
        let finalContent = "";
        let receivedMeta: MessageMeta | undefined = undefined;

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
              } else if (event.type === "meta") {
                receivedMeta = event as MessageMeta;
              }
            } catch {
              /* ignore parse error */
            }
          }
        }

        const rec = extractRecommendation(finalContent);

        const assistantMsg: Message = {
          id: (Date.now() + 1).toString(),
          role: "assistant",
          content:
            finalContent ||
            "No data available for this query. System is connected and ready for events.",
          steps: currentSteps,
          meta: receivedMeta,
          recommendation: rec,
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, assistantMsg]);
      } catch (err: any) {
        setMessages((prev) => [
          ...prev,
          {
            id: (Date.now() + 1).toString(),
            role: "assistant",
            content: `Error communicating with operational agent: ${err.message}`,
            timestamp: new Date(),
          },
        ]);
      } finally {
        setLoading(false);
        setSteps([]);
      }
    },
    [loading]
  );

  // Auto-submit initialQuery if set
  useEffect(() => {
    if (isOpen && initialQuery) {
      submitQuery(initialQuery);
      clearInitialQuery();
    }
  }, [isOpen, initialQuery, submitQuery, clearInitialQuery]);

  const handleSubmit = useCallback(() => {
    submitQuery(query);
  }, [query, submitQuery]);

  const handleCopy = (id: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 1500);
  };

  if (!mounted || !isOpen) return null;

  const panelWidth = expanded ? "w-full sm:w-[520px] lg:w-[560px]" : "w-full sm:w-[390px] lg:w-[420px]";

  const content = (
    <>
      {/* Mobile Backdrop Overlay */}
      <div
        className="fixed inset-0 bg-slate-900/40 backdrop-blur-xs z-[9998] sm:hidden transition-opacity"
        onClick={closeAriv}
        aria-hidden="true"
      />

      {/* Slide-in Drawer Container */}
      <div
        id="ask-ariv-panel-container"
        role="dialog"
        aria-label="ASK ARIV Operational Assistant"
        className={`fixed right-0 top-0 bottom-0 z-[9999] ${panelWidth} flex flex-col bg-white border-l border-slate-200 shadow-2xl transition-all duration-300 ease-out select-text`}
      >
        {/* Enterprise Blue Header */}
        <div className="flex flex-col border-b border-blue-700/30 bg-gradient-to-r from-blue-700 via-blue-600 to-indigo-700 text-white flex-shrink-0 px-4 py-3 shadow-sm">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="w-8 h-8 rounded-lg bg-white/15 border border-white/20 flex items-center justify-center flex-shrink-0 shadow-inner">
                <Sparkles className="w-4 h-4 text-amber-300" />
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-bold text-white tracking-wide leading-tight">ASK ARIV</h3>
                  <span className="text-[10px] font-semibold uppercase bg-white/20 text-blue-100 px-1.5 py-0.5 rounded tracking-wider">
                    AI AGENT
                  </span>
                </div>
                <p className="text-xs text-blue-100/90 leading-tight truncate">Live Recovery Intelligence</p>
              </div>
            </div>

            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                className="hidden sm:flex p-1.5 text-blue-100 hover:text-white hover:bg-white/15 rounded-md transition-colors"
                title={expanded ? "Collapse width" : "Expand width"}
                aria-label={expanded ? "Collapse width" : "Expand width"}
              >
                {expanded ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
              </button>
              <button
                type="button"
                onClick={closeAriv}
                className="p-1.5 text-blue-100 hover:text-white hover:bg-white/15 rounded-md transition-colors"
                title="Close"
                aria-label="Close ASK ARIV"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Page-Aware Context Chip & Live Status Strip (Requirements 7 & 10) */}
          <div className="flex items-center justify-between gap-2 mt-2 pt-2 border-t border-white/15 text-[11px]">
            <div className="flex items-center gap-1.5 min-w-0">
              <Layers className="w-3.5 h-3.5 text-blue-200 flex-shrink-0" />
              <span className="font-medium text-white truncate">
                Context: <span className="text-blue-100 font-semibold">{pageContext.label}</span>
              </span>
            </div>

            <div className="flex items-center gap-1.5 text-blue-100 flex-shrink-0 font-mono text-[10px]">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-400"></span>
              </span>
              <span className="font-semibold text-emerald-300">LIVE</span>
              <span>· {formatLastUpdated(lastUpdated)}</span>
            </div>
          </div>
        </div>

        {/* Live Event Indicator Banner (Requirement 10) */}
        {latestActivity && (
          <div className="bg-blue-50/70 border-b border-blue-100 px-3.5 py-1.5 flex items-center justify-between text-xs text-blue-800 flex-shrink-0">
            <div className="flex items-center gap-1.5 truncate">
              <span className="text-xs">{latestActivity.icon}</span>
              <span className="truncate font-medium">{latestActivity.message}</span>
            </div>
            <span className="text-[10px] text-blue-500 font-mono flex-shrink-0">active</span>
          </div>
        )}

        {/* Main Conversation & Welcome State Area */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4 min-h-0 bg-slate-50/50">
          {/* Default Opening State (Requirement 8) */}
          {messages.length === 0 ? (
            <div className="flex flex-col h-full justify-between py-2 space-y-4">
              <div className="text-center pt-3 pb-1">
                <div className="w-12 h-12 mx-auto rounded-2xl bg-blue-50 border border-blue-200 flex items-center justify-center mb-2.5 shadow-sm">
                  <Bot className="w-6 h-6 text-blue-600" />
                </div>
                <h4 className="text-base font-bold text-slate-800">ASK ARIV</h4>
                <p className="text-xs font-semibold text-blue-600">Live Recovery Intelligence</p>
                <p className="text-xs text-slate-500 mt-1.5 max-w-xs mx-auto leading-relaxed">
                  I&apos;m connected to the current ARIV workspace. Grounded in authoritative PostgreSQL telemetry and Qdrant memory.
                </p>
              </div>

              {/* Quick Actions Prompts (Requirement 8 & 9) */}
              <div className="space-y-2">
                <p className="text-[11px] font-bold text-slate-400 uppercase tracking-wider pl-1">
                  Quick Prompts
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                  {quickActions.map((action) => (
                    <button
                      key={action.label}
                      type="button"
                      onClick={() => submitQuery(action.query)}
                      disabled={loading}
                      className="text-left text-xs font-medium text-slate-700 bg-white hover:text-blue-700 hover:bg-blue-50/80 hover:border-blue-300 p-2.5 rounded-lg border border-slate-200 shadow-xs transition-all flex items-start gap-1.5 group disabled:opacity-50"
                    >
                      <ChevronRight className="w-3.5 h-3.5 text-slate-400 group-hover:text-blue-600 group-hover:translate-x-0.5 transition-all mt-0.5 flex-shrink-0" />
                      <span className="leading-snug">{action.label}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="p-3 bg-white border border-slate-200 rounded-xl text-center shadow-2xs">
                <p className="text-[11px] text-slate-400">
                  Tip: Use <kbd className="font-mono bg-slate-100 px-1 py-0.5 rounded text-slate-600 border border-slate-200">Ctrl+Shift+A</kbd> to toggle this assistant anytime.
                </p>
              </div>
            </div>
          ) : (
            messages.map((msg) => (
              <div
                key={msg.id}
                className={msg.role === "user" ? "flex justify-end" : "flex justify-start"}
              >
                {/* Assistant Message */}
                {msg.role === "assistant" && (
                  <div className="flex items-start gap-2.5 max-w-full w-full">
                    <div className="w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center flex-shrink-0 mt-0.5 shadow-sm text-white">
                      <Bot className="w-4 h-4" />
                    </div>

                    <div className="space-y-2 flex-1 min-w-0">
                      {/* Investigation Steps Checklist (Requirement 11) */}
                      {msg.steps && msg.steps.length > 0 && (
                        <div className="bg-slate-100/80 rounded-lg p-2 space-y-1 text-xs text-slate-600 border border-slate-200/60 font-mono">
                          {msg.steps.map((step, i) => (
                            <div key={i} className="flex items-center gap-1.5 text-[11px]">
                              <span className="text-emerald-600 font-bold flex-shrink-0">✓</span>
                              <span className="truncate">{step}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Content Box */}
                      <div className="bg-white border border-slate-200 rounded-xl p-3.5 shadow-xs text-xs text-slate-800 leading-relaxed font-sans">
                        <pre className="whitespace-pre-wrap font-sans text-xs text-slate-800 leading-relaxed overflow-x-auto">
                          {msg.content}
                        </pre>

                        {/* Interactive Recommendation Action Card (Requirement 12) */}
                        {msg.recommendation && (
                          <div className="mt-3 p-3 bg-blue-50/90 border border-blue-200 rounded-lg space-y-2">
                            <div className="flex items-center justify-between text-xs">
                              <span className="font-bold text-blue-900 flex items-center gap-1.5">
                                <ShieldAlert className="w-3.5 h-3.5 text-blue-600" />
                                ARIV RECOMMENDATION
                              </span>
                              <span className="text-[10px] font-mono font-semibold uppercase bg-blue-600 text-white px-1.5 py-0.5 rounded">
                                {msg.recommendation.autonomy}
                              </span>
                            </div>

                            <div className="grid grid-cols-2 gap-2 text-[11px] text-slate-600 pt-1">
                              <div>
                                <span className="text-slate-400 block">Action:</span>
                                <span className="font-semibold text-slate-800 font-mono">
                                  {msg.recommendation.action}
                                </span>
                              </div>
                              <div>
                                <span className="text-slate-400 block">Recoverability:</span>
                                <span className="font-semibold text-emerald-700">
                                  {msg.recommendation.recoverability}
                                </span>
                              </div>
                            </div>

                            {msg.recommendation.paymentUrl && (
                              <div className="pt-1">
                                <a
                                  href={msg.recommendation.paymentUrl}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="flex items-center justify-center gap-1.5 w-full py-2 px-3 text-xs font-semibold rounded-md bg-emerald-600 hover:bg-emerald-500 text-white shadow-xs transition-colors text-center"
                                >
                                  <span>Open Razorpay Test Payment Link</span>
                                  <ArrowRight className="w-3.5 h-3.5" />
                                </a>
                              </div>
                            )}

                            <div className="flex items-center gap-2 pt-2 border-t border-blue-200/60">
                              <button
                                type="button"
                                onClick={() => {
                                  closeAriv();
                                  router.push("/cases");
                                }}
                                className="flex-1 px-2.5 py-1.5 text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-md transition-colors text-center"
                              >
                                Inspect Queue
                              </button>
                              <button
                                type="button"
                                onClick={() => {
                                  closeAriv();
                                  router.push("/demo");
                                }}
                                className="flex-1 px-2.5 py-1.5 text-xs font-semibold text-blue-700 bg-white hover:bg-blue-50 border border-blue-300 rounded-md transition-colors text-center"
                              >
                                Simulator
                              </button>
                            </div>
                          </div>
                        )}

                        {/* Structured Action & Navigation Links */}
                        {msg.meta?.links && msg.meta.links.length > 0 && (
                          <div className="mt-3 pt-2.5 border-t border-slate-200/80 flex flex-wrap gap-1.5">
                            {msg.meta.links.map((link, idx) => {
                              const isExt = Boolean(link.is_external || link.isExternal || link.href.startsWith("http"));
                              if (isExt) {
                                return (
                                  <a
                                    key={idx}
                                    href={link.href}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs transition-colors shadow-2xs"
                                  >
                                    <span>{link.label}</span>
                                    <ExternalLink className="w-3.5 h-3.5" />
                                  </a>
                                );
                              }
                              return (
                                <button
                                  key={idx}
                                  type="button"
                                  onClick={() => {
                                    closeAriv();
                                    router.push(link.href);
                                  }}
                                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-blue-50 hover:bg-blue-100/80 text-blue-700 font-medium text-xs border border-blue-200 transition-colors shadow-2xs"
                                >
                                  <span>{link.label}</span>
                                  <ArrowRight className="w-3 h-3 text-blue-500" />
                                </button>
                              );
                            })}
                            {msg.meta.can_recover && (
                              <button
                                type="button"
                                onClick={() => submitQuery("Recover this case.")}
                                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500 hover:bg-amber-400 text-white font-semibold text-xs transition-colors shadow-2xs"
                              >
                                <span>⚡ Recover This Case</span>
                              </button>
                            )}
                          </div>
                        )}

                        {/* Actions bar: timestamp & copy */}
                        <div className="flex items-center justify-between mt-2 pt-2 border-t border-slate-100 text-[10px] text-slate-400">
                          <span>
                            {msg.timestamp.toLocaleTimeString([], {
                              hour: "2-digit",
                              minute: "2-digit",
                            })}
                          </span>
                          <button
                            type="button"
                            onClick={() => handleCopy(msg.id, msg.content)}
                            className="flex items-center gap-1 hover:text-slate-600 transition-colors p-1"
                            title="Copy response"
                          >
                            {copiedId === msg.id ? (
                              <>
                                <Check className="w-3 h-3 text-emerald-600" />
                                <span className="text-emerald-600">Copied</span>
                              </>
                            ) : (
                              <>
                                <Copy className="w-3 h-3" />
                                <span>Copy</span>
                              </>
                            )}
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* User Message */}
                {msg.role === "user" && (
                  <div className="flex items-start gap-2 max-w-[85%]">
                    <div className="space-y-1">
                      <div className="bg-blue-600 text-white rounded-xl px-3.5 py-2.5 shadow-xs">
                        <p className="text-xs leading-relaxed">{msg.content}</p>
                      </div>
                      <p className="text-[10px] text-slate-400 text-right pr-1">
                        {msg.timestamp.toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </p>
                    </div>
                    <div className="w-7 h-7 rounded-lg bg-slate-200 flex items-center justify-center flex-shrink-0 mt-0.5 text-slate-600">
                      <MessageSquare className="w-4 h-4" />
                    </div>
                  </div>
                )}
              </div>
            ))
          )}

          {/* Live Reasoning Streaming Steps (Requirement 11) */}
          {loading && (
            <div className="flex items-start gap-2.5 w-full">
              <div className="w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center flex-shrink-0 mt-0.5 text-white">
                <Bot className="w-4 h-4" />
              </div>
              <div className="bg-white border border-slate-200 rounded-xl p-3 w-full shadow-xs space-y-2">
                <div className="flex items-center gap-2 text-xs font-semibold text-blue-700">
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-600" />
                  <span>● Investigating workspace state...</span>
                </div>
                <div className="space-y-1 font-mono text-[11px] text-slate-500 pl-1">
                  {steps.map((step, i) => (
                    <div key={i} className="flex items-center gap-1.5 text-emerald-700">
                      <span>✓</span>
                      <span>{step}</span>
                    </div>
                  ))}
                  <div className="flex items-center gap-1.5 text-blue-600 animate-pulse">
                    <span>•</span>
                    <span>Streaming grounded response...</span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Clear Thread Bar */}
        {messages.length > 0 && (
          <div className="px-4 py-1.5 border-t border-slate-100 bg-white flex items-center justify-between text-xs text-slate-400 flex-shrink-0">
            <button
              type="button"
              onClick={() => setMessages([])}
              className="hover:text-slate-700 transition-colors"
            >
              Clear conversation
            </button>
            <span className="font-mono text-[10px] text-slate-300">Grounded Mode</span>
          </div>
        )}

        {/* Query Input Bar */}
        <div className="border-t border-slate-200 p-3 bg-slate-50 flex-shrink-0">
          <div className="flex items-center gap-2 bg-white border border-slate-200 rounded-xl px-3 py-2.5 focus-within:ring-2 focus-within:ring-blue-500/20 focus-within:border-blue-400 transition-all shadow-xs">
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
              placeholder="Ask about any case, failure, or action..."
              className="flex-1 bg-transparent text-xs text-slate-800 placeholder:text-slate-400 outline-none"
              disabled={loading}
              aria-label="Ask ARIV query input"
            />
            {loading ? (
              <Loader2 className="w-4 h-4 animate-spin text-blue-600 flex-shrink-0" />
            ) : (
              <button
                type="button"
                onClick={handleSubmit}
                disabled={!query.trim()}
                className="w-6 h-6 rounded-md bg-blue-600 hover:bg-blue-700 disabled:opacity-40 disabled:hover:bg-blue-600 text-white flex items-center justify-center transition-colors flex-shrink-0"
                aria-label="Send query"
              >
                <ArrowUp className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>
      </div>
    </>
  );

  return createPortal(content, document.body);
}
