# Sample files for Map data

Two CAD drawings and a GeoJSON file to try map data with: import, place on the map, view, make
records from a layer. The tests in `backend/tests/test_sample_drawings.py` import them too.

## `mina-camp-utm37n.dxf`: a surveyed site in Saudi Arabia

A site drawn as a surveyor would: metres, in **UTM zone 37N (EPSG:32637)**, at Mina, Makkah
(about 21.413 N, 39.893 E).

| Layer | What is on it |
|---|---|
| `CAMP_BOUNDARY` | the site outline: nine sides, 40 x 26 m |
| `DOORS` | four entrances (lines on the walls) with their names: D1-south, D2-east, D3-north, D4-west |
| `OBSTACLES` | five closed areas: latrines, generator, water-tank (a circle), trees, medical-store |
| `NO_BEDS` | fire-break and exhaust areas |
| `ZONE_MEDICAL_AREA` | a zone |
| `ROADS`, `NOTES` | a road around the site, and a note |

## `small-room-mm.dxf`: units and blocks

A 14 x 9 m room, one door, one pillar, in **millimetres**, with **no coordinate system**. Its
door is a block (the leaf and its swing arc), the way architects draw doors.

## `mina-camp.geojson`

The Mina site again in longitude and latitude, each feature's `layer` property naming its layer
and its `name` naming the shape.

## Try it

Go to Map data, then Import map data.

1. Upload `mina-camp-utm37n.dxf`. Region: Saudi Arabia, city Makkah. Choose **WGS 84 / UTM zone
   37N (EPSG:32637)** from the suggestions. All seven layers land on the map at Mina.
2. Upload `mina-camp.geojson`: it lands at Mina by itself (WGS 84 is chosen for you).
3. Upload `small-room-mm.dxf`: it has no coordinate system, so place it where you want it; its
   millimetres are read from the drawing's units.
4. Open a drawing and use *Make records* on a layer (for example `OBSTACLES`) to turn its shapes
   into records with their geometry, area and length.

The Assistant takes the same files (paperclip, or drop them on its panel).
