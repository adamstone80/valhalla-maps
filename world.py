#!/usr/bin/env python3
"""Build world/index.html, the zone map of DikuMUD II and DikuMUD III, from both checkouts.

  python3 world.py PATH/TO/DikuMUD3 PATH/TO/DikuMUD2

Every zone in each game's zone list is run through the game's own preprocessor
(DikuMUD3's vme/bin/pp), so macros are expanded and flags are plain numbers. From
that it reads each zone's header (title, creators, notes), rooms (names, flags,
exits, the room they sit in), monsters (level, aggressive) and resets, and works out:

  - links between zones: every exit whose room is in another zone
  - a level range: the middle 80% of the levels of the monsters the zone loads
  - a teleport point: a room for "cast controlled teleport <name>" that the spell
    accepts (no no-teleport flag on it or on a room it sits in), whose name no other
    room, monster or object in that game has (the spell takes the first unit with the
    longest matching name), with no aggressive monster loaded into it, preferring
    temples, inns, squares and shops
  - for a zone without one, the nearest teleport point and the walk from it

The layout places zones so that each link points the way its exits point, then
pushes boxes apart. Each view (DikuMUD III, DikuMUD II, both) has its own layout.
The result is filled into world-template.html.
"""
import collections
import heapq
import datetime
import json
import math
import os
import re
import subprocess
import sys

D3 = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/DikuMUD3"))
D2 = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser("~/DikuMUD2"))
HERE = os.path.dirname(os.path.abspath(__file__))
PP = os.path.join(D3, "vme/bin/pp")

GAMES = {
    "d3": dict(name="DikuMUD III", zondir=os.path.join(D3, "vme/zone"), include=[os.path.join(D3, "vme/include")],
               zonelist=os.path.join(D3, "vme/etc/zonelist"),
               no_tele=0x4000 | 0x8000 | 0x0010 | 0x0200,  # UNIT_FL_NO_TELEPORT in vme.h: four flags, any one blocks it
               aggressive=re.compile(r"aggressive@function")),
    "d2": dict(name="DikuMUD II", zondir=os.path.join(D2, "dm-dist-ii/zon"), include=[os.path.join(D2, "dm-dist-ii"), os.path.join(D2, "dm-dist-ii/zon")],
               zonelist=os.path.join(D2, "dm-dist-ii/zon/zonelist"),
               no_tele=0x0010,  # UNIT_FL_NO_TELEPORT in values.h
               aggressive=re.compile(r"\bspecial\s+30\b")),  # SFUN_AGGRESSIVE
}
UNIT_FL_NO_MOB, UNIT_FL_SACRED = 0x0040, 0x0020
ENTRY = ("udgaard", "temple")  # DEFAULT_ENTRY_ZONE/NAME in zon_basis: where players start and return after dying
# Zones that hold commands, spells, boards and other machinery, not places to visit
SYSTEM = {"basis", "basemove", "baseget", "baselook", "boards", "clans", "comm", "commands", "competition",
          "death", "function", "g_q", "guild_paths", "guilds", "helpzon", "mail", "quests", "randomt",
          "restrict", "set", "skills", "socials", "spells", "update", "wiz", "professions", "justice"}
# Regions: neighbourhoods of zones, drawn as one area each, by zone id (both games). A zone
# that isn't listed joins the region it has most exits to.
REGIONS = {
    "Midgaard": ["midgaard", "midwalls", "midsewers", "kingc", "arena", "sorcerer", "paladin_guild", "asgaard",
                 "academy", "citadel", "reslab", "thievesguild", "mageguild", "fightersguild", "clericguild"],
    "Udgaard & Cypress": ["udgaard", "offices", "newbie", "udsewer", "cypress", "rebirth", "youth",
                                   "goblin_cave", "gremlin", "barbarian", "clan_koh", "haunted"],
    "Haon-Dor": ["haon_dor", "halfzon", "elfdom", "toy", "ogre1", "ogre", "fields", "forest", "wcastle", "blcastle"],
    "Ratswarf & Torsbay": ["ratswarf", "torsbay", "farm", "farm1", "hobgob", "gazha", "bounty", "ww1", "ww2", "tower",
                             "cloud", "houses", "garden", "lostlands", "cthulu", "hills", "dwarves", "rotten"],
    "Nymgaard & Mystic Forest": ["nymgaard", "trees", "psionic", "sandzone", "sands2", "talen", "foothill",
                                       "ranger", "monk", "vine"],
    "Urland & Mountains": ["urland", "mount", "akaren", "arctic", "skaven", "tiamat", "gnome", "darkelf",
                                 "volcano", "hades1"],
    "Hades": ["hades2", "hades3", "hades4", "hades5", "hades6", "hades7", "hades8"],
    "Moors & Swamps": ["moor", "hamlet", "manse", "deadl1", "keep", "center", "etznab", "seren", "seren1",
                         "gobtown", "gobtown1"],
    "Xiyang & Desert": ["outxiyang", "xiyang", "xiyang2", "desert", "arabian", "assassin", "deathlink", "isledead",
                              "cemetery", "necro_guild", "neptune", "warntz", "demon_realm", "abyss1", "ishlor"],
    "Atlantis": ["atl_beach", "atl_sea", "atl_misc"],
}
REGION_OF = {z: r for r, zs in REGIONS.items() for z in zs}
DIRS = ["n", "e", "s", "w", "u", "d", "ne", "nw", "se", "sw"]
DVEC = {"n": (0, -1), "e": (1, 0), "s": (0, 1), "w": (-1, 0), "ne": (.71, -.71), "nw": (-.71, -.71),
        "se": (.71, .71), "sw": (-.71, .71), "u": (0, 0), "d": (0, 0)}
