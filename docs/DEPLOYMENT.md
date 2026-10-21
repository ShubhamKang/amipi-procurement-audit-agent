# Deployment guide

**Live deployment:** https://amipi-procurement-audit-agent.onrender.com/
(Render · free tier · native Python · Blueprint `render.yaml` · `main` branch · entrypoint `app/streamlit_app.py`.)

This tool was built for a local, single-reviewer workflow. It can be deployed, but a few
production concerns must be handled first. Read this before exposing it beyond localhost.

## 1. Secrets and API keys

- **Never commit `.env`.** It is git-ignored; only `.env.example` (no secrets) is tracked.
- The `GEMINI_API_KEY` must come from the environment or the host's secret store
  (e.g. `.streamlit/secrets.toml`, which is also git-ignored). No key is hard-coded.
- If a key is ever exposed (shared in a chat, pasted in an issue, committed by accident),
  **rotate it immediately** in Google AI Studio — treat it as compromised.
- For real (non-fictional) data, use a paid Gemini tier or run with `LLM_PROVIDER=none`/`mock`;
  free-tier prompts may be used by Google to improve their products.

## 2. Authentication

The UI now supports an optional password gate:

- Set `APP_PASSWORD` in the environment or `.streamlit/secrets.toml`. When set, users must
  sign in before the audit UI is shown. When unset, the app runs open (local/dev).
- This gates **access** only; reviewer names are still self-declared. For real segregation of
  duties, place the app behind an authenticated reverse proxy / SSO and serve over HTTPS.

## 3. Review ledger persistence (important)

Human review decisions are stored in a local SQLite file (`runs/audit.db`, configurable via
`DB_PATH`). On **ephemeral** hosting (Streamlit Community Cloud, Render/Fly free tiers, most
containers) the filesystem is **wiped on restart or redeploy — all decisions would be lost.**

Mitigations, in order of preference:

1. Mount a **persistent volume** and point `DB_PATH` at it (e.g. `/data/audit.db`).
2. Use a managed database (Postgres) — the `ReviewStore` API is small and can be re-pointed.
3. If neither is available, treat the deployment as **read-only / demo** and record real
   decisions elsewhere.

The store runs in **WAL mode** with a busy timeout, so a few concurrent reviewers are handled
gracefully; it is still not intended for high-concurrency multi-tenant use.

## 4. Host options

| Host | Persistence | Notes |
|---|---|---|
| Local / on-prem VM | Disk | Simplest; set `APP_PASSWORD`, serve behind nginx + TLS |
| Docker + volume | Volume | Mount `/data`; set `DB_PATH=/data/audit.db` |
| Render (free) · **current** | **Ephemeral** | Live demo; sleeps when idle, decisions reset on redeploy. Deployed via `render.yaml` |
| Render (Starter + disk) | Volume | Always-on + durable; set `plan: starter`, add the `disk:` block, `DB_PATH=/data/audit.db` |
| Streamlit Community Cloud | **Ephemeral** | Demo only, or external DB; secrets via app settings |
| Docker + volume / Fly / Railway | Volume | Mount `/data`; set `DB_PATH=/data/audit.db` |

### Run command

```bash
pip install -r requirements.txt && pip install -e .
streamlit run app/streamlit_app.py --server.headless true --server.port $PORT
```

On Render these are defined in `render.yaml` (no manual dashboard config needed):

```bash
# build
pip install --upgrade pip && pip install -r requirements.txt && pip install -e .
# start
streamlit run app/streamlit_app.py --server.port $PORT --server.address 0.0.0.0 \
  --server.headless true --server.enableCORS false --server.enableXsrfProtection false
```

`--server.address 0.0.0.0` and the disabled CORS/XSRF flags are required so Render's
external load balancer can reach the container. Deploy with **New + → Blueprint → select
the repo → Apply**, then paste `GEMINI_API_KEY` when prompted (it is marked `sync: false`).

## 5. Pre-deploy checklist

- [ ] `GEMINI_API_KEY` set via host secrets (not in the image); old keys rotated.
- [ ] `APP_PASSWORD` set (and app served over HTTPS).
- [ ] `DB_PATH` points at a persistent volume (or deployment is demo-only).
- [ ] `LLM_PROVIDER` chosen deliberately (`gemini` for live, `mock`/`none` for offline).
- [ ] `pytest` green in CI.
- [ ] `runs/` (cache, db) not baked into the image.
