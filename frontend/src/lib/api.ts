import type { DashboardData, FullCaseDetail, RecentCase, SimilarCase, OperationalActivityItem } from "./types";

/**
 * Frontend API client.
 * Note: All requests go through the Next.js proxy route (/api/proxy/v1/...)
 * which attaches the HMAC signature server-side securely.
 */

export const fetchProxy = async <T>(endpoint: string, init?: RequestInit): Promise<T> => {
  // endpoint should start with /v1/...
  const url = `/api/proxy${endpoint}`;
  const response = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(`API Error ${response.status}: ${errorBody}`);
  }

  return response.json();
};

export const recoveryApi = {
  getDashboard: () => fetchProxy<DashboardData>("/v1/recovery/dashboard"),
  getCases: (params?: { limit?: number; offset?: number; status?: string }) => {
    const search = new URLSearchParams();
    if (params?.limit) search.set("limit", String(params.limit));
    if (params?.offset) search.set("offset", String(params.offset));
    if (params?.status) search.set("status", params.status);
    const qs = search.toString();
    return fetchProxy<RecentCase[]>(`/v1/recovery/cases${qs ? `?${qs}` : ""}`);
  },
  getCaseDetail: (caseId: string) => fetchProxy<FullCaseDetail>(`/v1/recovery/cases/${caseId}/full`),
  getSimilarCases: (caseId: string) => fetchProxy<SimilarCase[]>(`/v1/recovery/cases/${caseId}/similar`),
  getActivity: (params?: { limit?: number; caseId?: string }) => {
    const search = new URLSearchParams();
    if (params?.limit) search.set("limit", String(params.limit));
    if (params?.caseId) search.set("case_id", params.caseId);
    const qs = search.toString();
    return fetchProxy<OperationalActivityItem[]>(`/v1/recovery/activity${qs ? `?${qs}` : ""}`);
  },
  seedDemo: () => fetchProxy<{ status: string; seeded_count: number; case_ids?: string[] }>("/v1/recovery/demo/seed", { method: "POST" }),
  getSystemHealth: () => fetchProxy<Record<string, unknown>>("/v1/health/dependencies"),
  getRouteHealth: () => fetchProxy<{ status: string; corridors: any[] }>("/v1/routes/health"),
};
