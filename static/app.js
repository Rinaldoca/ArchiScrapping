/**
 * ArchiScrapping — Frontend Application
 * Handles data fetching, rendering, filtering, charts, and interactions.
 */

// ─── State ──────────────────────────────────────────────────────────────────────
const state = {
    jobs: [],
    stats: null,
    filters: { cities: [], sources: [], job_types: [] },
    currentPage: 1,
    totalPages: 1,
    total: 0,
    loading: false,
    chartsInitialized: false,
    cityChart: null,
    sourceChart: null,
};

// ─── Debounce Utility ───────────────────────────────────────────────────────────
function debounce(fn, delay) {
    let timer;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), delay);
    };
}

// ─── Initialize ─────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    loadFilters();
    loadStats();
    loadJobs();
    checkScrapeStatus();
    checkTelegramStatus();

    // Filter event listeners
    document.getElementById("filter-search").addEventListener("input", debounce(applyFilters, 400));
    document.getElementById("filter-city").addEventListener("change", applyFilters);
    document.getElementById("filter-source").addEventListener("change", applyFilters);
    document.getElementById("filter-type").addEventListener("change", applyFilters);
    document.getElementById("filter-sort").addEventListener("change", applyFilters);
    document.getElementById("filter-salary").addEventListener("change", applyFilters);

    // Keyboard shortcut to close modal
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") closeModal();
    });

    // Periodically refresh status
    setInterval(checkScrapeStatus, 30000);
    // Refresh jobs every 5 minutes
    setInterval(() => { loadJobs(); loadStats(); }, 300000);
});

// ─── API Calls ──────────────────────────────────────────────────────────────────

async function loadJobs() {
    state.loading = true;
    showLoading(true);

    const params = new URLSearchParams();
    const search = document.getElementById("filter-search").value;
    const city = document.getElementById("filter-city").value;
    const source = document.getElementById("filter-source").value;
    const jobType = document.getElementById("filter-type").value;
    const sort = document.getElementById("filter-sort").value;
    const hasSalary = document.getElementById("filter-salary").checked;

    if (search) params.set("search", search);
    if (city) params.set("city", city);
    if (source) params.set("source", source);
    if (jobType) params.set("job_type", jobType);
    if (sort) params.set("sort", sort);
    if (hasSalary) params.set("has_salary", "true");
    params.set("page", state.currentPage);
    params.set("per_page", 30);

    try {
        const res = await fetch(`/api/jobs?${params}`);
        const data = await res.json();
        state.jobs = data.jobs;
        state.total = data.total;
        state.totalPages = data.total_pages;
        state.currentPage = data.page;
        renderJobs();
        renderPagination();
    } catch (err) {
        console.error("Failed to load jobs:", err);
        showEmptyState("Failed to load jobs. Please try again.");
    } finally {
        state.loading = false;
        showLoading(false);
    }
}

async function loadStats() {
    try {
        const res = await fetch("/api/stats");
        state.stats = await res.json();
        renderStats();
        renderCharts();
    } catch (err) {
        console.error("Failed to load stats:", err);
    }
}

async function loadFilters() {
    try {
        const res = await fetch("/api/filters");
        state.filters = await res.json();
        populateFilterDropdowns();
    } catch (err) {
        console.error("Failed to load filters:", err);
    }
}

async function checkScrapeStatus() {
    try {
        const res = await fetch("/api/scrape/status");
        const data = await res.json();
        updateScrapeStatus(data);
    } catch (err) {
        // Silently fail
    }
}

async function triggerScrape() {
    const btn = document.getElementById("btn-scrape");
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner" style="width:16px;height:16px;border-width:2px"></span> Scraping…`;

    try {
        await fetch("/api/scrape", { method: "POST" });
        updateScrapeStatus({ status: "running" });

        // Poll for completion
        const poll = setInterval(async () => {
            const res = await fetch("/api/scrape/status");
            const data = await res.json();
            updateScrapeStatus(data);
            if (data.status !== "running") {
                clearInterval(poll);
                btn.disabled = false;
                btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 11-6.219-8.56"/><polyline points="21 3 21 9 15 9"/></svg> Scrape Now`;
                // Reload data
                loadJobs();
                loadStats();
                loadFilters();
            }
        }, 5000);
    } catch (err) {
        console.error("Failed to trigger scrape:", err);
        btn.disabled = false;
        btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 11-6.219-8.56"/><polyline points="21 3 21 9 15 9"/></svg> Scrape Now`;
    }
}

