#!/usr/bin/env python3
"""Check world.html's DikuMUD III teleport points in a running game.

  verify_teleports.py WORLD_HTML PORT CHARACTER PASSWORD > verified.json

Logs in over telnet (an immortal: 'restore self' refills mana between casts), and for
every zone casts "controlled teleport <name>" and checks that the room it lands in has
the expected title; for a zone without a teleport point it casts to the nearest one
and walks the route, then checks the room it ends in. A failed cast caused by the
spell's own risk (a rift) is tried again.
"""
import json, re, socket, sys, time

html, port, who, pwd = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
data = json.loads(open(html).read().split("const DATA = ", 1)[1].split(";\nconst NS", 1)[0])
s = socket.create_connection(("127.0.0.1", port))
s.settimeout(0.3)


def read(quiet=1.0, until=None, limit=8.0):
    buf, end, stop = b"", time.time() + quiet, time.time() + limit
    while time.time() < min(end, stop):
        try:
            c = s.recv(65536)
            if not c:
                break
            buf += c
            end = time.time() + quiet
            if until and re.search(until, buf.decode("latin-1")):
                break
        except socket.timeout:
            pass
    t = re.sub(rb"\xff[\xfb-\xfe].|\xff\xfa.*?\xff\xf0|\xff[\xf0-\xfa]", b"", buf, flags=re.S).decode("latin-1")
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", t)


def say(line, **kw):
    s.sendall(line.encode() + b"\r\n")
    return read(**kw)


def here():
    out = say("look", quiet=0.8)
    lines = [l.strip() for l in out.split("\n") if l.strip() and not re.match(r"^\d+m/\d+e/\d+h>", l.strip())]
    return lines[0] if lines else ""


read(2)
say(who); say(pwd, quiet=2)
out = say("1", quiet=3)
say("wizinv 0")
result = {}
start = data["zones"]["d3:udgaard"]["teleport"][0]["room"] + "@udgaard"
steps_of = lambda w: [d for part in w.split(", ") for d in ([part] if part.startswith("open ") else [re.sub(r"^\d+", "", part)] * int(re.match(r"^(\d*)", part).group(1) or 1))]
DIRCMD = {"n": "north", "e": "east", "s": "south", "w": "west", "u": "up", "d": "down", "ne": "northeast", "nw": "northwest", "se": "southeast", "sw": "southwest"}
for key, z in sorted(data["zones"].items()):
    if z["g"] != "d3":
        continue
    target = z["teleport"][0] if z["teleport"] else None
    walk = z.get("walk")
    if not target and not walk:
        continue
    name = target["name"] if target else walk["name"]
    want = target["title"] if target else data["zones"]["d3:" + walk["zone"]]["teleport"][0]["title"]
    say(f"goto {start}", quiet=0.6)  # a room teleport may leave (the temple may not)
    landed, log = None, ""
    for attempt in range(4):
        say("restore self", quiet=0.5)
        log = say(f"cast controlled teleport {name}", quiet=2.5, limit=10)
        landed = here()
        if want.lower() in landed.lower():
            break
        if "rift" not in log.lower():
            break
    ok = want.lower() in landed.lower()
    entry = dict(cast=name, expected=want, landed=landed, ok=ok)
    if not ok:
        entry["said"] = " ".join(log.split())[:300]
    if walk and ok:
        for d in steps_of(walk["steps"]):
            say(d if d.startswith("open ") else DIRCMD[d], quiet=0.5)
        end = here()
        entry.update(walk=walk["steps"], walk_expected=walk["to"], walk_end=end, walk_ok=walk["to"].lower() in end.lower())
    result[key] = entry
    print(key, "OK" if ok and entry.get("walk_ok", True) else "FAIL", entry, file=sys.stderr, flush=True)
say("quit", quiet=1)
print(json.dumps(result, indent=1))
