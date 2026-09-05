"use client";

import { useState, useEffect, useCallback } from "react";

export type LiveState = "connected" | "updating" | "reconnecting" | "offline";

/**
 * Tracks:
 * - browser online/offline
 * - last successful API fetch timestamp
 * - current live state (connected | updating | reconnecting | offline)
 */
export function useLiveStatus() {
  const [liveState, setLiveState] = useState<LiveState>("connected");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [errorCount, setErrorCount] = useState(0);

  // Track browser online/offline
  useEffect(() => {
    const onOnline  = () => setLiveState("reconnecting");
    const onOffline = () => setLiveState("offline");
    window.addEventListener("online",  onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("online",  onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, []);

  const markSuccess = useCallback(() => {
    setLastUpdated(new Date());
    setErrorCount(0);
    setLiveState("connected");
  }, []);

  const markError = useCallback(() => {
    setErrorCount((c) => c + 1);
    setLiveState((prev) => (prev === "offline" ? "offline" : "reconnecting"));
  }, []);

  const markFetching = useCallback(() => {
    setLiveState((prev) => {
      if (prev === "offline") return "offline";
      if (prev === "reconnecting") return "reconnecting";
      return "updating";
    });
  }, []);

  return { liveState, lastUpdated, errorCount, markSuccess, markError, markFetching };
}

/** Human-readable "Updated N ago" label */
export function formatLastUpdated(date: Date | null): string {
  if (!date) return "Never";
  const diffMs = Date.now() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 5)  return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  return date.toLocaleTimeString();
}
