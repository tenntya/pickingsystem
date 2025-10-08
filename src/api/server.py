from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.app_core.pdf import PdfGenerationError
from src.app_core.pipeline import PipelineResult, run_pipeline
from src.app_core.printing import PrintError, list_printers, print_pdf

app = FastAPI(title="PickingSystem API", version="0.1.0")


class RenderPayload(BaseModel):
    shipment_path: str
    master_path: str
    template_dir: str = "src/templates"
    out_dir: str = "output"
    bom_path: str | None = None


class PrintPayload(BaseModel):
    pdf_path: str
    printer_name: str | None = None


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok"}


@app.get("/printers")
def printers() -> dict[str, Any]:
    return {"printers": list_printers()}


@app.post("/render")
def render(payload: RenderPayload) -> dict[str, Any]:
    try:
        result: PipelineResult = run_pipeline(
            shipment_path=payload.shipment_path,
            master_path=payload.master_path,
            template_dir=payload.template_dir,
            out_dir=payload.out_dir,
            bom_path=payload.bom_path,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"ファイルが見つかりません: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PdfGenerationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"予期しないエラー: {exc}") from exc

    return {
        "rows": len(result.rows),
        "pages": len(result.pages),
        "html": str(result.html_path),
        "pdf": str(result.pdf_path),
    }


@app.post("/print")
def print_endpoint(payload: PrintPayload) -> dict[str, Any]:
    try:
        print_pdf(payload.pdf_path, payload.printer_name)
    except PrintError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "queued"}
