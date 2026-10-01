# Sample files for the Map data and Camps workflow

Two CAD drawings and a GeoJSON file to try the whole workflow with: import, place on the map,
turn into a camp, type the numbers, lay it out. `make_samples.py` makes them
from the camp engine's examples.

## `mina-camp-utm37n.dxf`: a surveyed camp in Saudi Arabia

The engine's complex example ("Irregular camp, four doors"), drawn as a
surveyor would: metres, in **UTM zone 37N (EPSG:32637)**, at Mina, Makkah
(about 21.413 N, 39.893 E).

| Layer | What is on it |
|---|---|
| `CAMP_BOUNDARY` | the camp outline: nine sides, 40 × 26 m |
| `DOORS` | four doors (lines on the walls) with their names: D1-south, D2-east, D3-north, D4-west |
| `OBSTACLES` | five closed areas: latrines, generator, water-tank (a circle), trees, medical-store |
| `NO_BEDS` | fire-break and exhaust: people may walk, no beds |
| `ZONE_MEDICAL_AREA` | where the medical beds must go |
| `ROADS`, `NOTES` | context: a road around the camp, and a note; not part of the camp |

## `small-room-mm.dxf`: units and blocks

The small example (a 14 × 9 m room, one door, one pillar) in **millimetres**,
with **no coordinate system**. Its door is a block (the leaf and its swing arc),
the way architects draw doors.

## Try it

**A. Straight into a camp.** Go to Map data → Camps → *From a CAD drawing (.dxf)
or workbook (.xlsx)*.
1. Coordinate system: `EPSG:32637`. Pick `mina-camp-utm37n.dxf`.
2. The camp opens at Mina with its 4 doors, 5 closed areas, 2 no-bed areas and the
   medical zone. The notes say the `ROADS` layer was ignored.
3. A drawing holds shapes only, so type the numbers in the panels:
   - door capacities (Selected shape)
   - bed types; add a "medical" type and set it to go in `medical-area` (Beds)
   - corridor width (Settings)
4. Save, then open Layout and click Lay out.
5. Check Records, Relationships and Parameters: the camp is there as records.

`small-room-mm.dxf` needs no coordinate system: it is placed at the default
point. Use *Place on map* to move it. Its millimetres are read as metres from
the drawing's units, and the door block becomes one 1.5 m door.

**B. As map data first (any drawing).** Go to Map data → Import map data.
1. Upload `mina-camp-utm37n.dxf`.
2. Region: Saudi Arabia, city Makkah. Choose **WGS 84 / UTM zone 37N
   (EPSG:32637)** from the suggestions.
3. All seven layers land on the map: boundary, doors, closed areas, roads, notes, and so on.
4. Go to Camps → *Or from map data*. Choose this drawing and give each layer its
   role:
   - boundary: `CAMP_BOUNDARY`
   - doors: `DOORS`
   - closed areas: `OBSTACLES`
   - no-bed areas: `NO_BEDS`
   - bed zones: `ZONE_MEDICAL_AREA`

   Leave `ROADS` and `NOTES` out.
5. Continue as in A from step 3.

**C. GeoJSON.** `mina-camp.geojson` is the same camp in longitude and latitude,
each feature's `layer` property naming its layer and its `name` naming the
shape. Import it under Map data → Import map data: it lands at Mina by itself (WGS 84 is chosen
for you). Then make the camp from its layers as in B, step 4.

For your own drawings, use the same layer names (case does not matter), or any
names when going through Map data, since there you say which layer is which.
