"use client";

import { Badge } from "@/components/ui/badge";
import { ShieldCheck, User } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useLiveStatus } from "@/hooks/use-live-status";
import { LiveIndicator } from "@/components/LiveIndicator";

export default function Header() {
  const isDemo = process.env.NEXT_PUBLIC_DEMO_MODE === "true";
  const queryClient = useQueryClient();
  const { liveState, lastUpdated, markSuccess, markError } = useLiveStatus();

  // Mirror the global query state into the header LIVE indicator
  useEffect(() => {
    // Subscribe to query cache changes to detect global success/error
    const unsub = queryClient.getQueryCache().subscribe((event) => {
      if (event.type === "updated") {
        const query = event.query;
        if (query.state.status === "success") markSuccess();
        if (query.state.status === "error")   markError();
      }
    });
    return unsub;
  }, [queryClient, markSuccess, markError]);

  return (
    <header className="h-16 border-b border-slate-200 bg-white flex items-center justify-between px-6 shadow-sm z-10">
      <div className="flex items-center gap-4">
        <h2 className="text-lg font-semibold text-slate-900">Revenue Recovery Workspace</h2>

        {isDemo && (
          <Badge variant="destructive" className="bg-amber-100 text-amber-700 hover:bg-amber-200 border-amber-200">
            SANDBOX / DEMO
          </Badge>
        )}
      </div>

      <div className="flex items-center gap-5">
        {/* Global LIVE indicator */}
        <LiveIndicator state={liveState} lastUpdated={lastUpdated} />

        <div className="flex items-center gap-2 text-sm text-slate-500">
          <ShieldCheck className="w-4 h-4 text-emerald-600" />
          <span>Tenant Context Active</span>
        </div>

        <div className="flex items-center gap-3 pl-5 border-l border-slate-200">
          <div className="w-8 h-8 rounded-full bg-slate-100 border border-slate-200 flex items-center justify-center">
            <User className="w-4 h-4 text-slate-500" />
          </div>
          <div className="flex flex-col">
            <span className="text-sm font-medium text-slate-900">Admin</span>
            <span className="text-xs text-slate-500 font-mono">Workspace</span>
          </div>
        </div>
      </div>
    </header>
  );
}
