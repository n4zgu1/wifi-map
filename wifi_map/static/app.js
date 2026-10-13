"use strict";
const $ = id => document.getElementById(id);
const token = new URLSearchParams(location.hash.slice(1)).get("token") || sessionStorage.getItem("wifi-map-token") || "";
if (token) sessionStorage.setItem("wifi-map-token", token);
history.replaceState(null, "", "/");
const canvas = $("canvas"), ctx = canvas.getContext("2d");
let points = [], sessions = [], center = [0.5, 0.5], zoom = 16, drag = null;
const cache = new Map();
function project(lat, lon) {
  const s = Math.sin(Math.max(-85, Math.min(85, lat)) * Math.PI / 180);
  return [(lon + 180) / 360, 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)];
}
function visible() { return points.filter(p => !$("ap").value || p.ap_id === $("ap").value); }
function fit() {
  const ps = visible().map(p => project(p.lat, p.lon));
  if (!ps.length) return draw();
  const xs = ps.map(p => p[0]), ys = ps.map(p => p[1]);
  const lo = [Math.min(...xs), Math.min(...ys)], hi = [Math.max(...xs), Math.max(...ys)];
  center = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2];
  zoom = Math.max(2, Math.min(19, Math.floor(Math.log2(Math.min(canvas.clientWidth / Math.max(hi[0] - lo[0], 0.00001), canvas.clientHeight / Math.max(hi[1] - lo[1], 0.00001)) / 350))));
  draw();
}
function draw() {
  const w = canvas.clientWidth, h = canvas.clientHeight, scale = 256 * 2 ** zoom, dpr = devicePixelRatio || 1;
  canvas.width = w * dpr; canvas.height = h * dpr; ctx.scale(dpr, dpr);
  ctx.fillStyle = "#142131"; ctx.fillRect(0, 0, w, h);
  const ox = center[0] * scale - w / 2, oy = center[1] * scale - h / 2;
  ctx.strokeStyle = "#26384e";
  for (let x = -ox % 128; x < w; x += 128) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }
  for (let y = -oy % 128; y < h; y += 128) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }
  if ($("tiles").checked) {
    for (let x = Math.floor(ox / 256); x <= Math.floor((ox + w) / 256); x++) {
      for (let y = Math.floor(oy / 256); y <= Math.floor((oy + h) / 256); y++) {
        if (x < 0 || y < 0 || x >= 2 ** zoom || y >= 2 ** zoom) continue;
        const key = `${zoom}/${x}/${y}`;
        if (!cache.has(key)) {
          const img = new Image(); img.referrerPolicy = "no-referrer";
          img.onload = draw; img.src = `https://tile.openstreetmap.org/${key}.png`; cache.set(key, img);
          if (cache.size > 200) cache.delete(cache.keys().next().value);
        }
        const img = cache.get(key);
        if (img && img.complete && img.naturalWidth) ctx.drawImage(img, x * 256 - ox, y * 256 - oy, 256, 256);
      }
    }
  }
  for (const p of visible()) {
    const pos = project(p.lat, p.lon), x = pos[0] * scale - ox, y = pos[1] * scale - oy;
    if (x < -10 || y < -10 || x > w + 10 || y > h + 10) continue;
    ctx.fillStyle = `hsl(${Math.max(12, Math.min(155, (p.rssi + 95) * 2.6))},65%,58%)`;
    ctx.globalAlpha = 0.65; ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fill();
  }
  ctx.globalAlpha = 1;
  ctx.fillStyle = "#8ba7c5"; ctx.font = "12px system-ui"; ctx.fillText(`Zoom ${zoom} · ${visible().length} Messpunkte`, 12, 22);
}
async function api(path) {
  const response = await fetch(path, {headers: {Authorization: "Bearer " + token}});
  if (!response.ok) throw new Error(response.status === 401 ? "Zugriff verweigert: Öffne den vollständigen Link aus dem Terminal." : `HTTP ${response.status}`);
  return response.json();
}
function report(error) { $("status").textContent = error.message; }
async function loadPoints() {
  points = await api(`/api/points?session=${encodeURIComponent($("session").value)}`);
  const selected = $("ap").value; $("ap").replaceChildren(new Option("Alle", ""));
  for (const id of [...new Set(points.map(p => p.ap_id))].sort()) $("ap").add(new Option(id.slice(0, 12), id));
  if ([...$("ap").options].some(o => o.value === selected)) $("ap").value = selected;
  const s = sessions.find(s => s.id === $("session").value);
  $("status").textContent = s ? `${s.mode === "demo" ? "DEMO · " : ""}${s.access_points} Zugangspunkte · ${s.observations} Beobachtungen${points.length >= 50000 ? " · Anzeige auf 50.000 Punkte begrenzt" : ""}` : "Noch keine Messläufe. Starte capture oder demo.";
  fit();
}
async function refresh() {
  const selected = $("session").value; sessions = await api("/api/sessions"); $("session").replaceChildren();
  for (const s of sessions) $("session").add(new Option(`${new Date(s.started * 1000).toLocaleString()} · ${s.mode}`, s.id));
  if (sessions.some(s => s.id === selected)) $("session").value = selected;
  await loadPoints();
}
$("refresh").onclick = () => refresh().catch(report);
$("session").onchange = () => loadPoints().catch(report);
$("ap").onchange = fit; $("fit").onclick = fit;
$("tiles").onchange = () => { $("attribution").hidden = !$("tiles").checked; draw(); };
$("export").onclick = async () => {
  try {
    const data = await api(`/api/export?session=${encodeURIComponent($("session").value)}`);
    const url = URL.createObjectURL(new Blob([JSON.stringify(data)], {type: "application/geo+json"}));
    const a = document.createElement("a"); a.href = url; a.download = "wifi-map.geojson"; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (e) { report(e); }
};
canvas.onpointerdown = e => { drag = [e.clientX, e.clientY, ...center]; canvas.setPointerCapture(e.pointerId); };
canvas.onpointermove = e => { if (drag) { const scale = 256 * 2 ** zoom; center = [drag[2] - (e.clientX - drag[0]) / scale, drag[3] - (e.clientY - drag[1]) / scale]; draw(); } };
canvas.onpointerup = canvas.onpointercancel = () => { drag = null; };
canvas.addEventListener("wheel", e => { e.preventDefault(); zoom = Math.max(2, Math.min(19, zoom + (e.deltaY < 0 ? 1 : -1))); draw(); }, {passive: false});
new ResizeObserver(draw).observe(canvas); refresh().catch(report);
