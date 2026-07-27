# TTB Label Verification

Proof-of-concept TTB alcohol label verification app. The backend is Python 3.12
and FastAPI, the frontend is plain HTML/CSS/JavaScript, extraction uses a vision
model, and the app is stateless with no database.

## What the App Does

Given a label photo and the application data submitted for that product, the
app extracts the same seven fields from the image with a vision model and
compares each one against what was submitted:

`brand_name`, `class_type`, `abv`, `net_contents`, `producer`,
`country_of_origin`, `government_warning`

Each field gets its own PASS/FAIL (see [Comparison Rules](#comparison-rules) for
the matching strategy per field). The overall verdict follows one rule:
**`APPROVED` when every field passes, otherwise `NEEDS_REVIEW`.** Nothing is
auto-rejected outright — `NEEDS_REVIEW` means a human should look at the
per-field diffs before approving the label.

## Live URL

**Live URL:** https://ttb-label-verification-99tf.onrender.com

Previously hosted at `https://ttb-label-verification-production-ab6b.up.railway.app`
on Railway. That trial expired and the account will not be reactivated, so the
app now runs on Render's free tier instead. Because the free tier spins down
after ~15 minutes of inactivity, the first request after idle time can be
slow (or occasionally fail — see [Deploy To Render](#deploy-to-render) and
[Performance](#performance)); it recovers on retry.

## Architecture at a Glance

```
label image + application data
        |
        v
  app/routes.py            API layer: POST /verify, POST /verify/batch
        |
        v
  app/vision.py       -->  app/vision_helpers.py
  OpenAIVisionService       ImagePreprocessor, model-response parsing
        |
        v
  extracted label (7 fields)
        |
        v
  app/comparison.py         per-field match rules -> overall verdict
        |
        v
  VerificationResult (APPROVED / NEEDS_REVIEW)
```

| Module | Responsibility |
| --- | --- |
| `app/main.py` | FastAPI app factory, lifespan vision-model warm-up, `/health`, static file mount. |
| `app/routes.py` | API layer: `/verify` and `/verify/batch`, request parsing, batch concurrency. |
| `app/vision.py` | Vision service: `OpenAIVisionService` (real) and `FakeVisionService` (tests). |
| `app/vision_helpers.py` | `ImagePreprocessor` (resize/recompress/EXIF-normalize) and model-response parsing. |
| `app/comparison.py` | Comparison engine: per-field match strategies and the overall verdict rule. |
| `app/models.py` | Pydantic request/response schemas, including `LABEL_FIELD_NAMES`. |

## Requirements Guardrails

- Single-label verification must complete in under 5 seconds.
- Batch upload is required and supported through the UI and `/verify/batch`.
- Government warning text is compared as an exact, case-sensitive string.
- All other fields are normalized or fuzzy-matched before comparison.
- API keys must only be provided through environment variables.

## Environment

Copy `.env.example` for local use, but never commit a real `.env` file.

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` | Yes for real extraction | *(none)* | Vision model API key. Leave blank in examples and commits. |
| `OPENAI_VISION_MODEL` | No | `gpt-4.1-mini` | Vision-capable model name used by `OpenAIVisionService`. |
| `OPENAI_TIMEOUT_SECONDS` | No | `4.25` | Per-request model timeout. Keep tuned for the 5-second single-label target. |
| `OPENAI_REASONING_EFFORT` | No | *(blank, omitted)* | Optional reasoning effort value. Blank means omit it from requests. |
| `OPENAI_IMAGE_DETAIL` | No | `low` | Image detail sent to the vision model. |
| `OPENAI_MAX_OUTPUT_TOKENS` | No | `300` | Output token cap for extraction responses. |
| `IMAGE_MAX_SIDE` | No | `1280` | Largest image side, in pixels, after preprocessing. |
| `IMAGE_MAX_BYTES` | No | `1000000` | Maximum preprocessed image payload size, in bytes. |
| `MAX_BATCH_LABELS` | No | `10` | Per-request cap on images accepted by `/verify/batch`. |
| `MAX_BATCH_CONCURRENCY` | No | `4` | Max concurrent extractions within one batch request. |

## Model

The app uses `OPENAI_VISION_MODEL` (default: `gpt-4.1-mini`, see
`app/vision.py`) for label extraction. Chosen over `gpt-4o-mini` and
`gpt-4.1-nano` for the most reliable verbatim capture of the government
warning field, while staying well inside the 5-second single-label budget.
Before a submission or deploy, confirm this model id is still current:

```
python scripts/verify_model.py
```

This pings OpenAI's model list with `OPENAI_API_KEY` and fails if the
configured model isn't on it. The same check also runs in CI on every push
and pull request to `main` (see `.github/workflows/model-check.yml`), using
an `OPENAI_API_KEY` repository secret, so a renamed or retired model fails
the build instead of surfacing as a runtime error.

- Model in use: `gpt-4.1-mini`
- Last verified against the live OpenAI model list: 2026-07-12

## Local Development

macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Windows (PowerShell):

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

macOS/Linux: `.venv/bin/python scripts/run_vision_sample.py --mock`
Windows: `.\.venv\Scripts\python.exe scripts\run_vision_sample.py --mock`

Regenerate the demo sample image if it is missing or stale:

macOS/Linux: `.venv/bin/python scripts/run_vision_sample.py --mock --regenerate-sample`
Windows: `.\.venv\Scripts\python.exe scripts\run_vision_sample.py --mock --regenerate-sample`

Run with real extraction:

macOS/Linux:

```bash
export OPENAI_API_KEY="your-key-here"
.venv/bin/python scripts/run_vision_sample.py
```

Windows (PowerShell):

```powershell
$env:OPENAI_API_KEY="your-key-here"
.\.venv\Scripts\python.exe scripts\run_vision_sample.py
```

## API

`POST /verify`

- Multipart field `application_data`: JSON object with expected label fields.
- Multipart file `label_image`: one PNG, JPEG, or WebP label image.
- Returns one `VerificationResult` with per-field results and `latency_ms`.

```bash
curl -X POST https://ttb-label-verification-99tf.onrender.com/verify \
  -F 'application_data={"brand_name":"Example Estate","class_type":"Cabernet Sauvignon","abv":"13.5% alc/vol","net_contents":"750 mL","producer":"Example Wine Co.","country_of_origin":"USA","government_warning":"GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic beverages during pregnancy because of the risk of birth defects. (2) Consumption of alcoholic beverages impairs your ability to drive a car or operate machinery, and may cause health problems."}' \
  -F 'label_image=@scripts/sample_label.png;type=image/png'
```

`POST /verify/batch`

- Multipart field `application_data`: same JSON object used by `/verify`.
- Multipart files `label_images`: one to ten PNG, JPEG, or WebP images.
- Returns a batch summary plus ordered per-label results.

```bash
curl -X POST https://ttb-label-verification-99tf.onrender.com/verify/batch \
  -F 'application_data={"brand_name":"Example Estate","class_type":"Cabernet Sauvignon","abv":"13.5% alc/vol","net_contents":"750 mL","producer":"Example Wine Co.","country_of_origin":"USA","government_warning":"GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic beverages during pregnancy because of the risk of birth defects. (2) Consumption of alcoholic beverages impairs your ability to drive a car or operate machinery, and may cause health problems."}' \
  -F 'label_images=@label_front.png;type=image/png' \
  -F 'label_images=@label_back.jpg;type=image/jpeg'
```

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

A successful `/verify` response (`VerificationResult`):

```json
{
  "results": [
    {"field": "brand_name", "match_type": "fuzzy", "expected": "Example Estate", "found": "Example Estate", "status": "PASS"},
    {"field": "class_type", "match_type": "fuzzy", "expected": "Cabernet Sauvignon", "found": "Cabernet Sauvignon", "status": "PASS"},
    {"field": "abv", "match_type": "abv_numeric_tolerance", "expected": "13.5% alc/vol", "found": "13.5%", "status": "PASS"},
    {"field": "net_contents", "match_type": "net_contents_ml", "expected": "750 mL", "found": "750mL", "status": "PASS"},
    {"field": "producer", "match_type": "fuzzy", "expected": "Example Wine Co.", "found": "Example Wine Company", "status": "PASS"},
    {"field": "country_of_origin", "match_type": "country_synonym", "expected": "USA", "found": "United States", "status": "PASS"},
    {"field": "government_warning", "match_type": "exact_case_sensitive", "expected": "GOVERNMENT WARNING: ...", "found": "GOVERNMENT WARNING: ...", "status": "PASS"}
  ],
  "overall_verdict": "APPROVED",
  "latency_ms": 2905.4
}
```

A 422 error response, when `application_data` fails field validation (from
`_parse_application_data` in `app/routes.py`):

```json
{
  "detail": {
    "message": "application_data contains invalid field values.",
    "errors": [
      {
        "type": "string_type",
        "loc": ["abv"],
        "msg": "Input should be a valid string",
        "input": 13.5
      }
    ]
  }
}
```

## Comparison Rules

Every field uses one of five match strategies, applied in `app/comparison.py`:

| Field(s) | Strategy | Rule |
| --- | --- | --- |
| `brand_name`, `class_type`, `producer` | `fuzzy` | Normalized (casefold, punctuation-stripped), then similarity-ratio match with threshold `0.90` (`DEFAULT_FUZZY_THRESHOLD`). Falls back to a token-sorted comparison so word order doesn't cause a false FAIL. |
| `abv` | `abv_numeric_tolerance` | Percent value is parsed out of either field (handles `%`, "alc/vol", or "proof"), then compared with tolerance ±`0.1` (`ABV_TOLERANCE`). |
| `net_contents` | `net_contents_ml` | Value is normalized to milliliters (supports mL, L, cL, fl oz, oz) and compared with tolerance ±`1.0` mL (`NET_CONTENTS_ML_TOLERANCE`). |
| `country_of_origin` | `country_synonym` | Normalized and mapped through a synonym table (e.g. `USA`/`US` &rarr; `united states`, `UK`/`GB` &rarr; `united kingdom`) before comparing. |
| `government_warning` | `exact_case_sensitive` | Whitespace is collapsed on both sides, then compared as an **exact, case-sensitive** string — no fuzzy matching, per the hard requirement. |

## Deploy To Render

The app previously ran on Railway. Railway's trial expired (the account will
not be reactivated), so it now deploys to **Render's free web service tier**
instead, using the `render.yaml` blueprint at the repo root.

1. Push this repo to GitHub (Render deploys from a connected Git repo, not a
   CLI upload).
2. In the Render dashboard: **New > Blueprint**, connect the repo, and Render
   will read `render.yaml` and provision the `ttb-label-verification` web
   service automatically (`pip install -r requirements.txt`, then
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, with `/health` as the
   health check path).
3. Set `OPENAI_API_KEY` in the service's **Environment** tab — `render.yaml`
   marks it `sync: false` so Render prompts for it rather than storing it in
   the blueprint. Set any optional model-tuning variables (see
   [Environment](#environment)) the same way if you want non-default values.
   Do not put real keys in `.env.example`, README examples, source files,
   tests, or screenshots.
4. Once deployed, note the assigned `https://<service-name>.onrender.com` URL
   and update the [Live URL](#live-url) section above.

**Free-tier tradeoff:** unlike Railway's always-on paid plan, Render's free
tier spins the service down after ~15 minutes of inactivity. The first
request after idle time pays a cold-start penalty (container boot + the
`warm_up()` vision-model call in `app/main.py`'s lifespan hook) before
returning — expect it to exceed the 5-second `/verify` budget. Subsequent
requests while the service is warm stay within budget as before.

## Live Demo Check

After deployment, run the repeatable end-to-end check against the public URL.

**Live URL:** https://ttb-label-verification-99tf.onrender.com
**Last run on Render:** 2026-07-27 — 4/5 checks passed on a warm container;
one flaky run also failed on a cold-started container (see cold-start note
below). Re-run the script a couple of times if a check fails right after a
period of inactivity.
**Last verified end-to-end on the prior Railway deployment (all 5 checks
passing):** 2026-07-12

macOS/Linux: `.venv/bin/python scripts/live_demo_check.py <live-url>`
Windows: `.\.venv\Scripts\python.exe scripts\live_demo_check.py <live-url>`

Add `--verbose` to print compact field-level diagnostics for any failed check.

The script verifies:

- `/health` returns `status=ok`.
- A single-label `/verify` request is approved in under 5 seconds wall time.
- A two-image `/verify/batch` request succeeds with no item errors.
- A government warning with different capitalization fails with
  `match_type=exact_case_sensitive`.
- An imperfect, degraded image still returns a usable verification result.

## Performance

Target: single-label `/verify` under 5 seconds wall time.

Measured against the **deployed** URL (not local) with
`scripts/benchmark_latency.py`, which sends sequential `/verify` requests using
`scripts/sample_label.png` and times each one end-to-end:

```bash
python -m scripts.benchmark_latency <live-url> --requests 25
```

Note the `-m scripts.benchmark_latency` form — the script imports a helper from
`scripts/live_demo_check.py`, so it must run as a module, not
`python scripts/benchmark_latency.py`.

**Before the fix** (2026-07-12, n=25): `min=2166ms p50=3017ms p95=6749ms
max=8328ms`. p50 was comfortably inside the 5-second target; **p95 and max
were not** — 2 of the 25 requests took 7.4s and 8.3s. Root cause:
`OpenAIVisionService` built its client as `OpenAI(api_key=...,
timeout=timeout_seconds)` without setting `max_retries`, so the SDK's default
(`max_retries=2`) was active. A single attempt is bounded by
`OPENAI_TIMEOUT_SECONDS` (default `4.25`), so any call over ~4.3s is provably
at least two attempts — a timed-out/retryable first attempt, an SDK backoff
sleep, then a second attempt.

**Fixed**: the client is now built with `max_retries=0` (`app/vision.py`), so
a `/verify` call either succeeds within one `OPENAI_TIMEOUT_SECONDS` window or
fails fast with a `502`/`503` instead of silently retrying past the 5-second
budget.

**After the fix** (2026-07-12, n=25, live Railway URL, redeployed):

| Stat | Value |
| --- | --- |
| min | 2268 ms |
| p50 | 2837 ms |
| p95 | 3822 ms |
| max | 3926 ms |

All four stats, including p95 and max, were comfortably inside the 5-second
target on Railway.

**Re-measured on Render** (2026-07-27, n=25, warm container, live URL above):

| Stat | Value |
| --- | --- |
| min | 2294 ms |
| p50 | 2808 ms |
| p95 | 3621 ms |
| max | 3928 ms |

24 of 25 requests succeeded within the target; 1 failed with a `502` — the
expected `max_retries=0` fail-fast behavior (see [Limitations](#limitations))
rather than a Render-specific regression. Warm-container latency is
statistically indistinguishable from the Railway numbers above, so the
free-tier host swap did not change steady-state performance.

**Cold start:** `app/main.py`'s `lifespan` hook calls
`OpenAIVisionService.warm_up()` once at process startup (a throwaway
`responses.create` call) specifically so the first real user request doesn't
pay for provisioning the model server-side. This absorbs model-warm-up cost,
but not container-boot cost: on Render's free tier the service spins down
after ~15 minutes of inactivity, so the first request after idle time still
pays a full container-restart penalty. Observed in practice on 2026-07-27:
the first `/verify` after a cold start took 5994 ms wall time (over budget),
and a couple of the earliest post-idle requests returned `502` before the
container fully settled. Railway's paid always-on plan had no such spin-down;
this is a genuine tradeoff of the free-tier host, not a bug.

## Assumptions

- Label images are legible, right-side-up or EXIF-oriented, and photographed
  well enough for a vision model to read (the app does not attempt OCR
  correction or manual rotation).
- `application_data` submitted to the API is trusted, well-formed input — there
  is no adversarial-input hardening beyond standard JSON/Pydantic validation.
- The deployment environment has outbound network access to the OpenAI API and
  a valid `OPENAI_API_KEY` is configured before any `/verify` request is made.
- One API key is shared across all requests; there is no per-user or per-tenant
  key management.
- Labels are in English; extraction prompts and comparison rules are not
  localized.

## Limitations

- No persistence — nothing is stored between requests; there is no history of
  past verifications.
- No authentication or authorization on any endpoint.
- No OCR fallback if the vision model is unavailable or misconfigured; a
  `/verify` request in that state returns a `503`/`502` rather than degrading.
- Batch upload is capped at `MAX_BATCH_LABELS` (default 10) images per request,
  with at most `MAX_BATCH_CONCURRENCY` (default 4) extractions running at once.
- A transient vision-API failure (timeout, rate limit, 5xx) is not retried
  (`max_retries=0`, see [Performance](#performance)) — it surfaces as a
  `502`/`503` on `/verify`, or a per-item `ERROR` in `/verify/batch`, rather
  than quietly succeeding on a second attempt.
- The `producer` field captures the bottler/producer/importer **name** only.
  TTB labels also require a street address for this field, but it is not
  extracted or compared — a label with a wrong or missing address does not by
  itself fail verification.

## Tradeoffs

| Decision | Reason |
| --- | --- |
| Batch cap of 10 images, 4 concurrent | Bounds per-request OpenAI usage and cost; a proof-of-concept doesn't need unbounded batches. |
| One shared fuzzy threshold (`0.90`) for all fuzzy fields, not per-field tuning | Keeps the comparison engine simple; per-field thresholds would need labeled data to tune correctly. |
| OpenAI vision model instead of a traditional OCR pipeline | Meets the 5-second budget with higher accuracy on varied label layouts, at the cost of a paid external dependency and network reliance. |
| Stateless, no database | Matches the hard "no persistence" requirement and simplifies the free-tier deploy; means no audit trail of past verifications. |
| `gpt-4.1-mini` over `gpt-4o-mini` / `gpt-4.1-nano` | See [Model](#model) — chosen for the most reliable verbatim capture of the government warning field within the latency budget. |
| OpenAI SDK's `max_retries=0` (SDK default is 2) | A retried timeout/429/5xx was the confirmed cause of the p95/max latency tail exceeding 5s (see [Performance](#performance)); trades a slightly higher outright failure rate for a bounded, predictable single-attempt latency, in line with the hard 5-second requirement. |

## Approach / Tools

Built with an AI pair-programming workflow: [Codex](https://openai.com/codex)
writing code under a **Plan / Review / Execute** cadence defined in
[AGENTS.md](AGENTS.md).

- **PLAN** — propose an approach and list files/risks; no code written.
- **REVIEW** — critique that plan against the hard requirements and edge cases,
  then finalize it.
- **EXECUTE** — implement exactly the approved plan, with tests, then report
  how to verify it.

Each phase was scoped to a single unit of work and reviewed before the next one
started, visible directly in git history as one commit per phase (`Phase 1
complete` through `Phase 7 complete`, followed by targeted fix/polish/refactor
commits). Nearly all source under `app/`, `scripts/`, and `tests/` was
AI-generated within that loop; human involvement was setting the hard
requirements up front (in `AGENTS.md`) and reviewing/approving each phase
before execution, rather than hand-writing implementation code.

## Secret Audit

Run these checks before handoff:

```powershell
rg -n --hidden --glob '!.git' --glob '!.venv' --glob '!__pycache__' --glob '!.pytest_cache' --glob '!*.pyc' "sk-(proj|live|test)-|OPENAI_API_KEY\s*=\s*sk-|-----BEGIN (RSA |OPENSSH |DSA |EC |)PRIVATE KEY-----|Bearer\s+[A-Za-z0-9._-]{20,}" .
git grep -n -I -E "sk-(proj|live|test)-|OPENAI_API_KEY[[:space:]]*=[[:space:]]*sk-|-----BEGIN (RSA |OPENSSH |DSA |EC |)PRIVATE KEY-----|Bearer[[:space:]]+[A-Za-z0-9._-]{20,}" -- .
git grep -n -I -E "sk-(proj|live|test)-|OPENAI_API_KEY[[:space:]]*=[[:space:]]*sk-|-----BEGIN (RSA |OPENSSH |DSA |EC |)PRIVATE KEY-----|Bearer[[:space:]]+[A-Za-z0-9._-]{20,}" $(git rev-list --all) -- .
```

Expected result: no matches. `rg` and `git grep` return exit code `1` when no
matches are found.
