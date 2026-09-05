from fastapi import FastAPI
from app.api import routes
from app.database import Base, engine
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


@app.on_event("startup")
def startup():
    # create tables if not exist
    Base.metadata.create_all(bind=engine)


@app.get("/")
def root():
    return {"message": "CCS Digital Twin API", "docs": "/docs"}


app.include_router(routes.router, prefix="/api")
