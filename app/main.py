import logging
import threading

from fastapi import FastAPI
from app.api import routes
from app.database import Base, SessionLocal, engine
from app.services import prediction
import app.models
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="CCS Digital Twin API")

# CORS for local frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _warm_prediction_models():
    db = SessionLocal()
    try:
        prediction.warm_up(db)
    except Exception as exc:  # warm-up is best effort; requests train on demand if it fails
        logging.getLogger(__name__).warning("Prediction warm-up failed: %s", exc)
    finally:
        db.close()


@app.on_event("startup")
def startup():
    # create tables if not exist
    Base.metadata.create_all(bind=engine)
    # Train the prediction models in the background so the first Prediction page load is fast.
    threading.Thread(target=_warm_prediction_models, daemon=True).start()


@app.get("/")
def root():
    return {"message": "CCS Digital Twin API", "docs": "/docs"}


app.include_router(routes.router, prefix="/api")
