# Midgaard map

An interactive map of Midgaard, the starting city of [DikuMUD III](https://github.com/Seifert69/DikuMUD3) (Valhalla MUD): all 205 rooms with their names, every exit, doors, up/down links and the roads out to other zones.

**Open it:** https://adamstone80.github.io/midgaard-map/

- Drag to move, scroll or pinch to zoom; names that don't fit appear as you zoom in.
- Click a room for its exits; search finds rooms by name.
- "Game map underneath" shows the game's own drawing of the city.

Rooms are placed at the positions the game uses for its web client's map (`gmap(x,y)` in `midgaard.zon`, pixels on `vme/www/img/midgaard.jpg`).

## Rebuilding

`index.html` is generated from a DikuMUD3 checkout:

```
python3 build.py PATH/TO/DikuMUD3
```

It reads `vme/zone/midgaard.zon` and `vme/www/img/midgaard.jpg` and fills them into `template.html`.

## Licence

The room data and map image come from DikuMUD III and, like this page, are under the GNU LGPL 2.1 (see `LICENSE`). This is an unofficial fan map.
