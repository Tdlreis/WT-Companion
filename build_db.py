"""Monta o banco de dados de aviões (data/aircraft.json) a partir do datamine público
do War Thunder (github.com/gszabi99/War-Thunder-Datamine).

Não lê nem altera nenhum arquivo do jogo: só baixa os dados públicos do GitHub.
Rode de novo depois de um patch grande para atualizar BRs e fichas.

    python build_db.py
"""
import csv
import io
import json
import os
import re
import shutil
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

REPO = "gszabi99/War-Thunder-Datamine"
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
CACHE = os.path.join(DATA, "cache")
OUT = os.path.join(DATA, "aircraft.json")

LANG_COLUMNS = ["English", "French", "Italian", "German", "Spanish", "Russian", "Polish",
                "Czech", "Turkish", "Chinese", "Japanese", "Portuguese", "Ukrainian",
                "Serbian", "Hungarian", "Korean", "Belarusian", "Romanian", "TChinese",
                "HChinese", "Vietnamese"]


def http_get(url, retries=4):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "WarThunderCompanion"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))


def api(path):
    return json.loads(http_get(f"https://api.github.com/repos/{REPO}/{path}"))


def subtree(sha):
    """Lista {nome: sha} de uma pasta do repositório (sem recursão)."""
    tree = api(f"git/trees/{sha}")
    return {e["path"]: dict(e, name=e["path"]) for e in tree["tree"]}


def cached(path, sha, commit):
    """Baixa um arquivo do repositório, reaproveitando o cache se o sha não mudou."""
    local = os.path.join(CACHE, path.replace("/", os.sep))
    shafile = local + ".sha"
    if os.path.exists(local) and os.path.exists(shafile):
        with open(shafile, encoding="utf-8") as f:
            if f.read().strip() == sha:
                return local
    os.makedirs(os.path.dirname(local), exist_ok=True)
    data = http_get(f"https://raw.githubusercontent.com/{REPO}/{commit}/{path}")
    with open(local, "wb") as f:
        f.write(data)
    with open(shafile, "w", encoding="utf-8") as f:
        f.write(sha)
    return local


def cached_extract(path, sha, commit, extract):
    """Como cached(), mas guarda só o resumo que extract() tira do arquivo (cache pequeno)."""
    local = os.path.join(CACHE, "extract", path.replace("/", os.sep)) + ".json"
    try:
        with open(local, encoding="utf-8") as f:
            saved = json.load(f)
        if saved.get("sha") == sha:
            return saved["data"]
    except (OSError, ValueError):
        pass
    data = extract(json.loads(http_get(f"https://raw.githubusercontent.com/{REPO}/{commit}/{path}")))
    os.makedirs(os.path.dirname(local), exist_ok=True)
    with open(local, "w", encoding="utf-8") as f:
        json.dump({"sha": sha, "data": data}, f, ensure_ascii=False)
    return data


def extract_meta(meta):
    weapons = [{"trigger": w.get("trigger", ""), "blk": w.get("blk"), "bullets": w.get("bullets")}
               for w in collect_weapons(meta)]
    return {"fmFile": meta.get("fmFile"), "weapons": weapons, "ordnance": ordnance_types(meta)}


def extract_fm(fm):
    strength = (((fm.get("Aerodynamics") or {}).get("WingPlane") or {}).get("Strength") or {})
    mass = fm.get("Mass") or {}
    return {"vne": strength.get("VNE") or fm.get("Vne"), "mne": strength.get("MNE") or fm.get("VneMach"),
            "mass": mass.get("Takeoff"), "gearMax": mass.get("GearDestructionIndSpeed")}


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def br_from_rank(rank):
    if rank is None:
        return None
    return round(rank / 3.0 + 1.0, 1)


def weapon_key(blk):
    return os.path.splitext(os.path.basename(blk or ""))[0]


def collect_weapons(fmeta):
    """Armas fixas e torres de artilheiros da configuração padrão."""
    weapons = []
    slots = fmeta.get("WeaponSlots")
    if isinstance(slots, dict):
        for slot in as_list(slots.get("WeaponSlot")):
            presets = as_list(slot.get("WeaponPreset"))
            # slot 0 (ou um slot com uma única opção) faz parte do avião em si
            if slot.get("index") == 0 or (len(presets) == 1 and "tier" not in slot):
                for p in presets:
                    weapons += as_list(p.get("Weapon"))
    common = fmeta.get("commonWeapons")
    if isinstance(common, dict):
        weapons += [w for w in as_list(common.get("Weapon")) if "blk" in w]
    return weapons


