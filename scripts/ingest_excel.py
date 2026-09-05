"""CLI helper to ingest an Excel file into the database."""
import sys
from app.database import SessionLocal
from app.services.excel_ingest import ingest_excel


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/ingest_excel.py path/to/file.xlsx")
        sys.exit(1)
    path = sys.argv[1]
    db = SessionLocal()
    n = ingest_excel(path, db)
    print(f"Inserted {n} measurements")


if __name__ == "__main__":
    main()
