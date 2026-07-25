
```bash
          User Draws Region
                  │
                  ▼
         Polygon (GeoJSON)
                  │
     ┌────────────┴────────────┐
     ▼                         ▼
 Crop Landsat Raster      Crop Satellite Image
     ▼                         ▼
Calculate Statistics      Save Image
     ▼                         ▼
temperature values      Vision Model (optional)
     │                         │
     └──────────────┬──────────┘
                    ▼
             Structured Context
                    ▼
              LLM (Qwen2.5-VL-72B-Instruct)
                    ▼
      Sustainable Recommendations

```

## LLM-Qwen2.5-VL-72B-Instruct

Why this model?

Understands both images and text well.
Performs strongly on satellite imagery, maps, charts, and diagrams.
Can reason over structured numerical data (temperature, NDVI, land cover) alongside an image.
Produces detailed, practical recommendations.
Available through Groq's API (availability may vary by account/region).

```
{
  "location":"Kolkata",
  "area":2.1,
  "mean_temperature":39.8,
  "max_temperature":46.2,
  "hotspot_percentage":18,
  "vegetation":21,
  "building":49,
  "road":18,
  "water":2,
  "satellite_image":"tile.png"
}