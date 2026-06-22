# TTB Label Verification

Proof-of-concept TTB alcohol label verification app. The backend is Python 3.12
and FastAPI, the frontend is plain HTML/CSS/JavaScript, extraction uses a vision
model, and the app is stateless with no database.

## Requirements Guardrails

- Single-label verification must complete in under 5 seconds.
- Batch upload is required and supported through the UI and `/verify/batch`.
- Government warning text is compared as an exact, case-sensitive string.
- All other fields are normalized or fuzzy-matched before comparison.
- API keys must only be provided through environment variables.

## Environment

Copy `.env.example` for local use, but never commit a real `.env` file.

| Variable | Required | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | Yes for real extraction | Vision model API key. Leave blank in examples and commits. |
| `OPENAI_VISION_MODEL` | No | Vision-capable model name used by `OpenAIVisionService`. |
| `OPENAI_TIMEOUT_SECONDS` | No | Per-request model timeout. Keep tuned for the 5-second single-label target. |
| `OPENAI_REASONING_EFFORT` | No | Optional reasoning effort value. Blank means omit it from requests. |
| `OPENAI_IMAGE_DETAIL` | No | Image detail sent to the vision model. Defaults to `low`. |
| `OPENAI_MAX_OUTPUT_TOKENS` | No | Output token cap for extraction responses. |
| `IMAGE_MAX_SIDE` | No | Largest image side after preprocessing. |
| `IMAGE_MAX_BYTES` | No | Maximum preprocessed image payload size. |

## Local Development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. The first screen is the verifier: choose one or
more label images, enter the expected application data, and select **Verify
Labels**.

## Vision Smoke Test

Run without an API key:

```powershell
.\.venv\Scripts\python.exe scripts\run_vision_sample.py --mock
```

Regenerate the demo sample image if it is missing or stale:

```powershell
.\.venv\Scripts\python.exe scripts\run_vision_sample.py --mock --regenerate-sample
```

Run with real extraction:

```powershell
$env:OPENAI_API_KEY="your-key-here"
.\.venv\Scripts\python.exe scripts\run_vision_sample.py
```

## API

`POST /verify`

- Multipart field `application_data`: JSON object with expected label fields.
- Multipart file `label_image`: one PNG, JPEG, or WebP label image.
- Returns one `VerificationResult` with per-field results and `latency_ms`.

`POST /verify/batch`

- Multipart field `application_data`: same JSON object used by `/verify`.
- Multipart files `label_images`: one to ten PNG, JPEG, or WebP images.
- Returns a batch summary plus ordered per-label results.

Application fields:

```json
{
  "brand_name": "Example Estate",
  "class_type": "Cabernet Sauvignon",
  "abv": "13.5% alc/vol",
  "net_contents": "750 mL",
  "producer": "Example Wine Co.",
  "country_of_origin": "USA",
  "government_warning": "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic beverages during pregnancy because of the risk of birth defects. (2) Consumption of alcoholic beverages impairs your ability to drive a car or operate machinery, and may cause health problems."
}
```

## Deploy To Railway

```powershell
npm install -g @railway/cli
railway login
railway init --name ttb-label-verification
railway up
railway domain
```

Set `OPENAI_API_KEY` and any optional model tuning values as Railway environment
variables before running a live demo. Do not put real keys in `.env.example`,
README examples, source files, tests, or screenshots.

## Live Demo Check

After deployment, run the repeatable end-to-end check against the public URL:

```powershell
.\.venv\Scripts\python.exe scripts\live_demo_check.py https://your-app.up.railway.app
```

Add `--verbose` to print compact field-level diagnostics for any failed check.

The script verifies:

- `/health` returns `status=ok`.
- A single-label `/verify` request is approved in under 5 seconds wall time.
- A two-image `/verify/batch` request succeeds with no item errors.
- A government warning with different capitalization fails with
  `match_type=exact_case_sensitive`.
- An imperfect, degraded image still returns a usable verification result.

## Secret Audit

Run these checks before handoff:

```powershell
rg -n --hidden --glob '!.git' --glob '!.venv' --glob '!__pycache__' --glob '!.pytest_cache' --glob '!*.pyc' "sk-(proj|live|test)-|OPENAI_API_KEY\s*=\s*sk-|-----BEGIN (RSA |OPENSSH |DSA |EC |)PRIVATE KEY-----|Bearer\s+[A-Za-z0-9._-]{20,}" .
git grep -n -I -E "sk-(proj|live|test)-|OPENAI_API_KEY[[:space:]]*=[[:space:]]*sk-|-----BEGIN (RSA |OPENSSH |DSA |EC |)PRIVATE KEY-----|Bearer[[:space:]]+[A-Za-z0-9._-]{20,}" -- .
git grep -n -I -E "sk-(proj|live|test)-|OPENAI_API_KEY[[:space:]]*=[[:space:]]*sk-|-----BEGIN (RSA |OPENSSH |DSA |EC |)PRIVATE KEY-----|Bearer[[:space:]]+[A-Za-z0-9._-]{20,}" $(git rev-list --all) -- .
```

Expected result: no matches. `rg` and `git grep` return exit code `1` when no
matches are found.
