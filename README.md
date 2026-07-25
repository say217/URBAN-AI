# URBAN AI
West Bengal Land Surface Temperature Viewer (FastAPI)

<img width="1526" height="735" alt="image" src="https://github.com/user-attachments/assets/5688364c-955d-4125-8304-0310d1d3fb71" />



- check Features.md file we need to implement this features step by step in our project

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
