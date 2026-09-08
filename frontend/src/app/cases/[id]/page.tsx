"use client";

import { useQuery } from "@tanstack/react-query";
import { recoveryApi } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ArrowLeft, ArrowRight, Brain, Shield, Clock, CheckCircle2, AlertCircle,
  Database, Zap, AlertTriangle, BarChart2, Layers, ExternalLink, TrendingUp
} from "lucide-react";
import Link from "next/link";
import { use, useEffect } from "react";
import { useLiveStatus } from "@/hooks/use-live-status";
import { LiveStatusBadge } from "@/components/LiveIndicator";
import type { EconomicRanking } from "@/lib/types";

const formatCurrency = (minor: number) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" }).format(minor / 100);

const formatRupees = (major: number) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" }).format(major);

function Section({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="border border-slate-200 rounded-xl bg-white shadow-sm">
      <div className="flex items-center gap-2.5 px-5 py-3.5 border-b border-slate-200 bg-slate-50 rounded-t-xl">
        {icon}
        <span className="font-semibold text-sm text-slate-800">{title}</span>
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}

function DataRow({ label, value, className }: { label: string; value: React.ReactNode; className?: string }) {
  return (
    <div className="flex justify-between items-start py-1.5 border-b border-slate-100 last:border-0">
      <span className="text-xs text-slate-500">{label}</span>
      <span className={`text-xs font-semibold text-right max-w-[60%] ${className ?? "text-slate-800"}`}>{value}</span>
    </div>
  );
}

function PolicyBadge({ status }: { status: string }) {
  if (status === "APPROVED") {
    return (
      <div className="flex items-center gap-2 p-3 rounded-lg bg-emerald-50 border border-emerald-200">
        <CheckCircle2 className="w-5 h-5 text-emerald-600 flex-shrink-0" />
        <div>
          <div className="text-sm font-bold text-emerald-700">POLICY AUTHORIZED</div>
          <div className="text-xs text-emerald-600">Action cleared by deterministic policy engine.</div>
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2 p-3 rounded-lg bg-red-50 border border-red-200">
        <Shield className="w-5 h-5 text-red-600 flex-shrink-0" />
        <div>
          <div className="text-sm font-bold text-red-700">POLICY BLOCKED</div>
          <div className="text-xs text-red-600">AI proposed this action, but policy prevented execution.</div>
        </div>
      </div>
      <div className="text-xs text-slate-500 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">
        ✗ No provider request was dispatched.
      </div>
    </div>
  );
}

const formatEnr = (value: number | string | null | undefined) =>
  value != null && Number.isFinite(Number(value)) ? formatRupees(Number(value)) : "—";

const formatProbability = (value: number | string | null | undefined) =>
  value != null && Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(0)}%` : "—";

function EconomicOptimization({ economic, proposedAction, amountMinor }: {
  economic?: EconomicRanking;
  proposedAction: string;
  amountMinor: number;
}) {
  if (!economic?.available || !economic.ranked_candidates?.length) {
    return (
      <div className="flex flex-col gap-2">
        <div className="p-4 bg-amber-50 border border-amber-200 rounded-lg">
          <div className="text-xs font-bold text-amber-800 mb-1">NO ECONOMIC RANKING RECORDED</div>
          <div className="text-xs text-amber-700 leading-relaxed">
            No ENR candidate ranking was persisted for this case. ARIV shows no economic values rather than estimating or fabricating them.
          </div>
        </div>
        {economic?.expected_irv != null && Number.isFinite(Number(economic.expected_irv)) && (
          <div className="p-3 bg-white border border-slate-200 rounded-lg">
            <DataRow
              label="Selected Action Expected ENR"
              value={<span className="tabular-nums text-emerald-700">{formatRupees(Number(economic.expected_irv))}</span>}
            />
          </div>
        )}
      </div>
    );
  }

  const candidates = economic.ranked_candidates;
  const maxEnr = Math.max(...candidates.map((c) => Number(c.expected_net_recovery) || 0), 0.0001);
  const policyFor = (action: string) => economic.policy_evaluations?.find((p) => p.action === action);

  return (
    <div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
        <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-3">
          <div className="text-[11px] text-emerald-600 font-semibold mb-1">SELECTED ENR</div>
          <div className={`font-bold tabular-nums ${formatEnr(economic.selected_enr) === "—" ? "text-slate-400" : "text-emerald-800"}`}>
            {formatEnr(economic.selected_enr)}
          </div>
        </div>
        <div className="bg-white border border-slate-200 rounded-lg p-3">
          <div className="text-[11px] text-slate-400 font-semibold mb-1">RECOVERY PROBABILITY</div>
          <div className="font-bold text-slate-800 tabular-nums">{formatProbability(economic.selected_probability)}</div>
        </div>
        <div className="bg-white border border-slate-200 rounded-lg p-3">
          <div className="text-[11px] text-slate-400 font-semibold mb-1">REFERENCE AMOUNT</div>
          <div className="font-bold text-slate-800 tabular-nums">{formatCurrency(amountMinor)}</div>
        </div>
        <div className="bg-white border border-slate-200 rounded-lg p-3">
          <div className="text-[11px] text-slate-400 font-semibold mb-1">RANKING METHOD</div>
          <div className="font-bold text-slate-800">{economic.method}</div>
          <div className="text-[10px] text-slate-400">Selects action with max ENR</div>
        </div>
      </div>

      <div className="text-[11px] text-slate-400 font-mono border border-slate-200 rounded-lg px-3 py-2 bg-slate-50 mb-3">
        ENR = P(recovery) × amount − operational cost − risk penalty
      </div>

      <div className="space-y-2">
        {candidates.map((cand, i) => {
          const enr = Number(cand.expected_net_recovery) || 0;
          const pct = Math.max(0, Math.min(100, (enr / maxEnr) * 100));
          const isSelected = cand.action === proposedAction;
          const policy = policyFor(cand.action);
          return (
            <div
              key={`${cand.action}-${i}`}
              className={`p-3 rounded-lg border ${isSelected ? "bg-emerald-50/70 border-emerald-300" : "bg-white border-slate-200"}`}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  {isSelected && (
                    <Badge className="bg-emerald-600 text-white text-[9px] font-semibold shrink-0">SELECTED</Badge>
                  )}
                  <span className={`text-xs font-semibold truncate ${isSelected ? "text-emerald-800" : "text-slate-700"}`}>
                    {cand.action.replace(/_/g, " ")}
                  </span>
                  {policy && (
                    <Badge
                      variant="outline"
                      className={`shrink-0 text-[9px] border ${
                        policy.policy_status === "APPROVED"
                          ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                          : "bg-red-50 text-red-700 border-red-200"
                      }`}
                    >
                      POLICY {policy.policy_status.replace(/_/g, " ")}
                    </Badge>
                  )}
                </div>
                <span className={`text-xs font-bold tabular-nums shrink-0 ${isSelected ? "text-emerald-700" : "text-slate-800"}`}>
                  {formatRupees(enr)}
                </span>
              </div>
              <div className="flex items-center gap-2 mt-2">
                <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${isSelected ? "bg-emerald-500" : "bg-blue-500"}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="text-[10px] text-slate-400 tabular-nums w-16 text-right shrink-0">
                  p={formatProbability(cand.recovery_probability)}
                </span>
              </div>
              <div className="flex items-center gap-3 mt-1.5 text-[10px] text-slate-400 font-mono flex-wrap">
                <span>Amount {formatRupees(Number(cand.recoverable_amount) || 0)}</span>
                <span>− Cost {formatRupees(Number(cand.operational_cost) || 0)}</span>
                <span>− Risk {formatRupees(Number(cand.risk_penalty) || 0)}</span>
                <span className="text-[9px] bg-slate-100 border border-slate-200 rounded px-1 py-0.5 uppercase">
                  {Array.isArray(cand.probability_provenance)
                    ? cand.probability_provenance.join(", ")
                    : String(cand.probability_provenance ?? "")}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function CaseDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const resolvedParams = use(params);
  const caseId = resolvedParams.id;
  const { liveState, lastUpdated, markSuccess, markError, markFetching } = useLiveStatus();

  const { data: detail, isLoading, error, isFetching } = useQuery({
    queryKey: ["case", caseId],
    queryFn: () => recoveryApi.getCaseDetail(caseId),
    refetchInterval: 2_000,
    refetchIntervalInBackground: false,
    placeholderData: (previousData) => previousData,
  });

  useEffect(() => { if (isFetching) markFetching(); }, [isFetching, markFetching]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (detail) markSuccess(); }, [detail]);
  useEffect(() => { if (error) markError(); }, [error, markError]);

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-1/3 bg-slate-200 rounded-xl" />
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 space-y-4">
            <Skeleton className="h-64 bg-slate-200 rounded-xl" />
            <Skeleton className="h-64 bg-slate-200 rounded-xl" />
          </div>
          <div className="space-y-4">
            <Skeleton className="h-48 bg-slate-200 rounded-xl" />
            <Skeleton className="h-48 bg-slate-200 rounded-xl" />
          </div>
        </div>
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="p-6 bg-red-50 border border-red-200 rounded-xl text-red-700 flex items-center gap-3">
        <AlertTriangle className="w-5 h-5 flex-shrink-0" />
        <span>Failed to load case {caseId}. Check backend connectivity.</span>
      </div>
    );
  }

  const { case: c, classification, decision, execution, recovery, measurement, timeline, similar_cases, activities, economic } = detail;

  const isWaitingForPayment =
    (execution?.recovery_stage === "WAITING_FOR_PAYMENT" ||
      c.recovery_stage === "WAITING_FOR_PAYMENT" ||
      (c.context as any)?.recovery_stage === "WAITING_FOR_PAYMENT") &&
    recovery.outcome_status !== "RECOVERED";

  const paymentLinkUrl =
    execution?.payment_link_url ||
    (c.context as any)?.payment_link_url;

  const providerRef =
    execution?.provider_resource_id ||
    execution?.provider_reference ||
    (c.context as any)?.payment_link_id ||
    execution?.provider_request_id;

  return (
    <div className="space-y-6 animate-in fade-in duration-300 pb-16">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link href="/cases" className="p-2 hover:bg-slate-100 rounded-full text-slate-400 hover:text-slate-700 transition-colors">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div className="flex-1">
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-xl font-bold text-slate-900 font-mono">{c.id.split("-")[0]}…</h1>
            <Badge variant="outline" className={`border font-semibold text-xs ${
              c.status === "RECOVERED" ? "bg-emerald-50 text-emerald-700 border-emerald-200" :
              c.status === "FAILED" ? "bg-red-50 text-red-700 border-red-200" :
              c.status === "IN_PROGRESS" ? "bg-blue-50 text-blue-700 border-blue-200" :
              "bg-slate-100 text-slate-600 border-slate-200"
            }`}>
              {c.status}
            </Badge>
            {isWaitingForPayment && (
              <Badge variant="outline" className="border font-semibold text-xs bg-amber-50 text-amber-800 border-amber-300">
                WAITING FOR PAYMENT
              </Badge>
            )}
            <span className="text-xs text-slate-400 font-mono">{c.domain} · {c.case_type}</span>
          </div>
          <div className="flex items-center gap-3 mt-1">
            <p className="text-sm text-slate-500">
              {formatCurrency(c.amount_minor)} · opened {new Date(c.created_at).toLocaleString()}
            </p>
            <LiveStatusBadge state={liveState} lastUpdated={lastUpdated} />
          </div>
        </div>
      </div>

      {/* Waiting for Payment State Banner (Requirement 4) */}
      {isWaitingForPayment && (
        <div className="p-4 bg-amber-50/90 border border-amber-200 rounded-xl flex items-start gap-3">
          <Clock className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-bold text-amber-900 text-sm">ACTION SUCCEEDED — PAYMENT LINK DISPATCHED</span>
              <Badge className="bg-amber-200/80 text-amber-900 border-amber-300 hover:bg-amber-200 font-mono text-[10px]">
                RECOVERY NOT YET VERIFIED
              </Badge>
            </div>
            <p className="text-xs text-amber-800/90 mt-1 leading-relaxed">
              Recovery action succeeded and a Payment Link was generated. System is safely awaiting customer payment confirmation before verifying recovery.
            </p>
          </div>
        </div>
      )}

      {/* Payment Link Action Card */}
      {execution?.action_type === "GENERATE_PAYMENT_LINK" && Boolean(paymentLinkUrl) && (
        <div className="p-4 bg-gradient-to-r from-blue-50/80 via-indigo-50/40 to-blue-50/80 border border-blue-200 rounded-xl space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2">
              <span className="text-base">🔗</span>
              <span className="font-bold text-sm text-blue-950">RECOVERY ACTION: GENERATE_PAYMENT_LINK</span>
            </div>
            <Badge className="bg-blue-600 text-white font-mono text-[10px]">
              {execution?.status || "SUCCEEDED"}
            </Badge>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-white/90 border border-blue-100 rounded-lg p-3 text-xs">
            <div>
              <span className="text-slate-400 block text-[11px]">Recovery Amount</span>
              <span className="font-bold text-slate-900 tabular-nums">{formatCurrency(c.amount_minor)}</span>
            </div>
            <div>
              <span className="text-slate-400 block text-[11px]">Action Status</span>
              <span className="font-semibold text-emerald-700">{execution?.status || "SUCCEEDED"}</span>
            </div>
            <div>
              <span className="text-slate-400 block text-[11px]">Provider Reference</span>
              <span className="font-mono text-xs font-semibold text-slate-700 truncate block">
                {providerRef || "N/A"}
              </span>
            </div>
            <div>
              <span className="text-slate-400 block text-[11px]">Recovery Stage</span>
              <span className="font-semibold text-amber-700">
                {isWaitingForPayment ? "WAITING_FOR_PAYMENT" : recovery.outcome_status}
              </span>
            </div>
          </div>

          <div className="flex items-center justify-between gap-3 pt-1 flex-wrap">
            <span className="text-[11px] text-slate-500 font-mono truncate max-w-md">
              URL: {paymentLinkUrl}
            </span>
            <a
              href={paymentLinkUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white font-semibold text-xs rounded-lg shadow-sm hover:shadow transition-all"
            >
              <span>Open Razorpay Test Payment Link</span>
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Main Column */}
        <div className="lg:col-span-2 space-y-5">

          {/* Failure Intelligence */}
          <Section title="Failure Intelligence" icon={<Brain className="w-4 h-4 text-blue-600" />}>
            <div className="bg-slate-50 border border-slate-200 rounded-lg px-4 py-3 font-mono text-sm text-slate-700 mb-4 leading-relaxed">
              {decision.structured_explanation}
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                { label: "Failure Category", value: classification.failure_category, cls: "text-red-700" },
                { label: "Retryability", value: classification.retryability, cls: "" },
                { label: "Recoverability", value: classification.recoverability, cls: "text-emerald-700" },
                { label: "AI Confidence", value: `${(decision.ai_confidence * 100).toFixed(0)}%`, cls: "text-blue-700" },
              ].map(({ label, value, cls }) => (
                <div key={label} className="bg-white border border-slate-200 rounded-lg p-3">
                  <div className="text-xs text-slate-400 mb-1">{label}</div>
                  <div className={`font-bold text-sm ${cls || "text-slate-800"}`}>{value}</div>
                </div>
              ))}
            </div>
          </Section>

          {/* AI Decision */}
          <Section title="AI Decision" icon={<Brain className="w-4 h-4 text-purple-600" />}>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                <div className="text-xs text-blue-600 font-semibold mb-1">PROPOSED ACTION</div>
                <div className="font-bold text-blue-800">{decision.proposed_action}</div>
              </div>
              <div className="bg-slate-50 border border-slate-200 rounded-lg p-4">
                <div className="text-xs text-slate-500 font-semibold mb-1">BASELINE ACTION</div>
                <div className="font-bold text-slate-700">{decision.baseline_action}</div>
              </div>
            </div>
            <div className="mt-3">
              <DataRow label="Autonomy Level" value={decision.autonomy_level} />
              <DataRow label="Policy Version" value={decision.policy_version} className="text-slate-500 font-mono" />
              {decision.rejection_reason && (
                <DataRow label="Rejection Reason" value={decision.rejection_reason} className="text-red-600" />
              )}
            </div>
          </Section>

          {/* Economic Optimization (ENR) */}
          <Section title="Economic Optimization" icon={<TrendingUp className="w-4 h-4 text-emerald-600" />}>
            <EconomicOptimization economic={economic} proposedAction={decision.proposed_action} amountMinor={c.amount_minor} />
          </Section>

          {/* Policy Firewall */}
          <Section title="Policy Firewall" icon={<Shield className="w-4 h-4 text-red-600" />}>
            <PolicyBadge status={decision.policy_status} />
          </Section>

          {/* Execution & Provider */}
          {execution && (
            <Section title="Tool / MCP Execution" icon={<Zap className="w-4 h-4 text-amber-500" />}>
              <DataRow label="Action Type" value={execution.action_type} />
              <DataRow label="Execution Status" value={execution.status} />
              <DataRow label="Recovery Stage" value={execution.recovery_stage || (isWaitingForPayment ? "WAITING_FOR_PAYMENT" : "NONE")} />
              <DataRow label="Provider" value={execution.provider} />
              <DataRow label="Attempt Count" value={String(execution.attempt_count)} />
              {(providerRef || execution.provider_request_id) && (
                <DataRow
                  label="Provider Reference"
                  value={<span className="font-mono text-xs">{providerRef || execution.provider_request_id}</span>}
                  className="text-slate-700"
                />
              )}
              {paymentLinkUrl && (
                <DataRow
                  label="Payment Link"
                  value={
                    <a
                      href={paymentLinkUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:underline font-mono text-xs break-all"
                    >
                      {paymentLinkUrl}
                    </a>
                  }
                />
              )}
              {execution.is_unknown && (
                <div className="mt-3 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                  <div className="text-xs font-bold text-amber-700 mb-1">⚠ UNKNOWN STATE</div>
                  <div className="text-xs text-amber-600">
                    Provider state could not be confirmed. ARIV is reconciling without blind retry.
                    No duplicate execution was attempted while provider state was uncertain.
                  </div>
                </div>
              )}
            </Section>
          )}

          {/* Live Operational Activity Stream / Timeline */}
          <Section title="Live Case Activities & Audit Timeline" icon={<Clock className="w-4 h-4 text-blue-600" />}>
            {activities && activities.length > 0 ? (
              <div className="relative border-l-2 border-slate-200 ml-3 space-y-4 pb-2">
                {activities.map((act) => (
                  <div key={act.id} className="relative pl-6">
                    <div className={`absolute -left-[5px] top-1.5 w-2.5 h-2.5 rounded-full border-2 ${
                      act.severity === "error" ? "bg-red-500 border-red-300" :
                      act.severity === "success" ? "bg-emerald-500 border-emerald-300" :
                      act.severity === "warning" ? "bg-amber-500 border-amber-300" :
                      "bg-blue-500 border-blue-300"
                    }`} />
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm">{act.icon || "📌"}</span>
                        <span className="text-sm font-semibold text-slate-800">
                          {act.event_type ? act.event_type.replace(/_/g, " ") : "Activity"}
                        </span>
                      </div>
                      <span className="text-xs text-slate-400 font-mono">
                        {new Date(act.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                      </span>
                    </div>
                    <p className="text-xs text-slate-600 mt-1 leading-relaxed">{act.human_readable_message}</p>
                    <div className="flex items-center gap-3 mt-1.5 text-[10px] font-mono text-slate-400 flex-wrap">
                      {act.action_id && <span>Action: {act.action_id.slice(0, 8)}…</span>}
                      {act.metadata?.provider_resource_id && (
                        <span className="text-emerald-700 bg-emerald-50 px-1 py-0.5 rounded border border-emerald-200">
                          Provider Ref: {act.metadata.provider_resource_id}
                        </span>
                      )}
                      {act.metadata?.short_url && (
                        <a
                          href={act.metadata.short_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-600 hover:underline inline-flex items-center gap-0.5"
                        >
                          Payment Link <ArrowRight className="w-2.5 h-2.5" />
                        </a>
                      )}
                      <span className={`px-1 rounded uppercase font-semibold ${
                        act.severity === "success" ? "bg-emerald-50 text-emerald-700" :
                        act.severity === "error" ? "bg-red-50 text-red-700" :
                        act.severity === "warning" ? "bg-amber-50 text-amber-700" :
                        "bg-slate-100 text-slate-600"
                      }`}>
                        {act.status}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="relative border-l-2 border-slate-200 ml-3 space-y-5 pb-2">
                {timeline.map((event, i) => (
                  <div key={i} className="relative pl-6">
                    <div className={`absolute -left-[5px] top-1.5 w-2.5 h-2.5 rounded-full border-2 ${
                      event.status === "UNKNOWN" ? "bg-amber-500 border-amber-300" :
                      event.status === "DONE" || event.status === "RECOVERED" ? "bg-emerald-500 border-emerald-300" :
                      "bg-blue-500 border-blue-300"
                    }`} />
                    <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-3">
                      <span className="text-sm font-semibold text-slate-800">{event.stage}</span>
                      <span className="text-xs text-slate-400 font-mono">{new Date(event.timestamp).toLocaleString()}</span>
                    </div>
                    <p className="text-sm text-slate-500 mt-0.5">{event.description}</p>
                    {event.status === "UNKNOWN" && (
                      <Badge variant="outline" className="mt-1.5 bg-amber-50 text-amber-700 border-amber-200 text-xs">
                        UNKNOWN STATE — Reconciling
                      </Badge>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Section>
        </div>

        {/* Sidebar */}
        <div className="space-y-5">

          {/* Outcome & Attribution */}
          <Section title="Outcome & Attribution" icon={<CheckCircle2 className="w-4 h-4 text-emerald-600" />}>
            <div className="flex items-center gap-2 mb-3">
              {recovery.outcome_status === "RECOVERED" ? (
                <CheckCircle2 className="w-5 h-5 text-emerald-500" />
              ) : (
                <AlertCircle className="w-5 h-5 text-slate-400" />
              )}
              <span className={`font-bold text-base ${recovery.outcome_status === "RECOVERED" ? "text-emerald-600" : "text-slate-600"}`}>
                {recovery.outcome_status}
              </span>
            </div>
            <DataRow label="Recovered Amount" value={formatCurrency(recovery.recovered_amount_minor)} className="text-emerald-700" />
            <DataRow label="Recovery Source" value={recovery.recovery_source} />
            <DataRow label="Attribution Source" value={recovery.attribution_source} />
            <DataRow label="Attribution Decision" value={recovery.attribution_decision} />
            <DataRow label="Attribution Window" value={`${Math.round(recovery.attribution_window_seconds / 3600)}h`} />
          </Section>

          {/* Measurement */}
          {measurement && (
            <Section title="Incremental Measurement" icon={<BarChart2 className="w-4 h-4 text-blue-600" />}>
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 space-y-2 mb-3">
                <div className="flex justify-between text-sm">
                  <span className="text-slate-500">Treatment (Observed)</span>
                  <span className="font-semibold text-slate-800">{formatCurrency(measurement.treatment_recovery_minor)}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-slate-500">Baseline <Badge className="text-[9px] bg-blue-100 text-blue-600 border-blue-200 hover:bg-blue-100 ml-1">ESTIMATE</Badge></span>
                  <span className="font-semibold text-slate-800">{formatCurrency(measurement.estimated_control_recovery_minor)}</span>
                </div>
                <div className="flex justify-between text-sm font-bold pt-2 border-t border-blue-200">
                  <span className="text-blue-700">Net Incremental Value</span>
                  <span className="text-blue-700">{formatCurrency(measurement.incremental_recovery_minor)}</span>
                </div>
              </div>
              <div className="text-xs text-slate-400 text-center">{measurement.label}</div>
            </Section>
          )}

          {/* Recovery Memory */}
          <Section title="Recovery Memory" icon={<Database className="w-4 h-4 text-purple-600" />}>
            <div className="text-xs text-slate-400 mb-3">Historical precedent retrieved from Qdrant vector store.</div>
            {similar_cases && similar_cases.length > 0 ? (
              <div className="space-y-2">
                {similar_cases.map((sc, i) => (
                  <div key={i} className="p-2.5 rounded-lg bg-slate-50 border border-slate-200 text-xs space-y-1">
                    <div className="flex justify-between font-semibold">
                      <span className="text-slate-700">{sc.action_type}</span>
                      <span className={sc.outcome_status === "RECOVERED" ? "text-emerald-600" : "text-slate-500"}>
                        {sc.outcome_status}
                      </span>
                    </div>
                    <div className="text-slate-400 flex gap-2">
                      <span>{sc.failure_category}</span>
                      <span>·</span>
                      <span>{sc.time_to_recovery_bucket}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-sm text-slate-400 text-center py-4">
                No similar cases found in recovery memory.
              </div>
            )}
          </Section>

          {/* Raw Case Info */}
          <Section title="Case Info" icon={<Layers className="w-4 h-4 text-slate-500" />}>
            <DataRow label="Case ID" value={<span className="font-mono text-[10px] text-slate-500">{c.id}</span>} />
            <DataRow label="Tenant ID" value={<span className="font-mono text-[10px] text-slate-500">{c.tenant_id}</span>} />
            <DataRow label="Domain" value={c.domain} />
            <DataRow label="Case Type" value={c.case_type} />
          </Section>
        </div>
      </div>
    </div>
  );
}
