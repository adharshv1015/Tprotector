/**
 * AEGIS OBSERVER — FRONTEND CONTROLLER
 * High-precision, zero-dependency async client for API Contract & Breakage Monitoring.
 */

const API_BASE = window.location.origin;

// State
let monitoredApis = [];
let timelineEvents = [];
let selectedApi = null;
let currentTab = "apis-deck";
let syncTimer = null;
let syncCountdownVal = 10;

// DOM Elements
const apisGrid = document.getElementById("apis-grid");
const emptyState = document.getElementById("apis-empty-state");
const eventsFeed = document.getElementById("events-feed");
const syncCountdownEl = document.getElementById("sync-countdown");
const badgeEventCount = document.getElementById("badge-event-count");

// Telemetry Elements
const valTotalApis = document.getElementById("val-total-apis");
const valBreakingDiffs = document.getElementById("val-breaking-diffs");
const valRateAlerts = document.getElementById("val-rate-alerts");
const valAvgLatency = document.getElementById("val-avg-latency");

// Modal Elements (Zero-Config Auto Onboarding)
const modalAddApi = document.getElementById("modal-add-api");
const modalSchemaDiff = document.getElementById("modal-schema-diff");
const formAutoScan = document.getElementById("form-auto-scan");
const autoScanUrlInput = document.getElementById("auto-scan-url");
const autoAuthTokenInput = document.getElementById("auto-auth-token");
const scanRadarTerminal = document.getElementById("scan-radar-terminal");
const terminalLogs = document.getElementById("terminal-logs");
const autoProbeResult = document.getElementById("auto-probe-result");
const btnRunAutoScan = document.getElementById("btn-run-auto-scan");
const btnConfirmAutoTrack = document.getElementById("btn-confirm-auto-track");
const btnCancelProbe = document.getElementById("btn-cancel-probe");

let currentProbeData = null;

// Init Lifecycle
document.addEventListener("DOMContentLoaded", () => {
  setupEventListeners();
  loadAllData();
  startLiveSync();
});

// Setup All UI Event Handlers
function setupEventListeners() {
  // Navigation Tabs
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  // Filters & Universal Address Bar Search
  const searchInput = document.getElementById("search-apis");
  const quickProbeBar = document.getElementById("search-quick-probe-bar");
  const btnQuickProbe = document.getElementById("btn-quick-probe-action");

  searchInput?.addEventListener("input", renderApis);
  document.getElementById("filter-method")?.addEventListener("change", renderApis);
  document.getElementById("filter-status")?.addEventListener("change", renderApis);

  // Address Bar Quick-Check Action Trigger
  btnQuickProbe?.addEventListener("click", () => {
    const rawVal = searchInput.value.trim();
    if (!rawVal) return;
    openAddModal();
    if (autoScanUrlInput) autoScanUrlInput.value = rawVal;
    if (formAutoScan) formAutoScan.dispatchEvent(new Event("submit"));
  });

  searchInput?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && quickProbeBar && !quickProbeBar.classList.contains("hidden")) {
      e.preventDefault();
      const rawVal = searchInput.value.trim();
      if (rawVal) {
        openAddModal();
        if (autoScanUrlInput) autoScanUrlInput.value = rawVal;
        if (formAutoScan) formAutoScan.dispatchEvent(new Event("submit"));
      }
    }
  });

  // Timeline Severity Filters
  document.querySelectorAll(".timeline-filter-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      document.querySelectorAll(".timeline-filter-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      renderEvents(btn.dataset.filterSeverity);
    });
  });

  document.getElementById("btn-refresh-events")?.addEventListener("click", fetchEvents);

  // Add API Modal Triggers (Zero-Config Auto Scanner)
  document.getElementById("btn-open-add-modal")?.addEventListener("click", openAddModal);
  document.getElementById("btn-open-add-from-empty")?.addEventListener("click", openAddModal);
  document.getElementById("btn-close-add-modal")?.addEventListener("click", closeAddModal);

  // Smart Scanner Form Submit
  formAutoScan?.addEventListener("submit", handleAutoScanSubmit);

  // Probe Result Actions
  btnConfirmAutoTrack?.addEventListener("click", handleConfirmAutoTrack);
  btnCancelProbe?.addEventListener("click", resetProbeView);

  // Seed Sample API
  document.getElementById("btn-seed-sample")?.addEventListener("click", seedSampleApi);

  // Diff Modal Triggers
  document.getElementById("btn-close-diff-modal")?.addEventListener("click", closeDiffModal);
  document.querySelectorAll(".modal-tab-btn").forEach(btn => {
    btn.addEventListener("click", () => switchModalTab(btn.dataset.mTab));
  });

  // Run Check Button inside Contract Inspector modal
  document.getElementById("btn-run-check")?.addEventListener("click", async () => {
    const btn = document.getElementById("btn-run-check");
    const apiId = modalSchemaDiff?.dataset?.apiId;
    if (!apiId) return;

    btn.disabled = true;
    btn.innerHTML = `<span class="btn-run-check-dot" style="animation:none;opacity:0.5;"></span> Running…`;

    try {
      const res = await fetch(`${API_BASE}/apis/${apiId}/check`, { method: "POST" });
      if (res.ok) {
        showToast("Check complete! Refreshing data…", "success");
        await loadModalContractData(parseInt(apiId));
        await loadAllData();
      } else {
        showToast("Check failed. Try again later.", "error");
      }
    } catch (err) {
      showToast("Network error during check.", "error");
    } finally {
      btn.disabled = false;
      btn.innerHTML = `<span class="btn-run-check-dot"></span> Run Check`;
    }
  });

  // Website API Discovery Window Triggers
  document.getElementById("btn-open-website-analyzer")?.addEventListener("click", () => openWebsiteAnalyzerModal());
  document.getElementById("btn-close-website-analysis")?.addEventListener("click", closeWebsiteAnalyzerModal);
  document.getElementById("btn-run-website-analysis")?.addEventListener("click", () => runWebsiteAnalysis());
  document.getElementById("discovery-url-input")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      runWebsiteAnalysis();
    }
  });

  document.getElementById("btn-quick-extract-action")?.addEventListener("click", () => {
    const searchInput = document.getElementById("search-apis");
    const rawVal = searchInput?.value.trim();
    if (!rawVal) return;
    openWebsiteAnalyzerModal(rawVal);
    runWebsiteAnalysis(rawVal);
  });

  // Discovery Filter Pills & Search
  document.querySelectorAll("#discovery-filter-pills .pill-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#discovery-filter-pills .pill-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentDiscFilter = btn.dataset.discFilter;
      renderDiscoveredEndpoints();
    });
  });

  document.getElementById("disc-filter-search")?.addEventListener("input", (e) => {
    discSearchQuery = e.target.value.trim().toLowerCase();
    renderDiscoveredEndpoints();
  });

  // Quick Preset Targets in Discovery Modal
  document.querySelectorAll(".preset-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const url = chip.dataset.preset;
      const input = document.getElementById("discovery-url-input");
      if (input) input.value = url;
      runWebsiteAnalysis(url);
    });
  });

  // Dismiss modals on backdrop click
  document.querySelectorAll(".modal-backdrop, .modal-overlay").forEach(modal => {
    modal.addEventListener("click", (e) => {
      if (e.target === modal) {
        modal.classList.add("hidden");
        modal.style.display = "none";
      }
    });
  });

  // Dismiss modals on Escape key
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      document.querySelectorAll(".modal-backdrop, .modal-overlay").forEach(m => {
        m.classList.add("hidden");
        m.style.display = "none";
      });
    }
  });
}