// ─── Rendering ──────────────────────────────────────────────────────────────────

function renderStats() {
    if (!state.stats) return;
    const s = state.stats;

    document.getElementById("stat-total-value").textContent = (s.total_jobs || 0).toLocaleString();
    document.getElementById("stat-cities-value").textContent = (s.unique_cities || 0).toLocaleString();
    document.getElementById("stat-salary-value").textContent = s.avg_salary
        ? `€${Math.round(s.avg_salary).toLocaleString()}`
        : "—";
    document.getElementById("stat-multi-value").textContent = (s.multi_source_jobs || 0).toLocaleString();
}

function renderCharts() {
    if (!state.stats) return;

    const chartColors = [
        "#3b82f6", "#8b5cf6", "#10b981", "#f59e0b", "#f43f5e",
        "#06b6d4", "#ec4899", "#6366f1", "#14b8a6", "#eab308",
        "#ef4444", "#22c55e", "#a855f7", "#0ea5e9", "#f97316",
        "#84cc16", "#d946ef", "#2dd4bf", "#fb923c", "#64748b"
    ];

    // City chart
    const cityCtx = document.getElementById("chart-cities");
    if (cityCtx && state.stats.cities && state.stats.cities.length > 0) {
        if (state.cityChart) state.cityChart.destroy();
        state.cityChart = new Chart(cityCtx, {
            type: "bar",
            data: {
                labels: state.stats.cities.map(c => c.city),
                datasets: [{
                    label: "Jobs",
                    data: state.stats.cities.map(c => c.count),
                    backgroundColor: chartColors.slice(0, state.stats.cities.length).map(c => c + "40"),
                    borderColor: chartColors.slice(0, state.stats.cities.length),
                    borderWidth: 1.5,
                    borderRadius: 6,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: "rgba(17, 24, 39, 0.95)",
                        titleColor: "#f1f5f9",
                        bodyColor: "#94a3b8",
                        borderColor: "rgba(255,255,255,0.1)",
                        borderWidth: 1,
                        cornerRadius: 8,
                        padding: 12,
                    }
                },
                scales: {
                    x: {
                        ticks: { color: "#64748b", font: { size: 11 } },
                        grid: { display: false },
                        border: { display: false },
                    },
                    y: {
                        ticks: { color: "#64748b", font: { size: 11 } },
                        grid: { color: "rgba(255,255,255,0.04)" },
                        border: { display: false },
                    }
                },
            },
        });
    }

    // Source chart
    const sourceCtx = document.getElementById("chart-sources");
    if (sourceCtx && state.stats.sources && state.stats.sources.length > 0) {
        const sourceColors = {
            linkedin: "#0a66c2",
            indeed: "#2164f3",
            glassdoor: "#0caa41",
            google: "#4285f4",
            zip_recruiter: "#50c878",
        };
        if (state.sourceChart) state.sourceChart.destroy();
        state.sourceChart = new Chart(sourceCtx, {
            type: "doughnut",
            data: {
                labels: state.stats.sources.map(s => formatSourceName(s.source)),
                datasets: [{
                    data: state.stats.sources.map(s => s.count),
                    backgroundColor: state.stats.sources.map(s => (sourceColors[s.source] || "#64748b") + "60"),
                    borderColor: state.stats.sources.map(s => sourceColors[s.source] || "#64748b"),
                    borderWidth: 2,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "65%",
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: {
                            color: "#94a3b8",
                            padding: 16,
                            font: { size: 12 },
                            usePointStyle: true,
                            pointStyleWidth: 10,
                        },
                    },
                    tooltip: {
                        backgroundColor: "rgba(17, 24, 39, 0.95)",
                        titleColor: "#f1f5f9",
                        bodyColor: "#94a3b8",
                        borderColor: "rgba(255,255,255,0.1)",
                        borderWidth: 1,
                        cornerRadius: 8,
                        padding: 12,
                    }
                },
            },
        });
    }

    state.chartsInitialized = true;
}

