// Radar do painel: você no centro apontando para cima e os aviões em volta.
// É o mesmo dado do mapa que o jogo oferece no navegador (localhost:8111), só que centrado em você.
"use strict";

const RD = {
  from: new Map(), to: new Map(), hFrom: 0, hTo: 0, t0: 0, dur: 260,
  data: null, range: 4000, hits: [],
};

try { RD.range = Number(localStorage.getItem("wtc.range")) || 4000; } catch (e) { /* sem storage */ }

const lerp = (a, b, k) => a + (b - a) * k;
const lerpAngle = (a, b, k) => a + ((((b - a + Math.PI * 3) % (Math.PI * 2)) - Math.PI) * k);
const progress = (now) => Math.min(1, (now - RD.t0) / RD.dur);
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

async function pollRadar() {
  let wait = 250;
  try {
    const r = await fetch("/api/radar", { cache: "no-store" });
    onRadar(await r.json());
  } catch (e) {
    RD.data = { game: "down", objs: [] };
    wait = 2000;  // companion fechado: tenta de novo com calma
  }
  setTimeout(pollRadar, wait);
}

// a posição desenhada agora vira o ponto de partida da próxima animação
function onRadar(data) {
  const now = performance.now();
  const k = progress(now);
  const from = new Map();
  for (const [id, o] of RD.to) {
    const f = RD.from.get(id) || o;
    from.set(id, { rx: lerp(f.rx, o.rx, k), ry: lerp(f.ry, o.ry, k) });
  }
  RD.from = from;
  RD.hFrom = lerpAngle(RD.hFrom, RD.hTo, k);
  RD.to = new Map((data.objs || []).map((o) => [o.tid, o]));
  for (const [id, o] of RD.to) {
    const f = RD.from.get(id);
    if (f && Math.hypot(f.rx - o.rx, f.ry - o.ry) > 3000) RD.from.delete(id);  // respawn: sem animação
  }
  if (data.hdg) RD.hTo = Math.atan2(data.hdg[0], -data.hdg[1]);
  if (!RD.data || RD.data.game !== "battle") RD.hFrom = RD.hTo;
  RD.t0 = now;
  RD.data = data;
}

// inimigo atrás de você, perto e apontando para você
function isChaser(o, a, b) {
  const dist = Math.hypot(o.rx, o.ry);
  if (dist > 1200 || a > -dist * 0.5) return false;  // precisa estar atrás (entre 4h e 8h)
  const cos = (o.dx * -o.rx + o.dy * -o.ry) / (Math.hypot(o.dx, o.dy) * dist || 1);
  return cos > Math.cos(35 * Math.PI / 180);
}

function shape(ctx, cls) {
  ctx.beginPath();
  if (cls === "bomber") {
    ctx.rect(-6, -5, 12, 10);
  } else if (cls === "assault") {
    ctx.moveTo(0, -8); ctx.lineTo(6, 0); ctx.lineTo(0, 8); ctx.lineTo(-6, 0);
  } else {
    ctx.moveTo(0, -8); ctx.lineTo(5.5, 6); ctx.lineTo(-5.5, 6);
  }
  ctx.closePath();
}

