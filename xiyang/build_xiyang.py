#!/usr/bin/env python3
"""Build xiyang.html, a room map of Xiyang, from a DikuMUD II checkout.

  python3 xiyang/build_xiyang.py PATH/TO/DikuMUD2/dm-dist-ii

Reads zon/xiyang.zon (the city), zon/xiyang2.zon (harbour and palace extension) and
zon/oxiyang.zon (the lands outside), lays the rooms out from their exits (these zones
have no gmap positions) and fills them into a copy of template.html.
"""
import json, os, re, sys

D = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/DikuMUD2/dm-dist-ii")
HERE = os.path.dirname(os.path.abspath(__file__))
ZONES = ["xiyang", "xiyang2", "oxiyang"]
STEP = 26
DV = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0), "u": (0.5, -0.5), "d": (-0.5, 0.5)}
REV = {"n": "s", "s": "n", "e": "w", "w": "e", "u": "d", "d": "u"}

rooms = {}
for zone in ZONES:
    s = open(os.path.join(D, "zon", zone + ".zon"), errors="replace").read()
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"//[^\n]*", "", s)
    s = re.sub(r"%dil.*?(?=\n%)", "", s, flags=re.S)
    r = s[s.index("%rooms"):]
    r = r[:re.search(r"\n%(objects|mobiles|reset|end)", r).start()]
    for name, body in re.findall(r"\n[ \t]*([a-z_0-9]+)[ \t]*\n(.*?)\nend\b", r, flags=re.S):
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

out = list(rooms.values())
page = open(os.path.join(HERE, "..", "template.html")).read()
page = re.sub(r'\s*<image id="backdrop".*?</image>', "", page, flags=re.S)
page = re.sub(r'\s*<label class="tog">.*?</label>', "", page, flags=re.S)
page = page.replace('document.getElementById("img").onchange = ev => wrap.classList.toggle("showimg", ev.target.checked);', "")
page = page.replace('"midgaard"', '"home"').replace("${esc(r.id)}@midgaard", "${esc(r.id)}")
page = page.replace("Midgaard Room Map", "Xiyang Room Map").replace("<h1>Midgaard</h1>", "<h1>Xiyang</h1>")
page = page.replace("Show whole city", "Show everything").replace("Map of Midgaard rooms", "Map of Xiyang rooms").replace("Midgaard rooms and exits", "Xiyang rooms and exits")
page = page.replace("e.g. temple", "e.g. harbor")
page = re.sub(r'<p class="hint">Rooms sit at.*?</p>',
              '<p class="hint">These zones have no map positions in the game, so rooms are laid out from their exits: north is up, east is right. Where the city\'s streets bend, the picture bends too.</p>', page, flags=re.S)
page = re.sub(r'<p class="hint">Rooms, exits and the map image.*?</p>',
              '<p class="hint">Rooms and exits come from the <a href="https://github.com/Seifert69/DikuMUD2">DikuMUD II</a> zones xiyang, xiyang2 and oxiyang (the Xiyang of Valhalla\'s source may differ). An unofficial fan map: the game itself is the final word. <a href="world.html">Every zone and how they connect →</a></p>', page, flags=re.S)
page = page.replace("__ROOMS__", json.dumps(out, separators=(",", ":")))
open(os.path.join(HERE, "..", "xiyang.html"), "w").write(page)
print(f"xiyang.html: {len(out)} rooms, {sum(len(r['e']) for r in out)} exits, "
      f"{sum(1 for r in out for e in r['e'] if e['z'] != 'home')} leave the region")
