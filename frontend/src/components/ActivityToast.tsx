"use client";

import { useState, useEffect, useRef } from "react";
import { X, ArrowRight } from "lucide-react";
import type { OperationalActivityItem } from "@/lib/types";

export interface ActivityEvent {
  id: string;
  icon: string;
  message: string;
  at: Date;
  eventType?: string;
  caseId?: string | null;
  actionId?: string | null;
  providerReference?: string | null;
}

// ─── Toast store (singleton) ─────────────────────────────────────────────────

type Listener = (events: ActivityEvent[]) => void;

class ActivityStore {
  private events: ActivityEvent[] = [];
  private listeners: Listener[] = [];

  push(partial: Omit<ActivityEvent, "id" | "at">) {
    const ev: ActivityEvent = {
      ...partial,
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      at: new Date(),
    };
    this.events = [ev, ...this.events].slice(0, 5);
    this.listeners.forEach((l) => l([...this.events]));
  }

  subscribe(l: Listener) {
    this.listeners.push(l);
    return () => { this.listeners = this.listeners.filter((x) => x !== l); };
  }

  dismiss(id: string) {
    this.events = this.events.filter((e) => e.id !== id);
    this.listeners.forEach((l) => l([...this.events]));
  }
}

export const activityStore = new ActivityStore();

const seenActivityIds = new Set<string>();
let isInitialized = false;

export function ingestAuthoritativeActivities(activities?: OperationalActivityItem[]) {
  if (!activities || !Array.isArray(activities) || activities.length === 0) return;

  if (!isInitialized) {
    activities.forEach((act) => seenActivityIds.add(act.id));
    isInitialized = true;
    return;
  }

  const newEvents = activities
    .filter((act) => !seenActivityIds.has(act.id))
    .reverse();

  for (const act of newEvents) {
    seenActivityIds.add(act.id);
    activityStore.push({
      icon: act.icon || "📌",
      message: act.human_readable_message || act.event_type.replace(/_/g, " "),
      eventType: act.event_type,
      caseId: act.case_id,
      actionId: act.action_id,
      providerReference: act.metadata?.provider_resource_id,
    });
  }
}

// ─── ActivityToast component ──────────────────────────────────────────────────

export function ActivityToastContainer() {
  const [events, setEvents] = useState<ActivityEvent[]>([]);

  useEffect(() => {
    return activityStore.subscribe(setEvents);
  }, []);

  // Auto-dismiss after 8s
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  useEffect(() => {
    events.forEach((ev) => {
      if (!timers.current.has(ev.id)) {
        const t = setTimeout(() => {
          activityStore.dismiss(ev.id);
          timers.current.delete(ev.id);
        }, 8000);
        timers.current.set(ev.id, t);
      }
    });
  }, [events]);

  if (events.length === 0) return null;

  return (
    <div className="fixed bottom-20 right-6 z-50 flex flex-col gap-2 pointer-events-none max-w-sm">
      {events.map((ev) => (
        <div
          key={ev.id}
          className="flex flex-col gap-1.5 bg-white border border-slate-200 shadow-xl rounded-xl px-4 py-3 text-xs pointer-events-auto animate-in slide-in-from-right-4 duration-200 ring-1 ring-slate-900/5"
        >
          <div className="flex items-center gap-2.5">
            <span className="text-base flex-shrink-0">{ev.icon}</span>
            <div className="flex-1 min-w-0">
              <div className="font-bold text-slate-800 tracking-tight">
                {ev.eventType ? ev.eventType.replace(/_/g, " ") : "Recovery Activity"}
              </div>
              <p className="text-slate-600 mt-0.5 leading-snug break-words">
                {ev.message}
              </p>
            </div>
            <button
              onClick={() => activityStore.dismiss(ev.id)}
              className="text-slate-400 hover:text-slate-600 p-0.5 rounded transition-colors self-start"
              aria-label="Dismiss toast"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          {(ev.caseId || ev.providerReference) && (
            <div className="flex items-center justify-between pt-1.5 border-t border-slate-100 text-[10px]">
              <span className="font-mono text-slate-400">
                {ev.providerReference ? `Ref: ${ev.providerReference}` : ev.caseId ? `Case: ${ev.caseId.slice(0, 8)}…` : ""}
              </span>
              {ev.caseId && (
                <button
                  onClick={() => {
                    window.dispatchEvent(
                      new CustomEvent("ask-ariv-open", {
                        detail: { query: `Explain recovery case ${ev.caseId}` },
                      })
                    );
                    activityStore.dismiss(ev.id);
                  }}
                  className="inline-flex items-center gap-1 font-semibold text-blue-600 hover:text-blue-800 transition-colors"
                >
                  <span>Review</span>
                  <ArrowRight className="w-3 h-3" />
                </button>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