SECTION = re.compile(r"(?m)^[ \t]*%(zone|dil|rooms|objects|mobiles|reset|end)\b")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()


def zonelist(path):
    names = []
    for line in open(path, errors="replace"):
        line = line.strip()
        if line and not line.startswith(("#", "//")):
            names.append(line.split()[0])
    return names


def preprocess(game, fname):
    g = GAMES[game]
    args = [PP] + [f"-I{d}/" for d in g["include"]] + [fname]
    out = subprocess.run(args, cwd=g["zondir"], capture_output=True, text=True, errors="replace").stdout
    return "\n".join(l for l in out.split("\n") if not l.startswith("#line") and not l.startswith("# "))


def strings_out(text):
    """Replace every string literal by @@S<n>@@ so structure can be parsed safely."""
    strs = []

    def keep(m):
        strs.append(m.group(0)[1:-1].replace('\\"', '"'))
        return f"@@S{len(strs) - 1}@@"

    return re.sub(r'"(?:[^"\\]|\\.)*"', keep, text, flags=re.S), strs


def num_expr(e):
    e = e.strip()
    if not e or not re.fullmatch(r"[0-9a-fA-FxX+|()\s]+", e):
        return 0
    try:
        return int(eval(e.replace("X", "x"), {"__builtins__": {}}))
    except Exception:
        return 0


def flags_of(body):
    v = 0
    for m in re.finditer(r"\bflags\s*\{([^}]*)\}", body):
        for part in m.group(1).split(","):
            v |= num_expr(part)
    return v


def years_in(text):
    ys = {int(y) for y in re.findall(r"\b(19[89]\d|20[0-2]\d)\b", text)}
    for m in re.finditer(r"\b(" + "|".join(MONTHS) + r")[a-z]*\.?\s+(\d{2})\b", text, flags=re.I):
        y = int(m.group(2))
        ys.add(1900 + y if y >= 80 else 2000 + y)
    return sorted(y for y in ys if 1985 <= y <= datetime.date.today().year)


def plain(t):
    """A title as players see it: no HTML tags or old colour codes"""
    t = re.sub(r"<br\s*/?>", " ", t, flags=re.I)
    t = re.sub(r"<[^>]*>", "", t)
    t = re.sub(r"&(c\+?[a-z]|[a-z])", "", t)
    return re.sub(r"\s+", " ", t).strip()


def pretty_title(title, zone):
    """A zone without a real title ("hades3", "atl_sea") gets one a player can read: "Hades 3", "Atl Sea"."""
    if title and title.lower() != zone.lower():
        return title
    t = re.sub(r"(?<=[a-z])(?=\d)", " ", (title or zone).replace("_", " "))
    return " ".join(w[:1].upper() + w[1:] for w in t.split())


def ref(target, zone):
    """'room@zone', 'zone/room' or 'room' -> (zone, room)"""
    if "@" in target:
        r, z = target.split("@", 1)
    elif "/" in target:
        z, r = target.split("/", 1)
    else:
        z, r = zone, target
    return z.lower(), r.lower()


