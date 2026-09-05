"use client";

import { useQuery } from "@tanstack/react-query";
import { recoveryApi } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  TrendingUp,
  Scale,
  DollarSign,
  Zap,
  Info,
  CheckCircle2,
  PieChart as PieChartIcon,
  ShieldCheck
} from "lucide-react";

export default function ImpactPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["dashboard"],
    queryFn: recoveryApi.getDashboard,
    refetchInterval: 2_000,
    refetchIntervalInBackground: false,
  });

  const formatCurrency = (minor: number) => {
    return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(
      minor / 100
    );
  };

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-36 w-full bg-slate-100 rounded-lg" />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <Skeleton className="h-32 bg-slate-100 rounded-lg" />
          <Skeleton className="h-32 bg-slate-100 rounded-lg" />
          <Skeleton className="h-32 bg-slate-100 rounded-lg" />
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="p-6 bg-rose-50 border border-rose-200 rounded-lg text-rose-700 text-sm">
        Failed to load executive impact data. Please verify your connection to the ARIV backend.
      </div>
    );
  }

  const { kpis, action_performance, recent_cases } = data;

  const actionAttributedCount = recent_cases?.filter(
    (c) => c.recovery_source === "ACTION_ATTRIBUTED" || c.recovery_source === "RECOVERY_ACTION"
  ).length || 0;

  const organicCount = recent_cases?.filter(
    (c) => c.recovery_source === "ORGANIC_RECOVERY" || c.recovery_source === "ORGANIC"
  ).length || 0;

  const totalActionAttempts = action_performance?.reduce((acc, a) => acc + (a.attempts || 0), 0) || 0;

  return (
    <div className="space-y-6 max-w-6xl">
      {/* Header */}
      <div className="border-b border-slate-200 pb-5">
        <div className="flex items-center gap-2.5">
          <h1 className="text-xl font-bold text-slate-900 tracking-tight">Executive Impact & Causal Attribution</h1>
          <Badge className="bg-blue-600 text-white text-[11px]">DETERMINISTIC MEASUREMENT</Badge>
        </div>
        <p className="text-xs text-slate-500 mt-1">
          Counterfactual baseline modeling and true net-incremental revenue recovery verification.
        </p>
      </div>

      {/* Main Value Add Banner */}
      <div className="rounded-xl border border-blue-200 bg-gradient-to-r from-blue-50/70 via-white to-blue-50/40 p-6 shadow-sm">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-blue-800">
              <TrendingUp className="w-4 h-4 text-blue-600" />
              Net Incremental Recovered Revenue
            </div>
            <div className="text-3xl font-extrabold text-slate-900 mt-2">
              {formatCurrency(kpis?.estimated_incremental_recovery || 0)}
            </div>
            <p className="text-xs text-slate-600 mt-1 max-w-xl">
              True incremental uplift verified by deducting the counterfactual organic baseline ({formatCurrency(kpis?.observed_control_recovery || 0)}) from observed treatment recovery.
            </p>
          </div>

          <div className="flex items-center gap-6 border-t md:border-t-0 md:border-l border-slate-200 pt-4 md:pt-0 md:pl-6">
            <div>
              <div className="text-xs text-slate-500 font-medium">True Recovery Rate</div>
              <div className="text-2xl font-bold text-blue-600 mt-0.5">
                {(kpis?.recovery_rate_pct || 0).toFixed(1)}%
              </div>
              <span className="text-[11px] text-slate-400">Total volume recovered</span>
            </div>

            <div>
              <div className="text-xs text-slate-500 font-medium">Attribution Confidence</div>
              <div className="text-2xl font-bold text-emerald-600 mt-0.5">
                100%
              </div>
              <span className="text-[11px] text-slate-400">Deterministic ledger</span>
            </div>
          </div>
        </div>
      </div>

      {/* 3 Pillar Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        <Card className="border border-slate-200 bg-white shadow-sm">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
                Observed Recovery
              </CardTitle>
              <DollarSign className="w-4 h-4 text-emerald-600" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-slate-900">
              {formatCurrency(kpis?.recovered_revenue || 0)}
            </div>
            <p className="text-xs text-slate-500 mt-1">
              Revenue rescued across all settled recovery cases.
            </p>
          </CardContent>
        </Card>

        <Card className="border border-slate-200 bg-white shadow-sm">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
                Counterfactual Baseline
              </CardTitle>
              <Scale className="w-4 h-4 text-slate-400" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-slate-600">
              {formatCurrency(kpis?.observed_control_recovery || 0)}
            </div>
            <p className="text-xs text-slate-500 mt-1">
              Estimated natural recovery without ARIV intervention.
            </p>
          </CardContent>
        </Card>

        <Card className="border border-slate-200 bg-white shadow-sm">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
                Engine Interventions
              </CardTitle>
              <Zap className="w-4 h-4 text-blue-600" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-blue-600">
              {totalActionAttempts}
            </div>
            <p className="text-xs text-slate-500 mt-1">
              Dispatched via Execution Outbox to payment providers.
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Attribution Breakdown Table / Details */}
      <Card className="border border-slate-200 bg-white shadow-sm">
        <CardHeader className="pb-3 border-b border-slate-100">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-sm font-semibold text-slate-900">
                Attribution & Incremental Ledger
              </CardTitle>
              <CardDescription className="text-xs text-slate-500 mt-0.5">
                Every recovered transaction is definitively classified to prevent false claims.
              </CardDescription>
            </div>
            <Badge variant="outline" className="text-xs bg-slate-50 text-slate-600 border-slate-200">
              Strict Causality
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="pt-4">
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="p-4 rounded-lg bg-emerald-50/60 border border-emerald-200/80">
                <div className="flex items-center justify-between">
                  <div className="text-xs font-semibold text-emerald-800">Action Attributed</div>
                  <Badge className="bg-emerald-600 text-white text-[10px]">VERIFIED CAUSAL</Badge>
                </div>
                <div className="text-2xl font-bold text-emerald-900 mt-2">
                  {actionAttributedCount} Cases
                </div>
                <p className="text-xs text-emerald-700 mt-1">
                  Payment was confirmed via the ARIV-generated recovery instrument within the active attribution window.
                </p>
              </div>

              <div className="p-4 rounded-lg bg-slate-50 border border-slate-200">
                <div className="flex items-center justify-between">
                  <div className="text-xs font-semibold text-slate-700">Organic Recovery</div>
                  <Badge variant="outline" className="text-slate-600 border-slate-300 text-[10px]">BASELINE</Badge>
                </div>
                <div className="text-2xl font-bold text-slate-800 mt-2">
                  {organicCount} Cases
                </div>
                <p className="text-xs text-slate-600 mt-1">
                  Customer completed repayment independently outside of the ARIV intervention link. Not credited to ARIV.
                </p>
              </div>
            </div>

            {/* Action Performance Table */}
            {action_performance && action_performance.length > 0 && (
              <div className="mt-4 pt-4 border-t border-slate-100">
                <div className="text-xs font-semibold text-slate-800 uppercase tracking-wide mb-2">
                  Action Performance Breakdown
                </div>
                <div className="border border-slate-200 rounded-md overflow-hidden">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-50 text-slate-600 border-b border-slate-200">
                      <tr>
                        <th className="p-2.5 font-medium">Action Type</th>
                        <th className="p-2.5 font-medium">Attempts</th>
                        <th className="p-2.5 font-medium">Successes</th>
                        <th className="p-2.5 font-medium">Recovered Amount</th>
                        <th className="p-2.5 font-medium">Incremental Value</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {action_performance.map((ap, idx) => (
                        <tr key={idx} className="hover:bg-slate-50/50">
                          <td className="p-2.5 font-mono font-medium text-slate-800">{ap.action_type}</td>
                          <td className="p-2.5 text-slate-600">{ap.attempts}</td>
                          <td className="p-2.5 text-emerald-700 font-medium">{ap.successes}</td>
                          <td className="p-2.5 text-slate-900 font-semibold">{formatCurrency(ap.recovered_amount)}</td>
                          <td className="p-2.5 text-blue-700 font-medium">{formatCurrency(ap.estimated_incremental_value)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            <div className="flex items-start gap-2 p-3 bg-blue-50/50 border border-blue-100 rounded-md text-xs text-slate-600">
              <Info className="w-4 h-4 text-blue-600 shrink-0 mt-0.5" />
              <span>
                <strong>Methodology:</strong> Attribution utilizes deterministic payment transaction metadata and provider webhook correlation. Recovery amounts are strictly segregated to avoid cannibalization of organic revenue.
              </span>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
