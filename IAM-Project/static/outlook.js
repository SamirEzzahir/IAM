"use strict";

let outlookLoaded = false;
let outlookBusy = false;
let outlookTimer = null;
let outlookActive = false;
let outlookSubjects = [];
let outlookSenders = [];
const outlookColumns = JSON.parse($("outlookResultsTable").dataset.columns);

function renderOutlookTags() {
  for (const [kind, values] of [["Subject", outlookSubjects], ["Sender", outlookSenders]]) {
    const container = $(`outlook${kind}Tags`);
    container.replaceChildren();
    values.forEach((value, index) => {
      const tag = document.createElement("span");
      tag.className = "outlook-tag";
      const text = document.createElement("span");
      text.textContent = value;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "×";
      remove.setAttribute("aria-label", `Supprimer ${value}`);
      remove.disabled = outlookActive || outlookBusy;
      remove.addEventListener("click", () => {
        values.splice(index, 1);
        renderOutlookTags();
      });
      tag.append(text, remove);
      container.appendChild(tag);
    });
    $(`outlook${kind}Add`).disabled = !outlookLoaded || outlookActive || outlookBusy;
    $(`outlook${kind}Input`).disabled = !outlookLoaded || outlookActive || outlookBusy;
  }
}

function addOutlookTag(kind) {
  if (!outlookLoaded || outlookActive || outlookBusy) return false;
  const input = $(`outlook${kind}Input`);
  let value = input.value.trim().replace(/\s+/g, " ");
  if (!value) return true;
  const values = kind === "Subject" ? outlookSubjects : outlookSenders;
  if (kind === "Sender") {
    value = value.toLowerCase();
    if (!/^[^\s@<>;,]+@[^\s@<>;,]+\.[^\s@<>;,]+$/.test(value)) {
      toast("Saisissez une adresse email complète.");
      input.focus();
      return false;
    }
  }
  const normalize = text => text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const exists = values.some(item => kind === "Sender" ? item === value : normalize(item) === normalize(value));
  if (!exists) {
    if (values.length >= 100) { toast("Maximum 100 tags par filtre."); return false; }
    values.push(value);
  }
  input.value = "";
  renderOutlookTags();
  return true;
}

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
  outlookActive = active;
  if (!outlookLoaded) {
    const settings = data.settings || {};
    $("outlookFolder").value = settings.folder || "";
    $("outlookInterval").value = settings.interval || 30;
    $("outlookSince").value = settings.since || "";
    outlookSubjects = [...(settings.subjects || data.subjects || [])];
    outlookSenders = [...(settings.senders || [])];
    document.querySelector(`input[name="outlookMode"][value="${settings.mode === "since" ? "since" : "new"}"]`).checked = true;
    outlookLoaded = true;
    updateOutlookMode();
  }
  $("outlookForm").querySelectorAll("input").forEach(input => { input.disabled = active; });
  $("outlookStartBtn").disabled = active;
  $("outlookStopBtn").disabled = !active || data.status === "STOPPING";
  $("outlookResetBtn").disabled = active;
  renderOutlookTags();
  const labels = { STARTING: "Connexion Outlook…", RUNNING: "Surveillance active", STOPPING: "Arrêt en cours…", STOPPED: "Arrêté", ERROR: "Erreur" };
  $("outlookStatusBadge").textContent = labels[data.status] || data.status;
  $("outlookStatusBadge").className = `badge ${data.status === "RUNNING" ? "ok" : data.status === "ERROR" ? "error" : "neutral"}`;
  $("outlookSummary").textContent = `${data.total} ligne(s) · ${data.emails} email(s) traité(s) · ${data.skipped} sans tableau compatible`;
  $("outlookLastScan").textContent = `Dernière vérification : ${formatDate(data.last_scan)}${data.folder_label ? " · " + data.folder_label : ""}`;
  $("outlookMessage").innerHTML = [data.error, data.export_error].filter(Boolean).map(message => `<div class="warning">${escapeHtml(message)}</div>`).join("");
  renderPaginatedTable("outlook", "outlookResultsBody", data.rows || [], row =>
    `<tr>${outlookColumns.map(([key]) => `<td>${escapeHtml((key === "received" ? formatDate(row[key]) : row[key]) || "—")}</td>`).join("")}</tr>`,
    `<tr><td colspan="${outlookColumns.length}" class="empty">Aucune ligne collectée.</td></tr>`);
  $("outlookLog").innerHTML = (data.logs || []).map(line => `<div class="log-line ${escapeHtml(line.level.toLowerCase())}"><time>${escapeHtml(formatTime(line.time))}</time><span>${escapeHtml(line.message)}</span></div>`).join("");
}

async function pollOutlook() {
  if (outlookBusy) return;
  try {
    const data = await api("/api/outlook");
    if (!outlookBusy) renderOutlook(data.collection);
  } catch (error) {
    $("outlookMessage").innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
  }
}

async function outlookAction(path, body) {
  if (outlookBusy) return;
  outlookBusy = true;
  $("outlookStartBtn").disabled = true;
  $("outlookStopBtn").disabled = true;
  $("outlookResetBtn").disabled = true;
  renderOutlookTags();
  try {
    const data = await api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    renderOutlook(data.collection);
  } catch (error) {
    $("outlookMessage").innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
    $("outlookStartBtn").disabled = outlookActive;
    $("outlookStopBtn").disabled = !outlookActive;
    $("outlookResetBtn").disabled = outlookActive;
  } finally {
    outlookBusy = false;
    renderOutlookTags();
  }
}

$("outlookForm").addEventListener("submit", event => {
  event.preventDefault();
  if (!addOutlookTag("Subject") || !addOutlookTag("Sender")) return;
  if (!outlookSubjects.length) { toast("Ajoutez au moins un sujet."); return; }
  outlookAction("/api/outlook/start", {
    folder: $("outlookFolder").value.trim(), mode: outlookMode(),
    since: $("outlookSince").value, interval: Number($("outlookInterval").value),
    subjects: outlookSubjects, senders: outlookSenders,
  });
});
$("outlookStopBtn").addEventListener("click", () => outlookAction("/api/outlook/stop"));
$("outlookResetBtn").addEventListener("click", () => {
  if (outlookBusy || outlookActive) return;
  if (window.confirm("Effacer toutes les lignes, l’Excel et l’historique local de collecte ? Vos filtres et vos emails Outlook seront conservés. Pour relire les anciens emails ensuite, choisissez Depuis une date.")) {
    tablePageState.outlook = 1;
    outlookAction("/api/outlook/reset");
  }
});
for (const kind of ["Subject", "Sender"]) {
  $(`outlook${kind}Add`).addEventListener("click", () => addOutlookTag(kind));
  $(`outlook${kind}Input`).addEventListener("keydown", event => {
    if (event.key === "Enter") { event.preventDefault(); addOutlookTag(kind); }
  });
}
renderOutlookTags();
$("outlookDownloadBtn").href = appUrl("/api/outlook/result.xlsx");
document.querySelectorAll('input[name="outlookMode"]').forEach(input => input.addEventListener("change", updateOutlookMode));
pollOutlook();
outlookTimer = setInterval(pollOutlook, 3000);
