"use strict";
const base = document.body.dataset.base;
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const $ = id => document.getElementById(id);
function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
}
async function api(path, options = {}) {
  const response = await fetch(base + path, {cache: "no-store", ...options, headers: {"X-CSRF-Token": csrf, ...(options.headers || {})}});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Erreur ${response.status}`);
  return data;
}
function normalized(text) {return String(text).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]/g, "");}
