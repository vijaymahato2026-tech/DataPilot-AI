
/* =====================================================
   DATAPILOT AI — FRONTEND JAVASCRIPT
   Overview | Dataset Details | Visual Builder | Dashboards
===================================================== */

document.addEventListener("DOMContentLoaded", () => {
    const path = window.location.pathname;

    if (path === "/") {
        initializeOverview();
    } else if (path.startsWith("/dataset/")) {
        initializeDatasetPage();
    } else if (path.startsWith("/visual/")) {
        initializeVisualPage();
    } else if (path === "/dashboards") {
        initializeDashboards();
    }
});


/* =====================================================
   COMMON HELPERS
===================================================== */

async function apiRequest(url, options = {}) {
    const response = await fetch(url, options);
    let result;
    try {
        result = await response.json();
    } catch {
        throw new Error("The server returned an invalid response.");
    }
    if (!response.ok) {
        throw new Error(result.error || "Something went wrong.");
    }
    return result;
}

function showMessage(message, type = "success") {
    const el =
        document.getElementById("uploadMessage") ||
        document.getElementById("pageMessage");
    if (!el) { console.log(message); return; }
    el.textContent = message;
    el.className = `upload-message ${type}`;
}

function clearMessage() {
    const el =
        document.getElementById("uploadMessage") ||
        document.getElementById("pageMessage");
    if (el) { el.textContent = ""; el.className = "upload-message"; }
}

function formatNumber(value) {
    return Number(value || 0).toLocaleString();
}

function getDatasetId() {
    return window.location.pathname.split("/").filter(Boolean).pop();
}

function addOption(select, value, label) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
}

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value ?? "—";
}


/* =====================================================
   1. OVERVIEW PAGE
===================================================== */

function initializeOverview() {
    loadDatasets();
    const refreshBtn = document.getElementById("refreshButton");
    if (refreshBtn) refreshBtn.addEventListener("click", loadDatasets);
    initializeUpload();
}


/* ---- Load Datasets ---- */

async function loadDatasets() {
    try {
        const result = await apiRequest("/api/datasets");
        const datasets = result.datasets || [];

        setText("totalDatasets", result.total_datasets ?? datasets.length);

        let totalRows = 0;
        let totalColumns = 0;

        const table = document.getElementById("datasetTable");
        if (!table) return;

        table.innerHTML = "";

        if (datasets.length === 0) {
            table.innerHTML = `<tr><td colspan="5" class="empty-state">No datasets uploaded yet. Upload your first file above.</td></tr>`;
            setText("totalRows", "0");
            setText("totalColumns", "0");
            return;
        }

        datasets.forEach(dataset => {
            totalRows    += Number(dataset.total_rows    || 0);
            totalColumns += Number(dataset.total_columns || 0);

            const row = document.createElement("tr");

            const nameCell = document.createElement("td");
            const link = document.createElement("a");
            link.href = `/dataset/${encodeURIComponent(dataset.id)}`;
            link.className = "dataset-link";
            link.textContent = "▤ " + dataset.name;
            nameCell.appendChild(link);

            const rowsCell    = document.createElement("td");
            rowsCell.textContent = formatNumber(dataset.total_rows);

            const colsCell    = document.createElement("td");
            colsCell.textContent = formatNumber(dataset.total_columns);

            const dateCell    = document.createElement("td");
            dateCell.textContent = dataset.created_at
                ? new Date(dataset.created_at).toLocaleString()
                : "—";

            const actionCell  = document.createElement("td");

            const openBtn = document.createElement("button");
            openBtn.className = "table-action";
            openBtn.textContent = "Open";
            openBtn.addEventListener("click", () => {
                window.location.href = `/dataset/${encodeURIComponent(dataset.id)}`;
            });

            const delBtn = document.createElement("button");
            delBtn.className = "table-action delete";
            delBtn.textContent = "Delete";
            delBtn.addEventListener("click", () => deleteDataset(dataset.id));

            actionCell.append(openBtn, delBtn);
            row.append(nameCell, rowsCell, colsCell, dateCell, actionCell);
            table.appendChild(row);
        });

        setText("totalRows",    formatNumber(totalRows));
        setText("totalColumns", formatNumber(totalColumns));

    } catch (error) {
        console.error("Dataset loading error:", error);
        showMessage(error.message, "error");
    }
}


/* ---- File Upload ---- */

