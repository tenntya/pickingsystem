from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path

import requests
import uvicorn
from PySide6 import QtCore, QtWidgets

# 確実にプロジェクトルートを import path に追加
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from src.api import server as api_server  # noqa: E402
from src.app_core.printing import list_printers  # noqa: E402

API_URL = "http://127.0.0.1:8765"


def start_api_in_thread() -> uvicorn.Server:
    config = uvicorn.Config(
        app=api_server.app,
        host="127.0.0.1",
        port=8765,
        log_level="warning",
        reload=False,
    )
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    return server


def wait_for_api(timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = requests.get(f"{API_URL}/health", timeout=1)
            if response.ok:
                return True
        except requests.RequestException:
            time.sleep(0.3)
    return False


class WorkerThread(QtCore.QThread):
    finishedWithResult = QtCore.Signal(dict)
    failed = QtCore.Signal(str)

    def __init__(self, payload: dict[str, str], parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._payload = payload

    def run(self) -> None:
        try:
            response = requests.post(f"{API_URL}/render", json=self._payload, timeout=600)
            response.raise_for_status()
            self.finishedWithResult.emit(response.json())
        except requests.HTTPError as exc:
            detail = exc.response.json().get("detail") if exc.response else str(exc)
            self.failed.emit(str(detail))
        except Exception as exc:
            self.failed.emit(str(exc))


class PrintThread(QtCore.QThread):
    finishedOk = QtCore.Signal()
    failed = QtCore.Signal(str)

    def __init__(
        self, payload: dict[str, str | None], parent: QtCore.QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._payload = payload

    def run(self) -> None:
        try:
            response = requests.post(f"{API_URL}/print", json=self._payload, timeout=120)
            response.raise_for_status()
            self.finishedOk.emit()
        except requests.HTTPError as exc:
            detail = exc.response.json().get("detail") if exc.response else str(exc)
            self.failed.emit(str(detail))
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Picking System")
        self.resize(720, 480)

        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)

        self.ship_edit = self._add_path_field(
            layout,
            "出荷計画.xlsx",
            dialog_title="出荷計画 Excel を選択",
        )
        self.master_edit = self._add_path_field(
            layout,
            "品目マスタ.xlsx",
            dialog_title="品目マスタ Excel を選択",
        )
        self.bom_edit = self._add_path_field(
            layout,
            "BOM TSV (任意)",
            file_filter="TSV/TXT (*.txt *.tsv);;すべてのファイル (*.*)",
            dialog_title="BOM ファイルを選択",
        )
        self.output_edit = self._add_path_field(layout, "出力先フォルダ", directory=True)
        self.output_edit.setText(str(Path("output").resolve()))

        button_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(button_layout)

        self.generate_btn = QtWidgets.QPushButton("生成")
        self.generate_btn.clicked.connect(self._on_generate)
        button_layout.addWidget(self.generate_btn)

        self.print_btn = QtWidgets.QPushButton("印刷")
        self.print_btn.clicked.connect(self._on_print)
        self.print_btn.setEnabled(False)
        button_layout.addWidget(self.print_btn)

        self.printer_combo = QtWidgets.QComboBox()
        button_layout.addWidget(self.printer_combo)
        self._refresh_printers()

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, stretch=1)

        self.setCentralWidget(central)

        self._last_pdf: str | None = None

    def _add_path_field(
        self,
        layout: QtWidgets.QVBoxLayout,
        label_text: str,
        directory: bool = False,
        *,
        file_filter: str = "Excel (*.xlsx)",
        dialog_title: str | None = None,
    ) -> QtWidgets.QLineEdit:
        box = QtWidgets.QHBoxLayout()
        label = QtWidgets.QLabel(label_text)
        edit = QtWidgets.QLineEdit()
        button = QtWidgets.QPushButton("選択")
        box.addWidget(label)
        box.addWidget(edit, stretch=1)
        box.addWidget(button)
        layout.addLayout(box)

        if directory:
            button.clicked.connect(lambda: self._pick_directory(edit))
        else:
            title = dialog_title or "ファイルを選択"
            button.clicked.connect(lambda: self._pick_file(edit, file_filter, title))
        return edit

    def _pick_file(
        self,
        target: QtWidgets.QLineEdit,
        file_filter: str,
        dialog_title: str,
    ) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            dialog_title,
            str(Path.cwd()),
            file_filter,
        )
        if path:
            target.setText(path)

    def _pick_directory(self, target: QtWidgets.QLineEdit) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "出力先フォルダを選択", str(Path.cwd())
        )
        if path:
            target.setText(path)

    def _on_generate(self) -> None:
        shipment = self.ship_edit.text().strip()
        master = self.master_edit.text().strip()
        bom = self.bom_edit.text().strip()
        out_dir = self.output_edit.text().strip() or str(Path("output").resolve())

        if not shipment or not Path(shipment).exists():
            self._log("出荷計画ファイルを指定してください。")
            return
        if not master or not Path(master).exists():
            self._log("品目マスタファイルを指定してください。")
            return
        if bom and not Path(bom).exists():
            self._log(f"BOM ファイルが見つかりません: {bom}")
            return

        payload = {
            "shipment_path": shipment,
            "master_path": master,
            "template_dir": str(Path("src/templates").resolve()),
            "out_dir": out_dir,
        }
        if bom:
            payload["bom_path"] = bom
        self._log("生成処理を開始します...")
        self.generate_btn.setEnabled(False)
        worker = WorkerThread(payload, self)
        worker.finishedWithResult.connect(self._on_generate_success)
        worker.failed.connect(self._on_generate_failed)
        worker.finished.connect(lambda: self.generate_btn.setEnabled(True))
        worker.start()
        self._worker = worker

    def _on_generate_success(self, data: dict[str, object]) -> None:
        self._last_pdf = str(data.get("pdf")) if data.get("pdf") else None
        self.print_btn.setEnabled(bool(self._last_pdf))
        self._log(
            f"PDF を生成しました。行数: {data.get('rows')} 件 / ページ数: {data.get('pages')}。 出力先: {data.get('pdf')}"
        )

    def _on_generate_failed(self, message: str) -> None:
        self._log(f"生成処理でエラー: {message}")

    def _on_print(self) -> None:
        if not self._last_pdf:
            self._log("先に PDF を生成してください。")
            return
        printer = self.printer_combo.currentText()
        payload = {"pdf_path": self._last_pdf, "printer_name": printer or None}
        self._log("印刷ジョブを送信します...")
        self.print_btn.setEnabled(False)
        worker = PrintThread(payload, self)
        worker.finishedOk.connect(self._on_print_success)
        worker.failed.connect(self._on_print_failed)
        worker.finished.connect(lambda: self.print_btn.setEnabled(True))
        worker.start()
        self._print_worker = worker

    def _on_print_success(self) -> None:
        self._log("印刷ジョブを受け付けました。プリンタ側で確認してください。")

    def _on_print_failed(self, message: str) -> None:
        self._log(f"印刷エラー: {message}")

    def _log(self, message: str) -> None:
        self.log.appendPlainText(message)

    def _refresh_printers(self) -> None:
        self.printer_combo.clear()
        printers = list_printers()
        if printers:
            self.printer_combo.addItems(printers)
        else:
            self.printer_combo.addItem("(プリンタ情報なし)")
            self.printer_combo.setEnabled(False)


