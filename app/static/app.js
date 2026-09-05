/**
 * ARIV Phase 6 Recovery Dashboard & Product Experience
 * Vanilla JS client with HMAC-SHA256 authentication via Web Crypto API.
 */

// State
let currentAccountId = localStorage.getItem("ariv_account_id") || "acc_test_tenant";
let currentApiKey = localStorage.getItem("ariv_api_key") || "test_internal_key";
let currentFilter = "ALL";
let cachedCases = [];

// DOM Elements
const displayAccountId = document.getElementById("displayAccountId");
const btnSeedDemo = document.getElementById("btnSeedDemo");
const btnRefresh = document.getElementById("btnRefresh");
const btnConfig = document.getElementById("btnConfig");
const configModal = document.getElementById("configModal");
const btnCloseConfig = document.getElementById("btnCloseConfig");
const btnSaveConfig = document.getElementById("btnSaveConfig");
const inputAccountId = document.getElementById("inputAccountId");
const inputApiKey = document.getElementById("inputApiKey");

const demoBanner = document.getElementById("demoBanner");
const demoBannerText = document.getElementById("demoBannerText");
const btnCloseBanner = document.getElementById("btnCloseBanner");

const caseModal = document.getElementById("caseModal");
const btnCloseModal = document.getElementById("btnCloseModal");
const modalDomain = document.getElementById("modalDomain");
const modalStatus = document.getElementById("modalStatus");
const modalCaseId = document.getElementById("modalCaseId");
const modalCaseType = document.getElementById("modalCaseType");
const modalBody = document.getElementById("modalBody");

// Initialize
document.addEventListener("DOMContentLoaded", () => {
  displayAccountId.textContent = currentAccountId;
  inputAccountId.value = currentAccountId;
  inputApiKey.value = currentApiKey;

  setupEventListeners();
  loadAll();
});

function setupEventListeners() {
  btnRefresh.addEventListener("click", () => loadAll());
  btnSeedDemo.addEventListener("click", () => handleSeedDemo());
  btnCloseBanner.addEventListener("click", () => demoBanner.classList.add("hidden"));

  // Config modal
  btnConfig.addEventListener("click", () => configModal.classList.remove("hidden"));
  btnCloseConfig.addEventListener("click", () => configModal.classList.add("hidden"));
  btnSaveConfig.addEventListener("click", () => {
    currentAccountId = inputAccountId.value.trim() || "acc_test_tenant";
    currentApiKey = inputApiKey.value.trim() || "test_internal_key";
    localStorage.setItem("ariv_account_id", currentAccountId);
    localStorage.setItem("ariv_api_key", currentApiKey);
    displayAccountId.textContent = currentAccountId;
    configModal.classList.add("hidden");
    loadAll();
  });

  // Case modal close
  btnCloseModal.addEventListener("click", () => caseModal.classList.add("hidden"));
  caseModal.addEventListener("click", (e) => {
    if (e.target === caseModal) caseModal.classList.add("hidden");
  });

  // Filters
  document.querySelectorAll(".filter-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".filter-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentFilter = btn.dataset.filter;
      renderCasesTable();
    });
  });

  // Demo scenario cards
  document.querySelectorAll(".scenario-box").forEach((box) => {
    box.addEventListener("click", () => {
      const scenario = box.dataset.scenario;
      const matched = cachedCases.find((c) => c.scenario === scenario || (c.context && c.context.scenario === scenario));
      if (matched) {
        openCaseModal(matched.case_id || matched.id);
      } else {
        // If not loaded, seed and open
        handleSeedDemo().then(() => {
          const m = cachedCases.find((c) => c.scenario === scenario || (c.context && c.context.scenario === scenario));
          if (m) openCaseModal(m.case_id || m.id);
        });
      }
    });
  });
}

/**
 * Compute HMAC-SHA256 signature using browser native Web Crypto API.
 */
