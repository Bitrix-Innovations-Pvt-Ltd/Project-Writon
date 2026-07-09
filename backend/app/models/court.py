from sqlalchemy import Column, Integer, String, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base

class HighCourt(Base):
    __tablename__ = "high_courts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    territory = Column(JSON)
    principal_seat_city = Column(String)

    benches = relationship("HighCourtBench", back_populates="high_court", cascade="all, delete-orphan")


class HighCourtBench(Base):
    __tablename__ = "high_court_benches"

    id = Column(Integer, primary_key=True, index=True)
    high_court_id = Column(Integer, ForeignKey("high_courts.id"), nullable=False)
    name = Column(String)
    city = Column(String)
    bench_type = Column(String) # 'principal', 'permanent', 'circuit'
    jurisdiction_districts = Column(JSON, nullable=True)

    high_court = relationship("HighCourt", back_populates="benches")
