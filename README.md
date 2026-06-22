# TTB Label Verification

Phase 0 proof-of-concept scaffold for a stateless FastAPI app with a plain HTML frontend.

## Local Development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 and confirm the page shows the JSON response from `/health`.

## Railway Deploy

```powershell
npm install -g @railway/cli
railway login
railway init --name ttb-label-verification
railway up
railway domain
```

Open the generated Railway domain and confirm the page shows the JSON response from `/health`.
