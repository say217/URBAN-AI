# Feature Ideas — Thermal Intelligence Dashboard

Simple, low-effort additions you could make next.

## Map & Data
- **Multiple scene support** — dropdown to switch between several processed Landsat scenes instead of just one.
- **Date/time stamp on scenes** — show when the source Landsat image was captured.
- **Hover tooltip on map** — show temperature at the exact pixel under the cursor.
- **Export overlay as image** — download button for the current heat map view.
- **Compare mode** — side-by-side or slider comparison between two scenes (e.g. summer vs winter).

## Sidebar / Stats
- **Search/filter saved tiles** — list and preview previously saved `.map_image` crops.
- **Download stats as CSV/JSON** — one-click export of the KPI panel data.
- **Threshold alerts** — highlight when max temp crosses a value you set (e.g. "hotspot alert").
- **Unit toggle** — switch between Celsius and Fahrenheit.

## Chat Assistant
- **Suggested follow-up questions** — show 2–3 new chips after each AI reply.
- **Copy/share chat answer** — small copy-to-clipboard button on assistant messages.
- **Clear conversation button** — reset the chat history without reloading the page.

## HUD / Header
- **Sunrise/sunset time** — pairs naturally with the existing scene-time widget.
- **Air quality or humidity widget** — same style as the current weather HUD card.
- **Last-updated timestamp** — small label showing when the overlay was last processed.

## General UX
- **Light/dark theme toggle** — even just a single alternate palette.
- **Keyboard shortcuts** — e.g. `D` to toggle draw mode, `Esc` to cancel a selection.
- **Loading skeletons** — placeholder shimmer while the map/overlay first loads.
- **Mobile-friendly collapsed layout** — stack panels vertically on small screens.

## Nice-to-haves (more effort)
- **User accounts / saved sessions** — remember each user's saved tiles and chat history.
- **Multi-region raster stitching** — combine adjacent Landsat tiles into one continuous map.
- **Historical trend chart** — line chart of min/max temp across multiple processed dates.