async function computeHmacSha256(message, keyStr) {
  const enc = new TextEncoder();
  const keyData = enc.encode(keyStr);
  const msgData = enc.encode(message);

  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    keyData,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const signature = await crypto.subtle.sign("HMAC", cryptoKey, msgData);
  return Array.from(new Uint8Array(signature))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * Return authenticated headers matching backend HMAC verification.
 */
async function getAuthHeaders() {
  const signature = await computeHmacSha256(currentAccountId, currentApiKey);
  return {
    "X-Account-ID": currentAccountId,
    "X-Signature": signature,
    "Content-Type": "application/json",
  };
}

function formatInrMinor(minorUnits) {
  const val = (Number(minorUnits) || 0) / 100;
  return "₹" + val.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/**
 * Load dashboard and case list concurrently.
 */
async function loadAll() {
  try {
    await Promise.all([loadDashboardMetrics(), loadCases()]);
  } catch (err) {
    console.error("Failed to load dashboard data:", err);
  }
}

/**
 * Fetch and render KPIs, Funnel, and Action Analytics.
 */
async function loadDashboardMetrics() {
  try {
    const headers = await getAuthHeaders();
    const res = await fetch("/v1/recovery/dashboard", { headers });
    if (!res.ok) {
      if (res.status === 401) {
        console.warn("HMAC authentication failed for account:", currentAccountId);
      }
      return;
    }
    const data = await res.json();

    // KPIs
    const kpis = data.kpis || {};
    document.getElementById("kpiRevenueAtRisk").textContent = formatInrMinor(kpis.revenue_at_risk);
    document.getElementById("kpiEligibleRevenue").textContent = formatInrMinor(kpis.eligible_recovery);
    document.getElementById("kpiAttemptedRevenue").textContent = formatInrMinor(kpis.attempted_recovery);
    document.getElementById("kpiRecoveredRevenue").textContent = formatInrMinor(kpis.recovered_revenue);
    document.getElementById("kpiIncrementalEstimate").textContent = formatInrMinor(kpis.estimated_incremental_recovery);
    document.getElementById("kpiRecoveryRate").textContent = (kpis.recovery_rate_pct || 0).toFixed(1) + "%";

    // Funnel
    renderFunnel(data.funnel || []);

    // Action Performance Table
    renderActionPerf(data.action_performance || []);
  } catch (e) {
    console.error("Error loading dashboard metrics:", e);
  }
}

function renderFunnel(funnelSteps) {
  const container = document.getElementById("funnelContainer");
  if (!funnelSteps || funnelSteps.length === 0) {
    container.innerHTML = '<div class="funnel-loading">No funnel records yet.</div>';
    return;
  }

  const maxAmount = Math.max(...funnelSteps.map((s) => s.amount || 0), 1);
  let html = "";

  funnelSteps.forEach((step, idx) => {
    const pct = Math.max(12, Math.round(((step.amount || 0) / maxAmount) * 100));
    const isEstimate = step.badge === "ESTIMATE";
    const isRecovered = step.stage === "Recovered";

    const stepClass = isEstimate ? "funnel-step step-estimate" : isRecovered ? "funnel-step step-recovered" : "funnel-step";
    const badgeClass = isEstimate ? "badge badge-estimate" : "badge badge-observed";

    html += `
      <div class="${stepClass}">
        <div class="funnel-step-bar" style="width: ${pct}%"></div>
        <div class="funnel-step-content">
          <div class="funnel-step-left">
            <span class="funnel-index">${idx + 1}</span>
            <span class="funnel-stage-name">${step.stage}</span>
            <span class="${badgeClass}">${step.badge}</span>
          </div>
          <div class="funnel-step-right">
            <span class="funnel-count">${step.count} cases</span>
            <span class="funnel-amount">${formatInrMinor(step.amount)}</span>
          </div>
        </div>
      </div>
    `;
  });

  container.innerHTML = html;
}

function renderActionPerf(actions) {
  const tbody = document.getElementById("actionPerfBody");
  if (!actions || actions.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="text-center">No action executions recorded yet.</td></tr>';
    return;
  }

  let html = "";
  actions.forEach((a) => {
    html += `
      <tr>
        <td class="font-mono"><strong>${a.action_type}</strong></td>
        <td>${a.attempts}</td>
        <td><span class="text-emerald font-mono">${a.succeeded}</span></td>
        <td><strong>${(a.win_rate_pct || 0).toFixed(1)}%</strong></td>
        <td class="font-mono text-emerald"><strong>${formatInrMinor(a.recovered_amount)}</strong></td>
      </tr>
    `;
  });
  tbody.innerHTML = html;
}

/**
 * Fetch and render authoritative cases from PostgreSQL.
 */
async function loadCases() {
  try {
    const headers = await getAuthHeaders();
    const res = await fetch("/v1/recovery/cases?limit=50", { headers });
    if (!res.ok) return;
    cachedCases = await res.json();
    renderCasesTable();
  } catch (e) {
    console.error("Error loading cases:", e);
  }
}

function renderCasesTable() {
  const tbody = document.getElementById("casesTableBody");
  let filtered = cachedCases;
  if (currentFilter !== "ALL") {
    filtered = cachedCases.filter((c) => c.status === currentFilter);
  }

  if (!filtered || filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" class="text-center">No recovery cases found for filter [${currentFilter}].</td></tr>`;
    return;
  }

  let html = "";
  filtered.forEach((c) => {
    const cid = c.case_id || c.id;
    const shortId = cid.substring(0, 8) + "...";
    const statusClass = c.status === "RECOVERED" ? "chip-success" : c.status === "FAILED" ? "chip-danger" : "chip-info";
    const dateStr = c.created_at ? new Date(c.created_at).toLocaleTimeString() : "-";

    html += `
      <tr>
        <td>
          <button class="case-id-btn" onclick="openCaseModal('${cid}')">${shortId}</button>
        </td>
        <td><span class="tag">${c.domain}</span></td>
        <td>${c.case_type}</td>
        <td class="font-mono"><strong>${formatInrMinor(c.amount_minor)}</strong></td>
        <td><span class="chip ${statusClass}">${c.status}</span></td>
        <td><span class="font-mono">${c.outcome_status}</span></td>
        <td><span class="tag tag-blue">${c.recovery_source}</span></td>
        <td class="font-mono">${dateStr}</td>
        <td>
          <button class="btn btn-secondary" onclick="openCaseModal('${cid}')" style="padding: 4px 8px; font-size: 11px;">
            Inspect
          </button>
        </td>
      </tr>
    `;
  });

  tbody.innerHTML = html;
}

/**
 * Fetch full case aggregation and display details modal.
 */
async function openCaseModal(caseId) {
  try {
    const headers = await getAuthHeaders();
    const res = await fetch(`/v1/recovery/cases/${caseId}/full`, { headers });
    if (!res.ok) {
      alert("Failed to load case detail.");
      return;
    }
    const data = await res.json();

    const c = data.case || {};
    const cl = data.classification || {};
    const d = data.decision || {};
    const ex = data.execution || {};
    const r = data.recovery || {};
    const m = data.measurement || {};
    const timeline = data.timeline || [];
    const similar = data.similar_cases || [];

    // Header info
    modalCaseId.textContent = c.id;
    modalDomain.textContent = c.domain;
    modalStatus.textContent = c.status;
    modalStatus.className = "case-status-badge " + (c.status.toLowerCase());
    modalCaseType.textContent = c.case_type;

    const isPolicyApproved = d.policy_status === "APPROVED";
    const isUnknownState = ex.is_unknown;

    // Construct body
    let bodyHtml = `
      <!-- ROW 1: CASE FINANCIALS & FAILURE CLASSIFICATION -->
      <div class="detail-grid">
        <div class="detail-pane">
          <div class="pane-title">
            <span>Authoritative Case Ledger</span>
            <span class="badge badge-observed">PostgreSQL</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Transaction Amount</span>
            <span class="meta-val font-mono">${formatInrMinor(c.amount_minor)}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Settled Recovery</span>
            <span class="meta-val font-mono text-emerald">${formatInrMinor(r.recovered_amount_minor)}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Recovery Source</span>
            <span class="meta-val"><span class="chip chip-info">${r.recovery_source}</span></span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Attribution Decision</span>
            <span class="meta-val">${r.attribution_decision || "N/A"}</span>
          </div>
        </div>

        <div class="detail-pane">
          <div class="pane-title">
            <span>Gateway Failure Intelligence</span>
            <span class="badge badge-observed">Classified</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Failure Category</span>
            <span class="meta-val"><strong>${cl.failure_category}</strong></span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Retryability</span>
            <span class="meta-val">${cl.retryability}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Recoverability</span>
            <span class="meta-val">${cl.recoverability}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Taxonomy Version</span>
            <span class="meta-val font-mono">${cl.taxonomy_version}</span>
          </div>
        </div>
      </div>

      <!-- ROW 2: SAFETY BOUNDARY (AI DECISION VS DETERMINISTIC POLICY) -->
      <div class="detail-pane">
        <div class="pane-title">
          <span>ARIV Decision & Deterministic Safety Boundary</span>
          <span class="badge badge-observed">${d.policy_version}</span>
        </div>
        <div class="detail-grid" style="margin-bottom: 12px;">
          <div>
            <div class="meta-row">
              <span class="meta-label">AI Proposed Action</span>
              <span class="meta-val font-mono">${d.proposed_action}</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">AI Confidence Score</span>
              <span class="meta-val font-mono text-blue">${((d.ai_confidence || 0) * 100).toFixed(0)}%</span>
            </div>
          </div>
          <div>
            <div class="meta-row">
              <span class="meta-label">Autonomy Level</span>
              <span class="meta-val">${d.autonomy_level}</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">Baseline Action</span>
              <span class="meta-val font-mono">${d.baseline_action}</span>
            </div>
          </div>
        </div>

        <div class="policy-box ${isPolicyApproved ? 'approved' : 'rejected'}">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
            <span class="policy-status-badge ${isPolicyApproved ? 'approved' : 'rejected'}">
              POLICY EVALUATION: ${d.policy_status}
            </span>
            <span style="font-size: 11px; color: var(--text-dim);">Hard Gate (Zero LLM Bypass)</span>
          </div>
          <div style="font-size: 12px; color: #e2e8f0;">
            ${d.rejection_reason ? `<strong>Blocked:</strong> ${d.rejection_reason}` : '<strong>Approved:</strong> Action is retriable and conforms to tenant rate and safety policies.'}
          </div>
        </div>
      </div>

      <!-- ROW 3: EXECUTION STATUS & RECONCILIATION -->
      <div class="detail-grid">
        <div class="detail-pane">
          <div class="pane-title">
            <span>Durable Execution & Provider Status</span>
            <span class="badge badge-observed">${ex.provider}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Action Dispatched</span>
            <span class="meta-val font-mono">${ex.action_type}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Provider Request ID</span>
            <span class="meta-val font-mono">${ex.provider_request_id || "None (Action Blocked)"}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Attempts Count</span>
            <span class="meta-val">${ex.attempt_count}</span>
          </div>
          ${isUnknownState ? `
            <div style="margin-top: 8px; padding: 8px 10px; background: rgba(245, 158, 11, 0.1); border-left: 3px solid var(--amber); font-size: 11px; color: #fbbf24;">
              ⚠️ <strong>UNKNOWN State Detected:</strong> Execution attempt timed out. Safe reconciliation worker scheduled to query provider ledger before re-dispatch.
            </div>
          ` : ''}
        </div>

        <!-- ROW 4: INCREMENTAL MEASUREMENT ESTIMATE -->
        <div class="detail-pane">
          <div class="pane-title">
            <span>Attribution & Incremental Valuation</span>
            <span class="badge badge-estimate">ESTIMATE</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Treatment Recovery (Actual)</span>
            <span class="meta-val font-mono text-emerald">${formatInrMinor(m ? m.treatment_recovery_minor : 0)}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Estimated Counterfactual Baseline</span>
            <span class="meta-val font-mono">${formatInrMinor(m ? m.estimated_control_recovery_minor : 0)}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Net Incremental Lift</span>
            <span class="meta-val font-mono text-amber"><strong>${formatInrMinor(m ? m.incremental_recovery_minor : 0)}</strong></span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Baseline Valuation Method</span>
            <span class="meta-val" style="font-size: 11px;">${m ? m.baseline_method : "N/A"}</span>
          </div>
        </div>
      </div>

      <!-- AUDIT TIMELINE -->
      <div class="detail-pane">
        <div class="pane-title">
          <span>Cryptographic Audit Trail & State Timeline</span>
          <span class="badge badge-observed">${timeline.length} Steps</span>
        </div>
        <div class="timeline-wrap">
    `;

    timeline.forEach((item) => {
      const isCompleted = item.status === "COMPLETED";
      const isFailed = item.status === "FAILED";
      const isUnknown = item.status === "UNKNOWN";
      const dotClass = isUnknown ? "unknown" : isFailed ? "failed" : isCompleted ? "completed" : "";

      bodyHtml += `
        <div class="timeline-item">
          <div class="timeline-dot ${dotClass}"></div>
          <div class="timeline-header">
            <span>${item.stage}</span>
            <span class="timeline-time">${new Date(item.timestamp).toLocaleTimeString()}</span>
          </div>
          <div class="timeline-desc">${item.description}</div>
        </div>
      `;
    });

    bodyHtml += `
        </div>
      </div>

      <!-- QDRANT SIMILAR CASES (TENANT ISOLATED) -->
      <div class="detail-pane">
        <div class="pane-title">
          <span>Qdrant Vector Memory — Similar Recovery Patterns</span>
          <span class="badge" style="background: rgba(168, 85, 247, 0.15); color: var(--purple); border: 1px solid rgba(168, 85, 247, 0.3);">
            Tenant-Isolated Cosine
          </span>
        </div>
        <p style="font-size: 11px; color: var(--text-dim);">Historical recovery precedents indexed in Qdrant using 768-dimensional semantic embeddings.</p>
        <div class="similar-grid">
    `;

    if (similar.length === 0) {
      bodyHtml += '<div style="font-size: 12px; color: var(--text-dim); padding: 10px 0;">No historical memory vectors matching this failure pattern yet.</div>';
    } else {
      similar.forEach((sim, idx) => {
        bodyHtml += `
          <div class="similar-card">
            <div class="similar-card-header">Pattern #${idx + 1}: ${sim.failure_category}</div>
            <div>Action: <strong>${sim.action_type}</strong></div>
            <div>Outcome: <span class="text-emerald">${sim.outcome_status}</span></div>
            <div style="margin-top: 4px; color: var(--text-dim); font-size: 10px;">Source: ${sim.recovery_source}</div>
          </div>
        `;
      });
    }

    bodyHtml += `
        </div>
      </div>
    `;

    modalBody.innerHTML = bodyHtml;
    caseModal.classList.remove("hidden");
  } catch (e) {
    console.error("Error displaying case modal:", e);
  }
}

/**
 * 1-Click Sandbox Demo Runner.
 */
async function handleSeedDemo() {
  btnSeedDemo.disabled = true;
  btnSeedDemo.textContent = "Seeding Sandbox...";
  try {
    const headers = await getAuthHeaders();
    const res = await fetch("/v1/recovery/demo/seed", {
      method: "POST",
      headers,
    });
    if (!res.ok) {
      const err = await res.json();
      alert("Demo seed error: " + (err.detail || res.statusText));
      return;
    }
    const result = await res.json();
    demoBannerText.innerHTML = `<strong>Sandbox Scenarios Seeded:</strong> ${result.seeded_count || 4} cases available (Customer Link Success, Policy Rejection, Reconciled Gateway Timeout, and Organic Recovery).`;
    demoBanner.classList.remove("hidden");

    await loadAll();
  } catch (e) {
    console.error("Failed to seed demo:", e);
    alert("Could not trigger demo seed: " + e.message);
  } finally {
    btnSeedDemo.disabled = false;
    btnSeedDemo.innerHTML = "<span>⚡ Seed Sandbox Scenarios</span>";
  }
}
window.openCaseModal = openCaseModal;
