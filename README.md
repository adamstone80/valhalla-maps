# Valhalla maps

Interactive maps of [DikuMUD III](https://github.com/Seifert69/DikuMUD3) (Valhalla MUD) and [DikuMUD II](https://github.com/Seifert69/DikuMUD2).

## World map: every zone and how they connect

**Open it:** https://adamstone80.github.io/midgaard-map/world.html

- One box per zone, its area growing with its number of rooms, coloured by how dangerous its weakest monsters are: novices, some experience, seasoned, the mightiest.
- **My level** fades the zones that don't suit a character of that level.
- The star marks the Temple of Udgaard, where players start and come back after dying.
- Dots on a box's edge are the rooms with an exit to another zone; lines join them (dashed: up or down; arrow: one way).
- Click a zone for:
  - a short introduction that hints at what waits there, without spoilers (see below)
  - the walk from the Temple of Udgaard, drawn on the map, never through a locked or hidden door
  - its teleport point, a room for `cast controlled teleport <name>`, with alternatives; for a zone with no teleport point, the nearest one and the walk from it
  - its exits, one line per zone they lead to
  - its makers, years, builder's notes and zone id, under "About this zone's data"
- Search finds zones by name, teleport point or anything in their introduction.
- "Whole world" shows every zone of both games, the closest picture of Valhalla; DikuMUD II zones that aren't in Valhalla's zone list are faded. The other two views show one game's source.
- Zones that hold only game machinery (commands, spells, boards) are left out.
- The address keeps the view and the zone, so a link opens the same zone.

Introductions:
- `tools/dossier.py` gathers each zone's public side (title, help text, room and monster descriptions, objects, levels, neighbours) and, separately, its quests (the quest guide's section, or the zone's DIL scripts).
- `tools/intros.py` asks Claude in three separate steps: turn each quest into a hint in general words (no names, places, steps or rewards; quests marked dormant or broken are dropped), write the introduction from the public side and those hints only, then check it against the quest notes. A name that isn't in the public side fails it too.
- Every introduction is reviewed by hand before it appears (`tools/review_sync.py`); `intros.json` holds only the approved text.
- The dossiers and the working file hold spoilers, so they stay in `tools/private/`, which git ignores.

How a teleport point is chosen:
- It must be a room the spell accepts: no no-teleport flag on it, or on a room it sits in.
- Its name must belong to no other room, monster or object in the game, because the spell goes to the first unit with the longest matching name.
- No aggressive monster may be loaded into it.
- Temples, inns, squares and shops come first.

The DikuMUD III teleport points and walks were tried in a test server (`tools/verify_teleports.py`, results in `tools/verified-d3.json`). The page says which were confirmed. DikuMUD II's points are worked out from its zone files only.

Limits:
- Only exits are drawn. Ships, portals and other moves made by DIL scripts are not.
- Valhalla runs zones whose source isn't public. A DikuMUD II zone that is also in DikuMUD III's zone list is marked as such.
- Walks are worked out from the zone files: a guard or a script in the game can stop one.

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

To write introductions for new or changed zones (a zone is written again only when its source changes):

```
python3 tools/dossier.py PATH/TO/DikuMUD3 PATH/TO/DikuMUD2 [QUEST_SECTIONS_DIR]
python3 tools/intros.py
python3 tools/review_sync.py export > tools/private/review-rows.json   # rows for the review page
python3 tools/review_sync.py apply ROWS.json                           # approved ones into intros.json
python3 world.py PATH/TO/DikuMUD3 PATH/TO/DikuMUD2 --drafts           # local preview with unreviewed ones
```

`world.py` needs a built DikuMUD3 (it runs the zone preprocessor `vme/bin/pp`). It reads every zone in each game's zone list. To check the teleport points again, run a DikuMUD3 server with an immortal and use:

```
python3 tools/verify_teleports.py world.html PORT NAME PASSWORD > tools/verified-d3.json
```

Then rebuild `world.html`.

## Licence

The zone data and map image come from DikuMUD III and DikuMUD II. Like these pages, they are under the GNU LGPL 2.1 (see `LICENSE`). These are unofficial fan maps: the game is the final word.
