from database import Base
from sqlalchemy import Column, DateTime, Integer, String, func


class URL(Base): # Base is from db.py which turns this ordinary-looking Python class into something SQLAlchemy knows how to map onto a real SQL table.
    __tablename__ = "urls"

    id = Column(Integer, primary_key = True, index = True) #index=True tells Postgres to build a fast lookup structure for this column
    short_code = Column(String(10), unique = True, index = True, nullable = False)
    long_url = Column(String(2048), nullable = False)
    created_at = Column(DateTime(timezone = True), server_default = func.now())
    click_count = Column(Integer, default = 0)