import json
import logging
from pathlib import Path
from fastapi import FastAPI, HTTPException, status, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError

from schemas import EnergyScenario, OptimizeEnergyResponse, HealthResponse
from llm_interpreter import interpret_operator_notes
from optimizer import solve_energy_optimization
from config import settings

logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger("main")

app = FastAPI(
    title="GridWise Smart Campus Energy Optimizer API",
    description="BUP CSE Fest 2026 Hackathon Preliminary Service",
    version="1.0.0"
)

# Robust path resolution for local & Vercel serverless
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=FileResponse)
def read_root():
    """Serves the rich interactive Web UI dashboard."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return JSONResponse(content={"message": "GridWise Optimizer API Ready", "docs": "/docs"})


@app.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
def health_check():
    """Readiness endpoint for judging harness."""
    return HealthResponse(status="ok")


@app.get("/api/sample-cases")
def get_sample_cases():
    """Returns sample cases for the UI dashboard selector."""
    sample_file = BASE_DIR / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
    if sample_file.exists():
        with open(sample_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("cases", [])
    return []


@app.post(
    "/optimize-energy",
    response_model=OptimizeEnergyResponse,
    status_code=status.HTTP_200_OK
)
def optimize_energy(scenario: EnergyScenario):
    """
    Main LLM interpretation + 24-hour energy optimization endpoint.
    """
    try:
        # Step 1: LLM interpretation + deterministic guardrails
        directives = interpret_operator_notes(scenario.operator_notes)

        # Step 2: Linear Programming energy optimization
        response = solve_energy_optimization(scenario, directives)

        return response

    except Exception as e:
        logger.error(f"Internal error processing scenario {scenario.scenario_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Controlled internal server error during energy optimization."
        )


@app.exception_handler(RequestValidationError)
def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handles malformed JSON or structurally invalid requests returning HTTP 400."""
    logger.warning(f"Request validation error on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": "Malformed JSON or structurally invalid request.", "errors": str(exc)}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=False)
