

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from .constants import TaskName
from .env import DistributedDebugEnv
from .models import Action, Observation, StepResult


@asynccontextmanager
async def lifespan(app: FastAPI):
    env = DistributedDebugEnv()
    env.start()
    app.state.env = env
    try:
        yield
    finally:
        env.close()


app = FastAPI(title="Distributed Systems Debug Environment", version="1.0.0", lifespan=lifespan)


@app.post("/reset", response_model=Observation)
async def reset(task_name: str) -> Observation:
    try:
        task = TaskName.parse(task_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        env: DistributedDebugEnv = app.state.env
        return env.reset(task_name=task)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/step", response_model=StepResult)
async def step(action: Action) -> StepResult:
    try:
        env: DistributedDebugEnv = app.state.env
        return env.step(action)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/state")
async def state() -> dict:
    try:
        env: DistributedDebugEnv = app.state.env
        return env.state()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "1.0.0"}
