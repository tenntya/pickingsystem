from __future__ import annotations

import os
import subprocess
from pathlib import Path

try:
    import win32print  # type: ignore
except ImportError:  # pragma: no cover
    win32print = None  # type: ignore


class PrintError(RuntimeError):
    pass


def list_printers() -> list[str]:
    if win32print is None:
        return []
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    printers = win32print.EnumPrinters(flags)
    return [printer[2] for printer in printers if printer[2]]


def print_pdf(pdf_path: str | Path, printer_name: str | None = None) -> None:
    pdf = Path(pdf_path)
    if not pdf.exists():
        raise PrintError(f"PDF ファイルが見つかりません: {pdf}")

    if os.environ.get("PICKING_AUTOTEST") == "1":
        return

    if os.name != "nt":
        raise PrintError("Windows 以外の印刷は未対応です")

    if printer_name:
        command = [
            "powershell",
            "-Command",
            f'Start-Process -FilePath "{pdf}" -Verb PrintTo -ArgumentList "{printer_name}"',
        ]
    else:
        command = [
            "powershell",
            "-Command",
            f'Start-Process -FilePath "{pdf}" -Verb Print',
        ]

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise PrintError(message or "印刷コマンドの実行に失敗しました。")


__all__ = ["PrintError", "list_printers", "print_pdf"]
