# TTB Label Verification

Proof-of-concept scaffold for a stateless FastAPI app with a plain HTML frontend.

## Local Development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 and confirm the page lets you upload one label image, enter application data, and see a verdict with per-field results.

## Vision Extraction

API keys must stay in environment variables. For local real-model extraction:

```powershell
$env:OPENAI_API_KEY="your-key-here"
$env:OPENAI_VISION_MODEL="gpt-5.5"
.\.venv\Scripts\python.exe scripts\run_vision_sample.py
```

To verify the sample path without an API key:

```powershell
.\.venv\Scripts\python.exe scripts\run_vision_sample.py --mock
```

## Railway Deploy

```powershell
npm install -g @railway/cli
railway login
railway init --name ttb-label-verification
railway up
railway domain
```

Set `OPENAI_API_KEY` in Railway environment variables before live verification. Optional model settings can use the names from `.env.example`.

Open the generated Railway domain and confirm the page lets you upload one label image, enter application data, and see a verdict with per-field results. Error responses should appear in the red verification error panel.
