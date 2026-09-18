"use strict";
const map = L.map("map", {preferCanvas:true}).setView([33.9, -5.1], 7);
const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom:19, attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
}).addTo(map);
tiles.on("tileerror", () => $("tile-warning").hidden = false);
let marker, groups = [], pcos = [], visible = {}, page = 1, clientQuery = "", firstLoad = true, lookupSequence = 0;
const enabledLayers = new Map();
const columnNames = ["ODF", "Login", "Série ONT", "Nom Client", "Adresse Client", "NE", "PCO", "OLT"];
function popup(feature) {
  const props = feature.properties;
  const el = node("div");
  el.append(node("strong", props.name));
  if (props.operator) el.append(node("p", "Zone " + props.operator));
  if (props.occupation) el.append(node("p", `${props.occupation.free} ports libres / ${props.occupation.total} · ${props.occupation.used} occupés`));
  else if (props.kind === "pco" && visible.occupation) el.append(node("p", "Occupation non renseignée"));
  return el;
}
function renderPcos() {
  const query = normalized($("pco-query").value);
  const rows = pcos.filter(f => normalized(f.properties.name).includes(query));
  if (visible.occupation) rows.sort((a,b) => (b.properties.occupation?.free ?? -1) - (a.properties.occupation?.free ?? -1));
  $("pco-head").replaceChildren(); $("pco-rows").replaceChildren();
  const head = node("tr");
  ["PCO", "GPS", ...(visible.occupation ? ["Ports occupés", "Capacité", "Ports libres"] : [])].forEach(t => head.append(node("th", t)));
  $("pco-head").append(head);
  for (const feature of rows.slice(0,100)) {
    const row = node("tr"), cell = node("td"), button = node("button", feature.properties.name, "pco-link");
    const [lon, lat] = feature.geometry.coordinates;
    button.type = "button";
    button.addEventListener("click", () => {$("gps").value = `${lat}, ${lon}`; lookup(); $("map").scrollIntoView({behavior:"smooth", block:"center"});});
    cell.append(button); row.append(cell, node("td", `${lat.toFixed(6)}, ${lon.toFixed(6)}`));
    if (visible.occupation) for (const key of ["used", "total", "free"]) row.append(node("td", feature.properties.occupation?.[key] ?? "—"));
    $("pco-rows").append(row);
  }
  $("pco-count").textContent = `${rows.length} PCO · ${Math.min(rows.length,100)} affichés${rows.length > 100 ? " : précisez la recherche" : ""}.`;
}
async function loadMap() {
  $("refresh").disabled = true;
  try {
    const data = await api("/api/map");
    visible = data.visibility;
    groups.forEach(layer => map.removeLayer(layer)); groups = [];
    $("layers").replaceChildren();
    const bounds = L.latLngBounds([]);
    for (const key of ["IAM","INWI","ORANGE","pco"]) {
      if (!visible[key]) continue;
      const features = data.features.filter(f => key === "pco" ? f.properties.kind === "pco" : f.properties.operator === key);
      const layer = L.geoJSON(features, {
        style: f => ({color:f.properties.color, weight:2, fillOpacity:.17}),
        pointToLayer: (f, latlng) => L.circleMarker(latlng, {radius:5, weight:1, color:"#fff", fillColor: f.properties.occupation?.free === 0 ? "#d84e4e" : "#146c68", fillOpacity:.9}),
        onEachFeature: (feature, item) => item.bindPopup(popup(feature))
      });
      if (enabledLayers.get(key) !== false) layer.addTo(map);
      groups.push(layer);
      if (layer.getBounds().isValid()) bounds.extend(layer.getBounds());
      const label = node("label", undefined, "check"), checkbox = node("input"), swatch = node("span", "", "swatch");
      checkbox.type = "checkbox"; checkbox.checked = enabledLayers.get(key) !== false;
      swatch.style.background = {IAM:"#2563eb", INWI:"#9333ea", ORANGE:"#f97316", pco:"#146c68"}[key];
      checkbox.addEventListener("change", () => {enabledLayers.set(key, checkbox.checked); checkbox.checked ? map.addLayer(layer) : map.removeLayer(layer);});
      label.append(checkbox, swatch, node("span", `${key === "pco" ? "PCO" : key} (${features.length})`));
      $("layers").append(label);
    }
    if (firstLoad && bounds.isValid()) map.fitBounds(bounds, {padding:[25,25], maxZoom:14});
    firstLoad = false;
    pcos = data.features.filter(f => f.properties.kind === "pco");
    $("pco-section").hidden = !visible.pco;
    $("clients-section").hidden = !visible.clients;
    if (!visible.clients) {$("client-rows").replaceChildren(); $("client-count").textContent = "";}
    renderPcos();
    $("data-note").textContent = data.features.length ? "Décochez une couche pour ajuster la carte. Actualisation automatique toutes les 60 secondes." : "Aucune donnée publiée. L'administrateur doit importer et activer les zones.";
    $("status").textContent = "Données actualisées à " + new Date().toLocaleTimeString("fr");
    if ($("gps").value.trim()) await lookup(false);
  } catch(error) {$("status").textContent = "Actualisation impossible : " + error.message;}
  finally {$("refresh").disabled = false;}
}
async function lookup(pan = true) {
  const sequence = ++lookupSequence;
  $("lookup-result").textContent = "Recherche des opérateurs…";
  try {
    const data = await api("/api/lookup?gps=" + encodeURIComponent($("gps").value));
    if (sequence !== lookupSequence) return;
    if (marker) map.removeLayer(marker);
    marker = L.circleMarker([data.lat,data.lon], {radius:9, color:"#142a40", fillColor:"#fff", fillOpacity:1, weight:3}).addTo(map);
    marker.bindPopup(node("div", `${data.lat}, ${data.lon}`));
    if (pan) map.setView([data.lat,data.lon], Math.max(map.getZoom(),15));
    $("lookup-result").replaceChildren(node("strong", data.matches.length ? "Opérateurs présents dans cette zone" : "Aucune couverture déclarée à ce point"));
    for (const match of data.matches) {
      const card = node("div", undefined, "operator-match"); card.style.borderColor = match.color;
      card.append(node("strong", match.operator), node("small", match.zones.join(" · ")));
      $("lookup-result").append(card);
    }
    if (!data.matches.length) $("lookup-result").append(node("small", "Résultat limité aux zones importées et autorisées par l'administrateur."));
  } catch(error) {if (sequence === lookupSequence) $("lookup-result").textContent = error.message;}
}
async function searchClients() {
  $("client-count").textContent = "Recherche…";
  try {
    const data = await api(`/api/clients?q=${encodeURIComponent(clientQuery)}&page=${page}`);
    $("client-rows").replaceChildren();
    for (const item of data.rows) {const tr = node("tr"); columnNames.forEach(key => tr.append(node("td",item[key]))); $("client-rows").append(tr);}
    $("client-count").textContent = `${data.total} résultat(s) · page ${data.page} · 50 résultats maximum par page`;
    $("previous").disabled = page <= 1; $("next").disabled = page * 50 >= data.total;
  } catch(error) {$("client-rows").replaceChildren(); $("client-count").textContent = error.message;}
}
$("gps-form").addEventListener("submit", event => {event.preventDefault(); lookup();});
map.on("click", event => {$("gps").value = `${event.latlng.lat.toFixed(6)}, ${event.latlng.lng.toFixed(6)}`; lookup();});
$("pco-query").addEventListener("input", renderPcos);
$("refresh").addEventListener("click", loadMap);
$("clients-form").addEventListener("submit", event => {event.preventDefault(); clientQuery = $("client-query").value; page = 1; searchClients();});
$("previous").addEventListener("click", () => {page--; searchClients();});
$("next").addEventListener("click", () => {page++; searchClients();});
loadMap();
setInterval(() => {if (!document.hidden && !$("refresh").disabled) loadMap();}, 60000);