function initializeUpload() {
    const fileInput   = document.getElementById("fileInput");
    const browseBtn   = document.getElementById("browseButton");
    const uploadBtn   = document.getElementById("uploadButton");
    const dropZone    = document.getElementById("dropZone");

    if (!fileInput || !browseBtn || !uploadBtn) return;

    let selectedFile = null;

    browseBtn.addEventListener("click", () => fileInput.click());

    fileInput.addEventListener("change", () => {
        if (fileInput.files.length) selectFile(fileInput.files[0]);
    });

    function selectFile(file) {
        const allowed = ["csv", "xlsx", "json", "pdf"];
        const ext = file.name.split(".").pop().toLowerCase();
        if (!allowed.includes(ext)) {
            showMessage("Please select a CSV, XLSX, JSON or PDF file.", "error");
            return;
        }
        if (file.size > 25 * 1024 * 1024) {
            showMessage("File size must be less than 25 MB.", "error");
            return;
        }
        selectedFile = file;
        setText("selectedFile", "Selected: " + file.name);
        uploadBtn.disabled = false;
        clearMessage();
    }

    if (dropZone) {
        dropZone.addEventListener("dragover", e => {
            e.preventDefault();
            dropZone.classList.add("drag-over");
        });
        dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
        dropZone.addEventListener("drop", e => {
            e.preventDefault();
            dropZone.classList.remove("drag-over");
            const file = e.dataTransfer.files[0];
            if (file) { selectFile(file); fileInput.files = e.dataTransfer.files; }
        });
    }

    uploadBtn.addEventListener("click", async () => {
        if (!selectedFile) return;

        const formData = new FormData();
        formData.append("file", selectedFile);

        uploadBtn.disabled = true;

        const progressContainer = document.getElementById("progressContainer");
        const progressFill      = document.getElementById("progressFill");
        const uploadStatus      = document.getElementById("uploadStatus");

        if (progressContainer) progressContainer.hidden = false;
        if (progressFill)      progressFill.style.width = "0%";

        showMessage("Uploading your dataset…", "success");

        try {
            const result = await new Promise((resolve, reject) => {
                const xhr = new XMLHttpRequest();
                xhr.open("POST", "/api/datasets/upload");

                xhr.upload.addEventListener("progress", e => {
                    if (e.lengthComputable) {
                        const pct = Math.round((e.loaded / e.total) * 100);
                        if (progressFill)  progressFill.style.width = pct + "%";
                        if (uploadStatus)  uploadStatus.textContent = `Uploading… ${pct}%`;
                    }
                });

                xhr.onload = () => {
                    let data;
                    try { data = JSON.parse(xhr.responseText); }
                    catch { reject(new Error("Invalid server response.")); return; }
                    if (xhr.status >= 200 && xhr.status < 300) resolve(data);
                    else reject(new Error(data.error || "Upload failed."));
                };

                xhr.onerror = () => reject(new Error("Network error during upload."));
                xhr.send(formData);
            });

            if (progressFill) progressFill.style.width = "100%";
            if (uploadStatus) uploadStatus.textContent = "Upload complete!";

            showMessage(result.message || "Dataset uploaded successfully!", "success");

            selectedFile = null;
            fileInput.value = "";
            setText("selectedFile", "");
            uploadBtn.disabled = true;

            await loadDatasets();

        } catch (error) {
            showMessage(error.message, "error");
            if (uploadStatus) uploadStatus.textContent = "Upload failed.";
        } finally {
            uploadBtn.disabled = !selectedFile;
        }
    });
}


/* ---- Delete Dataset ---- */

async function deleteDataset(datasetId) {
    if (!confirm("Are you sure you want to delete this dataset? This cannot be undone.")) return;
    try {
        const result = await apiRequest(`/api/datasets/${encodeURIComponent(datasetId)}`, { method: "DELETE" });
        showMessage(result.message || "Dataset deleted successfully.", "success");
        await loadDatasets();
    } catch (error) {
        showMessage(error.message, "error");
    }
}


/* =====================================================
   2. DATASET DETAILS PAGE
===================================================== */

async function initializeDatasetPage() {
    const datasetId = getDatasetId();
    if (!datasetId) return;

    const visualBtn = document.getElementById("createVisualButton");
    if (visualBtn) visualBtn.href = `/visual/${encodeURIComponent(datasetId)}`;

    try {
        await Promise.all([
            loadDatasetProfile(datasetId),
            loadDatasetPreview(datasetId)
        ]);
    } catch (error) {
        console.error("Dataset page error:", error);
        showMessage(error.message, "error");
    }
}


/* ---- Dataset Profile ---- */

