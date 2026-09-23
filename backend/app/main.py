"""智能电商助手 - FastAPI 后端."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import Base, engine
from .routers import dashboard, products, users, orders, meta, agent

Base.metadata.create_all(bind=engine, checkfirst=True)

app = FastAPI(title="智能电商助手 API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(meta.router)
app.include_router(dashboard.router)
app.include_router(products.router)
app.include_router(users.router)
app.include_router(orders.router)
app.include_router(agent.router)


@app.get("/")
def root():
    return {"ok": True, "service": "smart-mall-helper backend", "docs": "/docs"}
