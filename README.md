# CCS Digital Twin (FastAPI + PostgreSQL + Streamlit)

This project provides a PostgreSQL-backed CO2 injection monitoring dashboard. Excel remains an ingestion source; FastAPI reads dashboard data from PostgreSQL and Streamlit consumes the API.

Project structure

```text
app/
  api/routes.py          FastAPI routes and dashboard endpoints
  core/config.py         Environment-based configuration
  database.py            SQLAlchemy engine and session dependency
  models.py              ORM models for fulldata and subset_data
  schemas.py             Pydantic API schemas
  crud.py                Database query operations
  services/              Excel ingestion, analysis, and ML services
  frontend/streamlit_app.py
                          Streamlit dashboard client
data/                    Source Excel and SEGY files
scripts/                 Operational CLI scripts
```

Quick start

1. Copy `.env.example` to `.env` and set your PostgreSQL password:

```env
DATABASE_URL=postgresql+psycopg2://postgres:<your_password>@localhost:5432/co2_injection_db
```

The database and tables must already exist. The ORM models map to `fulldata` and `subset_data`; `wells` and `measurements` remain available for the legacy ingestion workflow.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run the API:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

4. Ingest an Excel file:

```bash
python scripts/ingest_excel.py path/to/excel.xlsx
```

API endpoints

- `GET /api/health` — verify database connectivity.
- `GET /api/data/fulldata?limit=10` — return recent rows from `fulldata`.
- `GET /api/data/subset-data?limit=10` — return recent rows from `subset_data`.
- `GET /api/dashboard/metrics?start=ISO&end=ISO` — return PostgreSQL KPIs and chart-ready time series.
- `POST /api/ingest-excel` — upload an Excel file to ingest.
- `GET /api/metrics/injection?start=ISO&end=ISO&well=NAME` — time series and KPIs.
- `GET /api/anomalies?start=ISO&end=ISO&well=NAME` — anomaly detection results.

Run the Streamlit frontend in a second terminal:

```powershell
$env:BACKEND_URL = "http://localhost:8000"
python -m streamlit run app/frontend/streamlit_app.py
```

Frontend integration

- The Streamlit app uses an absolute backend URL. Set the `BACKEND_URL` environment variable to point to the running FastAPI server (default is `http://localhost:8000`). Example (PowerShell):

    ```powershell
    $env:BACKEND_URL = "http://localhost:8000"
    python -m streamlit run app/frontend/streamlit_app.py
    ```

- Alternatively run a reverse proxy so Streamlit and FastAPI share the same origin. Example `nginx` snippet (proxy `/api/` to FastAPI running on port 8000):

    ```nginx
    location /api/ {
      proxy_pass http://127.0.0.1:8000/api/;
      proxy_set_header Host $host;
    }
    location / {
      proxy_pass http://127.0.0.1:8501/; # Streamlit
    }
    ```

- FastAPI already enables CORS for common dev workflows; if you set `BACKEND_URL` point the front-end to the backend and ensure CORS is configured in `app/main.py` for your origin.

Tips

- Add timeouts and retries for requests in the UI if you see intermittent network errors.
- If you want, I can add a small note in the README showing how to run both services together with a simple `docker-compose` proxy. 
