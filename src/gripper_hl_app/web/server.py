"""FastAPI host for 慧灵 Z-EFG-C65 gripper."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from typing import Any, AsyncIterator, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from gripper_hl_app.paths import APP_TITLE, static_dir
from gripper_hl_app.service import GripperHlService


class ConnectBody(BaseModel):
    dry_run: Optional[bool] = None


class RateProbeBody(BaseModel):
    duration_s: float = Field(default=3.0, ge=0.5, le=30.0)


class InitBody(BaseModel):
    timeout_s: float = Field(default=15.0, ge=1.0, le=60.0)


class CommandBody(BaseModel):
    position_mm: Optional[float] = None
    position_norm: Optional[float] = None
    speed_mm_s: Optional[float] = None
    current_a: Optional[float] = None
    open: Optional[bool] = None
    close: Optional[bool] = None
    wait_ms: Optional[int] = None
    initialize: Optional[bool] = None
    action: Optional[str] = None


def _sse_pack(payload: dict[str, Any], *, event: str = "gripper") -> bytes:
    body = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return f"event: {event}\ndata: {body}\n\n".encode("utf-8")


async def _sse_stream(service: GripperHlService, *, hz: float) -> AsyncIterator[bytes]:
    interval = 1.0 / max(1.0, min(float(hz), 50.0))
    last_step: int | None = None
    last_ping = time.perf_counter()
    while True:
        st = service.status()
        step = int(st.get("seq") or 0)
        frame = {"ts": st.get("ts"), "step": step, "panel": st}
        if last_step is None or step != last_step:
            yield _sse_pack(frame)
            last_step = step
        now = time.perf_counter()
        if now - last_ping >= 15.0:
            yield b": ping\n\n"
            last_ping = now
        await asyncio.sleep(interval)


def create_app(service: GripperHlService) -> FastAPI:
    app = FastAPI(title=APP_TITLE, version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    static = static_dir()
    if static.is_dir():
        app.mount("/static", StaticFiles(directory=str(static)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> Any:
        index_path = static / "index.html"
        if index_path.is_file():
            return FileResponse(index_path)
        return HTMLResponse("<h1>gripper-hl</h1><p>static/index.html missing</p>")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "app": "gripper-hl-host"}

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return service.status()

    @app.get("/api/ports")
    def ports() -> dict[str, Any]:
        return service.list_ports()

    @app.post("/api/connect")
    def connect(body: ConnectBody | None = None) -> dict[str, Any]:
        dry = None if body is None else body.dry_run
        try:
            return service.connect(dry_run=dry)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e

    @app.post("/api/disconnect")
    def disconnect() -> dict[str, Any]:
        return service.disconnect()

    @app.post("/api/probe")
    def probe() -> dict[str, Any]:
        try:
            return service.probe()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e

    @app.post("/api/rate-probe")
    def rate_probe(body: RateProbeBody | None = None) -> dict[str, Any]:
        dur = 3.0 if body is None else float(body.duration_s)
        out = service.rate_probe(duration_s=dur)
        if not out.get("ok"):
            raise HTTPException(status_code=400, detail=out.get("error") or "rate probe failed")
        return out

    @app.post("/api/initialize")
    def initialize(body: InitBody | None = None) -> dict[str, Any]:
        timeout = 15.0 if body is None else float(body.timeout_s)
        out = service.initialize(timeout_s=timeout)
        if not out.get("ok"):
            raise HTTPException(status_code=400, detail=out.get("error") or "initialize failed")
        return out

    @app.post("/api/command")
    def command(body: CommandBody) -> dict[str, Any]:
        payload = body.model_dump(exclude_none=True)
        out = service.command(payload)
        if not out.get("ok"):
            raise HTTPException(status_code=400, detail=out.get("error") or "command failed")
        return out

    @app.post("/api/restart")
    def restart() -> dict[str, Any]:
        info = service.prepare_restart()

        def _reexec() -> None:
            time.sleep(0.35)
            exe = str(info.get("executable") or sys.executable)
            argv = list(info.get("argv") or [])
            if not argv or argv[0] != exe:
                argv = [exe] + [a for a in argv if a != exe]
            try:
                os.execv(exe, argv)
            except Exception:  # noqa: BLE001
                try:
                    import subprocess

                    subprocess.Popen(argv, cwd=os.getcwd())
                except Exception:  # noqa: BLE001
                    pass
                os._exit(1)

        threading.Thread(target=_reexec, name="gripper-hl-restart", daemon=True).start()
        return {"ok": True, "message": "backend restarting", **info}

    @app.get("/data")
    async def data(hz: float = Query(default=10.0, ge=1.0, le=50.0)) -> StreamingResponse:
        return StreamingResponse(
            _sse_stream(service, hz=hz),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


def main(service: GripperHlService, *, host: str = "127.0.0.1", port: int = 7021) -> None:
    app = create_app(service)
    uvicorn.run(app, host=host, port=int(port), log_level="info")
