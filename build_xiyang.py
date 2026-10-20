#!/usr/bin/env python3
"""Build xiyang/index.html, a room map of Xiyang, from the DikuMUD II zone files.

  python3 build_xiyang.py PATH/TO/DikuMUD3 PATH/TO/DikuMUD2

Reads zon/xiyang.zon (the city), zon/xiyang2.zon (harbour, ship and palace) and
zon/oxiyang.zon (zone outxiyang, the lands outside) with world.py's parser, which runs
them through DikuMUD III's preprocessor (vme/bin/pp), so the map and the world map read
the zones the same way. Lays the rooms out from their exits (these zones have no gmap
positions) and fills them into a copy of template.html.
"""
import json, os, re, sys

import world   # reads the two checkout paths from sys.argv, as world.py does

HERE = os.path.dirname(os.path.abspath(__file__))
ZONES = ["xiyang", "xiyang2", "outxiyang"]
FILES = {"xiyang": "xiyang.zon", "xiyang2": "xiyang2.zon", "outxiyang": "oxiyang.zon"}
# values.h: SECT_INSIDE 0, CITY 1, FIELD 2, FOREST 3, HILLS 4, MOUNTAIN 5, DESERT 6, SWAMP 7,
# WATER_SWIM 8, WATER_SAIL 9, UNDER_WATER 10, SNOW 11
SECT = ["inside", "city", "field", "forest", "hills", "mountain", "desert", "swamp",
        "water_swim", "water_sail", "under_water", "snow"]
STEP = 16   # px per grid cell; an exit normally spans two cells
DV = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0), "u": (0.5, -0.5), "d": (-0.5, 0.5)}
REV = {"n": "s", "s": "n", "e": "w", "w": "e", "u": "d", "d": "u"}

rooms = {}
for zone in ZONES:
    fname = os.path.join(world.GAMES["d2"]["zondir"], FILES[zone])
    Z = world.parse_zone("d2", fname)
    assert Z["id"] == zone, (fname, Z["id"])
    # The sector (for the dot's colour) is the one thing parse_zone does not keep
    text, _ = world.strings_out(world.preprocess("d2", fname))
    text = re.sub(r"dilbegin.*?dilend", "", text, flags=re.S)
    marks = list(world.SECTION.finditer(text))
    sect = {}
    for n, m in enumerate(marks):
        if m.group(1) == "rooms":
            part = text[m.end():marks[n + 1].start() if n + 1 < len(marks) else len(text)]
            for u in re.finditer(r"(?ms)^\s*([\w]+)\s*\n(.*?)^\s*end\s*$", part):
                mv = re.search(r"\bmovement\s+(\d+)", u.group(2))
                sect[u.group(1).lower()] = SECT[int(mv.group(1))] if mv and int(mv.group(1)) < len(SECT) else ""
    for sym, R in Z["rooms"].items():
        exits = []
        for d, z, r, door in R["exits"]:
            if d not in DV:
                raise SystemExit(f"{sym}@{zone}: a {d} exit, which this map cannot draw")
            e = dict(d=d, to=f"{r}@{z}" if z in ZONES else r, z="home" if z in ZONES else z)
            if door:
                e["door"] = True
                if door[1]: e["locked"] = True
                if door[2]: e["hidden"] = True
            exits.append(e)
        rooms[f"{sym}@{zone}"] = dict(id=f"{sym}@{zone}", t=R["title"] or sym, s=sect.get(sym, ""),
                                      e=exits, x=None, y=None)

# An exit to a room that does not exist cannot be drawn; say so rather than hide it
for k, r in rooms.items():
    for e in r["e"]:
        if e["z"] == "home" and e["to"] not in rooms:
            print(f"warning: {k} {e['d']} leads to {e['to']}, which is not in these zones", file=sys.stderr)
    r["e"] = [e for e in r["e"] if e["z"] != "home" or e["to"] in rooms]

# Lay out on a grid. Every exit wants its room one cell away in its direction (up and down:
# one cell diagonally). The city's exits agree with each other, so placing rooms breadth-first
# from the harbour gives each its true cell. Where two rooms want the same cell (a shop drawn
# over a street, an upper floor over the one below), the later one moves further along the same
# direction: its line stays straight and only gets longer. Up and down come last, so floors
# hang off the ground plan rather than shaping it.
import random
CELL = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0), "u": (1, -1), "d": (-1, 1)}
keys = list(rooms)
edges = [(k, e["to"], e["d"]) for k in keys for e in rooms[k]["e"] if e["z"] == "home"]
nbr = {k: [] for k in keys}
for a, b, d in edges:
    nbr[a].append((b, CELL[d], 1, d in "ud"))
    nbr[b].append((a, CELL[d], -1, d in "ud"))

