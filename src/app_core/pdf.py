# ============================================================
# インポート: 必要なライブラリとモジュールをインポート
# ============================================================
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from rich import print


# ============================================================
# PdfGenerationError: PDF生成時のエラーを表す例外クラス
# ============================================================
class PdfGenerationError(RuntimeError):
    """PDF生成処理で発生するエラーを表す例外"""
    pass


# ============================================================
# _wkhtmltopdf_exists: wkhtmltopdfコマンドが利用可能かチェック
# ============================================================
def _wkhtmltopdf_exists() -> bool:
    """
    システムにwkhtmltopdfコマンドがインストールされているか確認する

    Returns:
        bool: wkhtmltopdfが利用可能な場合True
    """
    return shutil.which("wkhtmltopdf") is not None


# ============================================================
# _generate_with_wkhtmltopdf: wkhtmltopdfでPDFを生成
# ============================================================
def _generate_with_wkhtmltopdf(html: Path, pdf: Path) -> None:
    """
    wkhtmltopdfコマンドを使用してHTMLからPDFを生成する

    Args:
        html: 入力HTMLファイルのパス
        pdf: 出力PDFファイルのパス

    Raises:
        PdfGenerationError: wkhtmltopdfの実行に失敗した場合
    """
    command = ["wkhtmltopdf", str(html), str(pdf)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise PdfGenerationError("wkhtmltopdf の実行に失敗しました:\n" + result.stderr.strip())


# ============================================================
# _generate_with_playwright: PlaywrightでPDFを生成
# ============================================================
def _generate_with_playwright(html: Path, pdf: Path) -> None:
    """
    Playwright (Chromiumブラウザ) を使用してHTMLからPDFを生成する

    Args:
        html: 入力HTMLファイルのパス
        pdf: 出力PDFファイルのパス

    Raises:
        PdfGenerationError: Playwrightの読み込みまたは実行に失敗した場合
    """
    # Playwrightライブラリのインポート
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise PdfGenerationError(
            "Playwright の読み込みに失敗しました。pip install playwright と playwright install chromium を実行してください。"
        ) from exc

    # HTMLファイルのfile://URLを生成
    file_url = html.resolve().as_uri()

    # Chromiumブラウザを起動してPDFを生成
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(file_url)
        page.pdf(
            path=str(pdf),
            format="A4",
            print_background=True,
            margin={"top": "5mm", "bottom": "5mm", "left": "5mm", "right": "5mm"},
        )
        browser.close()


# ============================================================
# generate_pdf: HTMLファイルからPDFを生成するメイン関数
# ============================================================
def generate_pdf(html_path: Path, pdf_path: Path) -> Path:
    """
    HTMLファイルからPDFを生成する
    wkhtmltopdfが利用可能ならそれを使用し、なければPlaywrightを使用する

    Args:
        html_path: 入力HTMLファイルのパス
        pdf_path: 出力PDFファイルのパス

    Returns:
        Path: 生成されたPDFファイルのパス

    Raises:
        PdfGenerationError: PDF生成に失敗した場合
    """
    # 出力ディレクトリを作成
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # wkhtmltopdfが利用可能な場合はそれを使用
        if _wkhtmltopdf_exists():
            _generate_with_wkhtmltopdf(html_path, pdf_path)
        else:
            # wkhtmltopdfがない場合はPlaywrightを使用
            print("[yellow]wkhtmltopdf が見つかりません。Playwright で PDF を生成します。[/yellow]")
            _generate_with_playwright(html_path, pdf_path)
    except PdfGenerationError:
        raise
    except Exception as exc:
        raise PdfGenerationError(f"PDF 生成処理で予期せぬエラーが発生しました: {exc}") from exc
    return pdf_path


# ============================================================
# エクスポート: 外部から利用可能なシンボル
# ============================================================
__all__ = ["PdfGenerationError", "generate_pdf"]
