from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from rich import print


class PdfGenerationError(RuntimeError):
    pass


def _wkhtmltopdf_exists() -> bool:
    return shutil.which("wkhtmltopdf") is not None


def _generate_with_wkhtmltopdf(html: Path, pdf: Path) -> None:
    command = ["wkhtmltopdf", str(html), str(pdf)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise PdfGenerationError("wkhtmltopdf の実行に失敗しました:\n" + result.stderr.strip())


def _generate_with_playwright(html: Path, pdf: Path) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise PdfGenerationError(
            "Playwright の読み込みに失敗しました。pip install playwright と playwright install chromium を実行してください。"
        ) from exc

    file_url = html.resolve().as_uri()
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


def generate_pdf(html_path: Path, pdf_path: Path) -> Path:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if _wkhtmltopdf_exists():
            _generate_with_wkhtmltopdf(html_path, pdf_path)
        else:
            print("[yellow]wkhtmltopdf が見つかりません。Playwright で PDF を生成します。[/yellow]")
            _generate_with_playwright(html_path, pdf_path)
    except PdfGenerationError:
        raise
    except Exception as exc:
        raise PdfGenerationError(f"PDF 生成処理で予期せぬエラーが発生しました: {exc}") from exc
    return pdf_path


__all__ = ["PdfGenerationError", "generate_pdf"]