def parse_zone(game, fname):
    raw = preprocess(game, fname)
    text, strs = strings_out(raw)
    S = lambda m: strs[int(m)]
    text = re.sub(r"dilbegin.*?dilend", "", text, flags=re.S)
    parts = {}
    marks = list(SECTION.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        parts.setdefault(m.group(1), "")
        parts[m.group(1)] += text[m.end():end]
    if "zone" not in parts:
        return None
    hdr = parts["zone"]
    zm = re.match(r"\s*([\w-]+)", hdr)
    zone = (zm.group(1) if zm else os.path.basename(fname)[:-4]).lower()

    def hstr(key):
        m = re.search(rf"(?m)^\s*{key}\s+@@S(\d+)@@", hdr)
        return S(m.group(1)).strip() if m else ""

    cm = re.search(r"\bcreators\s*\{([^}]*)\}", hdr)
    creators = [S(x) for x in re.findall(r"@@S(\d+)@@", cm.group(1))] if cm else []
    notes = hstr("notes")
    title = re.sub(r"(?<=[a-z])Mainland$", "", plain(hstr("title").split("@")[0]))  # "Thieves GuildMainland": an @ missing
    Z = dict(game=game, id=zone, file=os.path.basename(fname), title=title, creators=creators,
             notes=EMAIL.sub("[email removed]", notes), years=years_in(notes + " " + hstr("help")),
             rooms={}, mobs={}, objs={}, loads=[])

    unit_re = re.compile(r"(?ms)^\s*([\w]+)\s*\n(.*?)^\s*end\s*$")
    for m in unit_re.finditer(parts.get("rooms", "")):
        sym, body = m.group(1).lower(), m.group(2)
        nm = re.search(r"\bnames\s*\{([^}]*)\}", body)
        tm = re.search(r"\btitle\s+@@S(\d+)@@", body)
        im = re.search(r"(?m)^\s*in\s+([\w@/-]+)", body)
        exits = []
        for e in re.finditer(r"\bexit\s*\[\s*(\d+)\s*\]\s*to\s+([\w@/-]+)((?:(?!\bexit\s*\[)[^;])*)", body):
            d = int(e.group(1))
            if d >= len(DIRS):
                continue
            rest, door = e.group(3), None
            om = re.search(r"\bopen\s*\{([^}]*)\}", rest)
            of = 0
            for part in (om.group(1).split(",") if om else []):
                of |= num_expr(part)
            if of & 0x01:  # EX_OPEN_CLOSE: a door; EX_LOCKED 0x04, EX_HIDDEN 0x20
                km = re.search(r"\bkeyword\s*\{\s*@@S(\d+)@@", rest)
                door = (S(km.group(1)) if km else "door", bool(of & 0x04), bool(of & 0x20))
            exits.append((DIRS[d],) + ref(e.group(2), zone) + (door,))
        Z["rooms"][sym] = dict(names=[S(x) for x in re.findall(r"@@S(\d+)@@", nm.group(1))] if nm else [],
                               title=plain(S(tm.group(1))) if tm else sym,
                               flags=flags_of(body), inside=ref(im.group(1), zone) if im else None, exits=exits)
    for sec, store in (("mobiles", "mobs"), ("objects", "objs")):
        for m in unit_re.finditer(parts.get(sec, "")):
            sym, body = m.group(1).lower(), m.group(2)
            nm = re.search(r"\bnames\s*\{([^}]*)\}", body)
            lv = re.search(r"\blevel\s+(\d+)", body)
            Z[store][sym] = dict(names=[S(x) for x in re.findall(r"@@S(\d+)@@", nm.group(1))] if nm else [],
                                 level=int(lv.group(1)) if lv else None,
                                 aggressive=bool(GAMES[game]["aggressive"].search(body)))
    for m in re.finditer(r"\bload\s+([\w@/-]+)\s+into\s+([\w@/-]+)", parts.get("reset", "")):
        Z["loads"].append((ref(m.group(1), zone), ref(m.group(2), zone)))
    return Z


def load_game(game):
    g = GAMES[game]
    listed = zonelist(g["zonelist"])
    zones = {}
    for f in sorted(os.listdir(g["zondir"])):
        if not f.endswith(".zon") or f[:-4] not in listed:
            continue
        Z = parse_zone(game, f)
        if Z:
            zones[Z["id"]] = Z
    return zones, listed


def percentile(v, p):
    v = sorted(v)
    k = (len(v) - 1) * p
    return v[int(math.floor(k))] if v else None


def analyse(game, zones):
    g = GAMES[game]
    rooms = {(z, r): R for z, Z in zones.items() for r, R in Z["rooms"].items()}
    # names of every unit in the game: the spell takes the first unit with the longest match
    name_count = collections.Counter()
    for Z in zones.values():
        for store in ("rooms", "mobs", "objs"):
            for u in Z[store].values():
                for n in {n.lower().strip() for n in u["names"]}:
                    name_count[n] += 1
    loads_into = collections.defaultdict(list)
    for Z in zones.values():
        for (mz, ms), into in Z["loads"]:
            mob = zones.get(mz, {}).get("mobs", {}).get(ms)
            if mob:
                loads_into[into].append(mob)
    # exits that lead to a room that exists
    for (z, r), R in rooms.items():
        R["exits"] = [e for e in R["exits"] if (e[1], e[2]) in rooms]
    # reverse adjacency for "near the border"
    border = {k for k, R in rooms.items() if any(e[1] != k[0] for e in R["exits"])}
    near_border = set(border)
    for k in border:
        for e in rooms[k]["exits"]:
            if e[1] == k[0]:
                near_border.add((e[1], e[2]))

    def blocked(key):
        seen = set()
        while key and key in rooms and key not in seen:
            seen.add(key)
            if rooms[key]["flags"] & g["no_tele"]:
                return True
            key = rooms[key]["inside"]
        return False

    WANT = [(r"\btemple\b|\bchapel\b|\bshrine\b", 50), (r"\binn\b|\btavern\b|\bbar\b|\bpub\b", 40),
            (r"\bsquare\b|\bplaza\b|\bmarket\b|\bcommons?\b", 35), (r"\bshop\b|\bstore\b|\bbank\b|\bpost\b|smith|\bforge\b|\bbakery\b", 25),
            (r"\bguild\b|\bhall\b", 15), (r"\bentrance\b|\bgate\b|\broad\b|\bpath\b|\bbridge\b", 10),
            (r"\bdeath\b|\bpit\b|\blair\b|\bden\b|\bnest\b|\bprison\b|\bcell\b|\btrap\b|\bvoid\b|\bevil\b|\bdark\b|\bhell\b|\bdungeon\b|\bcrypt\b|\btomb\b", -60)]
    for z, Z in zones.items():
        cands = []
        for r, R in Z["rooms"].items():
            uniq = sorted({n.strip() for n in R["names"] if n.strip() and name_count[n.lower().strip()] == 1
                           and not re.fullmatch(r"[a-z ]*\d+", n.strip().lower())}, key=len)
            if not uniq or blocked((z, r)):
                continue
            aggr = [m for m in loads_into.get((z, r), []) if m["aggressive"]]
            if aggr:
                continue
            t = R["title"].lower()
            score = sum(w for pat, w in WANT if re.search(pat, t))
            score += 15 if R["flags"] & UNIT_FL_NO_MOB else 0
            score += 10 if (z, r) in near_border else 0
            score -= len(uniq[0]) / 10
            cands.append((score, r, uniq[0]))
        cands.sort(key=lambda c: -c[0])
        Z["teleport"] = [dict(room=r, name=n, title=Z["rooms"][r]["title"]) for s, r, n in cands[:4]]
        Z["blocked_rooms"] = sum(1 for r in Z["rooms"] if blocked((z, r)))
        Z["named_rooms"] = sum(1 for R in Z["rooms"].values() if R["names"])
        # level range: monsters loaded into this zone's rooms (or defined here)
        lv = [m["level"] for (rz, rr), ms in loads_into.items() if rz == z for m in ms if m["level"] is not None]
        if not lv:
            lv = [m["level"] for m in Z["mobs"].values() if m["level"] is not None]
        Z["levels"] = [percentile(lv, .1), percentile(lv, .9)] if lv else None
    # walk from the nearest teleport point to zones without one
    sources = {(z, t["room"]): (z, t["name"]) for z, Z in zones.items() for t in Z["teleport"][:1]}
    for z, Z in zones.items():
        if Z["teleport"] or not Z["rooms"]:
            continue
        # fewest steps, a door counting as 5; never through a locked door
        prev = {k: None for k in sources}
        dist = {k: 0 for k in sources}
        heap = [(0, i, k) for i, k in enumerate(sources)]
        heapq.heapify(heap)
        hit, tick = None, len(heap)
        while heap:
            c, _, k = heapq.heappop(heap)
            if c > dist.get(k, 1e9):
                continue
            if k[0] == z:
                hit = k
                break
            for d, ez, er, door in rooms[k]["exits"]:
                if door and (door[1] or door[2]):
                    continue
                n, nc = (ez, er), c + (5 if door else 1)
                if nc < dist.get(n, 1e9):
                    dist[n], prev[n] = nc, (k, d, door)
                    tick += 1
                    heapq.heappush(heap, (nc, tick, n))
        if not hit:
            Z["walk"] = None
            continue
        steps, k = [], hit
        while prev[k]:
            k, d, door = prev[k]
            steps.append(d)
            if door:
                steps.append("open " + door[0])
        steps.reverse()
        src = sources[k]
        Z["walk"] = dict(zone=src[0], name=src[1], steps=compress(steps), n=len(steps),
                         to=rooms[hit]["title"], to_room=hit[1])
    routes_from_entry(zones, rooms)
    return rooms


def routes_from_entry(zones, rooms):
    """The walk from where players start to the nearest room of every zone it reaches:
    fewest moves, a door counting as 5, never through a locked or hidden door."""
    start = ENTRY if ENTRY in rooms else None
    for Z in zones.values():
        Z["route"] = None
    if not start:
        return
    dist, prev, tick = {start: 0}, {start: None}, 0
    heap = [(0, 0, start)]
    first = {}
    while heap:
        c, _, k = heapq.heappop(heap)
        if c > dist[k]:
            continue
        first.setdefault(k[0], k)
        for d, ez, er, door in rooms[k]["exits"]:
            if door and (door[1] or door[2]):
                continue
            n, nc = (ez, er), c + (5 if door else 1)
            if nc < dist.get(n, 1e9):
                dist[n], prev[n] = nc, (k, d, door)
                tick += 1
                heapq.heappush(heap, (nc, tick, n))
    for z, hit in first.items():
        if z == start[0] or z not in zones:
            continue
        steps, via, k = [], [], hit
        while prev[k]:
            k, d, door = prev[k]
            steps.append(d)
            if door:
                steps.append("open " + door[0])
            if k[0] != z and (not via or via[-1] != k[0]):
                via.append(k[0])
        steps.reverse()
        via.reverse()
        zones[z]["route"] = dict(steps=compress(steps), n=sum(1 for s in steps if not s.startswith("open ")),
                                 via=[v for v in via if v != start[0]], to=rooms[hit]["title"])


def compress(steps):
    out = []
    for d in steps:
        if out and out[-1][0] == d and not d.startswith("open "):
            out[-1][1] += 1
        else:
            out.append([d, 1])
    return ", ".join(f"{n}{d}" if n > 1 else d for d, n in out)


# ---------------------------------------------------------------- views and layout

SPACE, PAD = 140, 90  # between linked zones' edges, and the least between any two in a group


def side(rooms):
    return 150 + 12 * math.sqrt(max(rooms, 1))


def layout(nodes, edges, anchor):
    """nodes: id -> size; edges: list of (a, b, (dx, dy) or None). Returns id -> (x, y) centres."""
    adj = collections.defaultdict(list)
    for a, b, v in edges:
        adj[a].append((b, v))
        adj[b].append((a, (-v[0], -v[1]) if v else None))
    comps, seen = [], set()
    order = sorted(nodes, key=lambda n: (n != anchor, -nodes[n]))
    for n in order:
        if n in seen:
            continue
        comp, q = [], [n]
        seen.add(n)
        while q:
            k = q.pop(0)
            comp.append(k)
            for m, _ in adj[k]:
                if m not in seen:
                    seen.add(m)
                    q.append(m)
        comps.append(comp)
    placed = {}
    linked = [c for c in comps if len(c) > 1]
    islands = [c[0] for c in comps if len(c) == 1]
    boxes = []
    for comp in linked:
        pos = {comp[0]: [0.0, 0.0]}
        q = [comp[0]]
        free_angle = collections.Counter()
        while q:
            k = q.pop(0)
            for m, v in adj[k]:
                if m in pos:
                    continue
                L = (nodes[k] + nodes[m]) / 2 + SPACE
                if v and (v[0] or v[1]):
                    pos[m] = [pos[k][0] + v[0] * L, pos[k][1] + v[1] * L]
                else:
                    a = 0.6 + free_angle[k] * 1.1
                    free_angle[k] += 1
                    pos[m] = [pos[k][0] + math.cos(a) * L, pos[k][1] + math.sin(a) * L]
                q.append(m)
        cedges = [(a, b, v) for a, b, v in edges if a in pos and b in pos and a != b]
        for it in range(500):
            k_spring = 0.25 if it < 350 else 0.08
            for a, b, v in cedges:
                L = (nodes[a] + nodes[b]) / 2 + SPACE
                dx, dy = pos[b][0] - pos[a][0], pos[b][1] - pos[a][1]
                if v and (v[0] or v[1]):
                    tx, ty = v[0] * L, v[1] * L
                else:
                    d = math.hypot(dx, dy) or 1
                    tx, ty = dx / d * L, dy / d * L
                cx, cy = (dx - tx) * k_spring / 2, (dy - ty) * k_spring / 2
                pos[a][0] += cx; pos[a][1] += cy
                pos[b][0] -= cx; pos[b][1] -= cy
            ks = list(pos)
            for i in range(len(ks)):
                for j in range(i + 1, len(ks)):
                    a, b = ks[i], ks[j]
                    need = (nodes[a] + nodes[b]) / 2 + 46
                    dx, dy = pos[b][0] - pos[a][0], pos[b][1] - pos[a][1]
                    ox, oy = need - abs(dx), need - abs(dy)
                    if ox > 0 and oy > 0:
                        if ox < oy:
                            s = (1 if dx >= 0 else -1) * ox / 2
                            pos[a][0] -= s; pos[b][0] += s
                        else:
                            s = (1 if dy >= 0 else -1) * oy / 2
                            pos[a][1] -= s; pos[b][1] += s
        # then only push apart until no two boxes overlap
        ks = list(pos)
        for it in range(600):
            moved = False
            for i in range(len(ks)):
                for j in range(i + 1, len(ks)):
                    a, b = ks[i], ks[j]
                    need = (nodes[a] + nodes[b]) / 2 + PAD
                    dx, dy = pos[b][0] - pos[a][0], pos[b][1] - pos[a][1]
                    ox, oy = need - abs(dx), need - abs(dy)
                    if ox > 0 and oy > 0:
                        moved = True
                        if ox < oy:
                            s = (1 if dx >= 0 else -1) * (ox / 2 + 1)
                            pos[a][0] -= s; pos[b][0] += s
                        else:
                            s = (1 if dy >= 0 else -1) * (oy / 2 + 1)
                            pos[a][1] -= s; pos[b][1] += s
            if not moved:
                break
        x0 = min(pos[n][0] - nodes[n] / 2 for n in pos); y0 = min(pos[n][1] - nodes[n] / 2 for n in pos)
        x1 = max(pos[n][0] + nodes[n] / 2 for n in pos); y1 = max(pos[n][1] + nodes[n] / 2 for n in pos)
        boxes.append((pos, x0, y0, x1, y1))
    # shelves: the largest group first, the others in rows to its right and below
    W = max((b[3] - b[1] for b in boxes), default=1000)
    x, y, row_h, gap = 0.0, 0.0, 0.0, 260
    for pos, x0, y0, x1, y1 in boxes:
        w, h = x1 - x0, y1 - y0
        if x > 0 and x + w > max(W, 2400):
            x, y, row_h = 0.0, y + row_h + gap, 0.0
        for n, p in pos.items():
            placed[n] = (p[0] - x0 + x, p[1] - y0 + y)
        x += w + gap
        row_h = max(row_h, h)
    y += row_h + gap + 80
    island_top = y
    x = 0.0
    width = max(W, 2400)
    row_h = 0
    for n in sorted(islands, key=lambda n: -nodes[n]):
        s = nodes[n]
        if x > 0 and x + s > width:
            x, y, row_h = 0.0, y + row_h + 60, 0
        placed[n] = (x + s / 2, y + s / 2)
        x += s + 60
        row_h = max(row_h, s)
    return placed, (island_top if islands else None)


def build_view(view, games, match):
    """Nodes and edges for one view: 'd3', 'd2' or 'both'."""
    nid = {}
    nodes = {}
    for game in view:
        for z, Z in games[game]["zones"].items():
            key = f"{game}:{z}"
            if view == ("d3", "d2") and game == "d2" and z in match["d2to3"]:
                key = f"d3:{match['d2to3'][z]}"
            nid[(game, z)] = key
            nodes.setdefault(key, []).append((game, z))
    edges = collections.defaultdict(list)  # (nodeA, nodeB) -> list of exits
    for game in view:
        for (z, r), R in games[game]["rooms"].items():
            for d, ez, er, door in R["exits"]:
                if ez == z:
                    continue
                a, b = nid[(game, z)], nid[(game, ez)]
                if a == b:
                    continue
                edges[(a, b)].append(dict(g=game, d=d, fz=z, fr=r, tz=ez, tr=er))
    # visible: zones with links, or with 3+ rooms
    def rooms_of(key):
        return max(len(games[g]["zones"][z]["rooms"]) for g, z in nodes[key])
    linked = {k for ab in edges for k in ab}
    visible = {k for k in nodes if (k in linked or rooms_of(k) >= 3)
               and not all(z in SYSTEM for g, z in nodes[k])}
    size = {k: side(rooms_of(k)) for k in visible}
    lay_edges = []
    for (a, b), ex in edges.items():
        if a not in visible or b not in visible:
            continue
        vs = [DVEC[e["d"]] for e in ex if e["d"] not in ("u", "d")]
        v = (sum(x for x, _ in vs) / len(vs), sum(y for _, y in vs) / len(vs)) if vs else None
        if v:
            L = math.hypot(*v) or 1
            v = (v[0] / L, v[1] / L)
        lay_edges.append((a, b, v))
    anchor = next((k for k in ("d3:midgaard", "d2:midgaard") if k in visible), None)
    reg = regions_of(visible, lay_edges)
    pos, island_top, frames = layout_regions(size, lay_edges, anchor, reg)
    return nodes, edges, visible, size, pos, island_top, frames, reg


def regions_of(visible, lay_edges):
    """node -> region name: the listed one, else the region it has most exits to"""
    reg = {k: REGION_OF.get(k.split(":", 1)[1]) for k in visible}
    links = collections.defaultdict(collections.Counter)
    for a, b, _ in lay_edges:
        links[a][b] += 1
        links[b][a] += 1
    for _ in range(len(visible)):
        changed = False
        for k in sorted(visible):
            if reg[k] is None:
                votes = collections.Counter()
                for m, n in links[k].items():
                    if reg.get(m):
                        votes[reg[m]] += n
                if votes:
                    reg[k] = votes.most_common(1)[0][0]
                    changed = True
        if not changed:
            break
    return reg


def layout_regions(size, lay_edges, anchor, reg):
    """Each region laid out on its own, then the regions placed apart, joined the way their
    exits point. Zones with no exits at all go on a shelf below. Returns centres, the shelf's
    top, and the regions' frames."""
    linked = {k for a, b, _ in lay_edges for k in (a, b)}
    islands = {k for k in size if k not in linked}
    names = sorted({reg[k] for k in size if k not in islands and reg[k]}, key=lambda r: list(REGIONS).index(r) if r in REGIONS else 99)
    for k in size:
        if k not in islands and not reg[k]:
            reg[k] = "Elsewhere"
            if "Elsewhere" not in names:
                names.append("Elsewhere")
    HEAD, MARGIN, GAP = 150, 90, 260  # title space, inner margin, least gap between regions
    local, frame = {}, {}
    for r in names:
        mine = {k: size[k] for k in size if reg[k] == r and k not in islands}
        inner = [(a, b, v) for a, b, v in lay_edges if a in mine and b in mine]
        hub = anchor if anchor in mine else max(mine, key=lambda k: (sum(1 for a, b, _ in inner if k in (a, b)), mine[k]))
        p, _ = layout(mine, inner, hub)
        x0 = min(p[k][0] - mine[k] / 2 for k in mine); y0 = min(p[k][1] - mine[k] / 2 for k in mine)
        x1 = max(p[k][0] + mine[k] / 2 for k in mine); y1 = max(p[k][1] + mine[k] / 2 for k in mine)
        # wide enough for its name at the whole-map zoom (about 65 units a letter)
        w = max(x1 - x0 + 2 * MARGIN, len(r) * 65 + 160)
        dx = (w - (x1 - x0)) / 2
        local[r] = {k: (p[k][0] - x0 + dx, p[k][1] - y0 + MARGIN + HEAD) for k in mine}
        frame[r] = [w, y1 - y0 + 2 * MARGIN + HEAD]
    # regions joined by exits, pointing the average way their exits go
    rv = collections.defaultdict(lambda: [0.0, 0.0, 0])
    for a, b, v in lay_edges:
        ra, rb = reg.get(a), reg.get(b)
        if not ra or not rb or ra == rb or a in islands or b in islands:
            continue
        key, sgn = ((ra, rb), 1) if ra < rb else ((rb, ra), -1)
        if v:
            rv[key][0] += sgn * v[0]; rv[key][1] += sgn * v[1]
        rv[key][2] += 1
    first = reg.get(anchor) if anchor in reg and anchor not in islands else names[0]
    c = {first: [0.0, 0.0]}
    q = [first]
    turn = collections.Counter()
    while q:
        r = q.pop(0)
        for (ra, rb), (vx, vy, n) in sorted(rv.items(), key=lambda t: -t[1][2]):
            if r not in (ra, rb):
                continue
            o, sg = (rb, 1) if r == ra else (ra, -1)
            if o in c:
                continue
            d = math.hypot(vx, vy)
            ang = math.atan2(sg * vy, sg * vx) if d > .3 else 0.8 + turn[r] * 1.3
            turn[r] += 1
            L = (max(frame[r]) + max(frame[o])) / 2 + GAP
            c[o] = [c[r][0] + math.cos(ang) * L, c[r][1] + math.sin(ang) * L]
            q.append(o)
    apart = [r for r in names if r not in c]  # no exits to another region: placed below
    names = [r for r in names if r in c]
    # pull linked regions together, keep every two apart by GAP
    for it in range(800):
        if it < 400:
            for (ra, rb), (vx, vy, n) in rv.items():
                dx, dy = c[rb][0] - c[ra][0], c[rb][1] - c[ra][1]
                k = 0.02
                c[ra][0] += dx * k; c[ra][1] += dy * k
                c[rb][0] -= dx * k; c[rb][1] -= dy * k
        moved = False
        for i, ra in enumerate(names):
            for rb in names[i + 1:]:
                dx, dy = c[rb][0] - c[ra][0], c[rb][1] - c[ra][1]
                ox = (frame[ra][0] + frame[rb][0]) / 2 + GAP - abs(dx)
                oy = (frame[ra][1] + frame[rb][1]) / 2 + GAP - abs(dy)
                if ox > 0 and oy > 0:
                    moved = True
                    if ox < oy:
                        s = (1 if dx >= 0 else -1) * (ox / 2 + 1)
                        c[ra][0] -= s; c[rb][0] += s
                    else:
                        s = (1 if dy >= 0 else -1) * (oy / 2 + 1)
                        c[ra][1] -= s; c[rb][1] += s
        if it >= 400 and not moved:
            break
    placed, frames = {}, []
    gx0 = min(c[r][0] - frame[r][0] / 2 for r in names); gy0 = min(c[r][1] - frame[r][1] / 2 for r in names)
    for r in names:
        fx, fy = c[r][0] - frame[r][0] / 2 - gx0, c[r][1] - frame[r][1] / 2 - gy0
        for k, (x, y) in local[r].items():
            placed[k] = (x + fx, y + fy)
        frames.append(dict(n=r, x=round(fx, 1), y=round(fy, 1), w=round(frame[r][0], 1), h=round(frame[r][1], 1)))
    y = max(f["y"] + f["h"] for f in frames) + GAP
    x = 0.0
    for r in apart:
        for k, (lx, ly) in local[r].items():
            placed[k] = (lx + x, ly + y)
        frames.append(dict(n=r, x=round(x, 1), y=round(y, 1), w=round(frame[r][0], 1), h=round(frame[r][1], 1)))
        x += frame[r][0] + GAP
    # zones with no exits at all: a shelf below everything
    island_top = None
    if islands:
        width = max(f["x"] + f["w"] for f in frames)
        y = max(f["y"] + f["h"] for f in frames) + GAP + 80
        island_top, x, row_h = y, 0.0, 0
        for n in sorted(islands, key=lambda n: -size[n]):
            s = size[n]
            if x > 0 and x + s > width:
                x, y, row_h = 0.0, y + row_h + 60, 0
            placed[n] = (x + s / 2, y + s / 2)
            x += s + 60
            row_h = max(row_h, s)
    return placed, island_top, frames


def match_zones(z3, z2):
    """DikuMUD II zone -> DikuMUD III zone, by the rooms they share."""
    d2to3, notes = {}, []
    for a, A in z3.items():
        ra = set(A["rooms"])
        best = (0, None)
        for b, B in z2.items():
            rb = set(B["rooms"])
            if not ra or not rb:
                continue
            j = len(ra & rb) / len(ra | rb)
            if j > best[0]:
                best = (j, b)
        j, b = best
        same = a.replace("-", "_") == (b or "").replace("-", "_")
        if b and (j >= 0.3 or (same and j >= 0.1)) and b not in d2to3:
            d2to3[b] = a
            notes.append(f"{a} <- {b}: {j:.2f}")
    return d2to3, notes


def main():
    games = {}
    for game in ("d3", "d2"):
        zones, listed = load_game(game)
        rooms = analyse(game, zones)
        games[game] = dict(zones=zones, rooms=rooms, listed=listed)
        print(f"{game}: {len(zones)} zones parsed, {len(rooms)} rooms, "
              f"{sum(1 for Z in zones.values() if Z['teleport'])} with a teleport point", file=sys.stderr)
    d2to3, mnotes = match_zones(games["d3"]["zones"], games["d2"]["zones"])
    print("matched:", "; ".join(mnotes), file=sys.stderr)
    match = dict(d2to3=d2to3)
    d3listed = set(games["d3"]["listed"])

    out_zones = {}
    for game in ("d3", "d2"):
        for z, Z in games[game]["zones"].items():
            border = []
            for r, R in Z["rooms"].items():
                for d, ez, er, door in R["exits"]:
                    if ez != z:
                        to = games[game]["zones"][ez]["rooms"][er]
                        border.append(dict(r=r, t=R["title"], d=d, z=ez, tr=er, tt=to["title"]))
            out_zones[f"{game}:{z}"] = dict(
                g=game, id=z, file=Z["file"], title=pretty_title(Z["title"], z), creators=Z["creators"], years=Z["years"],
                notes=Z["notes"], rooms=len(Z["rooms"]), levels=Z["levels"], teleport=Z["teleport"],
                walk=Z.get("walk"), route=Z.get("route"), blocked=Z["blocked_rooms"],
                valhalla=(game == "d3" or z in d3listed), named=Z["named_rooms"], border=border,
                in_d3_list=(game == "d2" and z in d3listed and z not in games["d3"]["zones"]),
                twin=(f"d3:{d2to3[z]}" if game == "d2" and z in d2to3 else
                      next((f"d2:{b}" for b, a in d2to3.items() if a == z), None) if game == "d3" else None))

    views = {}
    for vname, vgames in (("d3", ("d3",)), ("d2", ("d2",)), ("both", ("d3", "d2"))):
        nodes, edges, visible, size, pos, island_top, frames, reg = build_view(vgames, games, match)
        vn = []
        for k in visible:
            members = [f"{g}:{z}" for g, z in nodes[k]]
            vn.append(dict(k=k, m=members, x=round(pos[k][0], 1), y=round(pos[k][1], 1), s=round(size[k], 1), r=reg.get(k)))
        ve = []
        for (a, b), ex in edges.items():
            if a in visible and b in visible:
                for e in ex:
                    ve.append(dict(a=a, b=b, **e))
        views[vname] = dict(nodes=vn, edges=ve, islands=island_top, regions=frames)
        print(f"view {vname}: {len(vn)} zones, {len(ve)} exits", file=sys.stderr)

    # teleport points and walks checked in a running DikuMUD III (tools/verify_teleports.py)
    vfile = os.path.join(HERE, "tools/verified-d3.json")
    verified = {}
    if os.path.exists(vfile):
        when = datetime.date.fromtimestamp(os.path.getmtime(vfile)).isoformat()
        for k, e in json.load(open(vfile)).items():
            z = out_zones.get(k)
            if not z:
                continue
            name_now = z["teleport"][0]["name"] if z["teleport"] else (z["walk"] or {}).get("name")
            walk_now = (z["walk"] or {}).get("steps")
            if e.get("cast") != name_now or (walk_now and e.get("walk") != walk_now):
                continue  # checked something this build no longer suggests
            verified[k] = dict(ok=e["ok"], walk_ok=e.get("walk_ok"), walk_end=e.get("walk_end"), on=when)
    # introductions: intros.json holds the reviewed ones (tools/review_sync.py); --drafts also
    # shows the ones not yet reviewed, from tools/private/intros-work.json, for a local preview
    intros = {}
    if "--drafts" in sys.argv and os.path.exists(os.path.join(HERE, "tools/private/intros-work.json")):
        for k, i in json.load(open(os.path.join(HERE, "tools/private/intros-work.json"))).items():
            if i["status"] == "pending":
                intros[k] = dict(intro=i["intro"], teaser=i["teaser"], draft=True)
    if os.path.exists(os.path.join(HERE, "intros.json")):
        intros.update(json.load(open(os.path.join(HERE, "intros.json"))))
    for k, z in out_zones.items():
        i = intros.get(k) or (intros.get(z["twin"]) if z["g"] == "d2" and z["twin"] else None)
        if i:
            z["intro"], z["teaser"], z["draft"] = i["intro"], i["teaser"], bool(i.get("draft"))
    data = dict(zones=out_zones, views=views, built=datetime.date.today().isoformat(), verified=verified,
                counts={g: dict(zones=len(games[g]["zones"]), listed=len(games[g]["listed"])) for g in games})
    page = open(os.path.join(HERE, "world-template.html")).read()
    page = page.replace("__DATA__", json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/"))
    open(os.path.join(HERE, "world", "index.html"), "w").write(page)
    print(f"world/index.html written ({len(page) // 1024} KB)", file=sys.stderr)


if __name__ == "__main__":
    main()
