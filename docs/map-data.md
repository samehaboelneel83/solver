# Map data: CAD drawings and GIS files as layers

Any DXF drawing, or a GeoJSON, KML/KMZ, GPX, Shapefile, GeoPackage or CSV
file (section 1b), can be brought onto the map, layer by layer, and kept in
the database as GIS features. Nothing in the pipeline knows what the drawing is
of. Camps (and anything else) are built *from* map data by pointing at its
layers.

```
DXF upload ─► CAD parser ─► coordinate system ─► WGS 84 geometry ─► database (PostGIS) ─► map
             app/gis/cad    app/gis/crs          app/gis/convert     app/gis/store         Map data pages
```

## 1. Parse (`backend/app/gis/cad.py`)

Every model-space entity becomes features of four kinds, in the drawing's
own coordinates and units:

| Kind | From |
|---|---|
| point | `POINT`; a block reference's insertion point, with its attributes |
| line | `LINE`, open `LWPOLYLINE`/`POLYLINE`, `ARC`, open `SPLINE`, elliptical arcs |
| polygon | closed polylines, `CIRCLE`, `ELLIPSE`, closed `SPLINE`, `HATCH` (with holes and islands), `SOLID`, `TRACE`, `3DFACE`, polyface meshes |
| text | `TEXT`, `MTEXT`, block `ATTRIB`s: the words, height and rotation |

- **Layers** keep their name, colour (ACI or true colour), linetype and on/off/frozen state.
- **Blocks** are exploded where inserted, nested blocks too. Each piece keeps
  the block name, the block path and the insert's attributes. A piece drawn on
  layer 0 takes the insert's layer and BYBLOCK colour, as AutoCAD draws it.
- **Dimensions, leaders, multileaders and tables** become their lines and text.
- **Curves** are flattened to within 1 cm. Polylines with bulges (arc
  segments) are followed.
- **What has no 2D geometry** (images, viewports, 3D solids, OLE) is counted
  as "skipped", never dropped silently. Z is kept as `elevation`.
- **Damaged files** are repaired while reading, and the repair is noted. A
  DWG must be saved as DXF first.

## 1b. Other spatial files (`backend/app/gis/formats.py`)

Each reader gives the same layers of point, line and polygon features as a
DXF, so placing, storing, viewing and making a camp from a layer work the
same. Attributes become feature properties. Multi-part shapes become one
feature per part, with a `part` number. Polygons keep their holes. No library
beyond shapely and pyproj is needed: shapefiles and GeoPackages are read
directly.

| Format | File | Layers | Coordinate system |
|---|---|---|---|
| GeoJSON | `.geojson`, `.json` | a `layer` property, else points / lines / polygons | WGS 84 (RFC 7946), or the legacy `crs` member |
| KML / KMZ | `.kml`, `.kmz` | the folder a placemark is in | WGS 84 |
| GPX | `.gpx` | waypoints, routes, tracks | WGS 84 |
| Shapefile | `.zip` of `.shp`, `.shx`, `.dbf`, `.prj` (`.cpg` for the text encoding) | each `.shp` | the `.prj` |
| GeoPackage | `.gpkg` | each feature table | the table's SRS |
| CSV | `.csv` (`,` `;` tab or `\|`) | a `layer` column, else the file | none: chosen when placing |

- **CSV shapes:** a CSV row's shape is a WKT column (`wkt`, `geometry`, `geom`,
  `the_geom`, `shape`) or two coordinate columns (`lon`/`lat`,
  `longitude`/`latitude`, `x`/`y`, `easting`/`northing`).
- **Coordinate system:** a system the file names is offered first and chosen
  for you.
- **Camps from longitude/latitude data:** a camp made from a file in longitude
  and latitude is laid out in metres. Its grid is turned to its longest wall
  (the camp's `bearing`), so walls drawn straight on any grid stay straight
  and its doors sit on them.
- **Names:** a shape's own `name` (or `label`, `id`) attribute names it, where
  a DXF needs a text beside it.

## 2. Where is it? (`backend/app/gis/crs.py`)

A DXF rarely says its coordinate system. `X = 523450, Y = 3341250` is in
Egypt in UTM zone 36N, in the Pacific in zone 1N, and nowhere at all as
degrees. So the system is **chosen by where the drawing lands**, previewed
over imagery before anything is stored:

- **Roughly where the site is**, the first question of the import: a country of the Middle East and
  North Africa (Egypt, Saudi Arabia, the UAE, Qatar, Kuwait, Bahrain, Oman, Yemen, Jordan, Iraq,
  Syria, Lebanon, Palestine, Israel, Turkey, Iran, Libya, Sudan, Cyprus), or a position. Every
  regional system in the EPSG registry whose area meets that place is tried — national grids such as
  Qatar National Grid, Dubai Local TM, Jordan TM, the Iraq National Grids, KSA-GRF17, TUREF, the
  Egyptian belts, and the UTM zones on local datums — and only those that put the drawing there are
  offered, one entry per place (datums that land within 3 km of each other are listed together, WGS 84
  first). When one place is left, or one lies near a given position, it is chosen; when the numbers fit
  two places in a country (Egypt spans UTM 35N and 36N), the person chooses on the map. The answer is
  remembered in the browser for the next import.
- **Near which city**, in the larger countries. Saudi Arabia spans UTM zones 36N to 40N, so the same
  numbers fit three or four places across the kingdom; choosing the nearest city (Riyadh, Jeddah,
  Makkah, Madinah, Dammam, Jubail, NEOM, Tabuk, Abha...) picks the zone. The same lists exist for
  Egypt, the UAE, Oman, Iraq, Iran, Turkey, Jordan, Syria, Yemen, Libya and Sudan.
- **The datum**: systems that land within 3 km of each other differ only by datum (in Saudi Arabia
  WGS 84, KSA-GRF17, MTRF-2000, Ain el Abd, ED50), by metres to a few hundred metres, which matters
  on a site plan. The entry offers them in a list; the drawing's surveyor's note or title block says
  which. Aramco Lambert (EPSG:2318) drawings are recognised by their own numbers.
- **The drawing's own geographic location** (AutoCAD GEODATA), when present.
- **The domain's usual drawing CRS**: the setting `spatial.drawing_crs` (an
  EPSG code; 0 means ask). Setting it once, e.g. to 32636, makes it the
  first choice for every import.
