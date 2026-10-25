// WT Companion: painel do navegador. Lê /api/state (servidor local) e compara aviões.
"use strict";

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const nf = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const fmt = (v) => (v == null ? "—" : nf.format(v));
const fmtDec = (v, dec) => (v == null ? "—" : dec == null ? nf.format(v)
  : new Intl.NumberFormat("pt-BR", { minimumFractionDigits: dec, maximumFractionDigits: dec }).format(v));

let DB = null;        // { aircraft, names, version }
let STATE = null;     // última resposta de /api/state
let MANUAL = null;    // { id, nick } escolhido à mão
let SEARCH = [];      // índice de busca
let LIFE = null;      // partida + vida atual: quando muda (você caiu, nasceu de novo), sai do modo manual

const CLS = { fighter: "Caça", bomber: "Bombardeiro", assault: "Ataque ao solo" };
const SUB = {
  interceptor: "Interceptador", jet_fighter: "Caça a jato", dive_bomber: "Bombardeiro de mergulho",
  frontline_bomber: "Bombardeiro tático", longrange_bomber: "Bombardeiro pesado", light_bomber: "Bombardeiro leve",
  jet_bomber: "Bombardeiro a jato", torpedo: "Torpedeiro", naval_aircraft: "Naval (porta-aviões)",
  hydroplane: "Hidroavião", strike_aircraft: "Avião de ataque", aa_fighter: "Caça pesado",
};
const COUNTRY = {
  usa: "EUA", germany: "Alemanha", ussr: "URSS", britain: "Reino Unido", japan: "Japão", italy: "Itália",
  france: "França", china: "China", sweden: "Suécia", israel: "Israel",
};
const ORD = { bombs: "bombas", rockets: "foguetes", torpedoes: "torpedos", atgm: "mísseis AT", aam: "mísseis ar-ar", agm: "mísseis ar-solo", "guided bombs": "bombas guiadas" };

