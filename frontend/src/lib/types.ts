export interface KPIStats {
  revenue_at_risk: number;
  eligible_recovery: number;
  attempted_recovery: number;
  recovered_revenue: number;
  estimated_incremental_recovery: number;
  observed_treatment_recovery: number;
  observed_control_recovery: number;
  recovery_rate_pct: number;
  is_estimate: boolean;
  label: string;
}

export interface FunnelStage {
  stage: string;
  amount: number;
  count: number;
  badge: string;
}

export interface ActionPerformance {
  action_type: string;
  cases: number;
  attempts: number;
  successes: number;
  failures: number;
  recovered_amount: number;
  estimated_incremental_value: number;
  failure_rate_pct: number;
}

export interface RecentCase {
  case_id: string;
  domain: string;
  case_type: string;
  status: string;
  amount_minor: number;
  outcome_status: string;
  recovered_amount_minor: number;
  recovery_source: string;
  created_at: string;
  updated_at?: string;
}

export interface OperationalActivityItem {
  id: string;
  timestamp: string;
  event_type: string;
  case_id?: string | null;
  action_id?: string | null;
  severity: "info" | "success" | "warning" | "error";
  icon: string;
  human_readable_message: string;
  status: string;
  metadata?: Record<string, any>;
}

export interface DashboardData {
  tenant_id: string;
  kpis: KPIStats;
  funnel: FunnelStage[];
  action_performance: ActionPerformance[];
  recent_cases: RecentCase[];
  recent_activity?: OperationalActivityItem[];
}

export interface TimelineEvent {
  stage: string;
  timestamp: string;
  status: string;
  description: string;
}

export interface SimilarCase {
  measurement_id?: string;
  failure_category: string;
  domain: string;
  action_type: string;
  outcome_status: string;
  recovery_source: string;
  amount_bucket: string;
  time_to_recovery_bucket: string;
}

export interface EconomicCandidate {
  action: string;
  recovery_probability: number;
  probability_provenance: string[];
  recoverable_amount: number;
  operational_cost: number;
  risk_penalty: number;
  expected_net_recovery: number;
}

export interface EconomicPolicyEvaluation {
  action: string;
  expected_net_recovery: number;
  recovery_probability: number;
  policy_status: string;
  autonomy_level: string;
  rejection_reason?: string | null;
}

export interface EconomicRanking {
  available: boolean;
  method: string;
  ranked_candidates: EconomicCandidate[];
  selected_enr?: number | null;
  selected_probability?: number | null;
  selected_provenance?: string[];
  policy_evaluations?: EconomicPolicyEvaluation[];
  expected_irv?: number | null;
}

export interface FullCaseDetail {
  case: {
    id: string;
    tenant_id: string;
    domain: string;
    case_type: string;
    status: string;
    amount_minor: number;
    created_at: string;
    updated_at?: string;
    context?: Record<string, any>;
    recovery_stage?: string;
  };
  classification: {
    failure_category: string;
    retryability: string;
    recoverability: string;
    taxonomy_version: string;
    explanation: string;
  };
  decision: {
    proposed_action: string;
    baseline_action: string;
    ai_confidence: number;
    policy_status: string;
    autonomy_level: string;
    rejection_reason?: string;
    structured_explanation: string;
    policy_version: string;
  };
  economic?: EconomicRanking;
  execution: {
    action_type: string;
    status: string;
    provider: string;
    provider_request_id?: string;
    provider_resource_id?: string;
    provider_reference?: string;
    payment_link_url?: string;
    recovery_stage?: string;
    attempt_count: number;
    is_unknown: boolean;
  };
  recovery: {
    outcome_status: string;
    recovered_amount_minor: number;
    recovery_source: string;
    attribution_source: string;
    attribution_decision: string;
    attribution_window_seconds: number;
    recovered_at?: string;
    provider_reference?: string;
  };
  measurement?: {
    treatment_recovery_minor: number;
    control_recovery_minor: number;
    estimated_control_recovery_minor: number;
    incremental_recovery_minor: number;
    baseline_method: string;
    is_counterfactual_estimate: boolean;
    label: string;
  };
  timeline: TimelineEvent[];
  similar_cases: SimilarCase[];
  activities?: OperationalActivityItem[];
}
