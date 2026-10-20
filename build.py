#!/usr/bin/env python3
"""Build midgaard/index.html, the Midgaard room map, from a DikuMUD3 checkout.

  python3 build.py PATH/TO/DikuMUD3

Reads vme/zone/midgaard.zon (rooms, titles, exits, doors, gmap positions) and
vme/www/img/midgaard.jpg (the game's own map, shown underneath on request), and
fills them into template.html.
"""
import base64, json, os, re, sys

D = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/DikuMUD3")
HERE = os.path.dirname(os.path.abspath(__file__))

s = open(os.path.join(D, "vme/zone/midgaard.zon"), errors="replace").read()
s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
s = re.sub(r"dilbegin.*?dilend", "", s, flags=re.S)
s = re.sub(r"//[^\n]*", "", s)
r = s[s.index("%rooms"):]
r = r[:re.search(r"\n%(objects|mobiles|reset|end)", r).start()]

rooms = []
for name, body in re.findall(r"\n\s*([a-z_0-9]+)\s*\n(.*?)\nend\b", r, flags=re.S):
    title = re.search(r'\btitle\s+"([^"]*)"', body)
    nostr = re.sub(r'"(?:[^"\\]|\\.)*"', '""', body)  # exits only outside strings
    exits = []
    for m in re.finditer(r"(?:^|\n|;)\s*(north|east|south|west|up|down)\s+to\s+([\w@/]+)([^\n;]*)", nostr):
        d, to, rest = m.groups()
        if "/" in to:
            zone, room = to.split("/", 1)
        elif "@" in to:
            room, zone = to.split("@", 1)
        else:
            room, zone = to, "midgaard"
        e = dict(d=d[0], to=room, z=zone)
        if "EX_OPEN_CLOSE" in rest:
            e["door"] = True
        exits.append(e)
    g = re.search(r"gmap\(\s*(-?\d+)\s*,\s*(-?\d+)\s*\)", body)
    sect = re.search(r"movement\s+(\w+)", body)
    rooms.append(dict(id=name, t=title.group(1).strip() if title else name,
                      x=int(g.group(1)) if g else None, y=int(g.group(2)) if g else None,
                      s=sect.group(1).replace("SECT_", "").lower() if sect else "", e=exits))

ids = {x["id"] for x in rooms}
missing = [(x["id"], e["to"]) for x in rooms for e in x["e"] if e["z"] == "midgaard" and e["to"] not in ids]
assert not missing, missing

img = base64.b64encode(open(os.path.join(D, "vme/www/img/midgaard.jpg"), "rb").read()).decode()
page = open(os.path.join(HERE, "template.html")).read()
page = page.replace("__ROOMS__", json.dumps(rooms, separators=(",", ":"))).replace("__MAP__", img)
open(os.path.join(HERE, "midgaard", "index.html"), "w").write(page)
print(f"midgaard/index.html: {len(rooms)} rooms, {sum(len(x['e']) for x in rooms)} exits")