function renderJobs() {
    const grid = document.getElementById("jobs-grid");
    const label = document.getElementById("jobs-count-label");

    if (!state.jobs || state.jobs.length === 0) {
        label.innerHTML = "No jobs found";
        grid.innerHTML = `
            <div class="empty-state">
                <h3>No jobs found</h3>
                <p>Try adjusting your filters or wait for the next scrape.</p>
            </div>
        `;
        return;
    }

    label.innerHTML = `Showing <strong>${state.jobs.length}</strong> of <strong>${state.total.toLocaleString()}</strong> jobs`;

    grid.innerHTML = state.jobs.map((job, i) => renderJobCard(job, i)).join("");
}

function renderJobCard(job, index) {
    const delay = Math.min(index * 40, 600);
    const sourceBadges = (job.source_names || [])
        .map(s => `<span class="source-badge source-badge--${s}">${formatSourceName(s)}</span>`)
        .join("");

    const multiTag = job.source_count > 1
        ? `<span class="multi-source-tag">📡 ${job.source_count} sources</span>`
        : "";

    const salary = job.salary_display
        ? `<div class="job-salary">${job.salary_display}</div>`
        : `<div class="job-salary job-salary--none">Salary not listed</div>`;

    const dateStr = formatDate(job.date_posted || job.first_seen);

    return `
        <article class="job-card" style="animation-delay: ${delay}ms" onclick="openJobModal(${index})" tabindex="0" role="button" aria-label="View details for ${escapeHtml(job.title)}">
            <div class="job-card-main">
                <div class="job-card-title">${escapeHtml(job.title)}</div>
                <div class="job-card-company">${escapeHtml(job.company || "Unknown Company")}</div>
                <div class="job-card-meta">
                    ${job.city ? `
                    <span class="job-meta-item">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z"/><circle cx="12" cy="10" r="3"/></svg>
                        ${escapeHtml(job.city)}${job.state ? `, ${escapeHtml(job.state)}` : ""}
                    </span>` : ""}
                    ${job.job_type ? `
                    <span class="job-meta-item">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2"/></svg>
                        ${formatJobType(job.job_type)}
                    </span>` : ""}
                    <span class="job-meta-item">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                        ${dateStr}
                    </span>
                </div>
            </div>
            <div class="job-card-right">
                ${salary}
                <div class="source-badges">
                    ${sourceBadges}
                    ${multiTag}
                </div>
            </div>
        </article>
    `;
}

function renderPagination() {
    const html = buildPaginationHTML();
    document.getElementById("pagination-top").innerHTML = html;
    document.getElementById("pagination-bottom").innerHTML = html;
}

function buildPaginationHTML() {
    if (state.totalPages <= 1) return "";

    let html = "";
    html += `<button class="page-btn" onclick="goToPage(${state.currentPage - 1})" ${state.currentPage <= 1 ? "disabled" : ""}>‹ Prev</button>`;

    const range = 2;
    const start = Math.max(1, state.currentPage - range);
    const end = Math.min(state.totalPages, state.currentPage + range);

    if (start > 1) {
        html += `<button class="page-btn" onclick="goToPage(1)">1</button>`;
        if (start > 2) html += `<span style="color:var(--text-muted)">…</span>`;
    }

    for (let i = start; i <= end; i++) {
        html += `<button class="page-btn ${i === state.currentPage ? 'active' : ''}" onclick="goToPage(${i})">${i}</button>`;
    }

    if (end < state.totalPages) {
        if (end < state.totalPages - 1) html += `<span style="color:var(--text-muted)">…</span>`;
        html += `<button class="page-btn" onclick="goToPage(${state.totalPages})">${state.totalPages}</button>`;
    }

    html += `<button class="page-btn" onclick="goToPage(${state.currentPage + 1})" ${state.currentPage >= state.totalPages ? "disabled" : ""}>Next ›</button>`;

    return html;
}

