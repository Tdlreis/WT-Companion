"""War Thunder Companion: painel que identifica e compara o avião inimigo.

Usa somente a interface web oficial que o próprio jogo abre em http://localhost:8111
(a mesma do mapa no navegador). Não lê memória, não injeta nada, não manda nada no chat
e não mexe nos arquivos do jogo.

    python companion.py            abre o painel em http://localhost:8191
    python companion.py --lan      também libera o painel para o celular na mesma rede
"""
import json
import math
import os
import re
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(ROOT, "web")
DATA = os.path.join(ROOT, "data")
DB_FILE = os.path.join(DATA, "aircraft.json")
CONFIG_FILE = os.path.join(DATA, "config.json")
IMG_DIR = os.path.join(DATA, "img")
# fotos oficiais dos aviões, da wiki da Gaijin (mesmo id do datamine)
IMG_URL = "https://static.encyclopedia.warthunder.com/images/{}.png"
GAME = "http://127.0.0.1:8111"
PORT = 8191

MAP_CLASS = {"Fighter": "fighter", "Bomber": "bomber", "Assault": "assault"}
CLASS_ICON = {v: k for k, v in MAP_CLASS.items()}
SIDE_NAME = {0: "ally", 1: "enemy"}
# cor mais escura que o jogo usa nos primeiros segundos de um avião que acabou de nascer
SPAWN_COLORS = {"#e10b00", "#134aff"}
ZW = re.compile("[​‌‍⁠﻿]")
PLATFORM = re.compile(r"@(?:psn|live|xbox|steam)$", re.I)
# verbos do kill feed em inglês; para outros idiomas cai no modo genérico
VERBS = sorted(["shot down", "destroyed", "set afire", "severely damaged", "critically damaged",
                "damaged", "wrecked", "has destroyed", "has shot down"], key=len, reverse=True)
KILL_VERBS = {"shot down", "destroyed", "has shot down", "has destroyed", "wrecked"}
DAMAGE_VERBS = {"set afire", "severely damaged", "critically damaged", "damaged"}
VERB_PT = {"set afire": "pôs fogo em você", "critically damaged": "te danificou gravemente",
           "severely damaged": "te danificou bastante", "damaged": "te danificou"}

# peso de cada pista que liga um nome a um avião do mapa (ver Match.settle). Medido em
# gravações reais: tiro seu, tiro em você e rádio acertaram 100%; troca de tiros ~97%;
# abate ~78% (o crédito pode chegar bem depois do tiro), por isso ele sozinho não basta.
W_CALL = 5.0     # foi marcado no rádio (ou mandou mensagem no rádio) e piscou no mapa
W_HIT = 3.0      # você acertou e ele era o único inimigo na sua frente
W_HITME = 2.0    # ele te acertou e era o único apontando para você
W_FIGHT = 1.2    # trocou tiros com alguém já reconhecido
W_PAIR = 1.0     # troca de tiros entre dois aviões sem nome, sem outro par parecido
W_KILL = 0.6     # derrubou alguém e era o único apontando para a vítima
W_LABEL = 1.0    # mínimo para mostrar o nome
W_SURE = 2.5     # a partir daqui o nome é dado como certo
HISTORY = 8.0    # segundos de mapa guardados para olhar "quem estava na frente de quem"
GUN_RANGE = 1200  # m: até onde um tiro de armas fixas costuma acertar
GUN_CONE = 15     # graus: quanto o alvo pode estar fora do nariz (mira com antecipação)
TURRET_RANGE = 800  # m: artilheiros atiram para qualquer lado, mas de perto
LEAD = 5          # folga mínima do melhor candidato sobre o segundo (graus + m/100)
PAIR_LEAD = 8     # folga quando nenhum dos dois aviões da briga tem nome ainda


def normalize(s):
    s = ZW.sub("", s or "")
    return re.sub(r"\s+", " ", s).strip().lower()


def strip_glyphs(s):
    return re.sub(r"^[^\w\[(]+", "", ZW.sub("", s or "")).strip()


def nick_tokens(name):
    """Pedaços do nome sem a tag de esquadrão ("=MONTY="), o símbolo de plataforma ("⋇") e "@psn"."""
    s = PLATFORM.sub("", ZW.sub("", name or "").replace("\xa0", " ").strip())
    toks = [t for t in s.split() if re.search(r"\w", t)]
    if len(toks) >= 2 and looks_like_clan(toks[0]):
        toks = toks[1:]
    return [re.sub(r"^[^\w]+", "", t) for t in toks]


def nick_key(name):
    """Chave estável de um jogador: a mesma no kill feed, no chat e nas marcações de rádio."""
    return " ".join(nick_tokens(name)).lower()


def nick_display(name):
    return " ".join(nick_tokens(name))


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


# ---------------------------------------------------------------- banco de aviões

class Database:
    def __init__(self):
        raw = load_json(DB_FILE, None)
        if not raw:
            print("ERRO: data/aircraft.json não encontrado. Rode antes:  python build_db.py")
            sys.exit(1)
        self.version = raw.get("version")
        self.built = raw.get("built")
        self.aircraft = raw["aircraft"]
        self.names = raw["names"]

    def lookup(self, vehicle_name, ref_br=None, cls=None):
        """Converte o nome que aparece no jogo ("Bf 109 G") no id do datamine."""
        ids = (self.names.get(normalize(vehicle_name))
               or self.names.get(normalize(strip_glyphs(vehicle_name))) or [])
        ids = [i for i in ids if i in self.aircraft]
        if not ids:
            return None, []
        if cls:
            same = [i for i in ids if self.aircraft[i]["cls"] == cls]
            ids = same or ids
        if ref_br is not None:
            ids = sorted(ids, key=lambda i: (abs((self.aircraft[i]["br"] or 0) - ref_br), i))
        return ids[0], ids

    def cls(self, uid):
        a = self.aircraft.get(uid or "")
        return a["cls"] if a else None

    def br(self, uid):
        a = self.aircraft.get(uid or "")
        return a["br"] if a else None

    def gunners(self, uid):
        a = self.aircraft.get(uid or "")
        return bool(a and a.get("turrets"))


