"""FastAPI app. Start with: uvicorn --factory caseforge.api.app:create_app"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from caseforge.api.service import DemoService, RunNotFound
from caseforge.composition import PermissionDenied


class StartRun(BaseModel):
    family: str
    seed: int = Field(ge=0, le=999)
    mode: Literal["deterministic", "single_agent", "hierarchical"] = "single_agent"
    model: str | None = None  # a model from GET /models; ignored in deterministic mode


class Answer(BaseModel):
    actor: str
    note: str | None = None


class StopRequest(BaseModel):
    actor: str
    reason: str = Field(min_length=1)


class ReleaseRequest(BaseModel):
    actor: str


def create_app(
    settings_path: str = "config/caseforge.yaml", *, service: DemoService | None = None
) -> FastAPI:
    svc = service or DemoService(settings_path)
    app = FastAPI(
        title="CaseForge operator API",
        description="Governed case handling. Demo runs replay recorded model answers at no cost.",
    )

    @app.exception_handler(RunNotFound)
    def _not_found(request: Request, exc: RunNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": f"run {exc} not found"})

    @app.exception_handler(PermissionDenied)
    def _denied(request: Request, exc: PermissionDenied) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    def _invalid(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/docs")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/cases")
    def cases() -> list[dict[str, Any]]:
        """Demo cases with recorded answers (benchmark cases without injected conditions)."""
        return svc.demo_cases()

    @app.get("/models")
    def models() -> list[str]:
        """Models with recorded demo answers."""
        return svc.demo_models()

    @app.post("/runs")
    def start_run(body: StartRun) -> dict[str, Any]:
        return svc.start_run(family=body.family, seed=body.seed, mode=body.mode, model=body.model)

    @app.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        return svc.get_run(run_id)

    @app.post("/runs/{run_id}/approve")
    def approve(run_id: str, body: Answer) -> dict[str, Any]:
        return svc.approve(run_id, actor=body.actor, note=body.note)

    @app.post("/runs/{run_id}/reject")
    def reject(run_id: str, body: Answer) -> dict[str, Any]:
        return svc.reject(run_id, actor=body.actor, note=body.note)

    @app.post("/runs/{run_id}/resume")
    def resume(run_id: str) -> dict[str, Any]:
        return svc.resume(run_id)

    @app.get("/governance")
    def governance() -> dict[str, Any]:
        return svc.governance()

    @app.post("/governance/emergency-stop")
    def engage_stop(body: StopRequest) -> dict[str, Any]:
        return svc.engage_stop(actor=body.actor, reason=body.reason)

    @app.post("/governance/emergency-stop/release")
    def release_stop(body: ReleaseRequest) -> dict[str, Any]:
        return svc.release_stop(actor=body.actor)

    @app.get("/evaluation")
    def evaluation() -> dict[str, Any]:
        return svc.evaluation()

    return app
