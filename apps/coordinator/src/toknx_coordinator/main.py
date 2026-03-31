from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from toknx_coordinator.api.routes.account import router as account_router
from toknx_coordinator.api.routes.auth import router as auth_router
from toknx_coordinator.api.routes.consumer import router as consumer_router
from toknx_coordinator.api.routes.nodes import router as nodes_router
from toknx_coordinator.api.routes.public import router as public_router
from toknx_coordinator.core.config import get_settings
from toknx_coordinator.db.session import SessionLocal, init_db
from toknx_coordinator.services.events import EventBus
from toknx_coordinator.services.job_router import TunnelManager

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    app.state.event_bus = EventBus()
    app.state.session_factory = SessionLocal
    app.state.tunnel_manager = TunnelManager(app.state.event_bus, SessionLocal)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(settings.dashboard_origin)],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(account_router)
app.include_router(nodes_router)
app.include_router(consumer_router)
app.include_router(public_router)


def run() -> None:
    import uvicorn

    uvicorn.run("toknx_coordinator.main:app", host="0.0.0.0", port=8000, reload=False)