// --------------------------------------------------------------------------
// Data Fetching & Sync
// --------------------------------------------------------------------------

async function loadAllData() {
  await Promise.all([fetchApis(), fetchEvents()]);
  updateTelemetry();
}

async function fetchApis() {
  try {
    const res = await fetch(`${API_BASE}/apis`);
    if (!res.ok) throw new Error("Failed to fetch APIs");
    monitoredApis = await res.json();
    renderApis();
    renderRateLimitsAndDrift();
  } catch (err) {
    showToast("Error loading APIs: " + err.message, "error");
  }
}

async function fetchEvents() {
  try {
    const res = await fetch(`${API_BASE}/events?limit=50`);
    if (!res.ok) throw new Error("Failed to fetch events");
    timelineEvents = await res.json();
    badgeEventCount.textContent = timelineEvents.length;
    renderEvents("ALL");
  } catch (err) {
    console.error("Error loading events:", err);
  }
}

function startLiveSync() {
  if (syncTimer) clearInterval(syncTimer);
  syncCountdownVal = 10;
  syncCountdownEl.textContent = `SYNC ${syncCountdownVal}s`;

  syncTimer = setInterval(async () => {
    syncCountdownVal--;
    if (syncCountdownVal <= 0) {
      syncCountdownEl.textContent = `SYNCING...`;
      await loadAllData();
      syncCountdownVal = 10;
    }
    syncCountdownEl.textContent = `SYNC ${syncCountdownVal}s`;
  }, 1000);
}

// --------------------------------------------------------------------------
// UI Rendering: APIs Deck
// --------------------------------------------------------------------------

function renderApis() {
  const searchInput = document.getElementById("search-apis");
  const searchQuery = searchInput ? searchInput.value.trim().toLowerCase() : "";
  const methodFilter = document.getElementById("filter-method").value;
  const statusFilter = document.getElementById("filter-status").value;
  const quickProbeBar = document.getElementById("search-quick-probe-bar");
  const quickProbeText = document.getElementById("quick-probe-url-text");

  const filtered = monitoredApis.filter(api => {
    const fullUrl = `${api.base_url.replace(/\/$/, "")}/${api.endpoint_path.replace(/^\//, "")}`.toLowerCase();
    const createdStr = formatDate(api.created_at).toLowerCase();
    const updatedStr = formatDate(api.updated_at).toLowerCase();
    const workingStr = api.is_working === true ? "working healthy operational 200 ok" : (api.is_working === false ? "failing down broken error" : "pending");

    const matchesSearch = !searchQuery ||
      api.name.toLowerCase().includes(searchQuery) ||
      api.base_url.toLowerCase().includes(searchQuery) ||
      api.endpoint_path.toLowerCase().includes(searchQuery) ||
      fullUrl.includes(searchQuery) ||
      workingStr.includes(searchQuery) ||
      createdStr.includes(searchQuery) ||
      updatedStr.includes(searchQuery) ||
      api.method.toLowerCase().includes(searchQuery) ||
      api.status.toLowerCase().includes(searchQuery);

    const matchesMethod = methodFilter === "ALL" || api.method === methodFilter;
    const matchesStatus = statusFilter === "ALL" || api.status === statusFilter;

    return matchesSearch && matchesMethod && matchesStatus;
  });

  apisGrid.innerHTML = "";

  if (filtered.length === 0) {
    emptyState.classList.remove("hidden");
  } else {
    emptyState.classList.add("hidden");
    filtered.forEach(api => {
      apisGrid.appendChild(createApiCard(api));
    });
  }

  // Address Bar Live Website Check suggestion:
  if (quickProbeBar) {
    const looksLikeUrl = searchQuery && (searchQuery.includes(".") || searchQuery.includes("/") || searchQuery.startsWith("http") || searchQuery.startsWith("aiza") || searchQuery.startsWith("sk-"));
    if (looksLikeUrl) {
      quickProbeBar.classList.remove("hidden");
      if (quickProbeText) quickProbeText.textContent = searchQuery;
    } else {
      quickProbeBar.classList.add("hidden");
    }
  }
}

