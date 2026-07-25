# URBAN AI
West Bengal Land Surface Temperature Viewer (FastAPI)

## Setup

```bash
python -m venv .venv

.venv/scripts/activate

pip install -r requirements.txt
```

## Run

```bash
uvicorn Main.run:app --reload --port 8000
```

Put your Landsat `..._ST_B10.TIF` file somewhere accessible, then either:

- drop it at `./data/LC08_L2SP_139044_20260601_20260612_02_T1_ST_B10.TIF`, or
- point `app.py` at it via an environment variable:

```bash
export LANDSAT_B10_PATH=/path/to/your_ST_B10.TIF   # (Windows: set LANDSAT_B10_PATH=...)
```