grid, cell = {}, {}
def put(k, c):
    grid[c] = k; cell[k] = c
def nearest_free(c):
    for rad in range(1, 60):
        ring = [(c[0] + dx, c[1] + dy) for dx in range(-rad, rad + 1) for dy in range(-rad, rad + 1)
                if max(abs(dx), abs(dy)) == rad and (c[0] + dx, c[1] + dy) not in grid]
        if ring:
            return min(ring, key=lambda q: abs(q[0] - c[0]) + abs(q[1] - c[1]))
# Each floor (rooms joined by north, south, east and west) is laid out on its own, then hung
# beside the room its stairs leave from, in a place where it overlaps nothing. Within a floor,
# exits span two cells, so a room that finds its cell taken can sit halfway along its own line.
floor = {}
for k in keys:
    if k in floor:
        continue
    floor[k] = k; todo = [k]
    while todo:
        x = todo.pop()
        for o, v, sg, ud in nbr[x]:
            if not ud and o not in floor:
                floor[o] = k; todo.append(o)
members = {}
for k in keys:
    members.setdefault(floor[k], []).append(k)

def plan(root):
    """A floor's own layout, relative to its root: {room: cell}."""
    local, used = {root: (0, 0)}, {(0, 0)}
    streets, inside = [root], []      # streets first, so they keep their true cells
    while streets or inside:
        k = streets.pop(0) if streets else inside.pop(0)
        for o, v, sg, ud in nbr[k]:
            if ud or o in local:
                continue
            w = (sg * v[0], sg * v[1])
            far = (local[k][0] + 2 * w[0], local[k][1] + 2 * w[1])
            mid = (local[k][0] + w[0], local[k][1] + w[1])
            if far not in used: c = far
            elif mid not in used: c = mid
            else:
                c = next((far[0] + dx, far[1] + dy) for r in range(1, 40) for dx in range(-r, r + 1)
                         for dy in range(-r, r + 1) if max(abs(dx), abs(dy)) == r and (far[0] + dx, far[1] + dy) not in used)
            local[o] = c; used.add(c)
            (streets if rooms[o]["s"] in ("city", "field", "hills", "desert", "forest", "mountain") else inside).append(o)
    return local

def hang(local, ideal):
    """Place a floor so that it overlaps no room and keeps a cell clear around it, as near ideal as can be."""
    for r in range(0, 80):
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r:
                    continue
                off = (ideal[0] + dx, ideal[1] + dy)
                if all((c[0] + off[0] + ax, c[1] + off[1] + ay) not in grid
                       for c in local.values() for ax in (-1, 0, 1) for ay in (-1, 0, 1)):
                    for k, c in local.items():
                        put(k, (c[0] + off[0], c[1] + off[1]))
                    return

start = "dock_enter@xiyang2"
for root in [start] + keys:
    if root in cell:
        continue
    local = plan(root)
    hang(local, (0, 0) if not grid else (max(c[0] for c in grid) + 4, 0))
    queue = list(local)
    while queue:
        k = queue.pop(0)
        for o, v, sg, ud in nbr[k]:
            if o in cell:
                continue
            # o is on another floor, reached by stairs: place that whole floor
            local = plan(o)
            w = (sg * v[0], sg * v[1])
            want = (cell[k][0] + 2 * w[0], cell[k][1] + 2 * w[1])
            hang(local, (want[0] - local[o][0], want[1] - local[o][1]))
            queue.extend(local)

# What makes a drawn exit misleading, worst first: a line through a room that is not one of
# its ends (it looks like an exit into it), two lines on top of each other, a line pointing
# the wrong way, a bend. A long straight line is only slightly worse than a short one.
W_THROUGH, W_SHARED = 40, 15
pair_dir = {}
for a, b, d in edges:
    pair_dir.setdefault(tuple(sorted((a, b))), (a, b, d))   # the page draws each pair once, bent as its first exit says
lines = list(pair_dir.values())
lines_of = {k: [] for k in keys}
for n, (a, b, d) in enumerate(lines):
    lines_of[a].append(n)
    if b != a: lines_of[b].append(n)