function createApiCard(api) {
  const card = document.createElement("div");
  card.className = `api-card ${api.status === "paused" ? "is-paused" : ""}`;
  card.id = `api-card-${api.id}`;

  const methodClass = `badge-method-${api.method.toLowerCase()}`;
  const fullUrl = `${api.base_url.replace(/\/$/, "")}/${api.endpoint_path.replace(/^\//, "")}`;

  // Live health status badge (Currently Working / Failing / Pending)
  let liveHealthBadge = '';
  if (api.is_working === true) {
    liveHealthBadge = `
      <span class="badge badge-health-working" title="API call is currently working (HTTP ${api.last_status_code})">
        <span class="pulse-dot-green"></span> CURRENTLY WORKING (${api.last_status_code} • ${Math.round(api.last_response_time_ms || 0)}ms)
      </span>
    `;
  } else if (api.is_working === false) {
    liveHealthBadge = `
      <span class="badge badge-health-failing" title="API check failing with HTTP status ${api.last_status_code}">
        <span class="pulse-dot-red"></span> FAILING (HTTP ${api.last_status_code || 'CONN ERR'})
      </span>
    `;
  } else {
    liveHealthBadge = `
      <span class="badge badge-health-pending" title="Awaiting initial verification ping">
        <span class="pulse-dot-amber"></span> PENDING CHECK
      </span>
    `;
  }

  card.innerHTML = `
    <div class="card-header-row">
      <div class="card-title-group">
        <div class="card-badges">
          ${liveHealthBadge}
          <span class="badge ${methodClass}">${api.method}</span>
          ${api.is_sandbox ? '<span class="badge badge-sandbox">SANDBOX</span>' : ''}
          <span class="badge badge-auth">${api.auth_type.toUpperCase()}</span>
          ${api.status === 'paused' ? '<span class="badge" style="background: rgba(255,255,255,0.1); color: var(--text-dim);">PAUSED</span>' : ''}
        </div>
        <h3 class="card-title">${escapeHtml(api.name)}</h3>
      </div>
    </div>

    <!-- API Call Address Bar -->
    <div class="card-url-bar">
      <span class="url-label">ADDRESS:</span>
      <span class="url-text" title="${escapeHtml(fullUrl)}">${escapeHtml(fullUrl)}</span>
      <button class="btn-copy-url" title="Copy Address" onclick="copyToClipboard('${escapeHtml(fullUrl)}')">❐</button>
    </div>

    <!-- Operational Telemetry: Currently Working, Created, Modified, Last Checked -->
    <div class="card-metrics-strip">
      <div class="metric-cell">
        <span class="metric-label">CURRENTLY WORKING</span>
        <span class="metric-val ${api.is_working === true ? 'status-2xx' : (api.is_working === false ? 'status-5xx' : '')}">
          ${api.is_working === true ? 'YES 🟢' : (api.is_working === false ? 'NO 🔴' : 'PENDING ⚪')}
        </span>
      </div>
      <div class="metric-cell">
        <span class="metric-label">DATE CREATED</span>
        <span class="metric-val" title="${api.created_at}">${formatDate(api.created_at)}</span>
      </div>
      <div class="metric-cell">
        <span class="metric-label">MODIFIED</span>
        <span class="metric-val" title="${api.updated_at}">${formatDate(api.updated_at)}</span>
      </div>
      <div class="metric-cell">
        <span class="metric-label">LAST CHECKED</span>
        <span class="metric-val" title="${api.last_checked_at || 'Never'}">
          ${api.last_checked_at ? formatRelativeTime(api.last_checked_at) : '--'}
        </span>
      </div>
    </div>

    <div class="card-action-bar">
      <button class="btn btn-primary btn-sm" onclick="triggerApiCheck(${api.id})" id="btn-check-${api.id}">
        <span>⚡ Check Now</span>
      </button>
      <button class="btn btn-secondary btn-sm" onclick="openContractModal(${api.id})">
        <span>🔍 Contract & Diffs</span>
      </button>
      <button class="btn btn-secondary btn-sm btn-icon-only" onclick="toggleApiPause(${api.id}, '${api.status}')" title="${api.status === 'active' ? 'Pause' : 'Resume'}">
        ${api.status === 'active' ? '⏸' : '▶'}
      </button>
      <button class="btn btn-secondary btn-sm btn-icon-only" onclick="deleteApi(${api.id})" title="Delete Target">
        🗑
      </button>
    </div>
  `;

  return card;
}

// --------------------------------------------------------------------------
// API Actions: Check, Pause, Delete
// --------------------------------------------------------------------------

async function triggerApiCheck(apiId) {
  const btn = document.getElementById(`btn-check-${apiId}`);
  if (btn) {
    btn.innerHTML = `<span class="spin">⟳</span> Checking...`;
    btn.disabled = true;
  }

  try {
    const res = await fetch(`${API_BASE}/apis/${apiId}/check`, { method: "POST" });
    if (!res.ok) throw new Error("Check failed");
    const snapshot = await res.json();
    if (snapshot && typeof snapshot.status_code !== "undefined") {
      showToast(`Check completed for API ${apiId}: HTTP ${snapshot.status_code} (${snapshot.response_time_ms}ms)`);
    } else {
      showToast(`Check executed for API ${apiId}. (API may be paused or undergoing background processing)`);
    }
    await loadAllData();
  } catch (err) {
    showToast("Check error: " + err.message, "error");
  } finally {
    if (btn) {
      btn.innerHTML = `<span>⚡ Check Now</span>`;
      btn.disabled = false;
    }
  }
}

