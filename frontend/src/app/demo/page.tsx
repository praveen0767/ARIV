"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { recoveryApi } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Sparkles,
  Database,
  Terminal,
  ShieldAlert,
  Clock,
  ArrowRight,
  CheckCircle2,
  AlertTriangle,
  Play,
  RotateCcw
} from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import Link from "next/link";

interface ScenarioCardProps {
  id: number;
  title: string;
  badge: string;
  badgeVariant?: "blue" | "emerald" | "amber" | "rose";
  description: string;
  expectedOutcome: string;
  policyNote: string;
  onRun?: () => void;
  isLoading?: boolean;
}

function ScenarioCard({
  id,
  title,
  badge,
  badgeVariant = "blue",
  description,
  expectedOutcome,
  policyNote,
  onRun,
  isLoading,
}: ScenarioCardProps) {
  const badgeStyles = {
    blue: "bg-blue-50 text-blue-700 border-blue-200",
    emerald: "bg-emerald-50 text-emerald-700 border-emerald-200",
    amber: "bg-amber-50 text-amber-700 border-amber-200",
    rose: "bg-rose-50 text-rose-700 border-rose-200",
  }[badgeVariant];

  return (
    <Card className="border border-slate-200 bg-white hover:border-blue-300 transition-all shadow-sm">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="w-6 h-6 rounded-full bg-slate-100 text-slate-600 flex items-center justify-center text-xs font-semibold">
              {id}
            </span>
            <CardTitle className="text-sm font-semibold text-slate-900">{title}</CardTitle>
          </div>
          <Badge variant="outline" className={`text-[11px] font-medium ${badgeStyles}`}>
            {badge}
          </Badge>
        </div>
        <CardDescription className="text-xs text-slate-500 mt-1">{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2.5 text-xs">
        <div className="p-2.5 rounded bg-slate-50 border border-slate-100 space-y-1">
          <div className="font-medium text-slate-700">Expected Engine Workflow:</div>
          <div className="text-slate-600 leading-relaxed">{expectedOutcome}</div>
        </div>
        <div className="flex items-start gap-1.5 text-slate-500">
          <ShieldAlert className="w-3.5 h-3.5 text-blue-600 shrink-0 mt-0.5" />
          <span className="text-[11px]">Safety Policy: {policyNote}</span>
        </div>
      </CardContent>
    </Card>
  );
}

export default function DemoSandboxPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [log, setLog] = useState<string[]>([
    "[" + new Date().toLocaleTimeString() + "] Control Plane simulator initialized.",
    "[" + new Date().toLocaleTimeString() + "] Ready to inject deterministic scenarios into PostgreSQL and Qdrant.",
  ]);

  const addLog = (msg: string) => {
    setLog(prev => [`[${new Date().toLocaleTimeString()}] ${msg}`, ...prev.slice(0, 30)]);
  };

  const seedMutation = useMutation({
    mutationFn: recoveryApi.seedDemo,
    onMutate: () => {
      addLog("Starting deterministic scenario injection (4 sandbox cases)...");
    },
    onSuccess: (data) => {
      if (data.status === "already_seeded") {
        addLog("Verification: Demo sandbox cases already exist in DB.");
        toast({
          title: "Cases Ready",
          description: "4 deterministic sandbox cases are already present in the workspace.",
        });
      } else {
        addLog(`Success: Injected ${data.seeded_count} complete recovery cases.`);
        toast({
          title: "Demo Scenarios Active",
          description: `Successfully injected ${data.seeded_count} deterministic cases into ARIV.`,
        });
      }
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["cases"] });
    },
    onError: (error: any) => {
      addLog(`ERROR: ${error.message}`);
      toast({
        title: "Seeding Failed",
        description: error.message,
        variant: "destructive",
      });
    }
  });

  return (
    <div className="space-y-6 max-w-6xl">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-xl font-bold text-slate-900 tracking-tight">Recovery Simulator & Scenario Control</h1>
            <Badge className="bg-blue-600 hover:bg-blue-700 text-white text-[11px]">SANDBOX SUITE</Badge>
          </div>
          <p className="text-xs text-slate-500 mt-1">
            Execute and observe the 4 core ARIV decision cycles against deterministic test telemetry.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            onClick={() => seedMutation.mutate()}
            disabled={seedMutation.isPending}
            className="bg-blue-600 hover:bg-blue-700 text-white font-medium text-xs h-9 px-4 shadow-sm"
          >
            <Database className="w-3.5 h-3.5 mr-2" />
            {seedMutation.isPending ? "Injecting Data..." : "Seed All 4 Scenarios"}
          </Button>
          <Link href="/cases">
            <Button variant="outline" className="border-slate-200 text-slate-700 hover:bg-slate-50 text-xs h-9 px-3">
              View Cases Queue
              <ArrowRight className="w-3.5 h-3.5 ml-1.5" />
            </Button>
          </Link>
        </div>
      </div>

      {/* Simulator Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <ScenarioCard
          id={1}
          title="Action Attributed Recovery"
          badge="HAPPY PATH"
          badgeVariant="emerald"
          description="Customer payment fails due to technical gateway timeout; ARIV generates Razorpay recovery link; customer completes payment within attribution window."
          expectedOutcome="EVENT → DIAGNOSIS → MEMORY MATCH → POLICY AUTHORIZED → EXECUTION OUTBOX → PAID → ACTION ATTRIBUTED."
          policyNote="Within rate limit, non-fraud customer, authorized recovery action."
        />

        <ScenarioCard
          id={2}
          title="Policy Engine Rejection"
          badge="SAFETY FIREWALL"
          badgeVariant="rose"
          description="High-risk fraud decline or non-retriable failure. Engine attempts recovery action but Policy Engine intercepts and decisively blocks provider dispatch."
          expectedOutcome="EVENT → HIGH RISK → ACTION PROPOSED → POLICY BLOCKED → DISPATCH SUPPRESSED → ZERO DUPLICATE CHARGES."
          policyNote="Non-retriable failure code blocks blind retries. No provider request dispatched."
        />

        <ScenarioCard
          id={3}
          title="Provider Degradation & UNKNOWN State"
          badge="RECONCILIATION"
          badgeVariant="amber"
          description="Provider times out during recovery execution. State shifts to UNKNOWN without blind retry; periodic reconciliation queries provider for true status."
          expectedOutcome="EVENT → DISPATCH → TIMEOUT → STATE: UNKNOWN → SAFE RECONCILIATION → RESOLUTION."
          policyNote="Policy forbids immediate blind retry when provider response is ambiguous."
        />

        <ScenarioCard
          id={4}
          title="Organic Baseline Recovery"
          badge="COUNTERFACTUAL"
          badgeVariant="blue"
          description="Customer retries organically without receiving ARIV recovery intervention. Demonstrates causal measurement vs. organic baseline."
          expectedOutcome="EVENT → NO DISPATCH → CUSTOMER RETRIES OUTSIDE → PAID → ATTRIBUTION: ORGANIC_RECOVERY."
          policyNote="Zero intervention cost attributed; measured against counterfactual baseline."
        />
      </div>

      {/* Real-time Simulator Console */}
      <Card className="border border-slate-200 bg-white shadow-sm">
        <CardHeader className="py-3 px-4 border-b border-slate-100 flex flex-row items-center justify-between">
          <div className="flex items-center gap-2">
            <Terminal className="w-4 h-4 text-blue-600" />
            <CardTitle className="text-xs font-semibold text-slate-800 tracking-wide uppercase">
              Simulator Telemetry Console
            </CardTitle>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setLog(["[" + new Date().toLocaleTimeString() + "] Console cleared."])}
            className="h-6 text-[11px] text-slate-500 hover:text-slate-800"
          >
            Clear Log
          </Button>
        </CardHeader>
        <CardContent className="p-3">
          <div className="h-40 overflow-y-auto font-mono text-[11px] bg-slate-900 text-slate-200 rounded p-3 space-y-1.5 leading-relaxed">
            {log.map((entry, idx) => (
              <div key={idx} className="flex items-start gap-2">
                <span className="text-blue-400 select-none">&gt;</span>
                <span className={entry.includes("ERROR") ? "text-rose-400" : entry.includes("Success") ? "text-emerald-400" : "text-slate-300"}>
                  {entry}
                </span>
              </div>
            ))}
          </div>
        </CardContent>
        <CardFooter className="py-2.5 px-4 bg-slate-50 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
          <div className="flex items-center gap-2">
            <span className="inline-block w-2 h-2 rounded-full bg-emerald-500"></span>
            <span>PostgreSQL & Qdrant Connected</span>
          </div>
          <span>Tenant: default-merchant</span>
        </CardFooter>
      </Card>
    </div>
  );
}