- **Degrees**, when the numbers look like longitude and latitude.
- **Systems whose area of use the drawing falls in**: the Egyptian belts
  (Red 22992, Purple 22993, Extended Purple 22994, Blue 22991), Palestine
  and Israel grids, Adindan UTM, and European national grids. World-wide
  systems (Web Mercator) fit any numbers, so they are listed last and never
  pre-selected.
- **Every UTM zone**, north and south, each with the place the drawing
  would land: the zone is not in the numbers.
- **Any EPSG code or name**, searched in the full registry.
- **Local engineering coordinates**: the drawing point *(x, y)* is at a
  longitude and latitude (typed, pasted or clicked on the map). The drawing's
  north is turned *n* degrees, and lengths are scaled.

Units come from `$INSUNITS`, or are set by hand. Millimetre drawings of UTM
coordinates are scaled before projecting; degrees are never scaled. The
preview warns when the drawing would fall off the map, would be implausibly
large, or would land outside the chosen system's area of use.

A wrong choice is fixed later without the file: each feature keeps its
drawing coordinates (`gis_feature.source`). *Source & location → Choose
another coordinate system* places the whole dataset again.

## 3. Store (migration 0097, `backend/app/gis/store.py`)

| Table | Holds |
|---|---|
| `gis_upload` | a file being imported, kept a day |
| `gis_dataset` | one drawing: source file, placement, extent, notes |
| `gis_layer` | its layers: name, colour, visibility, counts |
| `gis_feature` | every feature: `geometry` (GeoJSON, WGS 84), `source` (drawing coordinates), `properties` (entity, colour, text, block, attributes, handle), bounds |

All four tables are tenant-scoped (row-level security), like every other table.

**PostGIS.** The compose stack runs `postgis/postgis:16-3.4`, which is
Postgres 16 with the spatial extension, on the same data directory as
before. When the extension is available, migration 0097 creates it and adds
`gis_feature.geom geometry(Geometry, 4326)`. A trigger keeps `geom` in step
with `geometry`, and a GiST index covers it. Spatial SQL then works, and a
GIS desktop can read the features directly:

> QGIS → *Layer → Add Layer → Add PostGIS Layers* → the solver database →
> `gis_feature` (geometry column `geom`). Filter by `dataset_id` or `layer_id`.

Without the extension (a plain Postgres server) the tables are the same
without that column, and the platform works the same.

## 4. Map (`frontend/src/pages/MapData*.tsx`, `MapImport.tsx`, `MapView.tsx`)

- **Import**: choose the layers, choose where the drawing is with a live
  preview over satellite or street imagery, name it, import.
- **View**: layers in their CAD colours, or one colour per layer, shown or
  hidden and recoloured. Text appears at its height and angle; block
  references show as points. Click a feature for everything the drawing says
  about it. Search text, block names and attributes. Zoom to a layer.
- **Export**: GeoJSON (WGS 84), or CSV with WKT geometry.
- **Camps** are a tab of Map data, and kept as records of the domain (see
  `backend/camp_layout/README.md`).
- **Camps from map data**: *Map data → Camps → Or from map data*. Choose the
  boundary layer and the layers holding doors, closed areas, no-bed areas and
  bed zones; roles are guessed from layer names. The camp is laid out in the
  drawing's own grid, so straight walls stay straight. Touching door pieces
  (a leaf and its swing arc) become one door, snapped onto the wall.

Imagery comes from the tile index named by `spatial.tiles_index`, otherwise
from Esri World Imagery and OpenStreetMap, which the viewer's browser must
be able to reach.

## API

`/api/v1/gis/...`: see the docstring of `backend/app/api/gis.py`.

## Limits

- 50 MB per drawing, and 250,000 features per import (the rest are noted).
- The viewer shows up to 100,000 features at once.
- A camp built from map data keeps the drawing's grid: its bearing is the
  grid's turn from true north (a UTM zone's convergence, or a local grid's
  rotation), so it sits on the imagery exactly as drawn.
