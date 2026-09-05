"use client";

import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { recoveryApi } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Activity, DollarSign, Target, Zap, ArrowRight, TrendingUp, AlertTriangle, CheckCircle2 } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import Link from "next/link";
import { useLiveStatus } from "@/hooks/use-live-status";
import { LiveIndicator } from "@/components/LiveIndicator";
import { activityStore, ingestAuthoritativeActivities } from "@/components/ActivityToast";

const formatCurrency = (minor: number) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" }).format(minor / 100);

const FUNNEL_COLORS = ["#2563eb", "#3b82f6", "#60a5fa", "#10b981", "#059669"];

export default function DashboardOverview() {
  const { liveState, lastUpdated, markSuccess, markError, markFetching } = useLiveStatus();

  const { data, isLoading, error, isFetching } = useQuery({
    queryKey: ["dashboard"],
    queryFn: recoveryApi.getDashboard,
    // Refresh every 2 seconds
    refetchInterval: 2_000,
    // Pause polling when the tab is hidden
    refetchIntervalInBackground: false,
  });

  // Propagate fetch lifecycle to LIVE indicator
  useEffect(() => {
    if (isFetching) markFetching();
  }, [isFetching, markFetching]);

  // On success: mark LIVE, ingest real authoritative activities for proactive alerts
  useEffect(() => {
    if (data) {
      markSuccess();
      if (data.recent_activity) {
        ingestAuthoritativeActivities(data.recent_activity);
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  // On error: mark reconnecting
  useEffect(() => {
    if (error) markError();
  }, [error, markError]);

  if (isLoading && !data) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-32 w-full rounded-xl bg-slate-200" />
          ))}
        </div>
        <Skeleton className="h-[360px] w-full rounded-xl bg-slate-200" />
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="p-6 bg-red-50 border border-red-200 rounded-xl text-red-700 flex items-center gap-3">
        <AlertTriangle className="w-5 h-5 flex-shrink-0" />
        <div>
          <div className="font-semibold">Backend connectivity issue</div>
          <div className="text-sm mt-0.5 text-red-600">Retrying automatically…</div>
        </div>
      </div>
    );
  }

  const { kpis, funnel, action_performance, recent_cases } = data!;

  return (
    <div className="space-y-8 animate-in fade-in duration-300">

      {/* Page header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
            Revenue Recovery Overview
          </div>
          <h1 className="text-2xl font-bold text-slate-900">Command Center</h1>
          <p className="text-sm text-slate-500 mt-1">
            AI proposes · Policy governs · Tools execute · Attribution proves · Memory improves.
          </p>
        </div>
        {/* LIVE Indicator + Last Updated (Phase E & F) */}
        <div className="flex flex-col items-end gap-1.5 mt-1">
          <LiveIndicator state={liveState} lastUpdated={lastUpdated} />
        </div>
      </div>

      {/* KPI Strip */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card className="border-slate-200 shadow-sm hover:shadow-md transition-shadow">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Revenue At Risk</CardTitle>
            <Activity className="h-4 w-4 text-slate-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-slate-900">{formatCurrency(kpis.revenue_at_risk)}</div>
            <p className="text-xs text-slate-500 mt-1">Identified payment failures</p>
          </CardContent>
        </Card>

        <Card className="border-slate-200 shadow-sm hover:shadow-md transition-shadow">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Recovered Revenue</CardTitle>
            <DollarSign className="h-4 w-4 text-emerald-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-emerald-600">{formatCurrency(kpis.recovered_revenue)}</div>
            <p className="text-xs text-emerald-600/70 mt-1 flex items-center gap-1">
              <TrendingUp className="w-3 h-3" /> Observed successful recovery
            </p>
          </CardContent>
        </Card>

        <Card className="border-blue-100 bg-blue-50/50 shadow-sm hover:shadow-md transition-shadow">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-blue-600 uppercase tracking-wider">Incremental Estimate</CardTitle>
            <Target className="h-4 w-4 text-blue-500" />
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2">
              <div className="text-2xl font-bold text-blue-700">{formatCurrency(kpis.estimated_incremental_recovery)}</div>
              <Badge className="bg-blue-100 text-blue-700 hover:bg-blue-100 border-blue-200 text-[10px] font-bold">ESTIMATE</Badge>
            </div>
            <p className="text-xs text-blue-600/70 mt-1">Above baseline · heuristic</p>
          </CardContent>
        </Card>

        <Card className="border-slate-200 shadow-sm hover:shadow-md transition-shadow">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Recovery Rate</CardTitle>
            <Zap className="h-4 w-4 text-amber-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-amber-600">{kpis.recovery_rate_pct.toFixed(1)}%</div>
            <p className="text-xs text-amber-600/70 mt-1">Of eligible revenue at risk</p>
          </CardContent>
        </Card>
      </div>

      {/* AI Recovery Pipeline */}
      <div className="bg-slate-900 rounded-xl p-4 flex items-center gap-3 overflow-x-auto">
        {[
          "EVENT", "DIAGNOSIS", "CONTEXT", "MEMORY", "AI DECISION",
          "POLICY", "EXECUTION", "PROVIDER", "OUTCOME", "ATTRIBUTION"
        ].map((stage, i, arr) => (
          <div key={stage} className="flex items-center gap-3 flex-shrink-0">
            <span className="text-xs font-semibold text-slate-300 tracking-widest whitespace-nowrap">{stage}</span>
            {i < arr.length - 1 && <ArrowRight className="w-3 h-3 text-blue-500 flex-shrink-0" />}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recovery Funnel */}
        <Card className="border-slate-200 shadow-sm">
          <CardHeader>
            <CardTitle className="text-slate-900 text-base">Recovery Funnel</CardTitle>
            <CardDescription className="text-slate-500">Pipeline of recovery execution stages</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-[280px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={funnel} layout="vertical" margin={{ top: 5, right: 30, left: 40, bottom: 5 }}>
                  <XAxis type="number" hide />
                  <YAxis
                    dataKey="stage"
                    type="category"
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: "#64748b", fontSize: 11 }}
                    width={130}
                  />
                  <Tooltip
                    cursor={{ fill: "#f1f5f9" }}
                    contentStyle={{ backgroundColor: "#fff", borderColor: "#e2e8f0", color: "#0f172a", borderRadius: 8, fontSize: 12 }}
                    formatter={(value: unknown) => [formatCurrency(Number(value) || 0), "Amount"]}
                  />
                  <Bar dataKey="amount" radius={[0, 4, 4, 0]}>
                    {funnel.map((entry, index) => (
                      <Cell
                        key={`cell-${index}`}
                        fill={entry.badge === "ESTIMATE" ? "#3b82f6" : FUNNEL_COLORS[index % FUNNEL_COLORS.length]}
                        fillOpacity={0.85}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        {/* Action Performance */}
        <Card className="border-slate-200 shadow-sm">
          <CardHeader>
            <CardTitle className="text-slate-900 text-base">Action Performance</CardTitle>
            <CardDescription className="text-slate-500">Success rate by executed action type</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {action_performance.map((ap) => {
                const successRate = (ap.successes / Math.max(1, ap.successes + ap.failures)) * 100;
                return (
                  <div key={ap.action_type} className="flex items-center justify-between p-3 rounded-lg bg-slate-50 border border-slate-200 hover:border-slate-300 transition-colors">
                    <div>
                      <div className="font-semibold text-slate-800 text-sm">{ap.action_type}</div>
                      <div className="text-xs text-slate-500 mt-0.5">{ap.cases} cases · {ap.attempts} attempts</div>
                    </div>
                    <div className="text-right">
                      <div className={`text-sm font-bold ${successRate >= 70 ? "text-emerald-600" : successRate >= 40 ? "text-amber-600" : "text-red-600"}`}>
                        {successRate.toFixed(1)}% success
                      </div>
                      <div className="text-xs text-slate-500">{formatCurrency(ap.recovered_amount)} recovered</div>
                    </div>
                  </div>
                );
              })}
              {action_performance.length === 0 && (
                <div className="text-center py-10 text-slate-400 text-sm">
                  No actions executed yet. Run the demo simulator to generate data.
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Lower Row: Recent Cases & Live Activity Stream */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Cases */}
        <Card className="border-slate-200 shadow-sm flex flex-col">
          <CardHeader className="flex flex-row items-center justify-between pb-3">
            <div>
              <CardTitle className="text-slate-900 text-base">Recent Cases</CardTitle>
              <CardDescription className="text-slate-500 text-xs">Latest payment failures in operational queue</CardDescription>
            </div>
            <Link
              href="/cases"
              className="flex items-center gap-1 text-xs font-semibold text-blue-600 hover:text-blue-700 transition-colors"
            >
              View All <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </CardHeader>
          <CardContent className="flex-1 space-y-2">
            {recent_cases && recent_cases.length > 0 ? (
              recent_cases.slice(0, 6).map((c) => (
                <Link key={c.case_id} href={`/cases/${c.case_id}`}>
                  <div className="flex items-center justify-between p-2.5 rounded-lg border border-slate-100 hover:border-blue-200 hover:bg-blue-50/40 transition-colors cursor-pointer">
                    <div className="flex items-center gap-2.5 min-w-0">
                      <div className={`w-2 h-2 rounded-full flex-shrink-0 ${
                        c.status === "RECOVERED" ? "bg-emerald-500" :
                        c.status === "FAILED" ? "bg-red-500" :
                        c.status === "IN_PROGRESS" ? "bg-blue-500 animate-pulse" :
                        "bg-amber-400"
                      }`} />
                      <div className="min-w-0">
                        <div className="text-xs font-mono text-slate-700 font-semibold truncate">{c.case_id.split("-")[0]}…</div>
                        <div className="text-[10px] text-slate-400 truncate">{c.case_type} · {c.domain}</div>
                      </div>
                    </div>
                    <div className="flex items-center gap-3 flex-shrink-0">
                      <div className="text-xs font-semibold text-slate-800 tabular-nums">{formatCurrency(c.amount_minor)}</div>
                      <Badge
                        variant="outline"
                        className={`text-[9px] font-semibold ${
                          c.status === "RECOVERED" ? "bg-emerald-50 text-emerald-700 border-emerald-200" :
                          c.status === "FAILED" ? "bg-red-50 text-red-700 border-red-200" :
                          c.status === "IN_PROGRESS" ? "bg-blue-50 text-blue-700 border-blue-200" :
                          "bg-amber-50 text-amber-700 border-amber-200"
                        }`}
                      >
                        {c.status}
                      </Badge>
                    </div>
                  </div>
                </Link>
              ))
            ) : (
              <div className="text-center py-8 text-slate-400 text-xs">No cases yet.</div>
            )}
          </CardContent>
        </Card>

        {/* Live Operational Activity Stream */}
        <Card className="border-slate-200 shadow-sm flex flex-col">
          <CardHeader className="flex flex-row items-center justify-between pb-3">
            <div>
              <div className="flex items-center gap-2">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                </span>
                <CardTitle className="text-slate-900 text-base">Live Activity Stream</CardTitle>
              </div>
              <CardDescription className="text-slate-500 text-xs mt-0.5">Authoritative events from recovery pipeline</CardDescription>
            </div>
            <Badge variant="outline" className="font-mono text-[10px] text-slate-500 bg-slate-50">
              {data?.recent_activity?.length ?? 0} events
            </Badge>
          </CardHeader>
          <CardContent className="flex-1 overflow-y-auto max-h-[360px] space-y-2 pt-1 pr-2">
            {data?.recent_activity && data.recent_activity.length > 0 ? (
              data.recent_activity.map((ev) => (
                <div
                  key={ev.id}
                  className="p-2.5 rounded-lg bg-slate-50/90 border border-slate-200/80 hover:border-blue-200 transition-colors text-xs space-y-1"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="text-sm flex-shrink-0">{ev.icon || "📌"}</span>
                      <span className="font-semibold text-slate-800 tracking-tight truncate">
                        {ev.event_type ? ev.event_type.replace(/_/g, " ") : "Activity"}
                      </span>
                    </div>
                    <span className="font-mono text-[10px] text-slate-400 flex-shrink-0">
                      {new Date(ev.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                    </span>
                  </div>

                  <p className="text-slate-600 text-[11px] leading-snug pl-5 font-sans break-words">
                    {ev.human_readable_message}
                  </p>

                  <div className="flex items-center justify-between pl-5 pt-0.5 text-[10px] text-slate-400 font-mono">
                    <div className="flex items-center gap-2 truncate">
                      {ev.case_id && (
                        <Link
                          href={`/cases/${ev.case_id}`}
                          className="text-blue-600 hover:text-blue-800 hover:underline flex items-center gap-0.5"
                        >
                          Case: {ev.case_id.slice(0, 8)}…
                        </Link>
                      )}
                      {ev.action_id && (
                        <span>Action: {ev.action_id.slice(0, 8)}…</span>
                      )}
                      {ev.metadata?.provider_resource_id && (
                        <span className="text-emerald-700 bg-emerald-50 px-1 rounded border border-emerald-200">
                          Ref: {ev.metadata.provider_resource_id}
                        </span>
                      )}
                    </div>
                    <span className={`px-1.5 py-0.5 rounded font-semibold uppercase text-[9px] ${
                      ev.severity === "success" ? "bg-emerald-100 text-emerald-700" :
                      ev.severity === "error" ? "bg-red-100 text-red-700" :
                      ev.severity === "warning" ? "bg-amber-100 text-amber-700" :
                      "bg-slate-200/70 text-slate-600"
                    }`}>
                      {ev.status || ev.severity}
                    </span>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-center py-10 text-slate-400 text-xs">
                No activity recorded yet. Run a synthetic payment failure to observe live recovery events.
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Quick nav to cases */}
      <div className="flex items-center justify-between pt-2">
        <span className="text-sm text-slate-500">
          View all cases in the operational queue
        </span>
        <Link
          href="/cases"
          className="flex items-center gap-2 text-sm font-semibold text-blue-600 hover:text-blue-700 transition-colors"
        >
          Open Cases <ArrowRight className="w-4 h-4" />
        </Link>
      </div>
    </div>
  );
}