const plane = (id) => (id && DB ? DB.aircraft[id] : null);
const norm = (s) => String(s || "").replace(/[​-‍⁠﻿]/g, "").replace(/\s+/g, " ").trim().toLowerCase();
// o jogo põe símbolos da fonte dele antes de alguns nomes (▄, ◔…); fora do jogo viram quadrados
const nameOf = (a) => (a ? (a.name || a.id).replace(/\s+/g, " ").replace(/^[^\p{L}\p{N}(]+/u, "") : "?");
const isJet = (a) => a && (a.twr != null || a.tags.includes("jet_fighter") || a.tags.includes("jet_bomber"));
const heavy = (a) => a && (a.cls === "bomber" || a.cls === "assault");

// ------------------------------------------------------------------ inicialização

async function boot() {
  try {
    DB = await (await fetch("/data/aircraft.json")).json();
  } catch (e) {
    $("#fHero").innerHTML = `<p class="empty">Não consegui carregar o banco de aviões. O <b>companion.py</b> está rodando?</p>`;
    return;
  }
  SEARCH = Object.values(DB.aircraft).map((a) => ({
    id: a.id,
    keys: [a.name, a.full, a.short, a.pt, a.id].filter(Boolean).map(norm),
  }));
  $("#search").addEventListener("input", renderSearch);
  $("#saveNick").addEventListener("click", saveNick);
  $("#nick").addEventListener("keydown", (e) => e.key === "Enter" && saveNick());
  $("#nick").addEventListener("input", () => ($("#nick").dataset.touched = "1"));
  document.addEventListener("click", onClick);
  poll();
}

async function poll() {
  try {
    const r = await fetch("/api/state", { cache: "no-store" });
    STATE = await r.json();
  } catch (e) {
    STATE = { game: "down" };
  }
  const life = `${STATE.match}/${STATE.me?.life}/${STATE.me?.alive}`;
  if (LIFE !== null && life !== LIFE) MANUAL = null;
  LIFE = life;
  render();
  setTimeout(poll, 500);
}

async function saveNick() {
  const nick = $("#nick").value.trim();
  await fetch("/api/config", { method: "POST", body: JSON.stringify({ nick }) });
  delete $("#nick").dataset.touched;
}

function onClick(e) {
  const el = e.target.closest("[data-pick]");
  if (el) {
    MANUAL = { id: el.dataset.pick, nick: el.dataset.nick || null };
    $("#results").innerHTML = "";
    $("#search").value = "";
    render();
    window.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }
  if (e.target.closest("[data-auto]")) {
    MANUAL = null;
    render();
  }
}

// ------------------------------------------------------------------ fotos

function photo(id, cls, size) {
  const ph = `<span class="ph">✈<small>${esc(CLS[cls] || "")}</small></span>`;
  if (!id) return `<div class="photo ${size} noimg">${ph}</div>`;
  return `<div class="photo ${size}"><img src="/img/${encodeURIComponent(id)}.png" alt="" onerror="imgFail(this)">${ph}</div>`;
}

const thumb = (id) => (id ? `<img class="mini" src="/img/${encodeURIComponent(id)}.png" alt="" loading="lazy" onerror="imgFail(this)">` : `<span class="mini"></span>`);

// a foto pode ainda estar sendo baixada: tenta de novo algumas vezes antes de desistir
function imgFail(img) {
  const n = Number(img.dataset.tries || 0);
  if (n < 3) {
    img.dataset.tries = n + 1;
    setTimeout(() => { img.src = img.src.split("?")[0] + "?t=" + (n + 1); }, 1500 * (n + 1));
  } else if (img.classList.contains("mini")) {
    img.style.visibility = "hidden";
  } else {
    img.parentNode.classList.add("noimg");
  }
}

// ------------------------------------------------------------------ busca

function renderSearch() {
  const q = norm($("#search").value);
  const out = $("#results");
  if (q.length < 2) { out.innerHTML = ""; return; }
  const myBr = plane(STATE?.me?.id)?.br ?? null;
  const hits = [];
  for (const s of SEARCH) {
    let score = -1;
    for (const k of s.keys) {
      if (k === q) score = Math.max(score, 3);
      else if (k.startsWith(q)) score = Math.max(score, 2);
      else if (k.includes(q)) score = Math.max(score, 1);
    }
    if (score >= 0) hits.push({ id: s.id, score });
  }
  hits.sort((a, b) => b.score - a.score || brDist(a.id, myBr) - brDist(b.id, myBr));
  out.innerHTML = hits.slice(0, 10).map((h) => {
    const a = DB.aircraft[h.id];
    return `<li data-pick="${esc(a.id)}">${thumb(a.id)}<span class="grow">${esc(nameOf(a))}<span class="nick">${esc(CLS[a.cls] || a.cls)} · ${esc(COUNTRY[a.country] || a.country)}</span></span><span class="meta">BR ${fmt(a.br)}</span></li>`;
  }).join("") || `<li class="muted">Nada encontrado</li>`;
}

function brDist(id, br) {
  const a = DB.aircraft[id];
  return br == null || a.br == null ? 0 : Math.abs(a.br - br);
}

// ------------------------------------------------------------------ escolha do foco

// o servidor já limpa o que não vale mais: alvo e combate só com você vivo, e só com quem ainda voa
function autoFocus(S) {
  if (S.game !== "battle") return null;
  if (S.me && S.me.alive === false) {
    // deadFor vazio: ainda não nasceu nesta partida (não caiu)
    return S.me.deadFor != null && S.killer && S.killer.id ? { id: S.killer.id, player: S.killer, src: "killer" } : null;
  }
  const t = S.target;
  if (t) {
    if (t.who && t.who.id) return { id: t.who.id, player: t.who, src: "target", target: t };
    return { id: null, src: "target", target: t, cls: t.cls, candidates: t.candidates || [] };
  }
  if (S.engaged && S.engaged.id) return { id: S.engaged.id, player: S.engaged, src: "engaged" };
  return null;
}

// de onde veio o nome do alvo travado
const HOW_NOTE = {
  call: () => "marcado no rádio do time",
  hit: (t) => `você acertou ele na sua frente há ${t.age}s`,
  hitme: (t) => `ele te acertou apontando para você há ${t.age}s`,
  feed: (t) => `trocou tiros com um avião já reconhecido há ${t.age}s`,
  pair: (t) => `pela posição numa troca de tiros com um aliado há ${t.age}s`,
  kill: (t) => `pela posição num abate há ${t.age}s`,
};

const SRC_LABEL = {
  target: "🎯 Alvo travado",
  engaged: "💥 Em combate com você",
  killer: "☠ Te derrubou",
  manual: "📌 Escolhido por você",
};

// ------------------------------------------------------------------ render geral

const htmlCache = {};
function setHtml(sel, html) {
  if (htmlCache[sel] !== html) { $(sel).innerHTML = html; htmlCache[sel] = html; }
}

function render() {
  const S = STATE || {};
  renderHeader(S);
  if (!DB) return;

  const focus = MANUAL ? { id: MANUAL.id, src: "manual", player: findPlayer(S, MANUAL.nick) } : autoFocus(S);
  const me = plane(S.me?.id);

  const alertText = danger(S.target) || chaser(S);
  $("#alert").hidden = !alertText;
  setHtml("#alert", alertText);

  // confirmação rápida do seu abate; o card já foi para o próximo alvo
  const fl = S.flash && S.flash.id ? S.flash : null;
  $("#flash").hidden = !fl;
  setHtml("#flash", fl ? `✓ Você derrubou <b>${esc(nameOf(plane(fl.id)))}</b> <span class="muted">${esc(fl.nick)}</span>` : "");

  $("#manualBar").hidden = !MANUAL;
  setHtml("#manualBar", MANUAL ? `Modo manual: mostrando o avião que você escolheu. <button class="link" data-auto>Voltar ao automático</button>` : "");

  renderStrip(S, focus);
  if (focus) renderFocus(focus, me, S);
  else renderEmpty(S, me);

  renderPlayers(S, focus);
  renderRadar(S);
  renderLog(S);
  const nickBox = $("#nick");
  if (document.activeElement !== nickBox && !nickBox.dataset.touched) {
    nickBox.value = S.me?.nick || "";
    if (!S.me?.nick && S.me?.nickGuess) nickBox.placeholder = `parece ser: ${S.me.nickGuess}`;
  }
  setHtml("#dbInfo", `Banco: ${Object.keys(DB.aircraft).length} aviões · jogo ${esc(DB.version)} · gerado ${esc(DB.built)}`);
}

function findPlayer(S, nick) {
  if (!nick) return null;
  return (S.players || []).find((p) => p.nick === nick) || null;
}

function renderHeader(S) {
  const st = $("#status");
  const labels = { battle: "Em batalha", hangar: "No hangar", offline: "Jogo fechado", down: "Companion parado" };
  st.className = "pill " + (S.game === "battle" ? "battle" : S.game === "hangar" ? "hangar" : "offline");
  st.textContent = labels[S.game] || "Conectando…";

  const me = plane(S.me?.id);
  setHtml("#mine", me
    ? `${thumb(me.id)}<span>Você: <b>${esc(nameOf(me))}</b> · BR ${fmt(me.br)} · ${esc(CLS[me.cls] || me.cls)}</span>`
    : S.game === "battle" ? "Entre num avião para eu reconhecer o seu" : "");

  const dive = $("#dive");
  const ias = S.me?.ias;
  if (me && me.vne && ias != null && S.game === "battle") {
    const pct = Math.min(100, (ias / me.vne) * 100);
    const lvl = pct >= 95 ? "crit" : pct >= 85 ? "warn" : "";
    dive.hidden = false;
    dive.innerHTML = `<span>${fmt(Math.round(ias))} km/h · ${fmt(Math.round(S.me.alt || 0))} m</span>
      <span title="Velocidade indicada / limite estrutural (acima disso as asas quebram)">Mergulho</span>
      <span class="meter ${lvl}"><i style="width:${pct.toFixed(0)}%"></i></span>
      <span>${fmt(me.vne)}</span>`;
  } else {
    dive.hidden = true;
  }
}

function renderStrip(S, focus) {
  const strip = $("#targetStrip");
  const t = S.target;
  // quando o foco não é o alvo travado (modo manual), mostra o alvo numa faixa
  if (!t || (focus && focus.src === "target")) { strip.hidden = true; return; }
  strip.hidden = false;
  const who = t.who && t.who.id ? nameOf(plane(t.who.id)) : (CLS[t.cls] || "Inimigo");
  setHtml("#targetStrip", `🎯 Alvo travado: <b>${esc(who)}</b> ${targetGeo(t)} <button class="link" data-auto>Mostrar alvo</button>`);
}

function danger(t) {
  if (!t || t.dist == null) return "";
  if (t.towardMe && t.dist < 1500 && t.clock >= 4 && t.clock <= 8) return "⚠ ELE ESTÁ ATRÁS DE VOCÊ";
  if (t.towardMe && t.dist < 1200 && (t.clock >= 11 || t.clock <= 1)) return "⚠ VINDO DE FRENTE (HEAD-ON)";
  return "";
}

// qualquer inimigo (travado ou não) colado atrás de você e apontando para você
function chaser(S) {
  if (S.game !== "battle") return "";
  const e = (S.radar?.nearest || []).find((x) => x.towardMe && x.dist != null && x.dist < 1200 && x.clock >= 4 && x.clock <= 8);
  if (!e) return "";
  const who = e.id ? nameOf(plane(e.id)) : (CLS[e.cls] || "inimigo").toUpperCase();
  return `⚠ ${esc(who)} ATRÁS DE VOCÊ · ${e.dist} m · ${e.clock}h`;
}

function targetGeo(t) {
  const parts = [];
  if (t.dist != null) parts.push(t.dist >= 1000 ? `${nf.format(t.dist / 1000)} km` : `${t.dist} m`);
  if (t.clock) parts.push(`às ${t.clock} horas`);
  if (t.closing != null && Math.abs(t.closing) >= 5) parts.push(t.closing > 0 ? `aproximando ${t.closing} m/s` : `afastando ${-t.closing} m/s`);
  if (t.towardMe) parts.push("apontando para você");
  return parts.length ? "· " + parts.join(" · ") : "";
}

// ------------------------------------------------------------------ card principal

function renderEmpty(S, me) {
  const ingame = S.game === "battle";
  const out = ingame && S.me && S.me.alive === false;
  const dead = out && S.me.deadFor != null;
  const mine = me ? `<div class="mine-card">${photo(me.id, me.cls, "small")}<div><b>Seu avião: ${esc(nameOf(me))}</b><p class="hint">${esc(quickSelf(me))}</p></div></div>` : "";
  if (out) {
    setHtml("#fHead", `<span class="src">${dead ? "☠ Você caiu" : "Aguardando você nascer"}</span>`);
    setHtml("#fHero", `<div class="empty"><h1>${dead ? "Você caiu" : "Escolha o seu avião"}</h1>
      <p>${dead ? "Escolha o próximo avião. " : ""}O painel começa a procurar alvos quando você estiver no ar.</p></div>`);
    setHtml("#fTactic", "");
    setHtml("#fTiles", "");
    $("#fDetails").hidden = true;
    return;
  }
  setHtml("#fHead", `<span class="src">${ingame ? "Aguardando alvo" : "Sem partida"}</span>`);
  setHtml("#fHero", `<div class="empty">
    <h1>${ingame ? "Trave um inimigo" : S.game === "down" ? "O companion.py não está rodando" : "Entre numa batalha aérea"}</h1>
    <ol>
      <li><b>Trave o alvo</b> no jogo: aparece a classe e a distância na hora.</li>
      <li><b>Atire nele</b>: quando o kill feed disser que você acertou, o painel liga o nome ao avião que estava na frente do seu nariz.</li>
      <li>Ele te acertou? Quem estava apontando para você é reconhecido do mesmo jeito.</li>
      <li>O painel também aprende sozinho com as brigas dos aliados e com o rádio deles: quem é marcado pisca no mapa.</li>
      <li>Quer o modelo antes de atirar? Ligue o rádio rápido <b>"Attack [alvo]!"</b> a uma tecla (passo a passo no README) e aperte <b>uma vez</b> com o alvo travado. Não repita em sequência: o chat bloqueia por spam.</li>
      <li>Se alguém te derrubar, aparece quem foi e como vencer aquele avião.</li>
      <li>Ou busque qualquer avião em <b>Comparar com…</b></li>
    </ol>
    ${mine}
  </div>`);
  setHtml("#fTactic", "");
  setHtml("#fTiles", "");
  $("#fDetails").hidden = true;
}

function quickSelf(me) {
  const bits = [];
  if (me.speed) bits.push(`${fmt(me.speed)} km/h máx.`);
  if (me.climb) bits.push(`sobe ${fmt(me.climb)} m/s`);
  if (me.turn) bits.push(`curva em ${fmt(me.turn)} s`);
  if (me.vne) bits.push(`mergulho até ${fmt(me.vne)} km/h`);
  return bits.join(" · ");
}

function renderFocus(f, me, S) {
  const en = plane(f.id);
  const t = f.target || null;

  // linha de cima: de onde veio + posição ao vivo
  const live = [];
  if (f.src === "engaged" && f.player) live.push(`${f.player.dir === "out" ? "você acertou ele" : "ele te acertou"} há ${f.player.age}s`);
  if (f.src === "killer" && f.player) live.push(`há ${f.player.age}s`);
  if (t) live.push(targetGeo(t).replace(/^· /, ""));
  if (t?.alt) live.push(`altitude dele ~${fmt(t.alt.value)} m (há ${t.alt.age}s) · você ${fmt(Math.round(S.me?.alt || 0))} m`);
  setHtml("#fHead", `<span class="src">${SRC_LABEL[f.src] || ""}</span><span class="live">${live.filter(Boolean).map(esc).join(" · ")}</span>`);

  if (!en) return renderUnknown(f, me, t);

  const a = me ? analyze(me, en) : null;
  const pilot = [];
  if (f.player) pilot.push(`Piloto <b>${esc(f.player.nick)}</b>`);
  if (f.player?.kills) pilot.push(`${f.player.kills} abate(s) na partida`);
  if (f.src === "target" && t && HOW_NOTE[t.how]) pilot.push(`<span class="muted">${t.sure ? "certo" : "provável"}: ${HOW_NOTE[t.how](t)}</span>`);

  const badges = [
    `<span class="badge cls">${esc(CLS[en.cls] || en.cls)}</span>`,
    ...en.tags.filter((g) => SUB[g]).map((g) => `<span class="badge">${esc(SUB[g])}</span>`),
    `<span class="badge">BR ${fmt(en.br)}</span>`,
    `<span class="badge">${esc(COUNTRY[en.country] || en.country)}</span>`,
  ].join("");

  setHtml("#fHero", `${photo(en.id, en.cls, "big")}
    <div class="ident">
      <h1>${esc(nameOf(en))}</h1>
      <div class="badges">${badges}</div>
      ${pilot.length ? `<p class="pilot">${pilot.join(" · ")}</p>` : ""}
      ${a ? `<div class="ov ${a.overall.cls}"><span class="ico">${a.overall.icon}</span>${a.overall.text}</div>` : `<p class="hint">Entre num avião para eu comparar com o seu.</p>`}
    </div>`);

  setHtml("#fTactic", a ? `<div class="tactic"><div class="tname">${a.tactic.name}</div><div class="tline">${a.tactic.line}</div></div>` : "");
  setHtml("#fTiles", a ? `<div class="tiles">${a.tiles.map(tileHtml).join("")}</div>` : "");

  $("#fDetails").hidden = false;
  setHtml("#fDetailsBody", `${a ? `<p class="plan">${a.plan}</p>
      <div class="tips">
        <div><h3>A seu favor</h3><ul>${a.how.map((x) => `<li>${x}</li>`).join("") || "<li>Nada que se destaque.</li>"}</ul></div>
        <div><h3>Cuidado</h3><ul>${a.beware.map((x) => `<li>${x}</li>`).join("") || "<li>Nada que se destaque.</li>"}</ul></div>
      </div>` : ""}
    ${compareTable(me, en)}
    ${armsBlock(me, en)}`);
}

function renderUnknown(f, me, t) {
  const cls = f.cls || t?.cls;
  const cands = (f.candidates || []).filter((c) => c.id);
  setHtml("#fHero", `${photo(null, cls, "big")}
    <div class="ident">
      <h1>${esc(CLS[cls] || "Inimigo")} inimigo</h1>
      <div class="ov warn"><span class="ico">?</span>MODELO AINDA DESCONHECIDO</div>
      <p class="pilot">Acerte uns tiros nele: quando o kill feed disser que você acertou, o painel liga o nome a este avião. Com pressa? Aperte sua tecla de rádio rápido (<b>"Attack…"</b>) uma vez.</p>
    </div>`);
  setHtml("#fTactic", cands.length ? `<div class="tactic"><div class="tname">Pode ser um destes</div><div class="tline">Inimigos dessa classe vistos no kill feed (quem trocou tiros com você vem primeiro). Clique para comparar.</div>
    <div class="cands">${cands.map((c) => {
      const a = plane(c.id);
      return `<button class="chip" data-pick="${esc(c.id)}" data-nick="${esc(c.nick)}">${thumb(c.id)}<span>${esc(nameOf(a))}<small>${esc(c.nick)} · BR ${fmt(a?.br)}</small></span></button>`;
    }).join("")}</div></div>` : "");
  setHtml("#fTiles", "");
  $("#fDetails").hidden = false;
  setHtml("#fDetailsBody", classTips(cls, me));
}

function tileHtml(t) {
  const big = { me: "VOCÊ", en: "ELE", eq: "EMPATE", na: "—" }[t.who];
  const icon = { me: "▲", en: "▼", eq: "=", na: "" }[t.who];
  return `<div class="tile ${t.cls || t.who}" title="${esc(t.title || "")}">
    <span class="tlabel">${t.label}</span>
    <span class="tval"><span class="ico">${t.icon ?? icon}</span>${t.big ?? big}</span>
    <span class="tnum">${t.nums}</span></div>`;
}

// ------------------------------------------------------------------ comparação

const ROWS = [
  { k: "speed", label: "Velocidade máxima", unit: "km/h", better: "high", tol: 0.03, note: (a) => (a.speedAlt ? `a ${fmt(a.speedAlt)} m` : "") },
  { k: "climb", label: "Subida", unit: "m/s", better: "high", tol: 0.07 },
  { k: "turn", label: "Curva de 360°", unit: "s", better: "low", tol: 0.05 },
  { k: "roll", label: "Rolagem", unit: "°/s", better: "high", tol: 0.08 },
  { k: "vne", label: "Limite de mergulho", unit: "km/h", better: "high", tol: 0.03 },
  { k: "ceiling", label: "Teto", unit: "m", better: "high", tol: 0.05 },
  { k: "pwr", label: "Potência / peso", unit: "hp/kg", better: "high", tol: 0.06, dec: 2 },
  { k: "twr", label: "Empuxo / peso", unit: "", better: "high", tol: 0.06, dec: 2 },
  { k: "mass", label: "Peso de decolagem", unit: "kg", better: null, dec: 0 },
  { k: "br", label: "BR (arcade)", unit: "", better: null },
];
const ROW = Object.fromEntries(ROWS.map((r) => [r.k, r]));

function verdict(row, mv, ev) {
  if (!row.better || mv == null || ev == null) return "na";
  const rel = (mv - ev) / Math.max(Math.abs(ev), 1e-9);
  if (Math.abs(rel) <= row.tol) return "eq";
  return (row.better === "high" ? mv > ev : mv < ev) ? "me" : "en";
}

function compareTable(me, en) {
  const rows = ROWS.filter((r) => en[r.k] != null || (me && me[r.k] != null));
  const bar = (cls, val, max, a) => `<div class="cbar">
      <div class="track"><div class="bar ${cls}" style="width:${((val || 0) / max * 100).toFixed(1)}%"></div></div>
      <span class="num">${fmtDec(val, a.dec)} <span class="unit">${a.unit}</span>${a.note ? ` <span class="unit">${a.note}</span>` : ""}</span></div>`;
  const body = rows.map((r) => {
    const mv = me ? me[r.k] : null;
    const ev = en[r.k];
    const max = Math.max(mv || 0, ev || 0) || 1;
    const v = me ? verdict(r, mv, ev) : "na";
    const vtxt = { me: "▲ Você", en: "▼ Ele", eq: "= Igual", na: "" }[v];
    const tip = `${r.label}: você ${fmt(mv)} ${r.unit} · ele ${fmt(ev)} ${r.unit}${r.better === "low" ? " (menor é melhor)" : ""}`;
    return `<div class="crow" title="${esc(tip)}">
      <div class="chead"><span>${r.label}${r.better === "low" ? ` <span class="unit">(menor = melhor)</span>` : ""}</span><span class="v-${v}">${vtxt}</span></div>
      ${me ? bar("me", mv, max, { unit: r.unit, dec: r.dec, note: r.note ? esc(r.note(me)) : "" }) : ""}
      ${bar("en", ev, max, { unit: r.unit, dec: r.dec, note: r.note ? esc(r.note(en)) : "" })}</div>`;
  }).join("");
  return `<h3>Ficha comparada</h3>
    <div class="legend">${me ? `<span><i style="background:var(--me)"></i>Você: ${esc(nameOf(me))}</span>` : ""}<span><i style="background:var(--en)"></i>Ele: ${esc(nameOf(en))}</span></div>
    <div class="cmp">${body}</div>
    <p class="hint">Valores da ficha do jogo (datamine). No arcade os números absolutos mudam, mas a diferença entre os dois aviões vale.</p>`;
}

function armsBlock(me, en) {
  const side = (a, who, cls) => {
    const guns = a.guns.length ? a.guns.map((x) => `${x.count}× ${esc(x.name)}`) : ["sem armas fixas"];
    const tur = a.turrets.map((t, i) => `Artilheiro ${i + 1}: ${t.guns.map((g) => `${g.count}× ${esc(g.name)}`).join(", ")}`);
    const ord = a.ordnance.length ? [`Pode levar ${a.ordnance.map((o) => ORD[o] || o).join(", ")}`] : [];
    return `<div><span class="dot ${cls}"></span><span class="who">${who}</span>
      <ul>${[...guns, ...tur, ...ord].map((x) => `<li>${x}</li>`).join("")}</ul></div>`;
  };
  return `<h3>Armamento</h3><div class="arms">${side(en, "Ele: " + esc(nameOf(en)), "en")}${me ? side(me, "Você: " + esc(nameOf(me)), "me") : ""}</div>`;
}

// poder de fogo frontal aproximado: soma de (calibre/7,62)^2 por arma
function firepower(a) {
  let s = 0;
  for (const g of a.guns) {
    const m = /(\d+(?:\.\d+)?)\s*mm/.exec(g.name);
    const cal = m ? parseFloat(m[1]) : 7.62;
    s += g.count * Math.pow(cal / 7.62, 2);
  }
  return s;
}

function maxCaliber(guns) {
  let c = 0;
  for (const g of guns) {
    const m = /(\d+(?:\.\d+)?)\s*mm/.exec(g.name);
    if (m) c = Math.max(c, parseFloat(m[1]));
  }
  return c;
}

function turretGuns(a) {
  return a.turrets.reduce((n, t) => n + t.guns.reduce((m, g) => m + g.count, 0), 0);
}

// ------------------------------------------------------------------ análise e dicas

function statTile(k, label, me, en) {
  const r = ROW[k];
  const fmtU = (v) => `${fmtDec(v, r.dec)} ${r.unit}`;
  return {
    label, who: verdict(r, me[k], en[k]),
    nums: `<span><i class="dot me"></i>você ${fmtU(me[k])}</span><span><i class="dot en"></i>ele ${fmtU(en[k])}</span>`,
    title: `${r.label}: você ${fmtU(me[k])} · ele ${fmtU(en[k])}`,
  };
}

function gunnerTile(en) {
  const n = en.turrets.length;
  const g = turretGuns(en);
  return {
    label: "Artilheiros", who: n === 0 ? "me" : "en", cls: n === 0 ? "me" : n <= 2 ? "warn" : "en",
    icon: n === 0 ? "✓" : "!", big: n === 0 ? "NENHUM" : String(n),
    nums: n === 0 ? "pode atacar por trás" : `${g} arma(s) defensiva(s)`,
  };
}

function analyze(me, en) {
  const V = {};
  for (const r of ROWS) V[r.k] = verdict(r, me[r.k], en[r.k]);
  const how = [];
  const beware = [];
  let plan = "";
  let tactic;
  let overall;
  let tiles;
  const enHeavy = heavy(en);
  const meHeavy = heavy(me);
  const dSpeed = me.speed && en.speed ? me.speed - en.speed : 0;
  const dClimb = me.climb && en.climb ? me.climb - en.climb : 0;
  const nTur = en.turrets.length;

  if (enHeavy) {
    const kind = en.cls === "bomber" ? "Bombardeiro" : "Avião de ataque";
    tiles = [gunnerTile(en), statTile("speed", "Mais rápido", me, en), statTile("climb", "Sobe melhor", me, en), statTile("turn", "Curva melhor", me, en)];
    if (nTur) {
      tactic = { name: "↘ Passadas rápidas", line: "Venha de cima e de lado, mire motor e asa, e saia. Não fique atrás dele." };
      overall = nTur >= 3 ? { cls: "bad", icon: "!", text: `Cuidado: ${nTur} artilheiros` } : { cls: "warn", icon: "!", text: `Atenção: ${nTur} artilheiro(s)` };
      plan = `${kind} com ${nTur} artilheiro(s) (${turretGuns(en)} arma(s) defensiva(s)). Não fique colado atrás dele na mesma altura: é onde os artilheiros acertam. Faça passadas rápidas vindo de cima e de lado, mirando motores e asas, e saia sem parar atrás dele.`;
    } else {
      tactic = { name: "→ Ataque por trás", line: "Sem artilheiros: chegue por trás e mire nos motores e nas asas." };
      overall = { cls: "good", icon: "✓", text: "Alvo fácil: sem artilheiros" };
      plan = `${kind} sem artilheiros: dá para atacar por trás com calma. Mire nos motores e nas asas.`;
    }
    if (dSpeed > 15) how.push(`Ele é lento (${fmt(en.speed)} km/h contra ${fmt(me.speed)} km/h): você alcança fácil, mas não chegue rápido demais e passe na frente dele.`);
    else if (dSpeed < -15) beware.push(`Ele é rápido para a classe (${fmt(en.speed)} km/h): para alcançá-lo, venha de cima com altitude de sobra.`);
    if ((en.mass || 0) > 15000 || (en.crew || 0) >= 6) how.push("É grande e resistente: concentre os tiros numa asa ou num motor em vez de espalhar pela fuselagem.");
    if (en.climb && me.climb && me.climb > en.climb + 3) how.push(`Ele sobe só ${fmt(en.climb)} m/s: suba acima dele antes de atacar e mergulhe para a passada.`);
    if (nTur >= 3) beware.push("Muitas torres cobrindo quase todos os ângulos: ataques por baixo e de frente costumam ter menos armas apontadas para você.");
    if (en.guns.length && firepower(en) >= firepower(me) * 0.8) beware.push(`Tem armas fixas fortes na frente (${en.guns.map((g) => `${g.count}× ${g.name.replace(/ (machine gun|cannon)$/i, "")}`).join(", ")}): evite atacar de frente.`);
    if (meHeavy) how.push("Você também está num avião pesado: deixe os caças do time lidarem com ele se não tiver vantagem de altura.");
  } else {
    tiles = [statTile("turn", "Curva melhor", me, en), statTile("speed", "Mais rápido", me, en), statTile("climb", "Sobe melhor", me, en), statTile("vne", "Mergulha mais", me, en)];
    const score = tiles.reduce((s, t) => s + (t.who === "me" ? 1 : t.who === "en" ? -1 : 0), 0);
    overall = score >= 2 ? { cls: "good", icon: "▲", text: "Vantagem sua" }
      : score === 1 ? { cls: "good", icon: "▲", text: "Leve vantagem sua" }
      : score === 0 ? { cls: "eq", icon: "=", text: "Equilibrado" }
      : score === -1 ? { cls: "warn", icon: "▼", text: "Leve vantagem dele" }
      : { cls: "bad", icon: "▼", text: "Vantagem dele" };

    if (meHeavy) {
      tactic = { name: "✈ Voe reto e peça ajuda", line: "Não curve com ele. Deixe seus artilheiros atirarem e fique perto dos aliados." };
      overall = { cls: "bad", icon: "!", text: "Perigo para você" };
      plan = "Você está num avião pesado contra um caça. Não tente curvar com ele: voe reto e estável para seus artilheiros mirarem, fique perto dos aliados e da antiaérea do aeródromo.";
      if (!me.turrets.length) beware.push("Você não tem artilheiros: se ele chegar por trás, faça curvas de lado e mude de altitude o tempo todo, e corra para os aliados.");
      if (V.speed === "me") how.push(`Você é mais rápido (${fmt(me.speed)} vs ${fmt(en.speed)} km/h): mantenha velocidade e ele não te alcança.`);
      if (me.guns.length && firepower(me) > firepower(en) * 1.2) how.push("Seu armamento frontal é forte: se ele vier de frente, dá para responder.");
    } else {
      const turn = V.turn;
      const energyMe = ["speed", "climb", "vne"].filter((k) => V[k] === "me").length;
      const energyEn = ["speed", "climb", "vne"].filter((k) => V[k] === "en").length;
      if (turn === "me" && energyEn >= 1) {
        tactic = { name: "↻ Curve com ele", line: "Puxe para curvas fechadas. Se ele mergulhar em você, desvie no último segundo." };
        plan = "Puxe a luta para curvas fechadas (turnfight). Você curva melhor, mas ele tem mais energia: vai tentar mergulhar em você e subir de novo (boom & zoom). Quando ele vier mergulhando, curve forte no último segundo para o lado dele e não o persiga subindo.";
      } else if (turn === "en" && energyMe >= 1) {
        tactic = { name: "↘↗ Boom & Zoom", line: "Ataque de cima, atire e suba de novo. Não curve com ele." };
        plan = "Boom & Zoom: ganhe altura, mergulhe nele, atire numa passada rápida e suba de novo. Nunca entre em curva fechada com ele, porque ele curva melhor.";
      } else if (turn === "en" && energyEn >= 1) {
        tactic = { name: "⚑ Não lute sozinho", line: "Ele é melhor em quase tudo. Fique com aliados e ataque quando ele estiver distraído." };
        plan = "Ele é melhor em curva e em energia. Evite o 1 contra 1: fique perto dos aliados, ataque quando ele estiver ocupado com outro e não gaste altitude à toa.";
      } else if (turn === "me" && energyEn === 0) {
        tactic = { name: "▲ Vá pra cima", line: "Você é melhor ou igual em tudo. Ataque de cima e, se ele se defender, curve com ele." };
        plan = "Você é melhor ou igual em tudo: escolha a luta. O mais seguro é atacar de cima e, se ele se defender, levá-lo para as curvas.";
      } else if (turn === "eq" && energyMe > energyEn) {
        tactic = { name: "↘↗ Use sua energia", line: "Ataque de cima, use velocidade e subida. Não fique preso em curva lenta." };
        plan = "Curvam parecido, mas você tem mais energia. Ataque de cima e use velocidade e subida para escolher quando lutar. Não fique preso em curva lenta.";
      } else if (turn === "eq" && energyEn > energyMe) {
        tactic = { name: "↓ Lute baixo e lento", line: "Não persiga subindo. Force ele a curvar perto do chão." };
        plan = "Curvam parecido, mas ele tem mais energia. Não persiga subindo e não deixe ele ficar acima de você. Lute baixo e devagar, onde a vantagem dele some.";
      } else {
        tactic = { name: "↑ Altitude vence", line: "Aviões parecidos: chegue mais alto e mais rápido que ele." };
        plan = "Aviões muito parecidos: vence quem chegar com mais altitude e velocidade. Suba antes de entrar na luta e mire bem no indicador de antecipação.";
      }
      if (V.turn === "me") how.push(`Você fecha a curva em ${fmt(me.turn)} s contra ${fmt(en.turn)} s dele.`);
      if (V.turn === "en") beware.push(`Ele fecha a curva em ${fmt(en.turn)} s contra ${fmt(me.turn)} s seu: em curva sustentada ele chega na sua cauda.`);
      if (V.roll === "me") how.push(`Você rola mais rápido (${fmt(me.roll)} vs ${fmt(en.roll)} °/s): troque de direção de repente (tesoura) para ele errar os tiros.`);
      if (V.roll === "en") beware.push(`Ele rola mais rápido (${fmt(en.roll)} vs ${fmt(me.roll)} °/s): não adianta tentar se esquivar só girando.`);
      if (isJet(en) && !isJet(me)) beware.push("Ele é a jato: muito mais rápido em linha reta, mas acelera devagar. Force curvas e espere ele passar.");
    }
  }

  // regras que valem para qualquer par
  if (!enHeavy) {
    if (dClimb > 2) how.push(`Você sobe ${fmt(me.climb)} m/s contra ${fmt(en.climb)}: se ele estiver atrás, suba em ângulo suave e ele fica para trás.`);
    if (dClimb < -2) beware.push(`Não tente fugir subindo: ele sobe ${fmt(en.climb)} m/s e você ${fmt(me.climb)}.`);
    if (dSpeed > 15) how.push(`Você é ${fmt(dSpeed)} km/h mais rápido: dá para sair da luta em linha reta quando quiser.`);
    if (dSpeed < -15) beware.push(`Ele é ${fmt(-dSpeed)} km/h mais rápido: fugir em linha reta não funciona.`);
  }
  if (me.vne && en.vne) {
    const dv = me.vne - en.vne;
    if (dv >= 80) how.push(`No mergulho você aguenta até ${fmt(me.vne)} km/h e ele só ${fmt(en.vne)}: num mergulho longo e bem inclinado ele tem que desistir antes de você.`);
    else if (dv >= 30) how.push(`Seu limite de mergulho é um pouco maior (${fmt(me.vne)} vs ${fmt(en.vne)} km/h): ajuda, mas não conte só com isso para fugir.`);
    if (dv <= -30) beware.push(`Cuidado ao mergulhar: seu limite é ${fmt(me.vne)} km/h e o dele ${fmt(en.vne)}. Ele te segue no mergulho e suas asas quebram antes.`);
  }
  if (!enHeavy && me.guns.length && en.guns.length) {
    const fm = firepower(me), fe = firepower(en);
    if (fe > fm * 1.5) beware.push(`Poder de fogo dele bem maior (até ${maxCaliber(en.guns)} mm): evite tiro de frente (head-on).`);
    else if (fm > fe * 1.5) how.push(`Seu armamento é mais forte (até ${maxCaliber(me.guns)} mm): rajadas curtas bastam, e o head-on te favorece.`);
  }
  if (me.br != null && en.br != null && Math.abs(en.br - me.br) >= 0.7) {
    (en.br > me.br ? beware : how).push(`Ele está ${fmt(Math.abs(en.br - me.br))} BR ${en.br > me.br ? "acima" : "abaixo"} de você.`);
  }
  return { plan, how, beware, tactic, overall, tiles };
}

function classTips(cls, me) {
  if (cls === "bomber" || cls === "assault") {
    return `<h3>Dicas para ${cls === "bomber" ? "bombardeiros" : "aviões de ataque"}</h3><ul>
      <li>Quase sempre têm artilheiros traseiros: não fique colado atrás dele na mesma altura.</li>
      <li>Ataque de cima e de lado em passadas rápidas, mirando motores e asas.</li>
      <li>São pesados e curvam mal: depois da passada, suba e repita.</li></ul>`;
  }
  return `<h3>Dicas para caças</h3><ul>
    <li>Não entre em curva com ele antes de saber o modelo: muitos caças curvam melhor do que parecem.</li>
    <li>Altitude é vida: quem está mais alto escolhe a luta.</li>
    ${me ? `<li>Seu avião: ${esc(quickSelf(me))}.</li>` : ""}</ul>`;
}

// ------------------------------------------------------------------ listas laterais

function renderPlayers(S, focus) {
  const players = S.players || [];
  const enemies = players.filter((p) => p.side === "enemy" && p.id);
  const others = players.filter((p) => p.side !== "enemy" && !p.me && p.id);
  enemies.sort((a, b) => (a.dead - b.dead) || (plane(a.id)?.br ?? 0) - (plane(b.id)?.br ?? 0));
  const item = (p, extra) => {
    const a = plane(p.id);
    const active = focus && focus.id === p.id && (!focus.player || focus.player.nick === p.nick);
    return `<li data-pick="${esc(p.id)}" data-nick="${esc(p.nick)}" class="${p.dead ? "dead" : ""} ${active ? "active" : ""}">
      ${thumb(p.id)}<span class="grow">${esc(nameOf(a))}<span class="nick">${esc(p.nick)}${p.dead ? " · abatido" : ""}${p.kills ? ` · ${p.kills} abate(s)` : ""}${extra || ""}</span></span>
      <span class="meta">${esc(CLS[a?.cls] || "")}<br>BR ${fmt(a?.br)}</span></li>`;
  };
  setHtml("#enemies", enemies.map((p) => item(p)).join("") || `<li class="muted">Ninguém ainda. Os inimigos aparecem quando o kill feed fala deles.</li>`);
  $("#enemyCount").textContent = enemies.length ? `(${enemies.length})` : "";
  $("#othersTitle").textContent = `Aliados e não identificados (${others.length})`;
  setHtml("#others", others.map((p) => item(p, ` · ${p.side === "ally" ? "aliado" : "time ?"}`)).join(""));
}

function renderRadar(S) {
  const r = S.radar;
  if (!r || S.game !== "battle") { setHtml("#radar", `<p class="hint">Disponível durante a batalha.</p>`); return; }
  const counts = Object.entries(r.counts || {}).map(([k, n]) => `<span>${n} ${esc(CLS[k] || k)}${n > 1 ? "s" : ""}</span>`).join("");
  const list = (r.nearest || []).map((e) => {
    const close = e.dist != null && e.dist < 1500 && e.towardMe;
    const who = e.id ? `${esc(nameOf(plane(e.id)))} <span class="muted">${esc(e.nick)}</span>` : esc(CLS[e.cls] || e.cls);
    return `<li class="${close ? "close" : ""}"><span>${e.target ? "🎯 " : ""}${who}${e.towardMe ? " →você" : ""}</span><span>${e.dist != null ? (e.dist >= 1000 ? nf.format(e.dist / 1000) + " km" : e.dist + " m") : "?"}${e.clock ? ` · ${e.clock}h` : ""}</span></li>`;
  }).join("");
  setHtml("#radar", `<div class="radar-counts">${counts || "<span>nenhum inimigo no mapa</span>"}${r.named ? `<span>${r.named} reconhecido(s)</span>` : ""}</div>
    <ul class="radar-list">${list}</ul><p class="hint">O nome aparece quando o kill feed ou o rádio revelam quem é. A altitude dos inimigos só aparece quando um aviso de rádio de aliado informa (o jogo não manda esse dado de outro jeito).</p>`);
}

function renderLog(S) {
  const items = (S.log || []).map((x) => `<li class="${esc(x.kind)}">${esc(x.text)} <span class="muted">· ${x.age}s</span></li>`);
  setHtml("#log", items.join("") || `<li class="muted">Seus abates, mortes e marcações aparecem aqui.</li>`);
}

boot();
