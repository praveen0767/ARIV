"use client";

import React, { useState, useEffect } from "react";
import { createPortal } from "react-dom";
import { Sparkles, X, ArrowRight, ShieldAlert } from "lucide-react";
import { useAriv } from "@/context/ArivContext";

export function AskArivLauncher() {
  const { isOpen, toggleAriv, openAriv, proactiveEvent, dismissProactiveEvent } = useAriv();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) return null;

  // When drawer is open, hide launcher button so it doesn't overlap drawer content
  if (isOpen) return null;

  const content = (
    <div
      id="ask-ariv-launcher-container"
      className="fixed bottom-4 right-4 sm:bottom-6 sm:right-6 z-40 flex flex-col items-end gap-2.5 pointer-events-none"
    >
      {/* Proactive Notification Callout */}
      {proactiveEvent && (
        <div
          role="alert"
          className="pointer-events-auto bg-white/95 backdrop-blur-sm border border-blue-200 shadow-2xl rounded-xl p-3.5 w-72 sm:w-80 animate-in slide-in-from-bottom-4 fade-in duration-200 ring-1 ring-blue-500/10"
        >
          <div className="flex items-center justify-between gap-2 mb-1.5">
            <div className="flex items-center gap-1.5 text-xs font-bold text-blue-700">
              <span className="text-sm">{proactiveEvent.icon || "⚡"}</span>
              <span>{proactiveEvent.eventType ? proactiveEvent.eventType.replace(/_/g, " ") : "ASK ARIV ALERT"}</span>
            </div>
            <button
              onClick={dismissProactiveEvent}
              className="text-slate-400 hover:text-slate-600 p-0.5 rounded transition-colors"
              aria-label="Dismiss alert"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          <p className="text-xs text-slate-800 font-medium leading-snug mb-2.5">
            {proactiveEvent.message}
          </p>

          <div className="flex items-center justify-between pt-1 border-t border-slate-100">
            <span className="text-[10px] font-mono text-slate-500">
              {proactiveEvent.caseId ? `Case: ${proactiveEvent.caseId.slice(0, 8)}…` : "Live telemetry"}
            </span>
            <button
              onClick={() => {
                const q = proactiveEvent.caseId
                  ? `Explain recovery case ${proactiveEvent.caseId}`
                  : "What is ARIV doing right now?";
                openAriv(q);
                dismissProactiveEvent();
              }}
              className="inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:text-blue-800 transition-colors group"
            >
              <span>Review in ASK ARIV</span>
              <ArrowRight className="w-3 h-3 group-hover:translate-x-0.5 transition-transform" />
            </button>
          </div>
        </div>
      )}

      {/* Floating Enterprise Assistant Button / Pill (Requirements 1 & 3) */}
      <button
        id="ask-ariv-launcher-button"
        type="button"
        aria-label="Open ASK ARIV"
        onClick={toggleAriv}
        className="pointer-events-auto group relative flex items-center gap-2.5 px-4 py-2.5 sm:px-4.5 sm:py-3 bg-gradient-to-r from-blue-600 via-blue-700 to-indigo-700 hover:from-blue-700 hover:to-indigo-800 text-white font-medium text-xs sm:text-sm rounded-full shadow-lg hover:shadow-2xl hover:scale-[1.03] active:scale-[0.98] transition-all duration-200 border border-blue-400/40 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 ring-offset-slate-50 cursor-pointer select-none"
      >
        <div className="w-5 h-5 rounded-full bg-white/20 flex items-center justify-center flex-shrink-0">
          <Sparkles className="w-3.5 h-3.5 text-amber-300 animate-pulse group-hover:rotate-12 transition-transform" />
        </div>
        <span className="font-bold tracking-wide text-white">ASK ARIV</span>

        <span className="flex items-center gap-1.5 pl-2 border-l border-blue-400/40 text-[11px] sm:text-xs text-blue-100 font-normal">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-400"></span>
          </span>
          <span className="font-medium hidden sm:inline">Live Intelligence</span>
        </span>
      </button>
    </div>
  );

  return createPortal(content, document.body);
}