class Images:
    """Baixa a foto de cada avião na primeira vez e guarda em data/img."""

    def __init__(self, db):
        self.db = db
        self.queued = set()
        self.locks = {}
        self.locks_guard = threading.Lock()
        os.makedirs(IMG_DIR, exist_ok=True)

    def get(self, uid):
        if uid not in self.db.aircraft or not re.fullmatch(r"[A-Za-z0-9_.\-]+", uid):
            return None
        with self.locks_guard:
            lock = self.locks.setdefault(uid, threading.Lock())
        # um download por foto: quem chegar depois espera e lê o arquivo pronto
        with lock:
            path = os.path.join(IMG_DIR, uid + ".png")
            if os.path.exists(path):
                with open(path, "rb") as f:
                    return f.read()
            missing = path + ".missing"
            if os.path.exists(missing) and time.time() - os.path.getmtime(missing) < 86400:
                return None
            try:
                req = urllib.request.Request(IMG_URL.format(uid), headers={"User-Agent": "WTCompanion"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    data = r.read()
            except Exception:
                return None  # sem internet agora: tenta de novo depois
            if not data.startswith(b"\x89PNG"):
                open(missing, "w").close()
                return None
            with open(path, "wb") as f:
                f.write(data)
            return data

    def prefetch(self, uid):
        if not uid or uid in self.queued:
            return
        self.queued.add(uid)
        threading.Thread(target=self.get, args=(uid,), daemon=True).start()


# ---------------------------------------------------------------- leitura de mensagens

def paren_groups(msg):
    groups, depth, start = [], 0, 0
    for i, ch in enumerate(msg):
        if ch == "(":
            if depth == 0:
                start = i
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
            if depth == 0:
                groups.append((start, i))
    return groups


def looks_like_clan(tok):
    return len(tok) >= 3 and not tok[0].isalnum() and not tok[-1].isalnum()


def split_verb(text):
    for v in VERBS:
        if text.lower().startswith(v + " "):
            return v, text[len(v):].strip()
    toks = text.split()
    if len(toks) >= 3 and looks_like_clan(toks[-2]):
        return " ".join(toks[:-2]), " ".join(toks[-2:])
    if len(toks) >= 2:
        return " ".join(toks[:-1]), toks[-1]
    return text, ""


DISCONNECT = re.compile(r"^(.+?) has disconnected from the game")


def parse_feed(msg):
    """'A (Avião) shot down B (Avião2)' -> dict; None se não for entre dois jogadores."""
    msg = ZW.sub("", msg).replace("\xa0", " ").strip()
    g = paren_groups(msg)
    if not g:
        m = DISCONNECT.match(msg)
        return {"a": m.group(1), "av": "", "text": "has disconnected"} if m else None
    s0, e0 = g[0]
    a_name = msg[:s0].strip()
    a_veh = msg[s0 + 1:e0].strip()
    if not a_name:
        return None
    rest = msg[e0 + 1:].strip()
    if len(g) == 1 and rest in ("", ".", "!"):
        # "AAA shot down Fulano (Avião)": quem derrubou não é jogador
        m = re.match(r"^(.+?)\s+(%s)\s+(.+)$" % "|".join(map(re.escape, VERBS)), a_name)
        if m and m.group(2) in KILL_VERBS:
            return {"a": None, "av": "", "verb": m.group(2), "b": m.group(3), "bv": a_veh}
    if rest.startswith("has achieved") or len(g) < 2:
        return {"a": a_name, "av": a_veh, "text": rest}
    s1, e1 = g[-1]
    if msg[e1 + 1:].strip() not in ("", ".", "!"):
        return {"a": a_name, "av": a_veh, "text": rest}
    verb, b_name = split_verb(msg[e0 + 1:s1].strip())
    if not b_name or "[ai]" in b_name.lower():
        return {"a": a_name, "av": a_veh, "text": rest}
    return {"a": a_name, "av": a_veh, "verb": verb, "b": b_name, "bv": msg[s1 + 1:e1].strip()}


# mensagens de rádio que fazem o ícone de quem mandou piscar no mapa (texto digitado não faz)
SENDER_BLINK = re.compile(r"^(?:attention to the (?:map|designated grid)|thanks!|requesting a target)", re.I)
CALL_VERB = re.compile(r"^(?:someone,\s*)?(?:i'm\s+attacking|attack|eliminate|destroy)\s+", re.I)
CHAT_ALT = re.compile(r"([\d][\d.,\s]*)\s*m\s*\]")


def parse_chat_call(msg):
    """'Attack Fulano(F4U)! [F4, alt. 3200 m]' -> (nick, avião, altitude)."""
    clean = re.sub(r"<color=[^>]*>|</color>", "", ZW.sub("", msg)).replace("\xa0", " ")
    g = paren_groups(clean)
    if not g:
        return None
    s, e = g[-1]  # o avião é o último parêntese; o "[E4, alt. 1500 m]" vem depois, com colchetes
    before = clean[:s].strip()
    m = CALL_VERB.match(before)
    if not m:
        return None  # conversa comum com parênteses, não é marcação de rádio
    nick = before[m.end():].strip()
    veh = clean[s + 1:e].strip()
    if not nick or not veh:
        return None
    alt = None
    a = CHAT_ALT.search(clean)
    if a:
        try:
            alt = int(re.sub(r"[^\d]", "", a.group(1)))
        except ValueError:
            alt = None
    grid = re.search(r"\[([A-Z]{1,2}\d{1,2})\b", clean)
    return {"nick": nick, "veh": veh, "alt": alt, "grid": grid.group(1) if grid else None,
            "text": clean.strip()}


def current_match(msgs):
    """O jogo guarda mensagens de partidas anteriores: fica só com as que vêm depois da última
    vez que o relógio da partida ("time") voltou para trás."""
    msgs = sorted(msgs, key=lambda m: m.get("id", 0))
    start = 0
    for i in range(1, len(msgs)):
        if (msgs[i].get("time") or 0) < (msgs[i - 1].get("time") or 0) - 10:
            start = i
    return msgs[start:]


# ---------------------------------------------------------------- geometria

def color_side(o):
    r, g, b = (o.get("color[]") or [0, 0, 0])[:3]
    if o.get("icon") == "Player":
        # amarelo é você; azul é a câmera seguindo um aliado enquanto você espera o respawn
        return "player" if r > 200 and g > 150 and b < 100 else "spectator"
    if r > 150 and g < 120 and b < 120:
        return "enemy"
    return "ally"


def clock(hx, hy, vx, vy):
    """Posição do alvo em 'horas' (12 = à frente, 6 = atrás)."""
    if hx == 0 and hy == 0:
        return None
    a = math.degrees(math.atan2(vx, -vy) - math.atan2(hx, -hy)) % 360
    h = round(a / 30) % 12
    return 12 if h == 0 else h


def angle_between(ax, ay, bx, by):
    na, nb = math.hypot(ax, ay), math.hypot(bx, by)
    if na == 0 or nb == 0:
        return 180
    c = max(-1.0, min(1.0, (ax * bx + ay * by) / (na * nb)))
    return math.degrees(math.acos(c))


def shot_score(ax, ay, adx, ady, bx, by, gunners):
    """Quanto parece que A está atirando em B (menor = mais provável); None se não dá.
    Armas fixas: B na frente do nariz de A. Artilheiros: B só precisa estar perto."""
    d = math.hypot(bx - ax, by - ay)
    aim = angle_between(adx, ady, bx - ax, by - ay)
    if d <= GUN_RANGE and aim <= GUN_CONE:
        return aim + d / 100
    if gunners and d <= TURRET_RANGE:
        return 10 + d / 100
    return None


def pick(scores, lead):
    """O melhor candidato, só se ganhar do segundo com folga."""
    ranked = sorted(scores.items(), key=lambda kv: kv[1])
    if not ranked:
        return None
    if len(ranked) == 1 or ranked[1][1] - ranked[0][1] >= lead:
        return ranked[0][0]
    return None


def best_by(pairs, idx):
    """{(atirador, vítima): pontos} -> {atirador ou vítima: melhores pontos}."""
    out = {}
    for k, sc in pairs.items():
        out[k[idx]] = min(out.get(k[idx], 1e9), sc)
    return out


# ---------------------------------------------------------------- estado da partida

class Match:
    def __init__(self, db, nick):
        self.db = db
        self.nick = nick
        self.my_id = None
        self.reset()

    def reset(self):
        self.players = {}      # chave -> dados do jogador
        self.edges = []        # (a, b, mesmo_time)
        self.side = {}         # chave -> 0 (seu time) ou 1 (inimigo), recalculado a cada leitura
        self.engaged = []      # trocas de tiro com você
        self.killer = None     # quem te derrubou por último
        self.calls = []        # "Attack X!" do rádio do time
        self.call_wait = []    # mensagens de rádio esperando alguém piscar no mapa
        self.last_hit = {}     # (atirador, vítima) -> último dano no kill feed
        self.log = []
        self.my_vehicles = {}  # avião próprio -> chaves vistas com esse avião
        self.tracks = []       # aviões do mapa acompanhados leitura a leitura
        self.by_id = {}
        self.next_track = 1
        self.target = None     # rastro do alvo travado
        self.me_obj = None     # você no mapa (só enquanto está vivo)
        self.snaps = []        # últimos segundos do mapa
        self.scale = (65536.0, 65536.0)
        self.pending = []      # abates esperando o mapa mostrar quem sumiu
        self.alive = False
        self.dead_at = None
        self.dead_confirmed = False  # o kill feed confirmou (e não só o ícone sumiu)
        self.gone_seen = False       # depois de cair, o seu ícone já sumiu do mapa?
        self.missing_since = None
        self.spawn_at = None
        self.life = 0          # sobe a cada vez que você nasce: o painel usa para limpar
        self.fire_t = None     # última vez que o gatilho estava apertado
        self.trigger = False   # o avião mostra o gatilho (weapon1) no /indicators
        self.flash = None      # "você derrubou X", aparece por alguns segundos
        self.me_last = None    # sua última posição no mapa (x, y, hora)
        self.obs, self.obs_t = set(), None  # (atirador, vítima) já usados nesta leitura

    # -- jogadores
    def find_key(self, name):
        key = nick_key(name)
        if not key or key in self.players:
            return key
        # o mesmo jogador às vezes vem com outra tag de esquadrão: casa pelo fim do nome
        last = key.split()[-1]
        same = [k for k in self.players if k.split()[-1] == last]
        return same[0] if len(same) == 1 and len(last) >= 5 else key

    def player(self, name, vehicle, now, active=True):
        """Registra o jogador citado numa mensagem. active: a mensagem mostra que ele está voando."""
        key = self.find_key(name)
        if not key:
            return None
        p = self.players.get(key)
        if p is None:
            p = self.players[key] = {"key": key, "nick": nick_display(name), "vehicles": [], "id": None,
                                     "vehicle": None, "dead": False, "dead_at": None, "death_vehicle": None,
                                     "left": False, "kills": 0, "deaths": 0, "seen": 0}
        if p["dead"] and active and (now - p["dead_at"] > 10 or (vehicle and vehicle != p["death_vehicle"])):
            p["dead"] = False  # nasceu de novo
        if active:
            p["left"] = False
        # crédito de abate e "has achieved" podem chegar com o avião da vida anterior
        if vehicle and not p["dead"] and (active or not p["vehicle"]):
            self.set_vehicle(p, vehicle)
        p["seen"] = max(p["seen"], now)
        return p

    def set_vehicle(self, p, vehicle, cls=None):
        if p["vehicle"] != vehicle:
            p["vehicle"] = vehicle
            if vehicle not in p["vehicles"]:
                p["vehicles"].append(vehicle)
            p["id"] = self.db.lookup(vehicle, self.db.br(self.my_id), cls)[0] or p["id"]

    def icon_of(self, key):
        """Ícone do mapa do avião atual do jogador; None se o nome serve para mais de uma classe
        (o "Me 410 A" é caça numa versão e ataque em outra)."""
        p = self.players.get(key)
        if not p or not p["vehicle"]:
            return None
        cl = {self.db.cls(i) for i in self.db.lookup(p["vehicle"])[1]}
        return CLASS_ICON.get(cl.pop()) if len(cl) == 1 else None

    def my_key(self):
        return nick_key(self.nick) if self.nick else self.guess_nick()

    def guess_nick(self):
        """Sem nick configurado: quem aparece no kill feed com o seu avião em pelo menos dois aviões seus."""
        counts = {}
        for keys in self.my_vehicles.values():
            for k in keys:
                counts[k] = counts.get(k, 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        if not ranked or ranked[0][1] < 2 or (len(ranked) > 1 and ranked[1][1] == ranked[0][1]):
            return None
        return ranked[0][0]

    def sides(self):
        """Pinta os jogadores em dois times a partir de quem atirou em quem."""
        me = self.my_key()
        side = {}
        if not me:
            return side
        side[me] = 0
        adj = {}
        for a, b, same in self.edges:
            adj.setdefault(a, []).append((b, same))
            adj.setdefault(b, []).append((a, same))
        queue = [me]
        while queue:
            cur = queue.pop()
            for nxt, same in adj.get(cur, []):
                if nxt not in side:
                    side[nxt] = side[cur] if same else 1 - side[cur]
                    queue.append(nxt)
        return side

    def add_log(self, now, text, kind="info"):
        self.log.append({"t": now, "text": text, "kind": kind})
        self.log = self.log[-30:]

    def kill(self, p, killer, now, fresh):
        me = self.my_key()
        if p["dead"] and now - p["dead_at"] < 10:
            if p["key"] == me and killer:
                self.killer = {"key": killer["key"], "t": now}  # bateu e depois veio o crédito
            return False
        tr = self.track_of(p["key"])
        if tr:
            tr["wreck"] = now  # a trava fica uns segundos no avião caindo: não é mais alvo
        p["dead"], p["dead_at"], p["death_vehicle"] = True, now, p["vehicle"]
        p["deaths"] += 1
        if killer:
            killer["kills"] += 1
        if p["key"] == me:
            self.on_my_death(now, killer, confirmed=True)
        elif fresh:
            # dano grave de muito tempo atrás que só agora virou abate: o atirador já está longe
            hit = self.last_hit.get((killer["key"], p["key"])) if killer else None
            late = hit is not None and now - hit > 30
            self.pending.append({"key": p["key"], "killer": killer["key"] if killer and not late else None,
                                 "t": now})
        return True

    # -- kill feed
    def on_feed(self, msg, now, fresh=True):
        info = parse_feed(msg)
        if not info:
            return
        me = self.my_key()
        if info.get("a") is None:  # derrubado pela antiaérea
            b = self.player(info["b"], info["bv"], now, active=True)
            if b and self.kill(b, None, now, fresh) and b["key"] == me:
                self.add_log(now, "A antiaérea te derrubou", "bad")
            return
        if "b" not in info:
            text = info.get("text", "")
            gone = text.startswith(("has crashed", "has been wrecked", "has disconnected"))
            a = self.player(info["a"], info["av"], now, active=False)
            if not a:
                return
            self.learn_nick(a, info["av"])
            if gone:
                if text.startswith("has disconnected"):
                    a["left"] = True
                if self.kill(a, None, now, fresh) and a["key"] == me:
                    self.add_log(now, "Você caiu", "bad")
            return
        verb = info["verb"].lower()
        if "assist" in verb:
            return
        # crédito de abate pode chegar depois que o atirador já caiu, e o fogo de um tiro antigo continua
        # dando dano: nenhum dos dois prova que ele está voando
        pa = self.players.get(self.find_key(info["a"]))
        post = (verb in DAMAGE_VERBS and pa is not None and pa["dead"] and info["av"] == pa["death_vehicle"]
                and now - pa["dead_at"] < 60)
        a = self.player(info["a"], info["av"], now, active=verb in DAMAGE_VERBS and not post)
        b = self.player(info["b"], info["bv"], now, active=True)
        if not a or not b or a["key"] == b["key"]:
            return
        # um tiro rende duas ou três linhas na mesma leitura: a posição só conta uma vez
        if now != self.obs_t:
            self.obs, self.obs_t = set(), now
        seen = (a["key"], b["key"]) in self.obs
        self.obs.add((a["key"], b["key"]))
        geo = fresh and verb in DAMAGE_VERBS and not post and not seen
        self.learn_nick(a, info["av"])
        self.edges.append((a["key"], b["key"], False))
        self.side = self.sides()
        av, bv = strip_glyphs(info["av"]), strip_glyphs(info["bv"])
        killed = verb in KILL_VERBS and self.kill(b, a, now, fresh)
        if verb in DAMAGE_VERBS:
            self.last_hit[(a["key"], b["key"])] = now
        if me and a["key"] == me:
            self.engaged.append({"key": b["key"], "t": now, "dir": "out", "verb": verb})
            if geo:
                self.ev_my_hit(b, now)
            if killed:
                self.add_log(now, f"Você derrubou {bv} ({b['nick']})", "good")
                self.flash = {"key": b["key"], "t": now}
                tg = self.target
                if tg and not tg["label"] and self.icon_of(b["key"]) in (None, tg["icon"]):
                    tg["wreck"] = now  # você derrubou o que estava travado
        elif me and b["key"] == me:
            self.engaged.append({"key": a["key"], "t": now, "dir": "in", "verb": verb})
            if geo:
                self.ev_hit_me(a, now)
            if killed:
                self.add_log(now, f"{av} ({a['nick']}) te derrubou", "bad")
            elif verb in DAMAGE_VERBS:
                self.add_log(now, f"{av} ({a['nick']}) {VERB_PT.get(verb, 'te acertou')}", "warn")
        elif geo:
            self.ev_fight(a, b, now)
        self.engaged = self.engaged[-40:]

    def learn_nick(self, p, vehicle):
        """Ajuda a descobrir o seu nick quando ele não foi configurado."""
        mine = self.db.aircraft.get(self.my_id or "")
        if mine and vehicle:
            own = {normalize(mine.get(k) or "") for k in ("short", "name", "full")}
            if normalize(vehicle) in own or normalize(strip_glyphs(vehicle)) in own:
                self.my_vehicles.setdefault(self.my_id, set()).add(p["key"])

    # -- chat
    def on_chat(self, m, now, fresh=True):
        sender = PLATFORM.sub("", m.get("sender") or "")
        mode = (m.get("mode") or "").lower()
        me = self.my_key()
        s = self.player(sender, None, now, active=False) if sender else None
        if s and me and s["key"] != me:
            if m.get("enemy"):
                self.edges.append((s["key"], me, False))
            elif mode in ("team", "squad"):
                self.edges.append((s["key"], me, True))
                text = re.sub(r"<color=[^>]*>.*?</color>|</?color[^>]*>", "", ZW.sub("", m.get("msg") or "")).strip()
                if fresh and SENDER_BLINK.match(text):
                    # quem manda essas mensagens de rádio pisca no mapa: é assim que o aliado ganha nome
                    self.call_wait.append({"key": s["key"], "t": now, "side": "ally", "mine": False,
                                           "icon": self.icon_of(s["key"])})
        call = parse_chat_call(m.get("msg") or "")
        if not call or not s or m.get("enemy"):
            return
        t = self.player(call["nick"], None, now, active=True)
        if not t or t["key"] == s["key"]:
            return
        vid, ids = self.db.lookup(call["veh"], self.db.br(self.my_id))
        if vid and t["id"] not in ids:
            self.set_vehicle(t, call["veh"])  # o rádio diz o avião de agora
        self.edges.append((s["key"], t["key"], False))
        self.side = self.sides()
        self.calls.append({"by": s["key"], "key": t["key"], "t": now, "alt": call["alt"],
                           "grid": call["grid"], "veh": call["veh"]})
        self.calls = self.calls[-20:]
        if fresh:
            # quem é marcado pelo rádio pisca no mapa: é assim que o nome chega no avião certo
            self.call_wait.append({"key": t["key"], "t": now, "side": "enemy", "mine": s["key"] == me,
                                   "icon": self.icon_of(t["key"])})
        if me and s["key"] == me:
            self.add_log(now, f"Você marcou {strip_glyphs(call['veh'])} ({t['nick']})", "info")

    # -- você
    def update_me(self, me_obj, now):
        if not me_obj:
            self.me_obj = None
            self.gone_seen = True
            if self.alive:
                # o kill feed costuma avisar na mesma hora; sem ele, só depois de uns segundos sem ícone
                self.missing_since = self.missing_since or now
                if now - self.missing_since >= 4:
                    self.on_my_death(self.missing_since)
            return
        self.missing_since = None
        if not self.alive:
            if self.dead_confirmed and (now - self.dead_at < 5 or not self.gone_seen and now - self.dead_at < 60):
                return  # o kill feed já disse que você caiu; o avião ainda está caindo no mapa
            if self.dead_at is not None and not self.dead_confirmed and now - self.dead_at < 8:
                self.dead_at = None  # sumiu do mapa só por uns segundos, sem abate no kill feed
            else:
                self.life += 1
                self.spawn_at = now
                self.engaged = []
            self.alive = True
            self.dead_confirmed = False
        self.me_obj = me_obj

    def on_my_death(self, now, killer=None, confirmed=False):
        if self.spawn_at is not None and now <= self.spawn_at:
            return  # mensagem antiga (de antes de você nascer de novo), lida no buffer
        if killer:
            self.killer = {"key": killer["key"], "t": now}
        if confirmed:
            self.dead_confirmed = True
        if self.alive or self.dead_at is None:
            self.dead_at = now
            self.gone_seen = self.me_obj is None  # nasce de novo só depois que o ícone sumir
        self.alive = False
        self.me_obj = None
        self.target = None
        self.flash = None

    # -- rastros no mapa
    # O mapa não diz quem é quem. Cada avião vira um "rastro" que seguimos leitura a leitura, e o
    # rastro ganha o nome do jogador quando as pistas do kill feed e do rádio apontam para ele.
    def update_tracks(self, objs, now):
        W, H = self.scale
        live = []
        for o in objs:
            if o.get("type") != "aircraft" or o.get("icon") == "Player":
                continue
            live.append({"side": color_side(o), "icon": o.get("icon"), "o": o,
                         "x": o["x"] * W, "y": o["y"] * H, "dx": o.get("dx", 0), "dy": o.get("dy", 0),
                         "spawn": str(o.get("color", "")).lower() in SPAWN_COLORS})
        active = [tr for tr in self.tracks if tr["lost"] is None]
        pairs = []
        for i, item in enumerate(live):
            for tr in active:
                if tr["side"] == item["side"] and tr["icon"] == item["icon"]:
                    dt = max(now - tr["t"], 0.05)
                    d = math.hypot(item["x"] - tr["x"] - tr["vx"] * dt, item["y"] - tr["y"] - tr["vy"] * dt)
                    if d < 150 + 100 * dt:
                        pairs.append((d, i, tr))
        pairs.sort(key=lambda p: p[0])
        used_items, used_tracks = set(), set()
        for d, i, tr in pairs:
            if i in used_items or tr["id"] in used_tracks:
                continue
            used_items.add(i)
            used_tracks.add(tr["id"])
            live[i]["track"] = tr
        # o ícone sumiu por uns segundos (nuvem, ninguém do time vendo) e voltou: é o mesmo avião
        lost = [tr for tr in self.tracks if tr["lost"] is not None and not tr["dead"] and now - tr["lost"] < 12]
        pairs = []
        for i, item in enumerate(live):
            if i in used_items or item["spawn"]:
                continue  # cor de recém-nascido: é outra vida, não o mesmo avião voltando
            for tr in lost:
                if tr["side"] == item["side"] and tr["icon"] == item["icon"]:
                    gap = now - tr["t"]
                    speed = math.hypot(tr["vx"], tr["vy"])
                    d = math.hypot(item["x"] - tr["x"] - tr["dx"] * speed * gap,
                                   item["y"] - tr["y"] - tr["dy"] * speed * gap)
                    if d < 200 + 60 * gap:
                        pairs.append((d, i, tr))
        pairs.sort(key=lambda p: p[0])
        for d, i, tr in pairs:
            if i in used_items or tr["id"] in used_tracks:
                continue
            used_items.add(i)
            used_tracks.add(tr["id"])
            tr["lost"] = None
            live[i]["track"] = tr
        for i, item in enumerate(live):
            if i not in used_items:
                tr = {"id": self.next_track, "side": item["side"], "icon": item["icon"], "born": now,
                      "lost": None, "dead": False, "label": None, "votes": {}, "closing": None,
                      "x": item["x"], "y": item["y"], "t": now, "blink": 0, "blink_t": None,
                      "vx": item["dx"] * 150, "vy": item["dy"] * 150}
                self.next_track += 1
                self.tracks.append(tr)
                self.by_id[tr["id"]] = tr
                used_tracks.add(tr["id"])
                item["track"] = tr
            tr = item["track"]
            dt = now - tr["t"]
            if dt > 0.05:
                k = 0.5 if dt < 2 else 1.0
                vx = (item["x"] - tr["x"]) / dt
                vy = (item["y"] - tr["y"]) / dt
                if math.hypot(vx, vy) < 700:
                    tr["vx"] = tr["vx"] * (1 - k) + vx * k
                    tr["vy"] = tr["vy"] * (1 - k) + vy * k
            blink = item["o"].get("blink") or 0
            if blink and not tr["blink"]:
                tr["blink_t"], tr["blink_used"] = now, False
            tr.update(x=item["x"], y=item["y"], t=now, dx=item["dx"], dy=item["dy"], blink=blink,
                      locked=str(item["o"].get("icon_bg", "")).endswith("Target"))
        for tr in self.tracks:
            if tr["id"] not in used_tracks and tr["lost"] is None:
                tr["lost"] = tr["t"]  # última vez em que foi visto
        for tr in self.tracks:
            if tr["lost"] is not None and now - tr["lost"] >= 15:
                self.by_id.pop(tr["id"], None)
        self.tracks = [tr for tr in self.tracks if tr["id"] in self.by_id]
        return live

    def live(self):
        return [tr for tr in self.tracks if tr["lost"] is None]

    # -- mapa
    def on_map(self, objs, info, now, firing=False):
        if info and info.get("map_max") and info.get("map_min"):
            self.scale = (info["map_max"][0] - info["map_min"][0], info["map_max"][1] - info["map_min"][1])
        W, H = self.scale
        if not objs:
            # mapa vazio: partida carregando ou acabando, não quer dizer que você caiu
            self.me_obj = self.target = None
            return []
        icons = [o for o in objs if o.get("icon") == "Player"]
        me_obj = next((o for o in icons if color_side(o) == "player"), None)
        if me_obj is None and self.alive and self.me_last:
            # o seu ícone também pisca (em azul) às vezes: vale se continuar no mesmo caminho
            lx, ly, lt = self.me_last
            me_obj = next((o for o in icons if o.get("blink")
                           and math.hypot((o["x"] - lx) * W, (o["y"] - ly) * H) < 300 + 350 * (now - lt)), None)
        if me_obj:
            self.me_last = (me_obj["x"], me_obj["y"], now)
        self.update_me(me_obj, now)
        if firing and self.alive:
            self.fire_t = now
        live = self.update_tracks(objs, now)
        me = self.me_obj
        enemies = []
        target = None
        for item in live:
            if item["side"] != "enemy":
                continue
            o = item["o"]
            e = {"cls": MAP_CLASS.get(o.get("icon"), "fighter"), "track": item["track"],
                 "dx": item["dx"], "dy": item["dy"]}
            if me:
                vx, vy = item["x"] - me["x"] * W, item["y"] - me["y"] * H
                e["dist"] = round(math.hypot(vx, vy))
                e["clock"] = clock(me.get("dx", 0), me.get("dy", 0), vx, vy)
                # o inimigo está apontando para você?
                e["towardMe"] = angle_between(e["dx"], e["dy"], -vx, -vy) < 35
            enemies.append(e)
            if item["track"]["locked"] and me and now - item["track"].get("wreck", -1e9) >= 6:
                target = e  # a trava fica uns segundos depois que você cai ou que ele cai: só vale com os dois no ar
        enemies.sort(key=lambda e: e.get("dist", 0))

        if target:
            tr = target["track"]
            if tr is self.target and tr.get("dist") is not None and target.get("dist") is not None:
                rate = (tr["dist"] - target["dist"]) / max(now - tr["dist_t"], 0.1)
                tr["closing"] = rate if tr.get("closing") is None else tr["closing"] * 0.7 + rate * 0.3
            elif tr is not self.target:
                tr["closing"] = None
            tr.update(dist=target.get("dist"), dist_t=now, clock=target.get("clock"),
                      towardMe=target.get("towardMe"))
            self.target = tr
        else:
            self.target = None

        self.snaps.append({"t": now, "fire": firing,
                           "me": (me["x"] * W, me["y"] * H, me.get("dx", 0), me.get("dy", 0)) if me else None,
                           "objs": [(it["track"], it["x"], it["y"], it["dx"], it["dy"], it["track"]["locked"])
                                    for it in live]})
        while self.snaps and now - self.snaps[0]["t"] > HISTORY:
            self.snaps.pop(0)
        return enemies

    # -- pistas: quem estava na frente de quem quando o kill feed falou
    def pair_scores(self, t0, t1, shooter, victim, gunners, lock_bonus=False):
        """{(id do atirador, id da vítima): melhores pontos} nas leituras do mapa entre t0 e t1.
        shooter/victim filtram os rastros; o rastro None é você (id 0)."""
        out = {}
        for s in self.snaps:
            if not t0 <= s["t"] <= t1:
                continue
            items = list(s["objs"])
            if s["me"]:
                items.append((None,) + s["me"] + (False,))
            shooters = [it for it in items if shooter(it[0])]
            victims = [it for it in items if victim(it[0])]
            for a in shooters:
                for b in victims:
                    if a[0] is b[0]:
                        continue
                    sc = shot_score(a[1], a[2], a[3], a[4], b[1], b[2], gunners)
                    if sc is None:
                        continue
                    if lock_bonus and b[5]:
                        sc -= 5  # quase sempre você atira no que travou
                    k = (a[0]["id"] if a[0] else 0, b[0]["id"] if b[0] else 0)
                    out[k] = min(out.get(k, 1e9), sc)
        return out

    def vote(self, tr, key, w, how, now):
        if not tr or not key or tr["dead"]:
            return
        v = tr["votes"].setdefault(key, {"w": 0.0, "how": how, "best": 0.0, "t": now, "how_t": now})
        v["w"] = min(v["w"] + w, 10.0)
        if w >= v["best"]:
            v["best"], v["how"], v["how_t"] = w, how, now
        v["t"] = now

    def fits(self, key, side_name, icon=None):
        """Filtro de rastros do mesmo lado e da mesma classe do avião do jogador."""
        cls_icon = icon or self.icon_of(key)
        return lambda tr: tr is not None and tr["side"] == side_name and (not cls_icon or tr["icon"] == cls_icon)

    def ev_my_hit(self, b, now):
        """Você acertou b: ele é o inimigo que estava na frente do seu nariz, ao alcance das armas."""
        gunners = self.db.gunners(self.my_id)
        if self.trigger and not gunners and (self.fire_t is None or now - self.fire_t > 4):
            return  # crédito atrasado de um tiro antigo: quem está na frente agora não importa
        pairs = self.pair_scores(now - 3, now, lambda tr: tr is None, self.fits(b["key"], "enemy"),
                                 gunners, lock_bonus=True)
        tid = pick(best_by(pairs, 1), LEAD)
        if tid:
            self.vote(self.by_id.get(tid), b["key"], W_HIT, "hit", now)

    def ev_hit_me(self, a, now):
        """a te acertou: é o inimigo daquela classe com o nariz apontado para você."""
        pairs = self.pair_scores(now - 3, now, self.fits(a["key"], "enemy"), lambda tr: tr is None,
                                 self.db.gunners(a["id"]))
        tid = pick(best_by(pairs, 0), LEAD)
        if tid:
            self.vote(self.by_id.get(tid), a["key"], W_HITME, "hitme", now)

    def team_of(self, a, b):
        sa, sb = self.side.get(a["key"]), self.side.get(b["key"])
        if sa is None and sb is None:
            return None, None
        sa = 1 - sb if sa is None else sa
        sb = 1 - sa if sb is None else sb
        return (SIDE_NAME[sa], SIDE_NAME[sb]) if sa != sb else (None, None)

    def ev_fight(self, a, b, now):
        """a acertou b (nenhum dos dois é você)."""
        side_a, side_b = self.team_of(a, b)
        if not side_a:
            return
        ta, tb = self.track_of(a["key"]), self.track_of(b["key"])
        fa, fb = self.fits(a["key"], side_a), self.fits(b["key"], side_b)
        gunners = self.db.gunners(a["id"])
        if tb and not ta:
            tid = pick(best_by(self.pair_scores(now - 3, now, fa, lambda tr: tr is tb, gunners), 0), LEAD)
            self.vote(self.by_id.get(tid), a["key"], W_FIGHT, "feed", now)
        elif ta and not tb:
            tid = pick(best_by(self.pair_scores(now - 3, now, lambda tr: tr is ta, fb, gunners), 1), LEAD)
            self.vote(self.by_id.get(tid), b["key"], W_FIGHT, "feed", now)
        elif not ta and not tb and not gunners:
            pairs = self.pair_scores(now - 3, now, fa, fb, False)
            self.vote(self.by_id.get(pick(best_by(pairs, 0), PAIR_LEAD)), a["key"], W_PAIR, "pair", now)
            self.vote(self.by_id.get(pick(best_by(pairs, 1), PAIR_LEAD)), b["key"], W_PAIR, "pair", now)

    def resolve_kills(self, now):
        """Alguém caiu: o ícone dele some do mapa na mesma hora. Achando a vítima no mapa,
        quem estava apontando para ela é quem derrubou."""
        keep = []
        for k in self.pending:
            if now - k["t"] < 2.5:
                keep.append(k)
                continue
            # quem continua voando (ou pode voltar ao mapa) não pode ser ele
            for tr in self.tracks:
                if not tr["dead"]:
                    tr["votes"].pop(k["key"], None)
            sk = self.side.get(k["key"])
            icon = self.icon_of(k["key"])
            gone = [tr for tr in self.tracks
                    if tr["lost"] is not None and not tr["dead"] and tr["born"] < k["t"]
                    and k["t"] - 1.5 <= tr["lost"] <= k["t"] + 2.5
                    and (sk is None or tr["side"] == SIDE_NAME[sk]) and (not icon or tr["icon"] == icon)]
            if len(gone) > 1:
                named = [tr for tr in gone if (tr["label"] or {}).get("key") == k["key"]]
                gone = named or gone
            if len(gone) != 1:
                continue
            v = gone[0]
            v["dead"], v["final"] = True, k["key"]
            killer = self.players.get(k["killer"] or "")
            if not killer or killer["key"] == self.my_key() or (killer["dead"] and killer["dead_at"] < k["t"] - 1):
                continue
            side_a = "enemy" if v["side"] == "ally" else "ally"
            pairs = self.pair_scores(v["lost"] - 3, v["lost"] + 0.01, self.fits(killer["key"], side_a),
                                     lambda tr: tr is v, self.db.gunners(killer["id"]))
            tid = pick(best_by(pairs, 0), PAIR_LEAD)
            self.vote(self.by_id.get(tid), killer["key"], W_KILL, "kill", now)
        self.pending = keep

    def resolve_calls(self, now):
        """Liga cada mensagem de rádio ao avião que começou a piscar junto com ela."""
        waits = []
        for c in self.call_wait:
            cur = self.track_of(c["key"])
            if cur and cur["blink"] and cur["blink_t"] is not None and cur["blink_t"] < c["t"] - 1.5:
                continue  # marcou de novo quem ainda está piscando da marcação anterior
            c["cands"] = [tr for tr in self.live() if tr["side"] == c["side"] and tr["blink_t"] is not None
                          and not tr.get("blink_used") and abs(tr["blink_t"] - c["t"]) <= 1.5
                          and (not c["icon"] or tr["icon"] == c["icon"])]
            waits.append(c)
        keep = []
        for c in waits:
            # duas mensagens ao mesmo tempo disputando o mesmo avião piscando: nenhuma leva
            rival = any(w is not c and {id(tr) for tr in w["cands"]} & {id(tr) for tr in c["cands"]} for w in waits)
            if len(c["cands"]) == 1 and not rival:
                c["cands"][0]["blink_used"] = True
                self.vote(c["cands"][0], c["key"], W_CALL, "call", now)
            elif now - c["t"] <= 1.5:
                keep.append(c)
            elif c["mine"] and not c["cands"] and self.target and (not c["icon"] or self.target["icon"] == c["icon"]):
                self.vote(self.target, c["key"], W_CALL, "call", now)  # sua marcação vale para o seu alvo
        self.call_wait = keep

    def assign(self):
        """Cada nome vai para um rastro só: primeiro as pistas mais fortes."""
        me = self.my_key()
        options = []
        for tr in self.live():
            tr["label"] = None
            ranked = sorted(tr["votes"].items(), key=lambda kv: -kv[1]["w"])
            for i, (key, v) in enumerate(ranked):
                p = self.players.get(key)
                if not p or p["dead"] or p["left"] or key == me:
                    continue
                icon = self.icon_of(key)
                if icon and icon != tr["icon"]:
                    continue
                sk = self.side.get(key)
                if sk is not None and SIDE_NAME[sk] != tr["side"]:
                    continue
                rival = max([w["w"] for k2, w in ranked if k2 != key] or [0])
                if v["w"] >= W_LABEL and v["w"] >= 2 * rival:
                    options.append((v["w"], v["t"], tr, key, v))
        options.sort(key=lambda o: (-o[0], -o[1]))
        used_t, used_k = set(), set()
        for w, t, tr, key, v in options:
            if tr["id"] in used_t or key in used_k:
                continue
            used_t.add(tr["id"])
            used_k.add(key)
            tr["label"] = {"key": key, "how": v["how"], "t": t, "how_t": v["how_t"], "w": w}

    def settle(self, now):
        """Depois de ler o mapa e as mensagens: fecha as pistas pendentes e distribui os nomes."""
        self.side = self.sides()
        self.resolve_calls(now)
        self.resolve_kills(now)
        self.assign()

    def track_of(self, key):
        return next((tr for tr in self.live() if tr["label"] and tr["label"]["key"] == key), None)

    # -- quem é o alvo travado?
    def identify(self, now):
        tr = self.target
        if not tr or not self.alive:
            return None
        cls = MAP_CLASS.get(tr["icon"], "fighter")
        key, how, sure, age = None, None, False, None
        lab = tr["label"]
        if lab:
            key, how, age = lab["key"], lab["how"], round(now - lab["how_t"])
            sure = lab["w"] >= W_SURE
        # sem nome: os inimigos daquela classe que o kill feed já mostrou e que não estão em outro
        # avião do mapa. Não vira palpite: o kill feed só mostra parte do time inimigo.
        named = {t["label"]["key"] for t in self.live() if t["label"] and t is not tr}
        cands = [k for k, p in self.players.items()
                 if self.side.get(k) == 1 and not p["dead"] and not p["left"] and p["id"]
                 and self.icon_of(k) in (None, tr["icon"]) and k not in named and k != key]
        # quem trocou tiros com você nesta vida vem primeiro na lista de "pode ser"
        recent = {e["key"]: e["t"] for e in self.engaged}
        cands.sort(key=lambda k: (-recent.get(k, 0), -self.players[k]["seen"]))
        alt = None
        if key:
            a, a_age = self.call_alt(key, now)
            if a:
                alt = {"value": a, "age": a_age}
        return {"cls": cls, "dist": tr.get("dist"), "clock": tr.get("clock"),
                "towardMe": tr.get("towardMe"),
                "closing": round(tr["closing"]) if tr.get("closing") is not None else None,
                "who": self.public(key) if key else None, "how": how, "sure": sure, "age": age,
                "candidates": [self.public(k) for k in cands][:6], "alt": alt}

    def track_who(self, tr):
        """Jogador reconhecido num rastro (se ainda estiver vivo)."""
        lab = tr.get("label")
        p = self.players.get(lab["key"]) if lab else None
        return p if p and not p["dead"] else None

    def call_alt(self, key, now):
        """Altitude que algum aviso de rádio deu para esse jogador nos últimos 2 minutos."""
        for c in reversed(self.calls):
            if c["key"] == key and c["alt"] and now - c["t"] < 120:
                return c["alt"], round(now - c["t"])
        return None, None

    def radar(self, now):
        """Aviões em volta de você, em metros (rx = leste, ry = sul), para o radar do painel."""
        if not self.me_obj:
            return {"objs": [], "dead": not self.alive and self.dead_at is not None}
        W, H = self.scale
        mx, my = self.me_obj["x"] * W, self.me_obj["y"] * H
        objs = []
        for tr in self.live():
            item = {"tid": tr["id"], "side": tr["side"], "cls": MAP_CLASS.get(tr["icon"], "fighter"),
                    "rx": round(tr["x"] - mx), "ry": round(tr["y"] - my),
                    "dx": round(tr.get("dx", 0), 3), "dy": round(tr.get("dy", 0), 3)}
            if tr is self.target:
                item["target"] = True
            p = self.track_who(tr)
            if p and tr["side"] == "enemy":
                item.update(id=p["id"], nick=p["nick"])
                alt, age = self.call_alt(p["key"], now)
                if alt:
                    item.update(alt=alt, altAge=age)
            objs.append(item)
        return {"hdg": [self.me_obj.get("dx", 0), self.me_obj.get("dy", -1)], "objs": objs}

    def public(self, key):
        p = self.players.get(key)
        if not p:
            return None
        return {"key": key, "nick": p["nick"], "id": p["id"], "vehicle": p["vehicle"],
                "vehicles": p["vehicles"], "dead": p["dead"], "kills": p["kills"],
                "deaths": p["deaths"]}


# ---------------------------------------------------------------- leitura da API do jogo

def game_get(path, timeout=1.5):
    with urllib.request.urlopen(GAME + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


class Poller(threading.Thread):
    daemon = True

    def __init__(self, db, config, images):
        super().__init__()
        self.db = db
        self.config = config
        self.images = images
        self.match = Match(db, config.get("nick", ""))
        self.match_id = 1
        self.lock = threading.RLock()
        self.snapshot = {"game": "offline"}
        self.radar_snap = {"game": "offline", "objs": []}
        self.status = "offline"
        self.last_evt = self.last_dmg = self.last_chat = 0
        self.mission_t = 0     # relógio da partida na última mensagem lida
        self.backlog = True
        self.map_info = None
        self.map_gen = None
        self.my_id = None
        self.state = {}
        self.not_battle_since = None
        self.tick = 0

    def set_nick(self, nick):
        with self.lock:
            self.config["nick"] = nick
            self.match.nick = nick

    def run(self):
        while True:
            try:
                self.step()
            except Exception as exc:  # o jogo fechou, carregando etc.
                with self.lock:
                    self.status = "offline"
                    self.snapshot = {"game": "offline", "error": str(exc)[:120],
                                     "db": {"version": self.db.version, "built": self.db.built}}
                    self.radar_snap = {"game": "offline", "objs": []}
            time.sleep(0.25)

    def step(self):
        # mapa, gatilho e kill feed 4x por segundo; o resto com mais calma
        now = time.time()
        self.tick += 1
        if self.tick % 12 == 1 or self.map_info is None:
            self.map_info = game_get("/map_info.json")
            gen = self.map_info.get("map_generation")
            if self.map_info.get("valid") and gen is not None:
                if self.map_gen is not None and gen != self.map_gen:
                    self.new_match()
                self.map_gen = gen
        in_battle = bool(self.map_info and self.map_info.get("valid"))
        if not in_battle:
            # abriu no hangar: a primeira batalha é sempre partida nova (o buffer é da anterior)
            self.not_battle_since = self.not_battle_since or (now - 10 if self.map_gen is None else now)
        elif self.not_battle_since and now - self.not_battle_since > 10:
            self.new_match()
        if in_battle:
            self.not_battle_since = None

        ind = game_get("/indicators")
        firing = False
        if ind.get("valid") and ind.get("type") and ind.get("army") == "air":
            uid = ind["type"] if ind["type"] in self.db.aircraft else self.db.lookup(ind["type"])[0]
            if uid:  # na carga da partida vem "dummy_plane"
                self.my_id = uid
            weapons = [v for k, v in ind.items() if re.fullmatch(r"weapon\d+", k)]
            self.match.trigger = bool(weapons)
            firing = any((v or 0) >= 0.5 for v in weapons)
        if self.tick % 2 == 1:
            self.state = game_get("/state") if in_battle else {}
        objs = game_get("/map_obj.json") if in_battle else []
        hud, chat = self.fetch_messages()

        with self.lock:
            m = self.match
            m.my_id = self.my_id
            m.side = m.sides()
            enemies = m.on_map(objs, self.map_info, now, firing) if in_battle else []
            self.ingest(hud, chat, now)
            m = self.match  # pode ter começado outra partida no meio das mensagens
            if in_battle:
                m.settle(now)
            self.status = "battle" if in_battle else "hangar"
            self.snapshot = self.build(now, enemies, in_battle)
            st = self.state or {}
            self.radar_snap = dict(m.radar(now) if in_battle else {"objs": []}, game=self.status,
                                   me={"alt": st.get("H, m"), "ias": st.get("IAS, km/h")})

    def new_match(self):
        with self.lock:
            self.match.reset()
            self.match_id += 1
            self.mission_t = 0

    def fetch_messages(self):
        # se a última mensagem lida sumiu do jogo, ele foi reiniciado e os ids recomeçaram
        if self.tick % 30 == 0:
            if self.last_dmg and not game_get(f"/hudmsg?lastEvt=0&lastDmg={self.last_dmg - 1}").get("damage"):
                self.last_evt = self.last_dmg = 0
                self.backlog = True
            elif self.last_chat and not game_get(f"/gamechat?lastId={self.last_chat - 1}"):
                self.last_chat = 0
        hud = game_get(f"/hudmsg?lastEvt={self.last_evt}&lastDmg={self.last_dmg}")
        chat = game_get(f"/gamechat?lastId={self.last_chat}") if self.tick % 2 == 0 or self.backlog else []
        return hud, chat if isinstance(chat, list) else []

    def ingest(self, hud, chat, now):
        dmg = sorted(hud.get("damage", []), key=lambda m: m.get("id", 0))
        for m in hud.get("events", []):
            self.last_evt = max(self.last_evt, m.get("id", 0))
        for m in dmg:
            self.last_dmg = max(self.last_dmg, m.get("id", 0))
        for m in chat:
            self.last_chat = max(self.last_chat, m.get("id", 0))
        if self.backlog:
            # na primeira leitura vem o buffer inteiro: fica só a partida atual, com a hora de cada uma
            dmg, chat = current_match(dmg), current_match(chat)
            # kill feed e chat usam o mesmo relógio da partida: uma âncora só, tudo em ordem de hora
            newest = max([m.get("time") or 0 for m in dmg + chat] or [0])
            msgs = [(m.get("time") or newest, 0, m) for m in dmg] + [(m.get("time") or newest, 1, m) for m in chat]
            for mt, kind, m in sorted(msgs, key=lambda x: (x[0], x[1])):
                if kind == 0:
                    self.match.on_feed(m.get("msg", ""), now - (newest - mt), fresh=False)
                else:
                    self.match.on_chat(m, now - (newest - mt), fresh=False)
            self.mission_t = max([m.get("time") or 0 for m in dmg] or [0])
            self.backlog = False
            return
        for m in dmg:
            mt = m.get("time")
            if mt is not None:
                if mt < self.mission_t - 10:
                    self.new_match()  # o relógio da partida voltou: é outra partida
                self.mission_t = max(self.mission_t, mt)
            self.match.on_feed(m.get("msg", ""), now)
        for m in chat:
            self.match.on_chat(m, now)

    def build(self, now, enemies, in_battle):
        m = self.match
        me = m.my_key()
        side = m.side
        players = [m.public(k) for k in m.players]
        for p in players:
            p["side"] = {0: "ally", 1: "enemy"}.get(side.get(p["key"]), "unknown")
            p["me"] = p["key"] == me
            if p["side"] == "enemy":
                self.images.prefetch(p["id"])
        self.images.prefetch(self.my_id)
        target = engaged = killer = flash = None
        if in_battle and m.alive:
            target = m.identify(now)
            # só as trocas de tiro desta vida, com quem ainda está voando
            for e in reversed(m.engaged):
                p = m.players.get(e["key"])
                if p and not p["dead"] and now - e["t"] < 30 and e["t"] >= (m.spawn_at or 0):
                    engaged = dict(m.public(e["key"]), dir=e["dir"], verb=e["verb"], age=round(now - e["t"]))
                    break
        if in_battle and not m.alive and m.killer and m.dead_at and m.killer["t"] >= m.dead_at - 2 \
                and m.killer["key"] in m.players:
            killer = dict(m.public(m.killer["key"]), age=round(now - m.killer["t"]))
        if in_battle and m.alive and m.flash and now - m.flash["t"] < 6 and m.flash["key"] in m.players:
            flash = dict(m.public(m.flash["key"]), age=round(now - m.flash["t"]))
        counts = {}
        for e in enemies:
            counts[e["cls"]] = counts.get(e["cls"], 0) + 1
        nearest = []
        for e in enemies[:6]:
            item = {k: e.get(k) for k in ("cls", "dist", "clock", "towardMe")}
            p = m.track_who(e["track"])
            if p:
                item.update(id=p["id"], nick=p["nick"])
            item["target"] = e["track"] is m.target
            nearest.append(item)
        st = self.state or {}
        return {
            "game": self.status,
            "match": self.match_id,
            "db": {"version": self.db.version, "built": self.db.built},
            "me": {"id": self.my_id, "nick": self.config.get("nick") or "", "nickGuess": m.guess_nick(),
                   "key": me, "ias": st.get("IAS, km/h"), "tas": st.get("TAS, km/h"),
                   "alt": st.get("H, m"), "vy": st.get("Vy, m/s"), "mach": st.get("M"),
                   "alive": m.alive, "life": m.life,
                   "deadFor": round(now - m.dead_at) if not m.alive and m.dead_at else None},
            "target": target,
            "engaged": engaged,
            "killer": killer,
            "flash": flash,
            "players": players,
            "radar": {"counts": counts, "nearest": nearest,
                      "named": sum(1 for e in enemies if m.track_who(e["track"]))},
            "log": [dict(x, age=round(now - x["t"])) for x in m.log[-12:]][::-1],
        }


# ---------------------------------------------------------------- servidor do painel

class Handler(SimpleHTTPRequestHandler):
    poller = None

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB, **kw)

    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/state"):
            with self.poller.lock:
                return self.send_json(self.poller.snapshot)
        if self.path.startswith("/api/radar"):
            with self.poller.lock:
                return self.send_json(self.poller.radar_snap)
        if self.path.startswith("/img/"):
            uid = urllib.parse.unquote(self.path[5:].split("?")[0])
            data = self.poller.images.get(uid[:-4] if uid.endswith(".png") else uid)
            if not data:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "max-age=86400")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path.startswith("/data/aircraft.json"):
            with open(DB_FILE, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/config"):
            length = int(self.headers.get("Content-Length") or 0)
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self.send_json({"ok": False}, 400)
            nick = str(data.get("nick", "")).strip()[:40]
            self.poller.set_nick(nick)
            save_config(self.poller.config)
            return self.send_json({"ok": True, "nick": nick})
        self.send_json({"ok": False}, 404)


def save_config(cfg):
    os.makedirs(DATA, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def main():
    lan = "--lan" in sys.argv
    db = Database()
    config = load_json(CONFIG_FILE, {"nick": ""})
    poller = Poller(db, config, Images(db))
    poller.start()
    Handler.poller = poller
    host = "0.0.0.0" if lan else "127.0.0.1"
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else PORT
    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError:
        print(f"A porta {port} já está em uso: o companion provavelmente já está aberto em outra janela.")
        print(f"Abra http://localhost:{port} no navegador ou feche a outra janela.")
        sys.exit(1)
    url = f"http://localhost:{port}"
    print(f"War Thunder Companion rodando em {url}")
    print(f"Banco de aviões: {len(db.aircraft)} aviões (jogo {db.version})")
    if lan:
        ip = lan_ip()
        if ip:
            print(f"No celular (mesma rede Wi-Fi): http://{ip}:{port}")
    print("Deixe esta janela aberta. Ctrl+C para sair.")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
