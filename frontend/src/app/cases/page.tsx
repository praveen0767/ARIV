"use client";

import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { recoveryApi } from "@/lib/api";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import Link from "next/link";
import { formatDistanceToNow } from "date-fns";
import { ChevronRight, AlertTriangle, Clock, CheckCircle2, XCircle, Loader2, HelpCircle } from "lucide-react";
import { useLiveStatus } from "@/hooks/use-live-status";
import { LiveIndicator } from "@/components/LiveIndicator";

const FILTERS = [
  { label: "ALL", value: "" },
  { label: "OPEN", value: "OPEN" },
  { label: "IN PROGRESS", value: "IN_PROGRESS" },
  { label: "RECOVERED", value: "RECOVERED" },
  { label: "FAILED", value: "FAILED" },
];

const formatCurrency = (minor: number) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" }).format(minor / 100);

function StatusBadge({ status }: { status: string }) {
  const config: Record<string, { className: string; icon: React.ReactNode }> = {
    RECOVERED: {
      className: "bg-emerald-50 text-emerald-700 border-emerald-200",
      icon: <CheckCircle2 className="w-3 h-3" />,
    },
    FAILED: {
      className: "bg-red-50 text-red-700 border-red-200",
      icon: <XCircle className="w-3 h-3" />,
    },
    IN_PROGRESS: {
      className: "bg-blue-50 text-blue-700 border-blue-200",
      icon: <Loader2 className="w-3 h-3 animate-spin" />,
    },
    OPEN: {
      className: "bg-amber-50 text-amber-700 border-amber-200",
      icon: <Clock className="w-3 h-3" />,
    },
  };
  const c = config[status] ?? {
    className: "bg-slate-100 text-slate-600 border-slate-200",
    icon: <HelpCircle className="w-3 h-3" />,
  };
  return (
    <Badge variant="outline" className={`flex items-center gap-1.5 font-medium text-xs border ${c.className}`}>
      {c.icon}
      {status}
    </Badge>
  );
}

export default function CasesListPage() {
  const [statusFilter, setStatusFilter] = useState<string>("");
  const { liveState, lastUpdated, markSuccess, markError, markFetching } = useLiveStatus();

  const { data: cases, isLoading, error, isFetching } = useQuery({
    queryKey: ["cases", statusFilter],
    queryFn: () => recoveryApi.getCases(statusFilter ? { status: statusFilter } : undefined),
    refetchInterval: 2_000,
    refetchIntervalInBackground: false,
  });

  useEffect(() => { if (isFetching) markFetching(); }, [isFetching, markFetching]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (cases) markSuccess(); }, [cases]);
  useEffect(() => { if (error) markError(); }, [error, markError]);

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Recovery Operations</h1>
          <p className="text-sm text-slate-500 mt-1">
            Operational queue of all tenant-isolated payment failure interventions.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <LiveIndicator state={liveState} lastUpdated={lastUpdated} />
          <div className="flex gap-2">
          {FILTERS.map(({ label, value }) => (
            <button
              key={value}
              onClick={() => setStatusFilter(value)}
              className={`px-3 py-1.5 text-xs font-semibold rounded-lg border transition-all ${
                statusFilter === value
                  ? "bg-blue-600 border-blue-600 text-white shadow-sm"
                  : "bg-white border-slate-200 text-slate-600 hover:border-slate-300 hover:bg-slate-50"
              }`}
            >
              {label}
            </button>
          ))}
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="border border-slate-200 rounded-xl overflow-hidden shadow-sm bg-white">
        <Table>
          <TableHeader className="bg-slate-50">
            <TableRow className="border-slate-200 hover:bg-transparent">
              <TableHead className="text-slate-500 font-semibold text-xs uppercase tracking-wider">Case ID</TableHead>
              <TableHead className="text-slate-500 font-semibold text-xs uppercase tracking-wider">Type / Domain</TableHead>
              <TableHead className="text-slate-500 font-semibold text-xs uppercase tracking-wider">Amount</TableHead>
              <TableHead className="text-slate-500 font-semibold text-xs uppercase tracking-wider">Status</TableHead>
              <TableHead className="text-slate-500 font-semibold text-xs uppercase tracking-wider">Outcome</TableHead>
              <TableHead className="text-slate-500 font-semibold text-xs uppercase tracking-wider text-right">Age</TableHead>
              <TableHead className="w-8"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              [...Array(5)].map((_, i) => (
                <TableRow key={i} className="border-slate-100">
                  {[...Array(7)].map((_, j) => (
                    <TableCell key={j}><Skeleton className="h-4 w-full bg-slate-100 rounded" /></TableCell>
                  ))}
                </TableRow>
              ))
            ) : error ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-12">
                  <div className="flex flex-col items-center gap-2 text-red-500">
                    <AlertTriangle className="w-6 h-6" />
                    <span className="text-sm font-medium">Failed to load cases. Check backend connectivity.</span>
                  </div>
                </TableCell>
              </TableRow>
            ) : cases?.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-16">
                  <div className="text-slate-400 text-sm">
                    No cases found. Run the Demo Simulator to generate recovery scenarios.
                  </div>
                </TableCell>
              </TableRow>
            ) : (
              cases?.map((c) => (
                <TableRow
                  key={c.case_id}
                  className="border-slate-100 hover:bg-blue-50/50 transition-colors group cursor-pointer"
                >
                  <TableCell className="font-mono text-xs text-slate-500 group-hover:text-blue-700 transition-colors">
                    <Link href={`/cases/${c.case_id}`} className="hover:underline underline-offset-2">
                      {c.case_id.split("-")[0]}…
                    </Link>
                  </TableCell>
                  <TableCell>
                    <div className="font-semibold text-slate-800 text-sm">{c.case_type}</div>
                    <div className="text-xs text-slate-500">{c.domain}</div>
                  </TableCell>
                  <TableCell className="font-semibold text-slate-800 text-sm">
                    {formatCurrency(c.amount_minor)}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={c.status} />
                  </TableCell>
                  <TableCell>
                    {c.outcome_status !== "PENDING" && c.outcome_status !== "UNKNOWN" ? (
                      <div className="flex flex-col">
                        <span className={`text-sm font-semibold ${c.outcome_status === "RECOVERED" ? "text-emerald-600" : "text-slate-600"}`}>
                          {c.outcome_status}
                        </span>
                        <span className="text-xs text-slate-400">{c.recovery_source}</span>
                      </div>
                    ) : (
                      <span className="text-sm text-slate-400">—</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right text-xs text-slate-400">
                    {formatDistanceToNow(new Date(c.created_at), { addSuffix: true })}
                  </TableCell>
                  <TableCell>
                    <Link href={`/cases/${c.case_id}`}>
                      <ChevronRight className="w-4 h-4 text-slate-300 group-hover:text-blue-500 transition-colors" />
                    </Link>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
