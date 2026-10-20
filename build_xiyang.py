#!/usr/bin/env python3
"""Build xiyang/index.html, a room map of Xiyang, from a DikuMUD II checkout.

  python3 build_xiyang.py PATH/TO/DikuMUD2/dm-dist-ii

Reads zon/xiyang.zon (the city), zon/xiyang2.zon (harbour and palace extension) and
zon/oxiyang.zon (the lands outside), lays the rooms out from their exits (these zones
have no gmap positions) and fills them into a copy of template.html.
"""
import json, os, re, sys

D = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/DikuMUD2/dm-dist-ii")
HERE = os.path.dirname(os.path.abspath(__file__))
ZONES = ["xiyang", "xiyang2", "outxiyang"]   # zone names; the last one lives in oxiyang.zon
FILES = {"outxiyang": "oxiyang"}
STEP = 26
DV = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0), "u": (0.5, -0.5), "d": (-0.5, 0.5)}
REV = {"n": "s", "s": "n", "e": "w", "w": "e", "u": "d", "d": "u"}

rooms = {}
for zone in ZONES:
    s = open(os.path.join(D, "zon", FILES.get(zone, zone) + ".zon"), errors="replace").read()
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"//[^\n]*", "", s)
    s = re.sub(r"%dil.*?(?=\n%)", "", s, flags=re.S)
    r = s[s.index("%rooms"):]
    r = r[:re.search(r"\n%(objects|mobiles|reset|end)", r).start()]
    for name, body in re.findall(r"\n[ \t]*([a-z_0-9]+)[ \t]*\n(.*?)\nend\b", r, flags=re.S):
        if not re.search(r"\bmovement\s+SECT_", body):
            continue   # a monster defined among the rooms
        title = re.search(r'\btitle\s+"([^"]*)"', body)
        sect = re.search(r"movement\s+SECT_(\w+)", body)
        bare = re.sub(r'"(?:[^"\\]|\\.)*"', '""', body)
        exits = []
        for st in bare.split(";"):
            m = re.search(r"\b(north|east|south|west|up|down)\s+to\s+([\w@]+)", st)
            if not m:
                continue
            d, to = m.groups()
            room, _, z = to.partition("@")
            z = z or zone
            e = dict(d=d[0], to=room + "@" + z, z="home" if z in ZONES else z)
            if "EX_OPEN_CLOSE" in st:
                e["door"] = True
            exits.append(e)
        rooms[name + "@" + zone] = dict(id=name + "@" + zone, t=(title.group(1).strip() if title else name) or name,
                                        s=(sect.group(1).lower() if sect else ""), e=exits, x=None, y=None)

# drop exits to rooms that do not exist (keeps the page honest)
for r in rooms.values():
    r["e"] = [e for e in r["e"] if e["z"] != "home" or e["to"] in rooms]

# lay out: breadth-first from each unplaced room, in the exit's direction, nearest free cell
taken = {}
def free(cx, cy):
    for rad in range(0, 8):
        for dx in range(-rad, rad + 1):
            for dy in range(-rad, rad + 1):
                if max(abs(dx), abs(dy)) == rad and (cx + dx, cy + dy) not in taken:
                    return cx + dx, cy + dy
adj = {k: [] for k in rooms}
for k, r in rooms.items():
    for e in r["e"]:
        if e["z"] == "home":
            adj[k].append((e["d"], e["to"]))
            adj[e["to"]].append((REV[e["d"]], k))   # one-way exits still hint at the layout
off = 0
start = "dock_enter@xiyang2" if "dock_enter@xiyang2" in rooms else next(iter(rooms))
order = [start] + list(rooms)
for root in order:
    if rooms[root]["x"] is not None:
        continue
    cx, cy = free(off, 0)
    rooms[root].update(x=cx * STEP, y=cy * STEP); taken[(cx, cy)] = root
    queue = [root]
    while queue:
        k = queue.pop(0); r = rooms[k]
        for d, to in adj[k]:
            t = rooms[to]
            if t["x"] is not None:
                continue
            v = DV[d]
            gx, gy = free(round(r["x"] / STEP + v[0]), round(r["y"] / STEP + v[1]))
            t.update(x=gx * STEP, y=gy * STEP); taken[(gx, gy)] = to
            queue.append(to)
    off = max(c[0] for c in taken) + 3