async function loadDatasetProfile(datasetId) {
    const result  = await apiRequest(`/api/datasets/${encodeURIComponent(datasetId)}/profile`);
    const profile = result.profile || result;
    const columns = profile.columns || [];

    setText("datasetTitle",
        result.dataset_name || result.name || profile.name || "Dataset Details");
    setText("datasetRows",
        formatNumber(profile.total_rows ?? profile.rows ?? result.total_rows));
    setText("datasetColumns",
        formatNumber(profile.total_columns ?? profile.column_count ?? columns.length));
    setText("datasetDuplicates",
        formatNumber(profile.duplicate_rows ?? profile.duplicates ?? 0));

    const table = document.getElementById("profileTable");
    if (!table) return;

    table.innerHTML = "";

    if (!columns.length) {
        table.innerHTML = `<tr><td colspan="4" class="empty-state">No column profile information available.</td></tr>`;
        return;
    }

    columns.forEach(col => {
        const row = document.createElement("tr");

        const name = document.createElement("td");
        name.textContent = col.name || col.column || "—";

        const type = document.createElement("td");
        type.textContent = col.field_type || col.dtype || col.type || "—";

        const missing = document.createElement("td");
        missing.textContent = formatNumber(col.missing ?? col.missing_values);

        const unique = document.createElement("td");
        unique.textContent = formatNumber(col.unique ?? col.unique_values);

        row.append(name, type, missing, unique);
        table.appendChild(row);
    });
}


/* ---- Dataset Preview ---- */

async function loadDatasetPreview(datasetId) {
    const result  = await apiRequest(`/api/datasets/${encodeURIComponent(datasetId)}/preview`);
    const columns = result.columns || result.headers || [];
    const rows    = result.rows    || result.data    || [];

    const head = document.getElementById("previewHead");
    const body = document.getElementById("previewBody");
    if (!head || !body) return;

    head.innerHTML = "";
    body.innerHTML = "";

    if (!columns.length) {
        body.innerHTML = `<tr><td class="empty-state">No preview data available.</td></tr>`;
        return;
    }

    const headerRow = document.createElement("tr");
    columns.forEach(col => {
        const th = document.createElement("th");
        th.textContent = col;
        headerRow.appendChild(th);
    });
    head.appendChild(headerRow);

    if (!rows.length) {
        body.innerHTML = `<tr><td colspan="${columns.length}" class="empty-state">No rows available.</td></tr>`;
        return;
    }

    rows.forEach(row => {
        const tr = document.createElement("tr");
        columns.forEach((col, idx) => {
            const td    = document.createElement("td");
            const value = Array.isArray(row) ? row[idx] : row[col];
            td.textContent = (value === null || value === undefined) ? "—" : String(value);
            tr.appendChild(td);
        });
        body.appendChild(tr);
    });
}


/* =====================================================
   3. VISUAL BUILDER PAGE
===================================================== */

async function initializeVisualPage() {
    const datasetId = getDatasetId();
    if (!datasetId) return;

    const datasetUrl = `/dataset/${encodeURIComponent(datasetId)}`;
    const backLink   = document.getElementById("backToDataset");
    const visualBack = document.getElementById("visualBackLink");
    if (backLink)   backLink.href   = datasetUrl;
    if (visualBack) visualBack.href = datasetUrl;

    try {
        await loadVisualFields(datasetId);
    } catch (error) {
        console.error("Visual fields error:", error);
        showMessage(error.message, "error");
    }

    const createBtn = document.getElementById("createChartButton");
    if (createBtn) createBtn.addEventListener("click", () => createChart(datasetId));
}


/* ---- Load Visual Fields ---- */

async function loadVisualFields(datasetId) {
    const result  = await apiRequest(`/api/datasets/${encodeURIComponent(datasetId)}/profile`);
    const profile = result.profile || result;
    const columns = profile.columns || [];

    const xAxis       = document.getElementById("xAxis");
    const yAxis       = document.getElementById("yAxis");
    const legendField = document.getElementById("legendField");
    const fieldTags   = document.getElementById("availableFields");

    if (!xAxis || !yAxis || !legendField) return;

    xAxis.innerHTML = "<option value=''>Choose a field</option>";
    yAxis.innerHTML = "<option value=''>Choose a field</option>";
    legendField.innerHTML = "<option value=''>None</option>";

    columns.forEach(col => {
        const name = col.name || col.column;
        if (!name) return;
        addOption(xAxis,       name, name);
        addOption(yAxis,       name, name);
        addOption(legendField, name, name);
    });

    setText("fieldCount", `${columns.length} fields available`);

    if (fieldTags) {
        fieldTags.innerHTML = "";
        columns.forEach(col => {
            const name = col.name || col.column;
            if (!name) return;
            const tag = document.createElement("span");
            tag.className = "field-tag";
            tag.textContent = `${name} · ${col.field_type || col.dtype || "field"}`;
            fieldTags.appendChild(tag);
        });
    }
}


