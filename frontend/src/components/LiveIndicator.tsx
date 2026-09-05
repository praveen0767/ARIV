"use client";

import { useEffect, useState } from "react";
import { LiveState, formatLastUpdated } from "@/hooks/use-live-status";
import { Wifi, WifiOff, RefreshCw } from "lucide-react";

interface LiveIndicatorProps {
  state: LiveState;
  lastUpdated: Date | null;
}

export function LiveIndicator({ state, lastUpdated }: LiveIndicatorProps) {
  // Tick every 5s to keep "Updated Ns ago" label fresh
  const [, setTick] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setTick((t) => t + 1);
    }, 5000);
    return () => clearInterval(timer);
  }, []);

  if (state === "offline") {
    return (
      <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-red-50 border border-red-200 text-red-600 text-[11px] font-semibold select-none">
        <WifiOff className="w-3 h-3" />
        OFFLINE
      </div>
    );
  }

  if (state === "reconnecting") {
    return (
      <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-50 border border-amber-200 text-amber-700 text-[11px] font-semibold select-none">
        <RefreshCw className="w-3 h-3 animate-spin" />
        RECONNECTING
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 select-none">
      <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-700 text-[11px] font-bold">
        <span
          className={`w-1.5 h-1.5 rounded-full ${
            state === "updating" ? "bg-emerald-400 animate-ping" : "bg-emerald-500 animate-pulse"
          }`}
        />
        LIVE
      </div>
      {lastUpdated && (
        <span className="text-[10px] text-slate-400 tabular-nums hidden sm:block">
          Updated {formatLastUpdated(lastUpdated)}
        </span>
      )}
    </div>
  );
}

interface LiveIndicatorWithIconProps {
  state: LiveState;
  lastUpdated: Date | null;
}

export function LiveStatusBadge({ state, lastUpdated }: LiveIndicatorWithIconProps) {
  return (
    <div className="flex items-center gap-2">
      {state === "connected" || state === "updating" ? (
        <Wifi className="w-3.5 h-3.5 text-emerald-500" />
      ) : state === "offline" ? (
        <WifiOff className="w-3.5 h-3.5 text-red-500" />
      ) : (
        <RefreshCw className="w-3.5 h-3.5 text-amber-500 animate-spin" />
      )}
      <span className="text-[11px] text-slate-400 tabular-nums">
        {lastUpdated ? formatLastUpdated(lastUpdated) : "Connecting…"}
      </span>
    </div>
  );
}
