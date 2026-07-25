```

User query (natural language)
      │
      ▼
Agent (Claude, tool-calling)
      │  interprets intent → picks region + dates + metric
      ▼
Earth Engine backend (your "tool")
      │  MOD11A2 for country/state scale
      │  Landsat 8/9 ST_B10 for city/district drill-down
      │  returns: summary stats (JSON) + optional GeoTIFF/thumbnail
      ▼
Agent reasons over stats → sustainability recommendation
      │
      ▼
Your existing folium (2D) / pydeck (3D) visualization renders the result

```

# West Bengal Land Surface Temperature Viewer (FastAPI)

## Setup

```bash
pip install -r requirements.txt
```

Put your Landsat `..._ST_B10.TIF` file somewhere accessible, then either:

- drop it at `./data/LC08_L2SP_139044_20260601_20260612_02_T1_ST_B10.TIF`, or
- point `app.py` at it via an environment variable:

```bash
export LANDSAT_B10_PATH=/path/to/your_ST_B10.TIF   # (Windows: set LANDSAT_B10_PATH=...)
```

## Run

```bash
uvicorn Main.run:app --reload --port 8000
```

Then open **http://127.0.0.1:8000** in your browser.

## What it does

- `app.py` reads the ST_B10 band, crops it to a West Bengal bounding box
  (so you're not loading/serving the whole Landsat scene if it extends
  beyond the state), converts DN -> Kelvin -> Celsius, and computes:
  - a transparent PNG heat overlay (inferno colormap, alpha scaled by
    intensity) served at `/api/overlay.png`
  - precise geographic bounds (computed from all 4 corners of the cropped
    window, not just 2, so the overlay lines up correctly with the
    satellite basemap) plus a light sample of individual point readings,
    served as JSON at `/api/temperature`
- `templates/index.html` is a Leaflet page that fetches both endpoints and
  renders: a satellite/OSM/light basemap toggle, the temperature overlay,
  a legend, and a "Sample points" marker layer (the "other data") with
  click-to-see-temperature popups.
- Data is cached in memory after the first request, so the raster is only
  read and processed once per server run.

## Notes / things to adjust for your Landsat tile

- `WB_MIN_LON/MAX_LON/MIN_LAT/MAX_LAT` in `app.py` is an approximate West
  Bengal bounding box. If your Landsat scene (path/row 139/044 etc.) only
  covers part of the state, you'll only see that overlapping portion -
  that's expected, since a single Landsat scene is ~170x185 km and West
  Bengal is bigger than that. For full-state coverage you'd need to mosaic
  multiple WRS-2 scenes (see earlier discussion re: Earth Engine).
- `MAX_MARKER_POINTS` controls how many sample points render as clickable
  markers - raise/lower depending on how busy you want the map.
  