function populateFilterDropdowns() {
    const citySelect = document.getElementById("filter-city");
    const sourceSelect = document.getElementById("filter-source");
    const typeSelect = document.getElementById("filter-type");

    // Preserve current selections
    const currentCity = citySelect.value;
    const currentSource = sourceSelect.value;
    const currentType = typeSelect.value;

    // Cities
    citySelect.innerHTML = `<option value="">All Cities</option>`;
    (state.filters.cities || []).forEach(city => {
        citySelect.innerHTML += `<option value="${escapeHtml(city)}" ${city === currentCity ? "selected" : ""}>${escapeHtml(city)}</option>`;
    });

    // Sources
    sourceSelect.innerHTML = `<option value="">All Sources</option>`;
    (state.filters.sources || []).forEach(source => {
        sourceSelect.innerHTML += `<option value="${escapeHtml(source)}" ${source === currentSource ? "selected" : ""}>${formatSourceName(source)}</option>`;
    });

    // Job types
    typeSelect.innerHTML = `<option value="">All Types</option>`;
    (state.filters.job_types || []).forEach(jt => {
        typeSelect.innerHTML += `<option value="${escapeHtml(jt)}" ${jt === currentType ? "selected" : ""}>${formatJobType(jt)}</option>`;
    });
}

function updateScrapeStatus(data) {
    const statusEl = document.getElementById("scrape-status");
    const dot = statusEl.querySelector(".status-dot");
    const text = statusEl.querySelector(".status-text");

    dot.className = "status-dot";

    if (data.status === "running") {
        dot.classList.add("status-running");
        text.textContent = "Scraping in progress…";
    } else if (data.status === "success") {
        text.textContent = `Last scrape: ${formatDate(data.finished_at)} — ${data.jobs_new || 0} new`;
    } else if (data.status === "failed") {
        dot.classList.add("status-error");
        text.textContent = "Last scrape failed";
    } else {
        text.textContent = "Waiting for first scrape…";
    }
}

// ─── Modal ──────────────────────────────────────────────────────────────────────

function openJobModal(index) {
    const job = state.jobs[index];
    if (!job) return;

    const modal = document.getElementById("job-modal");
    const body = document.getElementById("modal-body");

    const sourcesHTML = (job.sources || []).map(s => `
        <div class="modal-source-link">
            <span class="source-badge source-badge--${s.site_name}">${formatSourceName(s.site_name)}</span>
            ${s.site_url ? `<a href="${escapeHtml(s.site_url)}" target="_blank" rel="noopener">View on ${formatSourceName(s.site_name)} →</a>` : `<span style="color:var(--text-muted);font-size:0.8rem">No direct link</span>`}
        </div>
    `).join("");

    const descriptionText = job.description
        ? escapeHtml(job.description).substring(0, 3000)
        : "No description available.";

    body.innerHTML = `
        <h2 class="modal-title">${escapeHtml(job.title)}</h2>
        <p class="modal-company">${escapeHtml(job.company || "Unknown Company")}</p>

        <div class="modal-meta">
            ${job.city ? `
            <span class="modal-meta-item">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z"/><circle cx="12" cy="10" r="3"/></svg>
                ${escapeHtml(job.city)}${job.state ? `, ${escapeHtml(job.state)}` : ""}
            </span>` : ""}
            ${job.job_type ? `
            <span class="modal-meta-item">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2"/></svg>
                ${formatJobType(job.job_type)}
            </span>` : ""}
            <span class="modal-meta-item">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                Posted: ${formatDate(job.date_posted || job.first_seen)}
            </span>
            <span class="modal-meta-item">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                First seen: ${formatDate(job.first_seen)}
            </span>
        </div>

        ${job.salary_display ? `<div class="modal-salary">💰 ${job.salary_display}</div>` : ""}

        <div class="modal-sources">
            <h4>Found on ${job.source_count} source${job.source_count > 1 ? 's' : ''}</h4>
            <div class="modal-source-links">
                ${sourcesHTML}
            </div>
        </div>

        <div class="modal-description">
            <h4>Description</h4>
            <div class="modal-description-text">${descriptionText}</div>
        </div>
    `;

    modal.classList.add("active");
    document.body.style.overflow = "hidden";
}

function closeModal(event) {
    if (event && event.target !== event.currentTarget) return;
    const modal = document.getElementById("job-modal");
    modal.classList.remove("active");
    document.body.style.overflow = "";
}

// ─── Helpers ────────────────────────────────────────────────────────────────────

function applyFilters() {
    state.currentPage = 1;
    loadJobs();
}