# The zones' own geometry is not consistent (a loop of streets need not close), so the first
# placement leaves some exits pointing the wrong way. Relax: pull every exit towards its
# direction, push rooms that crowd each other apart, and repeat.
keys = list(rooms)
edges = [(k, e["to"], DV[e["d"]]) for k in keys for e in rooms[k]["e"] if e["z"] == "home"]
MIN = STEP * 0.8
for it in range(500):
    f = {k: [0.0, 0.0] for k in keys}
    for a, b, v in edges:
        ra, rb = rooms[a], rooms[b]
        ex = (rb["x"] - ra["x"]) - v[0] * STEP
        ey = (rb["y"] - ra["y"]) - v[1] * STEP
        f[a][0] += ex * 0.25; f[a][1] += ey * 0.25
        f[b][0] -= ex * 0.25; f[b][1] -= ey * 0.25
    cells = {}
    for k in keys:
        cells.setdefault((int(rooms[k]["x"] // MIN), int(rooms[k]["y"] // MIN)), []).append(k)
    for (cx, cy), ks in cells.items():
        near = [o for dx in (-1, 0, 1) for dy in (-1, 0, 1) for o in cells.get((cx + dx, cy + dy), [])]
        for a in ks:
            for b in near:
                if a == b: continue
                dx, dy = rooms[a]["x"] - rooms[b]["x"], rooms[a]["y"] - rooms[b]["y"]
                d = (dx * dx + dy * dy) ** 0.5
                if d < MIN:
                    if d < 0.01: dx, dy, d = 1.0, 0.0, 1.0
                    push = (MIN - d) * 0.3
                    f[a][0] += dx / d * push; f[a][1] += dy / d * push
    for k in keys:
        rooms[k]["x"] += f[k][0] * 0.5; rooms[k]["y"] += f[k][1] * 0.5
# Snap to a grid so lines run at 0, 90, 180 or 270 degrees, then let each room hop to a
# nearby free cell where its exits sit closer to their direction (an exit's ideal is the
# neighbouring cell in that direction; up and down take a diagonal cell).
CELL = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0), "u": (1, -1), "d": (-1, 1)}
grid, cell = {}, {}
for k in sorted(keys, key=lambda k: -len(rooms[k]["e"])):
    c = (round(rooms[k]["x"] / STEP), round(rooms[k]["y"] / STEP))
    for rad in range(0, 8):
        spot = [(c[0] + dx, c[1] + dy) for dx in range(-rad, rad + 1) for dy in range(-rad, rad + 1)
                if max(abs(dx), abs(dy)) == rad and (c[0] + dx, c[1] + dy) not in grid]
        if spot:
            c = min(spot, key=lambda q: (q[0] - rooms[k]["x"] / STEP) ** 2 + (q[1] - rooms[k]["y"] / STEP) ** 2)
            break
    grid[c] = k; cell[k] = c
nbr = {k: [] for k in keys}
for a, b, _ in edges:
    d = next(e["d"] for e in rooms[a]["e"] if e["to"] == b and e["z"] == "home")
    nbr[a].append((b, CELL[d], 1)); nbr[b].append((a, CELL[d], -1))
def cost(k, c):
    return sum(abs(c[0] - cell[o][0] + sg * v[0]) + abs(c[1] - cell[o][1] + sg * v[1])
               for o, v, sg in nbr[k]) * 1.0
import math, random
random.seed(7)
def total(ks, over=None):
    over = over or {}
    return sum(cost(k, over.get(k, cell[k])) for k in ks)
SWEEPS = 5000
for sweep in range(SWEEPS):
    T = 1.2 * (1 - sweep / SWEEPS) ** 2 + 0.02
    order = keys[:]; random.shuffle(order)
    for k in order:
        here = cell[k]
        rad = 3 if sweep < SWEEPS * 0.8 else 1
        c = (here[0] + random.randint(-rad, rad), here[1] + random.randint(-rad, rad))
        if c == here:
            continue
        j = grid.get(c)
        if j is None:
            delta = cost(k, c) - cost(k, here)
            if delta <= 0 or random.random() < math.exp(-delta / T):
                del grid[here]; grid[c] = k; cell[k] = c
        else:
            ks = {k, j}
            before = total(ks)
            cell[k], cell[j] = c, here
            delta = total(ks) - before
            if delta <= 0 or random.random() < math.exp(-delta / T):
                grid[c], grid[here] = k, j
            else:
                cell[k], cell[j] = here, c
for k in keys:
    rooms[k]["x"], rooms[k]["y"] = cell[k][0] * STEP, cell[k][1] * STEP
wrong = 0
for a in keys:
    for e in rooms[a]["e"]:
        if e["z"] != "home": continue
        v, b = DV[e["d"]], rooms[e["to"]]
        if (b["x"] - rooms[a]["x"]) * v[0] + (b["y"] - rooms[a]["y"]) * v[1] <= 0:
            e["odd"] = True   # a maze: the exits do not fit a flat grid, so the map cannot show it truthfully
            wrong += 1
skew = sum(1 for a, b, _ in edges if rooms[a]["x"] != rooms[b]["x"] and rooms[a]["y"] != rooms[b]["y"])
print(f"{wrong} of {len(edges)} exits drawn against their direction; {skew} drawn with a bend")

out = list(rooms.values())
page = open(os.path.join(HERE, "template.html")).read()
page = re.sub(r'\s*<image id="backdrop".*?</image>', "", page, flags=re.S)
page = re.sub(r'\s*<label class="tog">.*?</label>', "", page, flags=re.S)
page = page.replace('document.getElementById("img").onchange = ev => wrap.classList.toggle("showimg", ev.target.checked);', "")
page = page.replace('"midgaard"', '"home"').replace("${esc(r.id)}@midgaard", "${esc(r.id)}")
page = page.replace("Midgaard Room Map", "Xiyang Room Map").replace("<h1>Midgaard</h1>", "<h1>Xiyang</h1>")
page = page.replace("Show whole city", "Show everything").replace("Map of Midgaard rooms", "Map of Xiyang rooms").replace("Midgaard rooms and exits", "Xiyang rooms and exits")
page = page.replace("e.g. temple", "e.g. harbor")
page = re.sub(r'<p class="hint">Rooms sit at.*?</p>',
              '<p class="hint">These zones have no map positions in the game, so rooms are laid out on a grid from their exits: north is up, east is right. Where the zone\'s streets don\'t fit a grid, a line takes a right-angle bend.</p>', page, flags=re.S)
page = re.sub(r'<p class="hint">Rooms, exits and the map image.*?</p>',
              '<p class="hint">Rooms and exits come from the <a href="https://github.com/Seifert69/DikuMUD2">DikuMUD II</a> zones xiyang, xiyang2 and outxiyang (the Xiyang of Valhalla\'s source may differ). An unofficial fan map: the game itself is the final word. <a href="../world/">Every zone and how they connect →</a> <a href="../midgaard/">Midgaard room by room →</a> <a href="../">All Valhalla maps</a></p>', page, flags=re.S)
page = page.replace("${oneway ? '<span class=\"tag oneway\">one way</span>' : \"\"}", "${oneway ? '<span class=\"tag oneway\">one way</span>' : \"\"}${e.odd ? '<span class=\"tag away\">drawn out of place: a maze</span>' : \"\"}")
page = page.replace('<a href="../xiyang/">Xiyang room by room →</a> ', "")
page = page.replace("const p = pairs.get(k) || { a: r.id, b: e.to, vert: false, door: false };", "const p = pairs.get(k) || { a: r.id, b: e.to, d: e.d, vert: false, door: false };")
old_edge = re.search(r"for \(const p of pairs.values\(\)\) \{.*?\n\}\n", page, flags=re.S).group(0)
new_edge = """for (const p of pairs.values()) {
  const a = byId.get(p.a), b = byId.get(p.b);
  // Lines run at right angles only: a pair that is not in line gets one bend
  const inLine = Math.abs(a.x - b.x) < 0.5 || Math.abs(a.y - b.y) < 0.5;
  const pts = inLine ? [[a.x, a.y], [b.x, b.y]]
    : [[a.x, a.y], (p.d === "n" || p.d === "s") ? [a.x, b.y] : [b.x, a.y], [b.x, b.y]];
  el("polyline", { points: pts.map(q => q.join(",")).join(" "), fill: "none", class: "edge" + (p.vert ? " vert" : "") }, edgesG);
  let best = null;
  for (let i = 0; i + 1 < pts.length; i++) {
    const [x1, y1] = pts[i], [x2, y2] = pts[i + 1];
    segs.push([x1, y1, x2, y2]);
    const L = Math.hypot(x2 - x1, y2 - y1);
    if (!best || L > best.L) best = { L, x1, y1, x2, y2 };
  }
  if (p.door && best.L > 0) addTick((best.x1 + best.x2) / 2, (best.y1 + best.y2) / 2, -(best.y2 - best.y1) / best.L, (best.x2 - best.x1) / best.L);
}
"""
page = page.replace(old_edge, new_edge)
page = page.replace("__ROOMS__", json.dumps(out, separators=(",", ":")))
open(os.path.join(HERE, "xiyang", "index.html"), "w").write(page)
print(f"xiyang/index.html: {len(out)} rooms, {sum(len(r['e']) for r in out)} exits, "
      f"{sum(1 for r in out for e in r['e'] if e['z'] != 'home')} leave the region")
