# EchoRole FastAPI boundary

Run all Python commands from the **repository root**. Existing modules remain at the root; do not run from `backend/` or add ad hoc `sys.path` mutations. Python 3.10+ is required.

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements-dev.txt
backend/.venv/Scripts/python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

On macOS/Linux use `backend/.venv/bin/python`. Runtime-only dependencies are in `requirements.txt`; `requirements-dev.txt` also enables tests.

```powershell
backend/.venv/Scripts/python -m unittest discover -s backend/tests -v
```

Implemented routes:

- `GET /api/v1/health`: process liveness only, not database/provider readiness.
- `GET /api/v1/scenarios/categories`: existing category list.
- `GET /api/v1/scenarios?category=...`: public previews; exact optional category filter. Unknown category returns an empty list.
- `GET /api/v1/scenarios/{scenario_id}`: public preview, or 404.
- OpenAPI: `/openapi.json`; interactive documentation: `/docs`.

Only `scenario_library.py` is currently reused. Explicit response fields exclude private role briefs. The API does not import `app.py`, call `init_db()`, initialize AI/RAG, open SQLite, or expose mutation endpoints. Next.js currently calls this API server-to-server, so no browser CORS policy is needed yet.

Keep credentials and local runtime directories out of Git. Existing AI/RAG configuration is deliberately not redefined. See `docs/migration-nextjs-fastapi.md` before adding stateful routes.

The application factory/router structure follows the [FastAPI first-steps documentation](https://fastapi.tiangolo.com/tutorial/first-steps/).
