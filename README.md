# Valhalla maps

Interactive maps of [DikuMUD III](https://github.com/Seifert69/DikuMUD3) (Valhalla MUD) and [DikuMUD II](https://github.com/Seifert69/DikuMUD2).

## World map: every zone and how they connect

**Open it:** https://adamstone80.github.io/midgaard-map/world.html

- One box per zone, its area growing with its number of rooms, with its title, monster levels and teleport point.
- Dots on a box's edge are the rooms with an exit to another zone; lines join them (dashed: up or down; arrow: one way).
- Click a zone for:
  - its teleport point, a room for `cast controlled teleport <name>`, with alternatives
  - for a zone with no teleport point, the nearest one and the walk from it
  - its makers, the years in its notes, and its exits
- Switch between DikuMUD III, DikuMUD II and both.
- The address keeps the view and the zone, so a link opens the same zone.

How a teleport point is chosen:
- It must be a room the spell accepts: no no-teleport flag on it, or on a room it sits in.
- Its name must belong to no other room, monster or object in the game, because the spell goes to the first unit with the longest matching name.
- No aggressive monster may be loaded into it.
- Temples, inns, squares and shops come first.

The DikuMUD III teleport points and walks were tried in a test server (`tools/verify_teleports.py`, results in `tools/verified-d3.json`). The page says which were confirmed. DikuMUD II's points are worked out from its zone files only.

Limits:
- Only exits are drawn. Ships, portals and other moves made by DIL scripts are not.
- Valhalla runs zones whose source isn't public. A DikuMUD II zone that is also in DikuMUD III's zone list is marked as such.

## Midgaard room by room

**Open it:** https://adamstone80.github.io/midgaard-map/

- All 205 rooms of Midgaard, with their names, every exit, doors, up/down links and the roads out to other zones.
- Drag to move, scroll or pinch to zoom; names that don't fit appear as you zoom in.
- Click a room for its exits; search finds rooms by name.
- "Game map underneath" shows the game's own drawing of the city.

Rooms are placed at the positions the game uses for its web client's map (`gmap(x,y)` in `midgaard.zon`, pixels on `vme/www/img/midgaard.jpg`).

## Rebuilding

```
python3 build.py PATH/TO/DikuMUD3                   # index.html from template.html
python3 world.py PATH/TO/DikuMUD3 PATH/TO/DikuMUD2  # world.html from world-template.html
```

`world.py` needs a built DikuMUD3 (it runs the zone preprocessor `vme/bin/pp`). It reads every zone in each game's zone list. To check the teleport points again, run a DikuMUD3 server with an immortal and use:

```
python3 tools/verify_teleports.py world.html PORT NAME PASSWORD > tools/verified-d3.json
```

Then rebuild `world.html`.

## Licence

The zone data and map image come from DikuMUD III and DikuMUD II. Like these pages, they are under the GNU LGPL 2.1 (see `LICENSE`). These are unofficial fan maps: the game is the final word.