def shape(n):
    a, b, d = lines[n]
    v = CELL[d]
    dx, dy = cell[b][0] - cell[a][0], cell[b][1] - cell[a][1]
    along = (dx * v[0] + dy * v[1]) / (v[0] * v[0] + v[1] * v[1])
    off = abs(dx * v[1] - dy * v[0])
    if along <= 0:
        t = 20 + off + abs(along)
    elif off:
        t = 4 + off
    else:
        t = 0.3 * max(0, along - 2)
    return t * (0.5 if d in "ud" else 1)

def path(n):
    """The cells a line passes between its ends, and its unit segments, as the page draws it."""
    a, b, d = lines[n]
    A, B = cell[a], cell[b]
    if A[0] != B[0] and A[1] != B[1]:
        pts = [A, (A[0], B[1]) if d in "ns" else (B[0], A[1]), B]
    else:
        pts = [A, B]
    inner, segs = [], []
    for p, q in zip(pts, pts[1:]):
        sx, sy = (q[0] > p[0]) - (q[0] < p[0]), (q[1] > p[1]) - (q[1] < p[1])
        c = p
        while c != q:
            nx = (c[0] + sx, c[1] + sy)
            segs.append((c, nx) if c < nx else (nx, c))
            c = nx
            if c != B: inner.append(c)
    return inner, segs

seg_use, cell_use, drawn = {}, {}, {}
P = 0.0      # the layout's total badness, kept up to date as lines and rooms move
def add_line(n):
    global P
    inner, segs = drawn[n] = path(n)
    P += shape(n)
    for c in inner:
        cell_use[c] = cell_use.get(c, 0) + 1
        if c in grid: P += W_THROUGH
    for sg_ in segs:
        u = seg_use.get(sg_, 0)
        if u: P += W_SHARED
        seg_use[sg_] = u + 1
def drop_line(n):
    global P
    inner, segs = drawn.pop(n)
    P -= shape(n)
    for c in inner:
        cell_use[c] -= 1
        if c in grid: P -= W_THROUGH
    for sg_ in segs:
        seg_use[sg_] -= 1
        if seg_use[sg_]: P -= W_SHARED
def lift(k):
    global P
    c = cell[k]; del grid[c]; P -= W_THROUGH * cell_use.get(c, 0)
def land(k, c):
    global P
    grid[c] = k; cell[k] = c; P += W_THROUGH * cell_use.get(c, 0)
def shift(moves):
    """Move rooms to new cells: moves is {room: cell}. Returns the change in badness."""
    before = P
    ls = sorted({n for k in moves for n in lines_of[k]})
    for n in ls: drop_line(n)
    for k in moves: lift(k)
    for k, c in moves.items(): land(k, c)
    for n in ls: add_line(n)
    return P - before

def fresh():
    global P
    seg_use.clear(); cell_use.clear(); drawn.clear(); P = 0.0
    for n in range(len(lines)): add_line(n)

# Tidy up: move or swap rooms where that draws their exits better, now and then accepting a
# worse move early on so a room can get out of a corner. Keep the best of a few runs.
import math
base_grid, base_cell = dict(grid), dict(cell)
fresh()
best = (P, dict(cell))
def report(label):
    th = sum(1 for n, (inner, _) in drawn.items() for c in inner if c in grid)
    sh = sum(u - 1 for u in seg_use.values() if u > 1)
    wr = sum(1 for n in range(len(lines)) if shape(n) >= 10 * (0.5 if lines[n][2] in "ud" else 1))
    print(f"{label}: badness {P:.1f} (through {th}, shared {sh}, wrong-way lines {wr})", file=sys.stderr)
report("layout before tidying")
for seed in range(4):
    random.seed(seed)
    grid.clear(); grid.update(base_grid); cell.clear(); cell.update(base_cell)
    fresh()
    SWEEPS = 1200
    for sweep in range(SWEEPS):
        T = 1.0 * (1 - sweep / SWEEPS) ** 2 + 0.02
        order = keys[:]; random.shuffle(order)
        for k in order:
            here = cell[k]
            rad = 2 if sweep < SWEEPS // 2 else 1
            c = (here[0] + random.randint(-rad, rad), here[1] + random.randint(-rad, rad))
            if c == here:
                continue
            j = grid.get(c)
            moves = {k: c} if j is None else {k: c, j: here}
            delta = shift(moves)
            if delta > 0 and random.random() >= math.exp(-delta / T):
                shift({k: here} if j is None else {k: here, j: c})
    fresh()   # recount from scratch, so the score is exact
    print(f"layout run {seed}: badness {P:.1f}", file=sys.stderr)
    if best is None or P < best[0]:
        best = (P, dict(cell))