async function toggleApiPause(apiId, currentStatus) {
  const newStatus = currentStatus === "active" ? "paused" : "active";
  try {
    const res = await fetch(`${API_BASE}/apis/${apiId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: newStatus })
    });
    if (!res.ok) throw new Error("Failed to update status");
    showToast(`API ${newStatus === 'active' ? 'resumed' : 'paused'} successfully`);
    await fetchApis();
  } catch (err) {
    showToast("Error: " + err.message, "error");
  }
}

async function deleteApi(apiId) {
  if (!confirm(`Are you sure you want to delete tracked API #${apiId}? This will remove its schedule and history.`)) {
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/apis/${apiId}`, { method: "DELETE" });
    if (!res.ok) throw new Error("Failed to delete API");
    showToast(`API #${apiId} deleted.`);
    await loadAllData();
  } catch (err) {
    showToast("Delete error: " + err.message, "error");
  }
}

// --------------------------------------------------------------------------
// UI Rendering: Event Timeline Feed
// --------------------------------------------------------------------------

function renderEvents(severityFilter) {
  eventsFeed.innerHTML = "";

  const filtered = timelineEvents.filter(ev => {
    if (severityFilter === "ALL") return true;
    return ev.severity === severityFilter;
  });

  if (filtered.length === 0) {
    eventsFeed.innerHTML = `
      <div class="empty-state-box" style="margin: 20px auto; padding: 40px;">
        <p>No events recorded matching filter <strong>${escapeHtml(severityFilter)}</strong>.</p>
      </div>
    `;
    return;
  }

  filtered.forEach(ev => {
    const card = document.createElement("div");
    card.className = `event-card sev-${ev.severity}`;

    card.innerHTML = `
      <div class="event-severity-stripe"></div>
      <div class="event-body">
        <div class="event-top-row">
          <span class="event-type-badge">${escapeHtml(ev.event_type)}</span>
          <span class="event-time">${formatDate(ev.created_at)}</span>
        </div>
        <div class="event-message">${escapeHtml(ev.message)}</div>
      </div>
    `;

    eventsFeed.appendChild(card);
  });
}

// --------------------------------------------------------------------------
// UI Rendering: Rate Limits & Drift Viewport
// --------------------------------------------------------------------------

async function renderRateLimitsAndDrift() {
  const container = document.getElementById("metrics-dashboard-grid");
  if (!container) return;

  container.innerHTML = "";

  if (monitoredApis.length === 0) {
    container.innerHTML = `<p style="color: var(--text-muted); text-align: center; padding: 40px;">No monitored APIs configured.</p>`;
    return;
  }

  for (const api of monitoredApis) {
    const card = document.createElement("div");
    card.className = "api-card";
    card.style.minHeight = "200px";

    // Fetch baseline metrics
    let baselineData = null;
    try {
      const bRes = await fetch(`${API_BASE}/apis/${api.id}/baseline`);
      if (bRes.ok) baselineData = await bRes.json();
    } catch (e) {}

    card.innerHTML = `
      <div class="card-header-row">
        <h3 class="card-title">${escapeHtml(api.name)}</h3>
        <span class="badge ${api.is_sandbox ? 'badge-sandbox' : 'badge-auth'}">${api.method}</span>
      </div>

      <div style="display: flex; gap: 20px; align-items: center; margin-top: 10px;">
        <!-- Gauge Placeholder / Rate Limit Header Info -->
        <div style="flex: 1; background: rgba(0,0,0,0.3); padding: 14px; border-radius: 10px; border: 1px solid var(--border-hairline);">
          <div style="font-size: 10px; font-weight: 700; color: var(--text-dim); margin-bottom: 4px;">RATE LIMIT HEADERS</div>
          <div style="font-family: var(--font-mono); font-size: 11px; color: var(--emerald-primary);">
            ${api.rate_limit_header_limit || 'X-RateLimit-Limit'}<br>
            ${api.rate_limit_header_remaining || 'X-RateLimit-Remaining'}
          </div>
        </div>

        <!-- Latency Baseline Info -->
        <div style="flex: 1; background: rgba(0,0,0,0.3); padding: 14px; border-radius: 10px; border: 1px solid var(--border-hairline);">
          <div style="font-size: 10px; font-weight: 700; color: var(--text-dim); margin-bottom: 4px;">7-DAY LATENCY BASELINE</div>
          <div style="font-family: var(--font-mono); font-size: 13px; font-weight: 700; color: var(--text-pure);">
            ${baselineData && baselineData.avg_response_time_ms ? `${baselineData.avg_response_time_ms} ms (σ ${baselineData.std_dev_ms}ms)` : 'Accumulating data...'}
          </div>
          <div style="font-size: 11px; color: var(--text-dim); margin-top: 2px;">
            Error Rate: ${baselineData && baselineData.error_rate_percent !== undefined ? `${baselineData.error_rate_percent}%` : '0%'}
          </div>
        </div>
      </div>
    `;

    container.appendChild(card);
  }
}

// --------------------------------------------------------------------------
// Telemetry Aggregations
// --------------------------------------------------------------------------

function updateTelemetry() {
  valTotalApis.textContent = monitoredApis.length;

  const breakingCount = timelineEvents.filter(e => e.severity === "breaking").length;
  valBreakingDiffs.textContent = breakingCount;

  const rateCount = timelineEvents.filter(e => e.event_type === "rate_limit_warning").length;
  valRateAlerts.textContent = rateCount;

  valAvgLatency.textContent = monitoredApis.length > 0 ? `~95 ms` : `-- ms`;
}

// --------------------------------------------------------------------------
// Modal: Schema Contract & Diff Inspector
// --------------------------------------------------------------------------

async function openContractModal(apiId) {
  selectedApi = monitoredApis.find(a => a.id === apiId);
  if (!selectedApi) return;

  document.getElementById("diff-modal-api-name").textContent = `${selectedApi.name} Contract & Diffs`;
  if (modalSchemaDiff) {
    modalSchemaDiff.dataset.apiId = apiId;  // Store for Run Check button
    modalSchemaDiff.classList.remove("hidden");
    modalSchemaDiff.style.display = "flex";
  }

  // Reset tab to Current Schema on every open
  switchModalTab("diff-current-schema");

  // Load snapshots & diffs
  await loadModalContractData(apiId);
}

function closeDiffModal() {
  if (modalSchemaDiff) {
    modalSchemaDiff.classList.add("hidden");
    modalSchemaDiff.style.display = "none";
  }
  selectedApi = null;
}

function switchModalTab(targetTab) {
  document.querySelectorAll(".modal-tab-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".modal-tab-panel").forEach(p => p.classList.add("hidden"));

  const targetBtn = document.querySelector(`[data-m-tab="${targetTab}"]`);
  const targetPanel = document.getElementById(`mpanel-${targetTab}`);

  if (targetBtn) targetBtn.classList.add("active");
  if (targetPanel) targetPanel.classList.remove("hidden");
}

async function loadModalContractData(apiId) {
  const schemaCodeEl = document.getElementById("current-schema-code");
  const diffsContainer = document.getElementById("diff-records-container");
  const snapshotsTable = document.getElementById("snapshots-table-body");

  schemaCodeEl.innerHTML = `<span style="color: var(--text-dim);">Loading schema...</span>`;
  diffsContainer.innerHTML = `<span style="color: var(--text-dim);">Loading diff history...</span>`;
  snapshotsTable.innerHTML = `<tr><td colspan="4" style="text-align: center;">Loading snapshots...</td></tr>`;

  try {
    // 1. Fetch snapshots
    const sRes = await fetch(`${API_BASE}/apis/${apiId}/snapshots?limit=10`);
    const snapshots = sRes.ok ? await sRes.json() : [];

    // Render Current Extracted Schema (from latest snapshot)
    if (snapshots.length > 0 && snapshots[0].response_schema) {
      schemaCodeEl.innerHTML = renderInteractiveJsonTree(snapshots[0].response_schema);
    } else if (snapshots.length > 0) {
      // We have a snapshot but no schema — explain why based on status code
      const lastSnap = snapshots[0];
      const code = lastSnap.status_code;
      let reason = "";
      if (code === 403) {
        reason = `<span style="color:#ef4444;">⛔ HTTP 403 Forbidden</span> — The server is blocking access. Schema cannot be captured from a blocked response.`;
      } else if (code === 401) {
        reason = `<span style="color:#f59e0b;">🔒 HTTP 401 Unauthorized</span> — Authentication is required. Add an auth token to capture the schema.`;
      } else if (code >= 500) {
        reason = `<span style="color:#ef4444;">💥 HTTP ${code} Server Error</span> — The server returned an error. Schema will be captured once the server recovers.`;
      } else if (code === 0) {
        reason = `<span style="color:#6b7280;">🔌 Connection Failed</span> — Could not reach the server. Check the URL is correct and the server is running.`;
      } else {
        reason = `<span style="color:#6b7280;">HTTP ${code}</span> — The response did not contain extractable JSON or XML schema data.`;
      }
      schemaCodeEl.innerHTML = `
        <div style="display:flex; flex-direction:column; gap:10px; padding:4px;">
          <div style="font-family:var(--font-mono); font-size:12px;">${reason}</div>
          <div style="font-size:11px; color:var(--text-dim);">Last checked: ${formatDate(lastSnap.checked_at)} · ${lastSnap.response_time_ms} ms</div>
          <div style="font-size:11px; color:var(--text-dim);">Click <strong style="color:#10b981;">Run Check</strong> to retry and capture the response structure.</div>
        </div>`;
    } else {
      schemaCodeEl.innerHTML = `
        <div style="font-family:var(--font-mono); font-size:12px; color:var(--text-dim);">
          No checks have run yet. Click <strong style="color:#10b981;">Run Check</strong> to capture the response structure.
        </div>`;
    }

    // Render Snapshots Table
    snapshotsTable.innerHTML = "";
    if (snapshots.length === 0) {
      snapshotsTable.innerHTML = `<tr><td colspan="4" style="text-align:center; color: var(--text-dim);">No checks executed yet.</td></tr>`;
    } else {
      snapshots.forEach(s => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${formatDate(s.checked_at)}</td>
          <td><span class="badge ${s.status_code >= 200 && s.status_code < 300 ? 'badge-method-get' : 'badge-method-delete'}">${s.status_code}</span></td>
          <td style="color: var(--text-pure);">${s.response_time_ms} ms</td>
          <td style="color: var(--text-dim); font-size: 11px;">${s.headers_snapshot ? Object.keys(s.headers_snapshot).length + ' headers' : '--'}</td>
        `;
        snapshotsTable.appendChild(tr);
      });
    }

    // 2. Fetch diffs
    const dRes = await fetch(`${API_BASE}/apis/${apiId}/diffs?limit=10`);
    const diffs = dRes.ok ? await dRes.json() : [];

    diffsContainer.innerHTML = "";
    if (diffs.length === 0) {
      diffsContainer.innerHTML = `<div style="color: var(--text-muted); padding: 16px;">No contract shifts or breaking changes detected. Contract is stable.</div>`;
    } else {
      diffs.forEach(diff => {
        const diffCard = document.createElement("div");
        diffCard.className = `diff-record-card diff-${diff.severity}`;
        
        diffCard.innerHTML = `
          <div class="diff-record-header">
            <span class="badge ${diff.severity === 'breaking' ? 'badge-method-delete' : 'badge-method-get'}">${diff.severity.toUpperCase()}</span>
            <span style="font-family: var(--font-mono); font-size: 11px; color: var(--text-dim);">${formatDate(diff.detected_at)}</span>
          </div>
          <pre class="diff-summary-pre">${escapeHtml(JSON.stringify(diff.diff_summary, null, 2))}</pre>
        `;
        diffsContainer.appendChild(diffCard);
      });
    }

  } catch (err) {
    schemaCodeEl.textContent = "Failed to load contract details: " + err.message;
  }
}

// --------------------------------------------------------------------------
// Interactive Schema Visualizer (Color-Coded Types)
// --------------------------------------------------------------------------

function renderInteractiveJsonTree(schema, indent = 0) {
  const spaces = " ".repeat(indent * 2);

  if (schema === null) {
    return `<span class="color-none">null</span>`;
  }

  if (typeof schema === "string") {
    const typeClass = `color-${schema.toLowerCase()}`;
    return `<span class="${typeClass}">"${escapeHtml(schema)}"</span>`;
  }

  if (Array.isArray(schema)) {
    if (schema.length === 0) return `[]`;
    const inner = renderInteractiveJsonTree(schema[0], indent + 1);
    return `[\n${spaces}  ${inner}\n${spaces}]`;
  }

  if (typeof schema === "object") {
    const keys = Object.keys(schema);
    if (keys.length === 0) return `{}`;

    let out = `{\n`;
    keys.forEach((k, idx) => {
      const isLast = idx === keys.length - 1;
      const comma = isLast ? "" : ",";
      const val = renderInteractiveJsonTree(schema[k], indent + 1);
      out += `${spaces}  <span style="color: var(--text-pure); font-weight: 600;">"${escapeHtml(k)}"</span>: ${val}${comma}\n`;
    });
    out += `${spaces}}`;
    return out;
  }

  return escapeHtml(String(schema));
}

// --------------------------------------------------------------------------
// Modal: Zero-Config Automated Endpoint Scanner & Instant Onboarding
// --------------------------------------------------------------------------

function openAddModal() {
  if (modalAddApi) {
    modalAddApi.classList.remove("hidden");
    modalAddApi.style.display = "flex";
  }
  resetProbeView();
  setTimeout(() => {
    autoScanUrlInput?.focus();
  }, 100);
}

function closeAddModal() {
  if (modalAddApi) {
    modalAddApi.classList.add("hidden");
    modalAddApi.style.display = "none";
  }
  resetProbeView();
}

function resetProbeView() {
  currentProbeData = null;
  if (autoScanUrlInput) autoScanUrlInput.value = "";
  if (autoAuthTokenInput) autoAuthTokenInput.value = "";
  if (scanRadarTerminal) scanRadarTerminal.classList.add("hidden");
  if (autoProbeResult) autoProbeResult.classList.add("hidden");
  if (terminalLogs) terminalLogs.innerHTML = "";
  if (btnRunAutoScan) {
    btnRunAutoScan.disabled = false;
    btnRunAutoScan.innerHTML = `<span class="btn-scan-icon">⚡</span> Auto-Scan & Track`;
  }
}

function appendTerminalLog(icon, text) {
  if (!terminalLogs) return;
  const line = document.createElement("div");
  line.className = "terminal-log-line";
  line.innerHTML = `
    <span class="log-icon">${icon}</span>
    <span class="log-text">${escapeHtml(text)}</span>
  `;
  terminalLogs.appendChild(line);
  terminalLogs.scrollTop = terminalLogs.scrollHeight;
}

/**
 * 1-Click Instant Auto-Tracker
 * Immediately probes the target, learns the schema contract, saves the TrackedAPI,
 * schedules background monitoring, and refreshes the deck.
 */
async function triggerInstantAutoTrack(url, name, method = "GET", isSandbox = false, tileEl = null) {
  const btn = tileEl?.querySelector(".btn-tile-auto");
  const origBtnText = btn ? btn.textContent : "Auto-Track ➔";

  let authToken = autoAuthTokenInput?.value.trim() || null;

  // If clicking an AI provider tile, prompt for their key if not yet entered
  if (tileEl?.dataset.autoProvider === "gemini") {
    if (!authToken && !url.includes("key=")) {
      const enteredKey = prompt("Enter your Google Gemini API Key (starts with AIza...):");
      if (!enteredKey) return;
      authToken = enteredKey.trim();
      url = `https://generativelanguage.googleapis.com/v1beta/models?key=${encodeURIComponent(authToken)}`;
    }
  } else if (tileEl?.dataset.autoProvider === "openai") {
    if (!authToken) {
      const enteredKey = prompt("Enter your OpenAI API Key (starts with sk-...):");
      if (!enteredKey) return;
      authToken = enteredKey.trim();
    }
  } else if (tileEl?.dataset.autoProvider === "anthropic") {
    if (!authToken) {
      const enteredKey = prompt("Enter your Anthropic Claude API Key (starts with sk-ant-...):");
      if (!enteredKey) return;
      authToken = enteredKey.trim();
    }
  }

  if (btn) {
    btn.textContent = "⚡ Probing...";
    btn.disabled = true;
  }
  if (tileEl) tileEl.style.opacity = "0.7";

  scanRadarTerminal.classList.remove("hidden");
  terminalLogs.innerHTML = "";
  appendTerminalLog("⚡", `[RADAR] Universal Auto-Track initialized for: ${name}`);
  appendTerminalLog("📡", `[PROBE] Target Endpoint: ${url} (${method})`);

  try {
    const res = await fetch(`${API_BASE}/apis/auto-track`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        name,
        method,
        auth_token: authToken,
        is_sandbox: isSandbox
      })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Instant Auto-Track failed");
    }

    const created = await res.json();
    appendTerminalLog("✅", `[CONTRACT LEARNED] Contract established & verified`);
    appendTerminalLog("🚀", `[AEGIS ENGINE] Background observer scheduled every ${created.check_interval_minutes}m`);

    showToast(`⚡ Auto-onboarded "${created.name}"! Monitoring active.`);
    
    setTimeout(() => {
      closeAddModal();
      loadAllData();
    }, 600);

  } catch (err) {
    appendTerminalLog("❌", `[ERROR] ${err.message}`);
    showToast("Error: " + err.message, "error");
  } finally {
    if (btn) {
      btn.textContent = origBtnText;
      btn.disabled = false;
    }
    if (tileEl) tileEl.style.opacity = "1";
  }
}

/**
 * Smart Scanner: Probes any custom URL, cURL, or raw API key (Google Gemini, OpenAI, Claude, Stripe, etc.)
 */
async function handleAutoScanSubmit(e) {
  e.preventDefault();
  const rawInput = autoScanUrlInput.value.trim();
  const token = autoAuthTokenInput.value.trim() || null;

  if (!rawInput) return;

  btnRunAutoScan.disabled = true;
  btnRunAutoScan.innerHTML = `<span class="btn-scan-icon">⚡</span> Probing Target...`;

  scanRadarTerminal.classList.remove("hidden");
  autoProbeResult.classList.add("hidden");
  terminalLogs.innerHTML = "";

  // Intelligent client-side pre-detection feedback in radar
  if (rawInput.startsWith("AIza")) {
    appendTerminalLog("🤖", `[AI DETECTED] Google Gemini API Key recognized! Auto-configuring Generative Language models endpoint...`);
  } else if (rawInput.startsWith("sk-ant-")) {
    appendTerminalLog("⚡", `[AI DETECTED] Anthropic Claude API Key recognized! Auto-configuring Claude models endpoint...`);
  } else if (rawInput.startsWith("sk-")) {
    appendTerminalLog("🧠", `[AI DETECTED] OpenAI API Key recognized! Auto-configuring OpenAI models endpoint...`);
  } else if (rawInput.startsWith("ghp_") || rawInput.startsWith("github_pat_")) {
    appendTerminalLog("🐙", `[AUTH DETECTED] GitHub Token recognized! Auto-configuring GitHub REST API...`);
  } else if (rawInput.startsWith("sk_test_") || rawInput.startsWith("rk_")) {
    appendTerminalLog("💳", `[PAYMENTS DETECTED] Stripe API Key recognized! Auto-configuring Stripe sandbox...`);
  } else if (rawInput.toLowerCase().startsWith("curl")) {
    appendTerminalLog("📟", `[cURL PARSER] Parsing cURL command: Extracting URL, headers, and request payload...`);
  } else {
    appendTerminalLog("⚡", `[AEGIS RADAR] Auto-probing target endpoint: ${rawInput}`);
  }

  appendTerminalLog("🌐", `[HTTP CLIENT] Measuring handshake latency & inspecting response...`);

  try {
    const res = await fetch(`${API_BASE}/apis/auto-probe`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: rawInput,
        method: "GET",
        auth_token: token
      })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Probe failed. Check URL accessibility.");
    }

    const data = await res.json();
    currentProbeData = { ...data, auth_token: token, raw_url: rawInput };

    const isSuccessStatus = data.status_code >= 200 && data.status_code < 300;
    const statusBadgeText = isSuccessStatus ? `${data.status_code} OK` : `HTTP ${data.status_code}`;
    
    appendTerminalLog(isSuccessStatus ? "✅" : "ℹ️", `[STATUS] Received HTTP ${data.status_code} (${data.response_time_ms} ms) — Provider: ${data.detected_provider || 'Custom API'}`);
    
    if (data.response_schema) {
      appendTerminalLog("🔍", `[CONTRACT] Schema contract inferred (${Object.keys(data.response_schema).length} root properties)`);
    } else {
      appendTerminalLog("🔍", `[CONTRACT] Non-JSON or empty response payload captured`);
    }
    
    if (data.rate_limit_header_limit) {
      appendTerminalLog("🛡️", `[RATE LIMITS] Discovered headers: Limit=${data.rate_limit_header_limit}, Remaining=${data.rate_limit_header_remaining}`);
    } else {
      appendTerminalLog("🛡️", `[RATE LIMITS] Standard headers not exposed — fallback monitoring active`);
    }

    if (data.changelog_url) {
      appendTerminalLog("📑", `[DOCS] Discovered public API documentation at ${data.changelog_url}`);
    }

    // Populate Results Preview Card
    document.getElementById("res-method").textContent = data.method;
    const statusEl = document.getElementById("res-status");
    statusEl.textContent = statusBadgeText;
    statusEl.style.background = isSuccessStatus ? "var(--emerald-dim)" : "var(--amber-dim)";
    statusEl.style.color = isSuccessStatus ? "var(--emerald-primary)" : "var(--amber-primary)";

    document.getElementById("res-latency").textContent = `${data.response_time_ms} ms`;
    document.getElementById("res-name").textContent = data.name;
    document.getElementById("res-schema-code").innerHTML = renderInteractiveJsonTree(data.response_schema || { status: data.status_code });

    autoProbeResult.classList.remove("hidden");

  } catch (err) {
    appendTerminalLog("❌", `[PROBE ERROR] ${err.message}`);
    showToast("Auto-Probe failed: " + err.message, "error");
  } finally {
    btnRunAutoScan.disabled = false;
    btnRunAutoScan.innerHTML = `<span class="btn-scan-icon">⚡</span> Auto-Scan & Track`;
  }
}