/* ---- Create Chart ---- */

async function createChart(datasetId) {
    const chartType   = document.getElementById("chartType")?.value;
    const xAxis       = document.getElementById("xAxis")?.value;
    const yAxis       = document.getElementById("yAxis")?.value;
    const aggregation = document.getElementById("aggregation")?.value;
    const legendField = document.getElementById("legendField")?.value;

    const chartPreview = document.getElementById("chartPreview");
    const createBtn    = document.getElementById("createChartButton");

    if (!chartPreview) return;

    if (!xAxis) {
        showMessage("Please select an X-axis field.", "error");
        return;
    }
    if (!["pie", "donut", "histogram", "table"].includes(chartType) && !yAxis) {
        showMessage("Please select a Y-axis field.", "error");
        return;
    }

    if (createBtn) { createBtn.disabled = true; createBtn.textContent = "Generating…"; }
    clearMessage();
    chartPreview.innerHTML = '<p class="empty-state" style="padding:40px;">Generating your chart…</p>';

    try {
        const result = await apiRequest(
            `/api/datasets/${encodeURIComponent(datasetId)}/chart`,
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    chart_type:   chartType,
                    x_axis:       xAxis,
                    y_axis:       yAxis,
                    aggregation:  aggregation,
                    legend_field: legendField || null
                })
            }
        );

        chartPreview.innerHTML = "";
        const chartEl = document.createElement("div");
        chartEl.style.cssText = "width:100%;min-height:380px;";
        chartPreview.appendChild(chartEl);

        if (result.chart_type === "table") {
            renderTableChart(chartEl, result);
        } else if (result.data && result.layout) {
            if (typeof Plotly === "undefined") throw new Error("Plotly library is not loaded.");
            Plotly.newPlot(chartEl, result.data, result.layout, { responsive: true });
        } else {
            throw new Error("The server did not return chart data.");
        }

    } catch (error) {
        console.error("Chart error:", error);
        chartPreview.innerHTML = `<p class="empty-state" style="color:var(--danger);padding:30px;">${error.message}</p>`;
        showMessage(error.message, "error");
    } finally {
        if (createBtn) { createBtn.disabled = false; createBtn.textContent = "📈 Generate Chart"; }
    }
}


/* ---- Table chart renderer ---- */