def ordnance_types(fmeta):
    kinds = set()

    def scan(o):
        if isinstance(o, dict):
            trig = o.get("trigger")
            if trig in ("bombs", "rockets", "torpedoes", "atgm", "aam", "agm", "guided bombs"):
                kinds.add(trig)
            for v in o.values():
                scan(v)
        elif isinstance(o, list):
            for v in o:
                scan(v)

    scan(fmeta.get("WeaponSlots"))
    for p in as_list((fmeta.get("weapon_presets") or {}).get("preset")):
        n = (p.get("name") or "").lower()
        for word, kind in (("bomb", "bombs"), ("rocket", "rockets"), ("torpedo", "torpedoes"),
                           ("hvar", "rockets"), ("kg", "bombs"), ("lb", "bombs")):
            if word in n:
                kinds.add(kind)
    return sorted(kinds)


def main():
    os.makedirs(CACHE, exist_ok=True)
    # versões antigas guardavam as fichas de voo inteiras (~180 MB)
    shutil.rmtree(os.path.join(CACHE, "aces.vromfs.bin_u"), ignore_errors=True)
    print("Consultando o datamine...")
    commit = api("commits/master")["sha"]
    top = subtree(commit)
    version = http_get(f"https://raw.githubusercontent.com/{REPO}/{commit}/version").decode().strip()
    print(f"Versão do jogo no datamine: {version}")

    char_cfg = subtree(subtree(top["char.vromfs.bin_u"]["sha"])["config"]["sha"])
    lang_dir = subtree(subtree(top["lang.vromfs.bin_u"]["sha"])["lang"]["sha"])
    aces = subtree(top["aces.vromfs.bin_u"]["sha"])
    fm_root = subtree(subtree(aces["gamedata"]["sha"])["flightmodels"]["sha"])
    fm_dir = subtree(fm_root["fm"]["sha"])

    print("Baixando tabelas gerais (preço/BR, tags, nomes)...")
    wpcost = load_json(cached("char.vromfs.bin_u/config/wpcost.blkx", char_cfg["wpcost.blkx"]["sha"], commit))
    unittags = load_json(cached("char.vromfs.bin_u/config/unittags.blkx", char_cfg["unittags.blkx"]["sha"], commit))
    units_csv = cached("lang.vromfs.bin_u/lang/units.csv", lang_dir["units.csv"]["sha"], commit)
    weap_csv = cached("lang.vromfs.bin_u/lang/units_weaponry.csv", lang_dir["units_weaponry.csv"]["sha"], commit)

    names = {}
    with open(units_csv, encoding="utf-8") as f:
        for row in csv.reader(f, delimiter=";"):
            if row and not row[0].startswith("<"):
                names[row[0]] = row[1:1 + len(LANG_COLUMNS)]
    weapon_names = {}
    with open(weap_csv, encoding="utf-8") as f:
        for row in csv.reader(f, delimiter=";"):
            if len(row) > 1 and row[0].startswith("weapons/") and row[0].count("/") == 1:
                weapon_names[row[0][8:]] = row[1]

    air_ids = [k for k, v in wpcost.items() if isinstance(v, dict) and v.get("unitMoveType") == "air"]
    print(f"{len(air_ids)} aviões. Baixando fichas de voo (pode levar alguns minutos na 1ª vez)...")

    def fetch_meta(uid):
        name = uid + ".blkx"
        entry = fm_root.get(name) or fm_root.get(name.lower())
        if not entry:
            return uid, None
        return uid, cached_extract(f"aces.vromfs.bin_u/gamedata/flightmodels/{entry['name']}",
                                   entry["sha"], commit, extract_meta)

    metas = {}
    done = 0
    with ThreadPoolExecutor(max_workers=16) as pool:
        for uid, meta in pool.map(fetch_meta, air_ids):
            metas[uid] = meta
            done += 1
            if done % 200 == 0:
                print(f"  {done}/{len(air_ids)}")

    fm_needed = {}
    for uid, meta in metas.items():
        if meta:
            base = os.path.basename(meta.get("fmFile") or uid).lower()
            fm_needed[uid] = os.path.splitext(base)[0] + ".blkx"

    def fetch_fm(fname):
        entry = None
        for cand in (fname, fname.replace("_", "-"), fname.replace("-", "_")):
            entry = fm_dir.get(cand)
            if entry:
                break
        if not entry:
            return fname, None
        return fname, cached_extract(f"aces.vromfs.bin_u/gamedata/flightmodels/fm/{entry['name']}",
                                     entry["sha"], commit, extract_fm)

    fms = {}
    with ThreadPoolExecutor(max_workers=16) as pool:
        for fname, fm in pool.map(fetch_fm, sorted(set(fm_needed.values()))):
            fms[fname] = fm
    print(f"  {len(fms)} modelos de voo.")

    aircraft = {}
    name_index = {}
    for uid in air_ids:
        cost = wpcost[uid]
        tags_block = unittags.get(uid, {})
        tags = sorted(t for t in tags_block.get("tags", {}) if t.startswith("type_"))
        shop = tags_block.get("Shop", {})
        meta = metas.get(uid) or {}
        fm = fms.get(fm_needed.get(uid, ""), None) or {}

        guns = {}
        turrets = {}
        for w in meta.get("weapons", []):
            trig = w.get("trigger", "")
            key = weapon_key(w.get("blk"))
            label = weapon_names.get(key) or key
            if trig.startswith("gunner"):
                t = turrets.setdefault(trig, {})
                t[label] = t.get(label, 0) + 1
            elif trig in ("machine gun", "cannon", "additional gun"):
                g = guns.setdefault(label, {"count": 0, "ammo": 0})
                g["count"] += 1
                g["ammo"] += int(w.get("bullets") or 0)

        def nm(suffix, lang=0):
            row = names.get(f"{uid}_{suffix}")
            return row[lang] if row and len(row) > lang and row[lang] else None

        speed = shop.get("maxSpeed")
        climb_time = shop.get("climbTime")
        aircraft[uid] = {
            "id": uid,
            "name": nm("shop") or nm("0") or uid,
            "full": nm("0"),
            "short": nm("1"),
            "pt": nm("shop", LANG_COLUMNS.index("Portuguese")),
            "country": (cost.get("country") or "").replace("country_", ""),
            "cls": (cost.get("unitClass") or "").replace("exp_", ""),
            "tags": [t[5:] for t in tags],
            "rank": cost.get("rank"),
            "br": br_from_rank(cost.get("economicRankArcade")),
            "brRB": br_from_rank(cost.get("economicRankHistorical")),
            "crew": cost.get("crewTotalCount"),
            "premium": bool(cost.get("costGold")),
            "speed": round(speed * 3.6) if speed else None,
            "speedAlt": round(shop["maxSpeedAlt"]) if shop.get("maxSpeedAlt") else None,
            "climb": round(shop["climbSpeed"], 1) if shop.get("climbSpeed") else None,
            "climbTime": round(climb_time) if climb_time else None,
            "climbAlt": round(shop["climbAlt"]) if shop.get("climbAlt") else None,
            "turn": shop.get("turnTime"),
            "roll": shop.get("rollRate"),
            "ceiling": round(shop["maxAltitude"]) if shop.get("maxAltitude") else None,
            "wingLoad": shop.get("wingLoading"),
            "pwr": shop.get("powerToWeightRatio"),
            "twr": shop.get("thrustToWeightRatio"),
            "takeoff": shop.get("airfieldLen"),
            "vne": fm.get("vne"),
            "mne": fm.get("mne"),
            "mass": fm.get("mass"),
            "gearMax": fm.get("gearMax"),
            "guns": [{"name": k, "count": v["count"], "ammo": v["ammo"]} for k, v in guns.items()],
            "turrets": [{"pos": k, "guns": [{"name": n, "count": c} for n, c in v.items()]}
                        for k, v in sorted(turrets.items())],
            "ordnance": meta.get("ordnance", []),
        }

        # nomes como aparecem no kill feed / chat, em todos os idiomas
        for suffix in ("shop", "0", "1", "2"):
            for value in names.get(f"{uid}_{suffix}", []):
                if value:
                    key = normalize(value)
                    lst = name_index.setdefault(key, [])
                    if uid not in lst:
                        lst.append(uid)
        name_index.setdefault(normalize(uid), [uid])

    os.makedirs(DATA, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"version": version, "built": time.strftime("%Y-%m-%d %H:%M"),
                   "aircraft": aircraft, "names": name_index}, f, ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(OUT) / 1024 / 1024
    print(f"Pronto: {len(aircraft)} aviões em {OUT} ({size:.1f} MB)")


ZW = re.compile("[​‌‍⁠﻿]")


def normalize(s):
    s = ZW.sub("", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
