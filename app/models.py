from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey, Time
from sqlalchemy.orm import relationship
from app.database import Base


class Well(Base):
    __tablename__ = "wells"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    location = Column(String, nullable=True)
    measurements = relationship("Measurement", back_populates="well")


class Measurement(Base):
    __tablename__ = "measurements"
    id = Column(Integer, primary_key=True, index=True)
    well_id = Column(Integer, ForeignKey("wells.id"), nullable=False, index=True)
    timestamp = Column(DateTime, index=True, nullable=False)
    bhp = Column(Float, nullable=True)
    bht = Column(Float, nullable=True)
    injection_rate = Column(Float, nullable=True)
    daily_injected = Column(Float, nullable=True)
    cumulative_co2 = Column(Float, nullable=True)
    annulus_pressure = Column(Float, nullable=True)
    pump_speed = Column(Float, nullable=True)

    well = relationship("Well", back_populates="measurements")


class FullData(Base):
    __tablename__ = "fulldata"

    timestamp = Column("date_time", DateTime, primary_key=True, index=True)
    injection_date = Column(Date, nullable=True)
    injection_time = Column(Time, nullable=True)
    surface_temp = Column("surface_temperature", Float, nullable=True)
    surface_psi = Column(Float, nullable=True)
    annulus_psi = Column(Float, nullable=True)
    flowrate_meter = Column(Float, nullable=True)
    pump_speed = Column(Float, nullable=True)
    calc_flow_from_pump_speed = Column(Float, nullable=True)
    flow_bpm = Column(Float, nullable=True)
    temperature_before_triplex = Column(Float, nullable=True)
    pressure_before_triplex = Column(Float, nullable=True)
    bhp = Column("bottom_hole_pressure", Float, nullable=True)
    corrected_bhp = Column("corrected_bottom_hole_pressure", Float, nullable=True)
    bht = Column("bottom_hole_temperature", Float, nullable=True)


class SubsetData(Base):
    __tablename__ = "subset_data"

    timestamp = Column("date_time", DateTime, primary_key=True, index=True)
    surface_temp = Column("surface_temperature", Float, nullable=True)
    surface_psi = Column(Float, nullable=True)
    annulus_psi = Column(Float, nullable=True)
    pump_speed = Column(Float, nullable=True)
    flow_bpm = Column(Float, nullable=True)
    flow_gpm = Column(Float, nullable=True)
