# ============================================================
# インポート: 必要なライブラリとモジュールをインポート
# ============================================================
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Windows印刷機能用ライブラリ (Windowsでのみ利用可能)
try:
    import win32print  # type: ignore
except ImportError:  # pragma: no cover
    win32print = None  # type: ignore


# ============================================================
# PrintError: 印刷時のエラーを表す例外クラス
# ============================================================
class PrintError(RuntimeError):
    """印刷処理で発生するエラーを表す例外"""
    pass


# ============================================================
# SumatraPDF の場所を探すヘルパー
# ------------------------------------------------------------
# 優先順位:
#  1. 環境変数 SUMATRA_PDF で明示指定
#  2. 配布物同梱 tools/SumatraPDF.exe (frozen 環境)
#  3. リポジトリ内 tools/SumatraPDF.exe (開発環境)
# ============================================================
def _resolve_sumatra_path() -> Path | None:
    candidates: list[Path] = []

    env_path = os.environ.get("SUMATRA_PDF")
    if env_path:
        candidates.append(Path(env_path))

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "tools" / "SumatraPDF.exe")
        if hasattr(sys, "_MEIPASS"):
            candidates.append(Path(sys._MEIPASS) / "tools" / "SumatraPDF.exe")
    else:
        # src/app_core から見てプロジェクトルートは2階層上
        repo_root = Path(__file__).resolve().parent.parent.parent
        candidates.append(repo_root / "tools" / "SumatraPDF.exe")

    for path in candidates:
        if path.exists():
            return path
    return None


# ============================================================
# Adobe Reader / Acrobat の場所を探すヘルパー
# ------------------------------------------------------------
# 優先順位:
#  1. 環境変数 ADOBE_READER で明示指定
#  2. よくあるインストールパスを順に探索
# ============================================================
def _resolve_adobe_reader_path() -> Path | None:
    env_path = os.environ.get("ADOBE_READER")
    if env_path:
        path = Path(env_path)
        if path.exists():
            return path

    candidates = [
        Path(r"C:\Program Files\Adobe\Acrobat DC\Acrobat\Acrobat.exe"),
        Path(r"C:\Program Files (x86)\Adobe\Acrobat DC\Acrobat\Acrobat.exe"),
        Path(r"C:\Program Files\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe"),
        Path(r"C:\Program Files (x86)\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe"),
        Path(r"C:\Program Files\Adobe\Acrobat Reader\Reader\AcroRd32.exe"),
        Path(r"C:\Program Files (x86)\Adobe\Acrobat Reader\Reader\AcroRd32.exe"),
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


# ============================================================
# list_printers: 利用可能なプリンタの一覧を取得
# ============================================================
def list_printers() -> list[str]:
    """
    システムに接続されているプリンタの一覧を取得する

    Returns:
        list[str]: プリンタ名のリスト (Windows以外または利用不可の場合は空リスト)
    """
    # win32printが利用できない場合は空リストを返す
    if win32print is None:
        return []

    # ローカルプリンタとネットワークプリンタの両方を列挙
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    printers = win32print.EnumPrinters(flags)

    # プリンタ名のみを抽出して返す
    return [printer[2] for printer in printers if printer[2]]


# ============================================================
# print_pdf: PDFファイルを印刷する
# ============================================================
def print_pdf(pdf_path: str | Path, printer_name: str | None = None) -> None:
    """
    PDFファイルをプリンタに送信して印刷する (Windows専用)

    Args:
        pdf_path: 印刷するPDFファイルのパス
        printer_name: プリンタ名 (Noneの場合はデフォルトプリンタを使用)

    Raises:
        PrintError: PDFファイルが見つからない、またはWindows以外、または印刷に失敗した場合
    """
    pdf = Path(pdf_path)

    # PDFファイルの存在確認
    if not pdf.exists():
        raise PrintError(f"PDF ファイルが見つかりません: {pdf}")

    # テストモードの場合は実際の印刷をスキップ
    if os.environ.get("PICKING_AUTOTEST") == "1":
        return

    # Windows以外のOSでは未対応
    if os.name != "nt":
        raise PrintError("Windows 以外の印刷は未対応です")

    # Adobe Reader / Acrobat が見つかればそれを優先利用
    adobe = _resolve_adobe_reader_path()
    if adobe:
        if printer_name:
            # /t PDF printer driver port  (driver/port は省略で空文字)
            command = [str(adobe), "/t", str(pdf), printer_name, "", ""]
        else:
            # 既定プリンタに出す場合
            command = [str(adobe), "/p", str(pdf)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            return
        message = result.stderr.strip() or result.stdout.strip()
        # Adobeが失敗した場合、Sumatra があればフォールバックする
        sumatra_fallback = _resolve_sumatra_path()
        if sumatra_fallback:
            command = [str(sumatra_fallback)]
            if printer_name:
                command += ["-print-to", printer_name]
            else:
                command += ["-print-to-default"]
            command.append(str(pdf))
            result = subprocess.run(command, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                return
            sumatra_msg = result.stderr.strip() or result.stdout.strip()
            raise PrintError(
                (message or "Adobe Reader 経由の印刷に失敗しました。")
                + f" (Adobe rc={result.returncode})"
                + (" / Sumatra: " + sumatra_msg if sumatra_msg else "")
            )
        raise PrintError(
            (message or "Adobe Reader 経由の印刷に失敗しました。")
            + f" (rc={result.returncode})"
        )

    # SumatraPDF があればそれを優先利用（既定アプリの関連付け不要）
    sumatra = _resolve_sumatra_path()
    if sumatra:
        command: list[str] = [str(sumatra)]
        if printer_name:
            command += ["-print-to", printer_name]
        else:
            command += ["-print-to-default"]
        command.append(str(pdf))

        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise PrintError(
                (message or "SumatraPDF 経由の印刷に失敗しました。")
                + f" (rc={result.returncode})"
            )
        return

    # PowerShellコマンドを構築
    if printer_name:
        # 指定プリンタに印刷
        command = [
            "powershell",
            "-Command",
            f'Start-Process -FilePath "{pdf}" -Verb PrintTo -ArgumentList "{printer_name}"',
        ]
    else:
        # デフォルトプリンタに印刷
        command = [
            "powershell",
            "-Command",
            f'Start-Process -FilePath "{pdf}" -Verb Print',
        ]

    # 印刷コマンドを実行
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        hint = ""
        # PDFアプリの関連付けが無い場合の典型的なエラーを補足
        if "アプリケーションが関連付けられていません" in message:
            hint = "（PDFに関連付けされた既定アプリを設定してください。例: Edge/Adobe/Acrobat Readerなど）"
        raise PrintError((message or "印刷コマンドの実行に失敗しました。") + (" " + hint if hint else ""))


# ============================================================
# エクスポート: 外部から利用可能なシンボル
# ============================================================
__all__ = ["PrintError", "list_printers", "print_pdf"]
