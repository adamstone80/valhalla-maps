#!/usr/bin/env python3
"""Write one dossier per zone: what the zone introductions are written from.

  python3 tools/dossier.py PATH/TO/DikuMUD3 PATH/TO/DikuMUD2 [QUEST_SECTIONS_DIR]

Each dossier (tools/private/dossiers/<game>_<zone>.json, kept out of git: it holds spoilers) has two halves:

  public  what a player sees by walking in: the zone's title, the builder's notes
          and help text, room titles and descriptions, monsters, objects, levels
          and neighbouring zones. The introduction may use any of it.
  sealed  the zone's quests: its section of the quest guide when there is one, else
          the zone's DIL scripts. Only tools/intros.py's hint step reads it, and turns
          each quest into one line of general language; the writer never sees it,
          and the leak check compares each introduction against it.
"""
import glob
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import world  # noqa: E402  (reads the two checkouts from sys.argv)

QUESTS = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else "/mnt/drive3/dikumud2-notes/quest-sections"
OUT = os.path.join(HERE, "tools/private/dossiers")  # spoilers: never committed

SYSTEM = world.SYSTEM

UNIT = re.compile(r"(?ms)^\s*([\w]+)\s*\n(.*?)^\s*end\s*$")


def clean(t, n=None):
    t = world.plain(t)
    return t[:n].rsplit(" ", 1)[0] + "…" if n and len(t) > n else t


def first_str(key, body, S):
    """The unit's own field, not one inside an exit or an extra description."""
    head = re.split(r"\bexit\s*\[|\bextra\s*\{", body)[0]
    m = re.search(rf"\b{key}\s+@@S(\d+)@@", head)
    return S(m.group(1)) if m else ""


def read_zone(game, fname):
    raw = world.preprocess(game, fname)
    dil = "\n".join(re.findall(r"dilbegin.*?dilend", raw, flags=re.S))
    text, strs = world.strings_out(raw)
    S = lambda m: strs[int(m)]
    text = re.sub(r"dilbegin.*?dilend", "", text, flags=re.S)
    parts, marks = {}, list(world.SECTION.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        parts[m.group(1)] = parts.get(m.group(1), "") + text[m.end():end]
    hm = re.search(r"(?m)^\s*help\s+@@S(\d+)@@", parts.get("zone", ""))
    units = {}
    for sec in ("rooms", "mobiles", "objects"):
        units[sec] = {}
        for m in UNIT.finditer(parts.get(sec, "")):
            sym, body = m.group(1).lower(), m.group(2)
            units[sec][sym] = dict(title=clean(first_str("title", body, S)), descr=first_str("descr", body, S))
    loads = re.findall(r"\bload\s+([\w@/-]+)", parts.get("reset", ""))
    return dict(help=S(hm.group(1)) if hm else "", units=units, dil=dil, loads=loads)


def quest_section(ids):
    """The quest guide sections whose heading names one of these zone ids."""
    out = []
    for f in sorted(glob.glob(os.path.join(QUESTS, "*.md"))):
        txt = open(f, errors="replace").read()
        head = txt.split("\n", 1)[0]
        if any(re.search(rf"`{re.escape(i)}`", head) for i in ids):
            out.append(txt.strip())
    return "\n\n".join(out)


def main():
    os.makedirs(OUT, exist_ok=True)
    games = {}
    for game in ("d3", "d2"):
        zones, listed = world.load_game(game)
        world.analyse(game, zones)
        games[game] = dict(zones=zones, listed=set(listed))
    d2to3, _ = world.match_zones(games["d3"]["zones"], games["d2"]["zones"])
    d3to2 = {a: b for b, a in d2to3.items()}
    index = {}
    for game in ("d3", "d2"):
        for z, Z in games[game]["zones"].items():
            key = f"{game}:{z}"
            if z in SYSTEM or len(Z["rooms"]) < 3:
                index[key] = dict(skip="system or no rooms")
                continue
            if game == "d2" and z in d2to3:
                index[key] = dict(same_as=f"d3:{d2to3[z]}")  # one introduction for the pair
                continue
            on_valhalla = game == "d3" or z in games["d3"]["listed"]
            if not on_valhalla:
                index[key] = dict(skip="not in Valhalla's zone list")
                continue
            R = read_zone(game, Z["file"])
            twin = d3to2.get(z) if game == "d3" else None
            R2 = read_zone("d2", games["d2"]["zones"][twin]["file"]) if twin else None
            rooms = R["units"]["rooms"]
            mobs, objs = R["units"]["mobiles"], R["units"]["objects"]
            loaded = {l.split("@")[0].lower() for l in R["loads"] if "@" not in l or l.endswith("@" + z)}
            mob_list = sorted(({"name": mobs[s]["title"] or s, "level": Z["mobs"].get(s, {}).get("level"),
                                "aggressive": Z["mobs"].get(s, {}).get("aggressive", False),
                                "descr": clean(mobs[s]["descr"], 160)}
                               for s in mobs if s in loaded or not loaded),
                              key=lambda m: -(m["level"] or 0))
            obj_list = [objs[s]["title"] for s in objs if objs[s]["title"] and (s in loaded or not loaded)]
            descs = [(r, clean(rooms[r]["descr"], 500)) for r in rooms if rooms[r]["descr"].strip()]
            # a spread of rooms: every n-th one, so the whole zone is represented
            step = max(1, len(descs) // 12)
            neighbours = sorted({games[game]["zones"][ez]["title"] for Rm in Z["rooms"].values()
                                 for _, ez, _, _ in Rm["exits"] if ez != z and ez in games[game]["zones"]})
            quest_ids = {z, Z["file"][:-4]} | ({twin} if twin else set())
            sealed_guide = quest_section(quest_ids)
            sealed_dil = R["dil"] + ("\n" + R2["dil"] if R2 else "")
            pub = dict(
                game=world.GAMES[game]["name"], id=z, title=Z["title"] or z, creators=Z["creators"],
                notes=Z["notes"], help=world.plain(R["help"]), levels=Z["levels"], rooms=len(Z["rooms"]),
                room_titles=sorted({world.plain(r["title"]) for r in Z["rooms"].values()})[:60],
                room_descriptions=[d for _, d in descs[::step][:14]],
                monsters=mob_list[:20], objects=sorted(set(obj_list))[:40], neighbours=neighbours)
            sealed = dict(quest_guide=sealed_guide, dil=sealed_dil[:60000] if not sealed_guide else "",
                          has_dil_quest=bool(re.search(r"qst\w+@quests|Quest\b|quests\s*\)", sealed_dil)))
            d = dict(key=key, public=pub, sealed=sealed)
            d["source_hash"] = hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]
            fn = f"{game}_{z}.json"
            json.dump(d, open(os.path.join(OUT, fn), "w"), indent=1, ensure_ascii=False)
            index[key] = dict(file=fn, hash=d["source_hash"], twin=f"d2:{twin}" if twin else None)
    json.dump(index, open(os.path.join(OUT, "index.json"), "w"), indent=1, sort_keys=True)
    n = sum(1 for v in index.values() if "file" in v)
    print(f"{n} dossiers; {sum(1 for v in index.values() if 'same_as' in v)} twins share one; "
          f"{sum(1 for v in index.values() if 'skip' in v)} skipped", file=sys.stderr)


if __name__ == "__main__":
    main()
