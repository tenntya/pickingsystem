# ============================================================
# インポート: 必要なライブラリとモジュールをインポート
# ============================================================
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.app_core.pdf import PdfGenerationError
from src.app_core.pipeline import PipelineResult, run_pipeline
from src.app_core.printing import PrintError, list_printers, print_pdf

# ============================================================
# FastAPIアプリケーションの初期化
# ============================================================
app = FastAPI(title="PickingSystem API", version="0.1.0")


# ============================================================
# リクエストペイロード: RenderPayload - PDF生成リクエスト
# ============================================================
class RenderPayload(BaseModel):
    """
    PDF生成APIのリクエストボディ
    - shipment_path: 出荷計画Excelファイルのパス
    - master_path: マスタExcelファイルのパス
    - template_dir: HTMLテンプレートディレクトリ
    - out_dir: 出力ディレクトリ
    - bom_path: BOMファイルのパス(オプション)
    """
    shipment_path: str
    master_path: str
    template_dir: str = "src/templates"
    out_dir: str = "output"
    bom_path: str | None = None


# ============================================================
# リクエストペイロード: PrintPayload - 印刷リクエスト
# ============================================================
class PrintPayload(BaseModel):
    """
    印刷APIのリクエストボディ
    - pdf_path: 印刷するPDFファイルのパス
    - printer_name: プリンタ名(Noneの場合はデフォルトプリンタ)
    """
    pdf_path: str
    printer_name: str | None = None


# ============================================================
# エンドポイント: /health - ヘルスチェック
# ============================================================
@app.get("/health")
def health() -> dict[str, Any]:
    """
    APIサーバーの稼働状態を確認する

    Returns:
        dict: {"status": "ok"}
    """
    return {"status": "ok"}


# ============================================================
# エンドポイント: /printers - 利用可能なプリンタ一覧を取得
# ============================================================
@app.get("/printers")
def printers() -> dict[str, Any]:
    """
    システムに接続されているプリンタの一覧を取得する

    Returns:
        dict: {"printers": [プリンタ名のリスト]}
    """
    return {"printers": list_printers()}


# ============================================================
# エンドポイント: /render - ピッキングリストのPDF生成
# ============================================================
@app.post("/render")
def render(payload: RenderPayload) -> dict[str, Any]:
    """
    出荷計画とマスタからピッキングリストPDFを生成する

    Args:
        payload: RenderPayload (出荷計画、マスタ、BOMのパス等)

    Returns:
        dict: 生成結果 (行数、ページ数、ファイルパス)

    Raises:
        HTTPException:
            - 404: ファイルが見つからない場合
            - 400: データの読み込みや処理に失敗した場合
            - 500: PDF生成や予期しないエラーが発生した場合
    """
    try:
        # パイプラインを実行してPDFを生成
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

    # 生成結果を返す
    return {
        "rows": len(result.rows),
        "pages": len(result.pages),
        "html": str(result.html_path),
        "pdf": str(result.pdf_path),
    }


# ============================================================
# エンドポイント: /print - PDFファイルを印刷
# ============================================================
@app.post("/print")
def print_endpoint(payload: PrintPayload) -> dict[str, Any]:
    """
    指定されたPDFファイルを印刷する

    Args:
        payload: PrintPayload (PDFパス、プリンタ名)

    Returns:
        dict: {"status": "queued"}

    Raises:
        HTTPException:
            - 500: 印刷に失敗した場合
    """
    try:
        print_pdf(payload.pdf_path, payload.printer_name)
    except PrintError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # 予期しない例外もメッセージ付きで返す
        raise HTTPException(status_code=500, detail=f"印刷で予期せぬエラー: {exc}") from exc
    return {"status": "queued"}
