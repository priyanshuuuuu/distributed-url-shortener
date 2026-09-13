import random
import string
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session
from sqlalchemy import select

from database import engine, get_db, Base
from models import URL

Base.metadata.create_all(bind = engine) #creates the table urls only if it already doesnt exist

app = FastAPI(title="URL Shortener Service")

ALPHABET  = string.ascii_letters + string.digits
CODE_LENGTH = 7

def generate_short_code() -> str:
    return "".join(random.choices(ALPHABET, k = CODE_LENGTH))

class ShortenRequest(BaseModel):
    url: HttpUrl

class ShortenResponse(BaseModel):
    short_code: str
    short_url: str
    long_url: str

@app.get("/health")
def health():
    return {"status": "ok", "service": "shortener"}

@app.post("/shorten", response_model = ShortenResponse)
def shorten_url(payload: ShortenRequest, db: Session = Depends(get_db)):
    # Retry on the (very rare) chance of a random collision
    for _ in range(5):
        code = generate_short_code()
        existing = db.scalar(select(URL).where(URL.short_code == code))
        if not existing:
            break
    else:
        raise HTTPException(status_code = 500, detail = "Could not generate a unique code, try again")

    new_url = URL(short_code = code, long_url = str(payload.url))
    db.add(new_url)
    db.commit()
    db.refresh(new_url)

    return ShortenResponse(
        short_code = code,
        short_url = f"http://localhost/{code}",
        long_url = str(payload.url),
    )

@app.get("/{short_code}")
def redirect_to_long_url(short_code: str, db: Session = Depends(get_db)):
    entry = db.scalar(select(URL).where(URL.short_code == short_code ))
    if not entry:
        raise HTTPException(status_code = 404, detail = "Short URL not found")

    entry.click_count += 1
    db.commit()

    return RedirectResponse(url = entry.long_url, status_code = 307)