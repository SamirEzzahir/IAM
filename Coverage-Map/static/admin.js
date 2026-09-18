"use strict";
const labels = {IAM:"IAM", INWI:"INWI", ORANGE:"ORANGE", pco:"Points PCO", occupation:"Occupation PCO", clients:"Base clients"};
async function refreshAdmin() {
  const data = await api("/api/admin/status");
  for (const [key, value] of Object.entries(data.visibility)) $("visibility-form").elements.namedItem(key).checked = value;
  document.querySelectorAll(".import-card").forEach(card => {
    const entry = data.datasets[card.dataset.kind];
    card.querySelector(".dataset-count").textContent = entry ? `${entry.count.toLocaleString("fr")} enregistrement(s) · ${new Date(entry.updated).toLocaleString("fr")}` : "Aucune donnée importée.";
  });
}
async function action(callback, success) {
  document.querySelectorAll("button").forEach(b => b.disabled = true);
  $("admin-status").textContent = "Traitement en cours…";
  try {
    const data = await callback();
    await refreshAdmin();
    $("admin-status").textContent = typeof success === "function" ? success(data) : success;
  } catch (error) {$("admin-status").textContent = error.message;}
  finally {document.querySelectorAll("button").forEach(b => b.disabled = false);}
}
$("visibility-form").addEventListener("submit", event => {
  event.preventDefault();
  const body = Object.fromEntries(Object.keys(labels).map(key => [key, event.target.elements.namedItem(key).checked]));
  action(() => api("/api/admin/visibility", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)}), "Visibilité enregistrée. Les utilisateurs recevront la mise à jour à la prochaine actualisation.");
});
document.querySelectorAll(".import-card").forEach(card => {
  const kind = card.dataset.kind;
  card.querySelector("form").addEventListener("submit", event => {
    event.preventDefault();
    if (!confirm(`Remplacer entièrement les données « ${labels[kind]} » par ce fichier ?`)) return;
    const body = new FormData(event.target);
    action(() => api(`/api/admin/import/${kind}`, {method:"POST", body}), data => `${labels[kind]} : ${data.count} enregistrement(s) importé(s).`);
  });
  card.querySelector(".clear").addEventListener("click", () => {
    if (!confirm(`Supprimer les données « ${labels[kind]} » du serveur ? Réimportez votre fichier source pour les restaurer.`)) return;
    action(() => api(`/api/admin/clear/${kind}`, {method:"POST"}), `${labels[kind]} vidé. Les autres jeux sont conservés.`);
  });
});
$("logout").addEventListener("click", async () => {
  try {await api("/api/admin/logout", {method:"POST"}); location.href = base + "/admin";}
  catch (error) {$("admin-status").textContent = error.message;}
});
refreshAdmin().then(() => $("admin-status").textContent = "Configuration prête. Sélectionnez les informations à partager.").catch(error => $("admin-status").textContent = error.message);