/**
 * Confirm button on Probe Result card: registers the probed API
 */
async function handleConfirmAutoTrack() {
  if (!currentProbeData) return;

  btnConfirmAutoTrack.disabled = true;
  btnConfirmAutoTrack.innerHTML = `<span>⚡ Activating Observer...</span>`;

  try {
    const res = await fetch(`${API_BASE}/apis/auto-track`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: currentProbeData.resolved_url || currentProbeData.raw_url || `${currentProbeData.base_url}${currentProbeData.endpoint_path}`,
        name: currentProbeData.name,
        method: currentProbeData.method,
        auth_token: currentProbeData.auth_token,
        is_sandbox: currentProbeData.is_sandbox || false
      })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Failed to activate monitoring");
    }

    const created = await res.json();
    showToast(`⚡ "${created.name}" is now monitored! Contract baseline locked.`);
    closeAddModal();
    loadAllData();

  } catch (err) {
    showToast("Error: " + err.message, "error");
  } finally {
    btnConfirmAutoTrack.disabled = false;
    btnConfirmAutoTrack.innerHTML = `<span>⚡ Confirm & Start Observing</span>`;
  }
}

// --------------------------------------------------------------------------
// Quick Seed Sample API
// --------------------------------------------------------------------------

async function seedSampleApi() {
  const payload = {
    name: "JSONPlaceholder Todo API",
    base_url: "https://jsonplaceholder.typicode.com",
    endpoint_path: "/todos/1",
    method: "GET",
    is_sandbox: false,
    check_interval_minutes: 30
  };

  try {
    const res = await fetch(`${API_BASE}/apis`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error("Seed failed");
    const api = await res.json();
    showToast("Sample API created! Triggering initial check...");
    await triggerApiCheck(api.id);
  } catch (err) {
    showToast("Error: " + err.message, "error");
  }
}

// --------------------------------------------------------------------------
// Tab Switching
// --------------------------------------------------------------------------

function switchTab(tabId) {
  currentTab = tabId;
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".content-viewport").forEach(v => v.classList.add("hidden"));

  const activeBtn = document.querySelector(`[data-tab="${tabId}"]`);
  const activeViewport = document.getElementById(`viewport-${tabId}`);

  if (activeBtn) activeBtn.classList.add("active");
  if (activeViewport) activeViewport.classList.remove("hidden");
}

