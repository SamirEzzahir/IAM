"use strict";

let outlookLoaded = false;
let outlookBusy = false;
let outlookTimer = null;

function outlookMode() {
  return document.querySelector('input[name="outlookMode"]:checked').value;
}

function updateOutlookMode() {
  const since = outlookMode() === "since";
  $("outlookSinceField").classList.toggle("is-hidden", !since);
  $("outlookSince").required = since;
}

function renderOutlook(data) {
  const active = ["STARTING", "RUNNING", "STOPPING"].includes(data.status);
  if (!outlookLoaded) {
    const settings = data.settings || {};
    $("outlookFolder").value = settings.folder || "";
    $("outlookInterval").value = settings.interval || 30;
    $("outlookSince").value = settings.since || "";
    document.querySelector(`input[name="outlookMode"][value="${settings.mode === "since" ? "since" : "new"}"]`).checked = true;
    outlookLoaded = true;
    updateOutlookMode();
  }
  $("outlookForm").querySelectorAll("input").forEach(input => { input.disabled = active; });
  $("outlookStartBtn").disabled = active;
  $("outlookStopBtn").disabled = !active || data.status === "STOPPING";
  const labels = { STARTING: "Connexion Outlook…", RUNNING: "Surveillance active", STOPPING: "Arrêt en cours…", STOPPED: "Arrêté", ERROR: "Erreur" };
  $("outlookStatusBadge").textContent = labels[data.status] || data.status;
  $("outlookStatusBadge").className = `badge ${data.status === "RUNNING" ? "ok" : data.status === "ERROR" ? "error" : "neutral"}`;
  $("outlookSummary").textContent = `${data.total} ligne(s) · ${data.emails} email(s) traité(s) · ${data.skipped} sans tableau compatible`;
  $("outlookLastScan").textContent = `Dernière vérification : ${formatDate(data.last_scan)}${data.folder_label ? " · " + data.folder_label : ""}`;
  $("outlookMessage").innerHTML = [data.error, data.export_error].filter(Boolean).map(message => `<div class="warning">${escapeHtml(message)}</div>`).join("");
  renderPaginatedTable("outlook", "outlookResultsBody", data.rows || [], row =>
    `<tr>${[row.commande, row.ont, row.version, row.technologie, row.client, row.login, row.odf, row.pco, row.brin, row.type_pco, row.pose_pco, row.pose_splitter, row.gps_pco, row.gps_splitter, row.longueur, row.msan, formatDate(row.received), row.subject].map(value => `<td>${escapeHtml(value || "—")}</td>`).join("")}</tr>`,
    '<tr><td colspan="18" class="empty">Aucune ligne collectée.</td></tr>');
  $("outlookLog").innerHTML = (data.logs || []).map(line => `<div class="log-line ${escapeHtml(line.level.toLowerCase())}"><time>${escapeHtml(formatTime(line.time))}</time><span>${escapeHtml(line.message)}</span></div>`).join("");
}

async function pollOutlook() {
  if (outlookBusy) return;
  try {
    const data = await api("/api/outlook");
    renderOutlook(data.collection);
  } catch (error) {
    $("outlookMessage").innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
  }
}

async function outlookAction(path, body) {
  if (outlookBusy) return;
  outlookBusy = true;
  $("outlookStartBtn").disabled = true;
  $("outlookStopBtn").disabled = true;
  try {
    const data = await api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    renderOutlook(data.collection);
  } catch (error) {
    $("outlookMessage").innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
    $("outlookStartBtn").disabled = false;
    $("outlookStopBtn").disabled = false;
  } finally {
    outlookBusy = false;
  }
}

$("outlookForm").addEventListener("submit", event => {
  event.preventDefault();
  outlookAction("/api/outlook/start", {
    folder: $("outlookFolder").value.trim(), mode: outlookMode(),
    since: $("outlookSince").value, interval: Number($("outlookInterval").value),
  });
});
$("outlookStopBtn").addEventListener("click", () => outlookAction("/api/outlook/stop"));
$("outlookDownloadBtn").href = appUrl("/api/outlook/result.xlsx");
document.querySelectorAll('input[name="outlookMode"]').forEach(input => input.addEventListener("change", updateOutlookMode));
pollOutlook();
outlookTimer = setInterval(pollOutlook, 3000);