def run_auto_test() -> None:
    shipment_env = os.environ.get("PICKING_AUTOTEST_SHIPMENT")
    master_env = os.environ.get("PICKING_AUTOTEST_MASTER")
    out_dir_env = os.environ.get("PICKING_AUTOTEST_OUT", "output/auto_test")
    if shipment_env and master_env:
        shipment_path = Path(shipment_env)
        master_path = Path(master_env)
    else:
        sample_dir = Path("sample_data")
        shipment_path = sample_dir / "出荷計画_ダミー.xlsx"
        master_path = sample_dir / "品目マスタ_ダミー.xlsx"
    payload = {
        "shipment_path": str(shipment_path.resolve()),
        "master_path": str(master_path.resolve()),
        "template_dir": str(Path("src/templates").resolve()),
        "out_dir": str(Path(out_dir_env).resolve()),
    }
    response = requests.post(f"{API_URL}/render", json=payload, timeout=600)
    response.raise_for_status()
    data = response.json()
    print("AUTO_TEST_RESULT", data)

    printer = os.environ.get("PICKING_AUTOTEST_PRINTER")
    print_payload = {"pdf_path": data["pdf"], "printer_name": printer}
    print_response = requests.post(f"{API_URL}/print", json=print_payload, timeout=60)
    if print_response.ok:
        print("AUTO_TEST_PRINT", print_response.json())
    else:
        print("AUTO_TEST_PRINT_ERROR", print_response.text)


def main(argv: Sequence[str] | None = None) -> None:
    args = list(argv or [])
    auto_mode = os.environ.get("PICKING_AUTOTEST") == "1" or "--auto-test" in args

    start_api_in_thread()
    if not wait_for_api():
        raise RuntimeError("API の起動に失敗しました。ログを確認してください。")

    if auto_mode:
        run_auto_test()
        return

    app = QtWidgets.QApplication([])
    window = MainWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
