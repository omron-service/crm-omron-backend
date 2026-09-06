from fastapi import FastAPI, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.api.v1 import mutations

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="CRM Omron Healthcare API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(mutations.router)

@app.get("/")
def root():
    return {"status": "online", "system": "CRM Omron Healthcare API"}

@app.get("/api/v1/public/track/{ticket_number}")
@limiter.limit("10/minute")
def track_ticket(request: Request, ticket_number: str):
    return {
        "ticket_number": ticket_number,
        "device_model": "Omron HEM-7120",
        "status": "Sedang Diperbaiki Teknisi",
        "current_location": "Service Center Pusat (Jakarta)"
    }