function goToPage(page) {
    if (page < 1 || page > state.totalPages) return;
    state.currentPage = page;
    loadJobs();
    // Scroll to top of jobs
    document.getElementById("jobs-section").scrollIntoView({ behavior: "smooth", block: "start" });
}

function showLoading(show) {
    const el = document.getElementById("loading-state");
    if (!el) return;
    if (show && state.jobs.length === 0) {
        el.classList.remove("hidden");
    } else {
        el.classList.add("hidden");
    }
}

function showEmptyState(message) {
    const grid = document.getElementById("jobs-grid");
    grid.innerHTML = `
        <div class="empty-state">
            <h3>Oops!</h3>
            <p>${message}</p>
        </div>
    `;
}

function formatSourceName(name) {
    const map = {
        linkedin: "LinkedIn",
        indeed: "Indeed",
        glassdoor: "Glassdoor",
        google: "Google",
        zip_recruiter: "ZipRecruiter",
        bayt: "Bayt",
    };
    return map[name] || name;
}

function formatJobType(type) {
    const map = {
        fulltime: "Full-time",
        parttime: "Part-time",
        contract: "Contract",
        internship: "Internship",
        temporary: "Temporary",
    };
    return map[type] || type;
}

function formatDate(dateStr) {
    if (!dateStr) return "Unknown";
    try {
        const date = new Date(dateStr);
        const now = new Date();
        const diffMs = now - date;
        const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

        if (diffDays === 0) return "Today";
        if (diffDays === 1) return "Yesterday";
        if (diffDays < 7) return `${diffDays} days ago`;
        if (diffDays < 30) return `${Math.floor(diffDays / 7)} weeks ago`;

        return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
    } catch {
        return dateStr;
    }
}

function escapeHtml(text) {
    if (!text) return "";
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

// ─── Telegram Alerts & UI ──────────────────────────────────────────────────────

async function checkTelegramStatus() {
    try {
        const res = await fetch("/api/telegram/status");
        const data = await res.json();
        const btn = document.getElementById("btn-telegram");
        const text = document.getElementById("telegram-btn-text");
        if (!btn || !text) return;

        if (data.configured) {
            text.textContent = "Telegram Active";
            btn.title = "Telegram alerts active. Click to send a test alert.";
            btn.style.borderColor = "rgba(16, 185, 129, 0.4)";
            btn.style.color = "#10b981";
        } else {
            text.textContent = "Telegram Alert";
            btn.title = "Telegram not configured yet. Click for setup instructions.";
        }
    } catch (e) {
        console.warn("Could not check Telegram status:", e);
    }
}

async function testTelegram() {
    const btn = document.getElementById("btn-telegram");
    if (btn) btn.disabled = true;

    try {
        const res = await fetch("/api/telegram/test", { method: "POST" });
        const data = await res.json();
        if (res.ok && data.status === "ok") {
            showToast("✅ " + data.message);
            checkTelegramStatus();
        } else {
            alert(
                "Telegram Notifications Setup:\n\n" +
                (data.message || "Not configured") + "\n\n" +
                "To enable Telegram alerts:\n" +
                "1. Message @BotFather on Telegram to create a bot & copy the token\n" +
                "2. Message your bot and get your chat ID from @userinfobot\n" +
                "3. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in Railway or your .env file!"
            );
        }
    } catch (err) {
        alert("Failed to test Telegram: " + err.message);
    } finally {
        if (btn) btn.disabled = false;
    }
}

function showToast(message) {
    let toast = document.getElementById("app-toast");
    if (!toast) {
        toast = document.createElement("div");
        toast.id = "app-toast";
        toast.style.position = "fixed";
        toast.style.bottom = "24px";
        toast.style.right = "24px";
        toast.style.background = "rgba(16, 185, 129, 0.95)";
        toast.style.color = "#fff";
        toast.style.padding = "12px 20px";
        toast.style.borderRadius = "8px";
        toast.style.boxShadow = "0 8px 24px rgba(0,0,0,0.5)";
        toast.style.zIndex = "9999";
        toast.style.fontWeight = "500";
        toast.style.transition = "opacity 0.3s ease";
        document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.style.opacity = "1";
    setTimeout(() => { toast.style.opacity = "0"; }, 4000);
}