function renderTableChart(container, chartData) {
    const columns = chartData.columns || [];
    const records = chartData.records || [];

    const wrapper = document.createElement("div");
    wrapper.style.cssText = "overflow-x:auto;max-height:420px;overflow-y:auto;border-radius:8px;border:1px solid #E8EAF2;";

    const table = document.createElement("table");
    table.style.cssText = "width:100%;border-collapse:collapse;";

    const thead = document.createElement("thead");
    const hRow  = document.createElement("tr");
    columns.forEach(col => {
        const th = document.createElement("th");
        th.textContent = col;
        hRow.appendChild(th);
    });
    thead.appendChild(hRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    records.forEach((rec, i) => {
        const tr = document.createElement("tr");
        if (i % 2) tr.style.background = "#F8F7FF";
        columns.forEach(col => {
            const td  = document.createElement("td");
            const val = rec[col];
            td.textContent = (val === null || val === undefined) ? "—" : String(val);
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrapper.appendChild(table);
    container.appendChild(wrapper);
}


/* =====================================================
   4. DASHBOARDS PAGE
===================================================== */

function initializeDashboards() {
    loadDashboards();
    setupDashboardModal();
}


/* ---- Load Dashboard Cards ---- */

async function loadDashboards() {
    const grid = document.getElementById("dashboardGrid");
    if (!grid) return;

    grid.innerHTML = '<div style="padding:50px;text-align:center;color:#9297AA;">Loading your dashboards…</div>';

    try {
        const result     = await apiRequest("/api/dashboards");
        const dashboards = result.dashboards || [];

        grid.innerHTML = "";

        if (!dashboards.length) {
            grid.innerHTML = `
                <div style="grid-column:1/-1;padding:60px 20px;text-align:center;color:#9297AA;">
                    <p style="font-size:16px;font-weight:600;margin:0;">No dashboards yet.</p>
                    <p style="margin:8px 0 0;font-size:13px;">Click <strong>Create dashboard</strong> above to get started.</p>
                </div>`;
            return;
        }

        dashboards.forEach(dashboard => grid.appendChild(buildDashboardCard(dashboard)));

    } catch (error) {
        showMessage(error.message, "error");
        grid.innerHTML = '<div style="padding:40px;text-align:center;color:var(--danger);">Could not load dashboards.</div>';
    }
}


function buildDashboardCard(dashboard) {
    const card = document.createElement("div");
    card.className = "content-card";
    card.style.cssText = "display:flex;flex-direction:column;gap:12px;margin-bottom:0;";

    const title = document.createElement("h3");
    title.textContent = dashboard.name || "Untitled";
    title.style.cssText = "font-size:17px;font-weight:700;margin:0;";

    const desc = document.createElement("p");
    desc.textContent = dashboard.description || "No description provided.";
    desc.style.cssText = "margin:0;font-size:13px;color:var(--muted);flex:1;";

    const meta = document.createElement("p");
    const ts   = dashboard.updated_at || dashboard.created_at;
    meta.textContent = ts ? "Updated " + new Date(ts).toLocaleString() : "";
    meta.style.cssText = "margin:0;font-size:11px;color:#B0B4C8;";

    const actions = document.createElement("div");
    actions.style.cssText = "display:flex;gap:8px;flex-wrap:wrap;";

    const dupBtn = document.createElement("button");
    dupBtn.className   = "table-action";
    dupBtn.textContent = "Duplicate";
    dupBtn.addEventListener("click", () => duplicateDashboard(dashboard.id));

    const delBtn = document.createElement("button");
    delBtn.className   = "table-action delete";
    delBtn.textContent = "Delete";
    delBtn.addEventListener("click", () => deleteDashboard(dashboard.id));

    actions.append(dupBtn, delBtn);
    card.append(title, desc, meta, actions);
    return card;
}


/* ---- Dashboard Modal ---- */

function setupDashboardModal() {
    const modal     = document.getElementById("dashboardModal");
    const openBtn   = document.getElementById("newDashboardButton");
    const closeBtn  = document.getElementById("closeDashboardModal");
    const cancelBtn = document.getElementById("cancelDashboard");
    const form      = document.getElementById("dashboardForm");

    if (!modal || !openBtn || !form) return;

    function openModal() {
        modal.style.display = "flex";
        document.getElementById("dashboardName").value        = "";
        document.getElementById("dashboardDescription").value = "";
        document.getElementById("dashboardName").focus();
    }

    function closeModal() { modal.style.display = "none"; }

    openBtn.addEventListener("click",   openModal);
    if (closeBtn)  closeBtn.addEventListener("click",  closeModal);
    if (cancelBtn) cancelBtn.addEventListener("click", closeModal);
    modal.addEventListener("click", e => { if (e.target === modal) closeModal(); });

    form.addEventListener("submit", async e => {
        e.preventDefault();
        const saveBtn     = document.getElementById("saveDashboardButton");
        const name        = document.getElementById("dashboardName").value.trim();
        const description = document.getElementById("dashboardDescription").value.trim();
        if (!name) return;

        if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = "Creating…"; }

        try {
            await apiRequest("/api/dashboards", {
                method:  "POST",
                headers: { "Content-Type": "application/json" },
                body:    JSON.stringify({ name, description })
            });
            closeModal();
            showDashboardMsg("Dashboard created successfully!", "success");
            await loadDashboards();
        } catch (error) {
            showDashboardMsg(error.message, "error");
        } finally {
            if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = "Create dashboard"; }
        }
    });
}

function showDashboardMsg(message, type = "success") {
    const el = document.getElementById("pageMessage");
    if (!el) return;
    el.textContent  = message;
    el.className    = `upload-message ${type}`;
    setTimeout(() => { el.textContent = ""; el.className = "upload-message"; }, 5000);
}


/* ---- Duplicate / Delete Dashboard ---- */

async function duplicateDashboard(dashboardId) {
    try {
        await apiRequest(`/api/dashboards/${encodeURIComponent(dashboardId)}/duplicate`, { method: "POST" });
        showDashboardMsg("Dashboard duplicated.", "success");
        await loadDashboards();
    } catch (error) {
        showDashboardMsg(error.message, "error");
    }
}

async function deleteDashboard(dashboardId) {
    if (!confirm("Delete this dashboard? This cannot be undone.")) return;
    try {
        await apiRequest(`/api/dashboards/${encodeURIComponent(dashboardId)}`, { method: "DELETE" });
        showDashboardMsg("Dashboard deleted.", "success");
        await loadDashboards();
    } catch (error) {
        showDashboardMsg(error.message, "error");
    }
}
