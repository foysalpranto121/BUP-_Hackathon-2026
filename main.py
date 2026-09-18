import logging
from fastapi import FastAPI, HTTPException, status, Request
from fastapi.responses import JSONResponse
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


@app.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
def health_check():
    """Readiness endpoint for judging harness."""
    return HealthResponse(status="ok")


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
    """Handles malformed JSON or structurally invalid requests returning HTTP 400 as per specification."""
    logger.warning(f"Request validation error on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": "Malformed JSON or structurally invalid request.", "errors": str(exc)}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=False)
