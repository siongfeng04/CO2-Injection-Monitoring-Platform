import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.services.fulldata import import_full_data


def main():
    db = SessionLocal()
    try:
        inserted = import_full_data(db)
        print(f"Inserted {inserted} rows into fulldata")
    finally:
        db.close()


if __name__ == "__main__":
    main()
