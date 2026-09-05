from sqlalchemy.orm import Session
from app import models
from datetime import datetime
from typing import List


def get_well_by_name(db: Session, name: str):
    return db.query(models.Well).filter(models.Well.name == name).first()


def create_well(db: Session, name: str, location: str = None):
    well = models.Well(name=name, location=location)
    db.add(well)
    db.commit()
    db.refresh(well)
    return well


def get_or_create_well(db: Session, name: str, location: str = None):
    well = get_well_by_name(db, name)
    if well:
        return well
    return create_well(db, name, location)


def bulk_insert_measurements(db: Session, measurements: List[dict]):
    objs = [models.Measurement(**m) for m in measurements]
    db.bulk_save_objects(objs)
    db.commit()


def query_measurements(db: Session, well_id: int, start: datetime, end: datetime):
    return (
        db.query(models.Measurement)
        .filter(models.Measurement.well_id == well_id)
        .filter(models.Measurement.timestamp >= start)
        .filter(models.Measurement.timestamp <= end)
        .order_by(models.Measurement.timestamp)
        .all()
    )


def get_full_data(db: Session, limit: int = 10):
    return (
        db.query(models.FullData)
        .order_by(models.FullData.timestamp.desc())
        .limit(min(max(limit, 1), 1000))
        .all()
    )


def get_subset_data(db: Session, limit: int = 10):
    return (
        db.query(models.SubsetData)
        .order_by(models.SubsetData.timestamp.desc())
        .limit(min(max(limit, 1), 1000))
        .all()
    )


def get_dashboard_measurements(db: Session, start: datetime, end: datetime):
    return (
        db.query(models.FullData)
        .filter(models.FullData.timestamp >= start)
        .filter(models.FullData.timestamp <= end)
        .order_by(models.FullData.timestamp)
        .all()
    )


def get_full_data_range(db: Session):
    return (
        db.query(models.FullData)
        .order_by(models.FullData.timestamp)
        .all()
    )


def get_subset_flow(db: Session, start: datetime, end: datetime):
    return (
        db.query(models.SubsetData)
        .filter(models.SubsetData.timestamp >= start)
        .filter(models.SubsetData.timestamp <= end)
        .order_by(models.SubsetData.timestamp)
        .all()
    )