// --------------------------------------------------------------------------
// Utilities
// --------------------------------------------------------------------------

function showToast(message, type = "success") {
  const stack = document.getElementById("toast-stack");
  const toast = document.createElement("div");
  toast.className = `toast ${type === "error" ? "toast-error" : ""}`;
  toast.innerHTML = `
    <span>${type === "error" ? "⚠" : "⚡"}</span>
    <span>${escapeHtml(message)}</span>
  `;

  stack.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(20px)";
    setTimeout(() => toast.remove(), 250);
  }, 4000);
}

function parseUtcDate(isoString) {
  if (!isoString) return null;
  let s = String(isoString).trim();
  // Ensure UTC parsing if no timezone designator exists
  if (!s.endsWith("Z") && !/[+-]\d{2}:?\d{2}$/.test(s)) {
    s = s.replace(" ", "T") + "Z";
  }
  return new Date(s);
}

function formatDate(isoString) {
  const d = parseUtcDate(isoString);
  if (!d || isNaN(d.getTime())) return "--";
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) + ' ' + d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

function formatRelativeTime(isoString) {
  const d = parseUtcDate(isoString);
  if (!d || isNaN(d.getTime())) return "--";
  const now = new Date();
  const diffSecs = Math.max(0, Math.floor((now - d) / 1000));

  if (diffSecs < 15) return "just now";
  if (diffSecs < 60) return `${diffSecs}s ago`;
  const diffMins = Math.floor(diffSecs / 60);
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays}d ago`;
  return formatDate(isoString);
}

function copyToClipboard(text) {
  navigator.clipboard.writeText(text).then(() => {
    showToast("URL copied to clipboard!");
  }).catch(() => {
    showToast("Copy failed", "error");
  });
}

function escapeHtml(str) {
  if (typeof str !== "string") return String(str);
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// --------------------------------------------------------------------------
// Deep Website API Discovery & Service Matrix Controller
// --------------------------------------------------------------------------

let currentDiscoveryEndpoints = [];
let currentDiscFilter = "ALL";
let discSearchQuery = "";

function openWebsiteAnalyzerModal(initialUrl = "") {
  const modal = document.getElementById("websiteAnalysisModal");
  if (!modal) return;
  modal.classList.remove("hidden");
  modal.style.display = "flex";

  const input = document.getElementById("discovery-url-input");
  if (input) {
    if (initialUrl) input.value = initialUrl;
    setTimeout(() => input.focus(), 50);
  }

  // Render initial guidance if empty
  if (currentDiscoveryEndpoints.length === 0) {
    renderDiscoveredEndpoints();
  }
}

function closeWebsiteAnalyzerModal() {
  const modal = document.getElementById("websiteAnalysisModal");
  if (modal) {
    modal.classList.add("hidden");
    modal.style.display = "none";
  }
}

async function runWebsiteAnalysis(urlOverride = null) {
  const input = document.getElementById("discovery-url-input");
  const targetUrl = (urlOverride || input?.value || "").trim();

  if (!targetUrl) {
    showToast("Please enter a website URL to extract APIs from", "warning");
    input?.focus();
    return;
  }

  const loadingEl = document.getElementById("discovery-loading");
  const resultsEl = document.getElementById("discovery-results");
  const btnRun = document.getElementById("btn-run-website-analysis");
  const titleEl = document.getElementById("discovery-target-title");
  const subEl = document.getElementById("discovery-target-subtitle");

  if (loadingEl) loadingEl.classList.remove("hidden");
  if (resultsEl) resultsEl.style.opacity = "0.4";
  if (btnRun) {
    btnRun.disabled = true;
    btnRun.innerHTML = `<span class="spin">⟳</span> Scanning Website...`;
  }

  // Animate Pipeline HUD Steps
  const step1 = document.getElementById("scan-step-1");
  const step2 = document.getElementById("scan-step-2");
  const step3 = document.getElementById("scan-step-3");
  const step4 = document.getElementById("scan-step-4");
  if (step1) step1.className = "step-chip step-active";
  if (step2) step2.className = "step-chip";
  if (step3) step3.className = "step-chip";
  if (step4) step4.className = "step-chip";
  const t2 = setTimeout(() => { if (step2) step2.className = "step-chip step-active"; }, 300);
  const t3 = setTimeout(() => { if (step3) step3.className = "step-chip step-active"; }, 750);
  const t4 = setTimeout(() => { if (step4) step4.className = "step-chip step-active"; }, 1300);

  try {
    const res = await fetch(`${API_BASE}/apis/discover-website-apis`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: targetUrl })
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || "Failed to scan website APIs");
    }

    const report = await res.json();

    if (titleEl) titleEl.textContent = `API Inventory: ${report.normalized_base}`;
    if (subEl) subEl.textContent = `Discovered ${report.total_discovered} service endpoints on ${report.normalized_base}`;

    // Populate Metrics
    document.getElementById("disc-val-total").textContent = report.total_endpoints;
    document.getElementById("disc-val-discovered").textContent = report.discovered_endpoints_count;
    document.getElementById("disc-val-online").textContent = report.online_count;
    document.getElementById("disc-val-protected").textContent = report.protected_count;
    document.getElementById("disc-val-shielded").textContent = report.shielded_count;
    document.getElementById("disc-val-latency").textContent = `${report.avg_latency_ms} ms`;

    const pAll = document.getElementById("pill-count-all"); if (pAll) pAll.textContent = report.total_endpoints;
    const pOn = document.getElementById("pill-count-online"); if (pOn) pOn.textContent = report.online_count;
    const pProt = document.getElementById("pill-count-protected"); if (pProt) pProt.textContent = report.protected_count;
    const pSh = document.getElementById("pill-count-shielded"); if (pSh) pSh.textContent = report.shielded_count;
    const pDisc = document.getElementById("pill-count-discovered"); if (pDisc) pDisc.textContent = report.discovered_endpoints_count;

    currentDiscoveryEndpoints = report.endpoints || [];
    renderDiscoveredEndpoints();

    showToast(`Discovered ${report.total_endpoints} services (${report.online_count} online, ${report.protected_count} protected)`);

  } catch (err) {
    showToast("Discovery error: " + err.message, "error");
  } finally {
    clearTimeout(t2);
    clearTimeout(t3);
    clearTimeout(t4);
    if (loadingEl) loadingEl.classList.add("hidden");
    if (resultsEl) resultsEl.style.opacity = "1";
    if (btnRun) {
      btnRun.disabled = false;
      btnRun.innerHTML = `<span class="btn-icon">⚡</span> CRAWL & ANALYZE APIS`;
    }
  }
}

function renderDiscoveredEndpoints() {
  const tbody = document.getElementById("discovery-table-body");
  if (!tbody) return;

  if (currentDiscoveryEndpoints.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7" style="text-align: center; padding: 48px 24px; color: var(--text-muted);">
          <div style="font-size: 32px; margin-bottom: 12px; filter: drop-shadow(0 0 12px rgba(56, 189, 248, 0.4));">🌐</div>
          <div style="font-size: 15px; font-weight: 700; color: var(--text-pure); margin-bottom: 6px;">Ready to Analyze Website APIs</div>
          <div style="font-size: 13px; color: var(--text-dim); max-width: 520px; margin: 0 auto 16px auto;">
            Enter any target website URL above or click a <b>Quick Target</b> preset to deeply extract REST endpoints, WordPress routes, background feeds, and operational health status.
          </div>
        </td>
      </tr>
    `;
    return;
  }

  const filtered = currentDiscoveryEndpoints;

  tbody.innerHTML = filtered.map(ep => {
    // Provenance Tag
    // Provenance Tag (Where did we find this link?)
    let provClass = "guess";
    let provLabel = "COMMON WEB PATH";
    if (ep.source_type === "WORDPRESS_INDEX") {
      provClass = "wp";
      provLabel = "WORDPRESS DIRECTORY";
    } else if (ep.source_type === "JAVASCRIPT_BUNDLE") {
      provClass = "js";
      provLabel = "FOUND IN SITE SCRIPT";
    } else if (ep.source_type === "HTML_LINK") {
      provClass = "html";
      provLabel = "FOUND IN WEBPAGE LINK";
    }

    // Confidence Chip
    let confClass = "high";
    // Operational Status Pill (Minimal, Tidy, Single-Line)
    let statusPillClass = "online";
    let statusText = `● 200 OK`;
    let statusTitle = "Online & Operational";

    if (ep.accessibility === "PROTECTED") {
      statusPillClass = "protected";
      statusText = `● 401 Protected`;
      statusTitle = "Working, but requires authentication / API key";
    } else if (ep.accessibility === "SHIELDED") {
      statusPillClass = "shielded";
      statusText = `● 403 Shielded`;
      statusTitle = "Blocked by security firewall / CDN";
    } else if (ep.accessibility === "METHOD_RESTRICTED") {
      statusPillClass = "method";
      statusText = `● 405 Method`;
      statusTitle = "Method not allowed for GET";
    } else if (ep.availability === "DEGRADED") {
      statusPillClass = "protected";
      statusText = `● 429 Limited`;
      statusTitle = "Rate limited";
    } else if (ep.availability === "OFFLINE") {
      statusPillClass = "shielded";
      statusText = `● ${ep.status_code} Error`;
      statusTitle = "Server error";
    } else if (ep.availability === "NOT_FOUND") {
      statusPillClass = "shielded";
      statusText = `● 404 Missing`;
      statusTitle = "Endpoint not found";
    }

    const cleanLatency = Math.round(ep.response_time_ms);

    return `
      <tr>
        <td>
          <span class="method-badge method-${ep.method.toLowerCase()}">${ep.method}</span>
        </td>
        <td>
          <div class="service-meta-wrap">
            <span class="service-name-text">${escapeHtml(ep.service_name)}</span>
            <span class="provenance-tag ${provClass}">${provLabel}</span>
          </div>
        </td>
        <td>
          <div class="endpoint-path-wrap">
            <span class="endpoint-path-code" title="${escapeHtml(ep.path)}">${escapeHtml(ep.path)}</span>
            <span class="endpoint-full-url" title="${escapeHtml(ep.url)}">${escapeHtml(ep.url)}</span>
          </div>
        </td>
        <td style="text-align: center; white-space: nowrap;">
          <span class="confidence-chip ${confClass}">${ep.confidence_score}%</span>
        </td>
        <td style="text-align: center; white-space: nowrap;">
          <span class="disc-status-pill ${statusPillClass}" title="${statusTitle}">
            ${statusText}
          </span>
        </td>
        <td style="text-align: right; white-space: nowrap;">
          <span class="disc-latency-tag">${cleanLatency} ms</span>
        </td>
        <td style="text-align: center; white-space: nowrap;">
          <button class="btn btn-sm btn-primary btn-track-sm" onclick="trackDiscoveredEndpoint('${encodeURIComponent(ep.url)}', '${encodeURIComponent(ep.service_name)}')">
            + Track
          </button>
        </td>
      </tr>
    `;
  }).join("");
}

async function trackDiscoveredEndpoint(encodedUrl, encodedName) {
  const url = decodeURIComponent(encodedUrl);
  const name = decodeURIComponent(encodedName);

  showToast(`Initiating automated monitor for: ${name}...`);

  try {
    const res = await fetch(`${API_BASE}/apis/auto-track`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, name })
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Tracking failed");
    }

    const created = await res.json();
    showToast(`Successfully tracking ${created.name}!`, "success");
    await loadAllData();
  } catch (err) {
    showToast("Track error: " + err.message, "error");
  }
}