function drawRadar() {
  const cv = document.getElementById("radarCanvas");
  if (!cv) return;
  const size = Math.max(200, Math.min(cv.parentElement.clientWidth, 460));
  const dpr = window.devicePixelRatio || 1;
  if (cv.width !== Math.round(size * dpr)) {
    cv.width = cv.height = Math.round(size * dpr);
    cv.style.width = cv.style.height = size + "px";
  }
  const ctx = cv.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, size, size);
  const C = {
    bg: cssVar("--surface-2"), surface: cssVar("--surface"), grid: cssVar("--axis"), ink: cssVar("--ink"),
    ink2: cssVar("--ink-2"), en: cssVar("--en"), al: cssVar("--me"), crit: cssVar("--crit"),
  };
  const cx = size / 2, cy = size / 2, R = size / 2 - 16;
  const font = (px, w = 400) => `${w} ${px}px system-ui, -apple-system, "Segoe UI", sans-serif`;

  // disco e anéis de distância
  ctx.fillStyle = C.bg;
  ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.fill();
  ctx.strokeStyle = C.grid; ctx.lineWidth = 1;
  ctx.setLineDash([3, 4]);
  ctx.beginPath(); ctx.arc(cx, cy, R / 2, 0, Math.PI * 2); ctx.stroke();
  ctx.setLineDash([]);
  ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.stroke();
  ctx.fillStyle = C.ink2; ctx.font = font(11);
  ctx.textAlign = "left";
  ctx.fillText(`${nf.format(RD.range / 2000)} km`, cx + R / 2 * 0.72 + 2, cy - R / 2 * 0.72);
  ctx.fillText(`${nf.format(RD.range / 1000)} km`, cx + R * 0.72 + 2, cy - R * 0.72);

  const data = RD.data;
  RD.hits = [];
  if (!data || data.game !== "battle" || data.dead) {
    ctx.fillStyle = C.ink2; ctx.font = font(13); ctx.textAlign = "center";
    ctx.fillText(data && data.game === "down" ? "Companion parado"
      : data && data.dead ? "Você caiu: volta quando você nascer" : "Disponível durante a batalha", cx, cy + 4);
    return;
  }

  const k = progress(performance.now());
  const th = lerpAngle(RD.hFrom, RD.hTo, k);
  const f = [Math.sin(th), -Math.cos(th)];   // sua frente, no mapa
  const r = [Math.cos(th), Math.sin(th)];    // sua direita, no mapa
  const s = R / RD.range;
  const screen = (x, y) => [cx + (x * r[0] + y * r[1]) * s, cy - (x * f[0] + y * f[1]) * s];

  // norte
  const [nx, ny] = screen(0, -RD.range * 0.9);
  ctx.fillStyle = C.ink2; ctx.font = font(12, 700); ctx.textAlign = "center";
  ctx.fillText("N", nx, ny + 4);

  const myAlt = data.me && data.me.alt;
  const objs = [...RD.to.values()].sort((a, b) => (a.side === "enemy") - (b.side === "enemy"));
  const labels = [];
  for (const o of objs) {
    const p0 = RD.from.get(o.tid) || o;
    const x = lerp(p0.rx, o.rx, k), y = lerp(p0.ry, o.ry, k);
    let [sx, sy] = screen(x, y);
    const off = Math.hypot(sx - cx, sy - cy);
    const out = off > R;
    if (out) { sx = cx + (sx - cx) * R / off; sy = cy + (sy - cy) * R / off; }
    const hx = o.dx * r[0] + o.dy * r[1], hy = -(o.dx * f[0] + o.dy * f[1]);

    if (o.side !== "enemy") {
      ctx.globalAlpha = out ? 0.35 : 0.7;
      ctx.fillStyle = C.al;
      ctx.beginPath(); ctx.arc(sx, sy, out ? 2.5 : 3.5, 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = 1;
      continue;
    }
    const a = x * f[0] + y * f[1];
    const chaser = !out && isChaser(o, a);
    ctx.save();
    ctx.translate(sx, sy);
    if (chaser) {
      const pulse = 0.55 + 0.45 * Math.sin(performance.now() / 160);
      ctx.strokeStyle = C.crit; ctx.globalAlpha = pulse; ctx.lineWidth = 3;
      ctx.beginPath(); ctx.arc(0, 0, 16, 0, Math.PI * 2); ctx.stroke();
      ctx.globalAlpha = 1;
    }
    if (o.target) {
      ctx.strokeStyle = C.ink; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(0, 0, 12, 0, Math.PI * 2); ctx.stroke();
    }
    // só o triângulo do caça gira; quadrado e losango ficam retos para não se confundirem
    const turn = Math.atan2(hx, -hy);
    if (out) ctx.scale(0.75, 0.75);
    if (!out) {
      ctx.strokeStyle = C.en; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(Math.sin(turn) * 8, -Math.cos(turn) * 8);
      ctx.lineTo(Math.sin(turn) * 18, -Math.cos(turn) * 18); ctx.stroke();
    }
    if (o.cls !== "bomber" && o.cls !== "assault") ctx.rotate(turn);
    shape(ctx, o.cls);
    ctx.lineWidth = 2; ctx.strokeStyle = C.bg; ctx.stroke();   // anel que separa marcas sobrepostas
    if (out) { ctx.strokeStyle = C.en; ctx.lineWidth = 1.5; ctx.stroke(); }
    else { ctx.fillStyle = C.en; ctx.fill(); }
    ctx.restore();

    RD.hits.push({ sx, sy, o, dist: Math.hypot(o.rx, o.ry), chaser });
    if (!out && (o.id || o.alt)) labels.push({ sx, sy, o });
  }

  // nomes e altitudes (só de quem o kill feed ou o rádio revelaram)
  ctx.font = font(11, 600);
  for (const { sx, sy, o } of labels) {
    const a = o.id && DB ? DB.aircraft[o.id] : null;
    const name = a ? (a.short || nameOf(a)).replace(/^[^\p{L}\p{N}(]+/u, "") : "";
    const alt = o.alt ? `${nf.format(o.alt)} m${myAlt != null ? ` (${o.alt - myAlt >= 0 ? "+" : ""}${nf.format(Math.round((o.alt - myAlt) / 100) * 100)})` : ""}` : "";
    const lines = [name, alt].filter(Boolean);
    const right = sx < cx + R * 0.45;
    ctx.textAlign = right ? "left" : "right";
    const tx = sx + (right ? 12 : -12);
    lines.forEach((t, i) => {
      const ty = sy - 2 + i * 13;
      ctx.lineWidth = 3; ctx.strokeStyle = C.bg; ctx.strokeText(t, tx, ty);
      ctx.fillStyle = C.ink; ctx.fillText(t, tx, ty);
    });
  }

  // você
  ctx.fillStyle = C.ink;
  ctx.beginPath(); ctx.moveTo(cx, cy - 10); ctx.lineTo(cx + 7, cy + 8); ctx.lineTo(cx, cy + 4); ctx.lineTo(cx - 7, cy + 8); ctx.closePath(); ctx.fill();
  if (myAlt != null) {
    ctx.font = font(12); ctx.fillStyle = C.ink2; ctx.textAlign = "left";
    ctx.fillText(`Você: ${nf.format(Math.round(myAlt))} m`, 6, size - 6);
  }
}

function loop() {
  drawRadar();
  requestAnimationFrame(loop);
}

function radarTip(e) {
  const tip = document.getElementById("radarTip");
  const box = e.currentTarget.getBoundingClientRect();
  const mx = e.clientX - box.left, my = e.clientY - box.top;
  const best = nearestHit(e);
  e.currentTarget.style.cursor = best && best.o.id ? "pointer" : "";
  if (!best) { tip.hidden = true; return; }
  const o = best.o;
  const a = o.id && DB ? DB.aircraft[o.id] : null;
  const myAlt = RD.data && RD.data.me && RD.data.me.alt;
  tip.innerHTML = `<b>${esc(a ? nameOf(a) : (CLS[o.cls] || "Inimigo"))}</b>${o.nick ? ` <span class="muted">${esc(o.nick)}</span>` : ""}
    <br>${best.dist >= 1000 ? nf.format(best.dist / 1000) + " km" : Math.round(best.dist) + " m"}${o.target ? " · seu alvo" : ""}${best.chaser ? " · <b>atrás de você!</b>" : ""}
    <br>${o.alt ? `altitude ${nf.format(o.alt)} m (aviso de rádio há ${o.altAge}s)${myAlt != null ? `, você ${nf.format(Math.round(myAlt))} m` : ""}` : "altitude desconhecida"}
    ${o.id ? "<br><span class=\"muted\">clique para comparar</span>" : ""}`;
  tip.hidden = false;
  tip.style.left = Math.min(mx + 14, box.width - 180) + "px";
  tip.style.top = (my + 14) + "px";
}

function nearestHit(e) {
  const box = e.currentTarget.getBoundingClientRect();
  const mx = e.clientX - box.left, my = e.clientY - box.top;
  let best = null;
  for (const h of RD.hits) {
    const d = Math.hypot(h.sx - mx, h.sy - my);
    if (d < 16 && (!best || d < best.d)) best = { ...h, d };
  }
  return best;
}

// clicar num inimigo reconhecido abre a comparação com ele
function radarClick(e) {
  const h = nearestHit(e);
  if (!h || !h.o.id) return;
  MANUAL = { id: h.o.id, nick: h.o.nick || null };
  render();
}

function setRange(v) {
  RD.range = v;
  try { localStorage.setItem("wtc.range", String(v)); } catch (e) { /* sem storage */ }
  for (const b of document.querySelectorAll("#rangeSel button")) b.classList.toggle("on", Number(b.dataset.range) === v);
}

document.getElementById("rangeSel").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-range]");
  if (b) setRange(Number(b.dataset.range));
});
const radarCanvas = document.getElementById("radarCanvas");
radarCanvas.addEventListener("mousemove", radarTip);
radarCanvas.addEventListener("click", radarClick);
radarCanvas.addEventListener("mouseleave", () => (document.getElementById("radarTip").hidden = true));
setRange(RD.range);
pollRadar();
requestAnimationFrame(loop);