cell.clear(); cell.update(best[1]); grid.clear(); grid.update({c: k for k, c in cell.items()})
fresh()

# Polish: try every nearby cell for each room, and move each dead-end branch (the rooms
# reachable only through one room, such as the palace behind its gate) as one block.
branches = []
links = {k: {o for o, *_ in nbr[k]} for k in keys}
for k in keys:
    for o in links[k]:
        seen, todo = {o}, [o]
        while todo and len(seen) <= 25:
            x = todo.pop()
            for y in links[x]:
                if y != k and y not in seen:
                    seen.add(y); todo.append(y)
        if len(seen) <= 25 and k not in seen:
            branches.append(frozenset(seen))
branches = sorted(set(branches), key=len)
improved = True
while improved:
    improved = False
    for group in [frozenset([k]) for k in keys] + branches:
        best_move, best_delta = None, -1e-9
        R = 3 if len(group) == 1 else 2
        for dx in range(-R, R + 1):
            for dy in range(-R, R + 1):
                if not (dx or dy):
                    continue
                moves = {k: (cell[k][0] + dx, cell[k][1] + dy) for k in group}
                if any(c in grid and grid[c] not in group for c in moves.values()):
                    continue
                back = {k: cell[k] for k in group}
                delta = shift(moves)
                shift(back)
                if delta < best_delta:
                    best_move, best_delta = moves, delta
        if best_move:
            shift(best_move); improved = True
fresh()
report("after polishing")
xs, ys = min(c[0] for c in cell.values()), min(c[1] for c in cell.values())
for k in keys:
    rooms[k]["x"], rooms[k]["y"] = (cell[k][0] - xs) * STEP, (cell[k][1] - ys) * STEP

wrong = 0
for a in keys:
    for e in rooms[a]["e"]:
        if e["z"] != "home": continue
        v, b = DV[e["d"]], rooms[e["to"]]
        if (b["x"] - rooms[a]["x"]) * v[0] + (b["y"] - rooms[a]["y"]) * v[1] <= 0:
            e["odd"] = True   # the exits around it do not fit a flat grid, so the map cannot show it truthfully
            wrong += 1
skew = sum(1 for a, b, d in edges if d not in "ud" and rooms[a]["x"] != rooms[b]["x"] and rooms[a]["y"] != rooms[b]["y"])
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
page = page.replace("${oneway ? '<span class=\"tag oneway\">one way</span>' : \"\"}", "${oneway ? '<span class=\"tag oneway\">one way</span>' : \"\"}${e.odd ? '<span class=\"tag away\">drawn out of place: these exits don\\'t fit a flat map</span>' : \"\"}")
page = page.replace('<a href="../xiyang/">Xiyang room by room →</a> ', "")
def tpl(a, b):
    global page
    assert a in page, a
    page = page.replace(a, b)
# Doors: say when one is hidden or locked
tpl("""${e.door ? '<span class="tag door">door</span>' : ""}""",
    """${e.door ? '<span class="tag door">' + (e.hidden ? "hidden " : "") + (e.locked ? "locked " : "") + 'door</span>' : ""}""")
# Sectors these zones use that Midgaard does not
tpl('["city", "inside", "field", "hills", "water_swim"].includes(r.s)',
    '["city", "inside", "field", "hills", "forest", "mountain", "desert", "swamp", "snow", "water_swim", "water_sail", "under_water"].includes(r.s)')
tpl(".node.water_swim { fill: var(--water); }",
    ".node.water_swim, .node.water_sail, .node.under_water { fill: var(--water); } .node.forest, .node.mountain, .node.desert, .node.swamp, .node.snow { fill: var(--open); }")
tpl('{ city: "Street", inside: "Indoors", field: "Field", hills: "Hills", water_swim: "Water" }',
    '{ city: "Street", inside: "Indoors", field: "Field", hills: "Hills", forest: "Forest", mountain: "Mountains", desert: "Desert", swamp: "Swamp", snow: "Snow", water_swim: "Water", water_sail: "Water (needs a boat)", under_water: "Under water" }')
tpl('<span>Fields and hills</span>', '<span>Fields, hills, forest, desert</span>')
tpl('<span>Inside a building</span>',
    '<span>Inside a building</span>\n        <svg viewBox="0 0 22 16"><circle cx="11" cy="8" r="5" fill="var(--water)"/></svg><span>Water</span>\n        <svg viewBox="0 0 22 16"><circle cx="11" cy="8" r="5" fill="var(--ink-soft)"/></svg><span>Not stated</span>')
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
