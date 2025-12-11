# ============================================================
# インポート: 必要なライブラリとモジュールをインポート
# ============================================================
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

# ============================================================
# プロジェクトルートをimportパスに追加
# ============================================================
# 確実にプロジェクトルートを import path に追加
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from src.api import server as api_server  # noqa: E402
from src.app_core.printing import list_printers  # noqa: E402

# ============================================================
# Uvicorn ログ設定: windowed 実行では sys.stdout が None になるため
# デフォルトのカラー有効フォーマッタが失敗するのを回避する
# ============================================================
LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(levelname)s %(name)s: %(message)s",
        }
    },
    "handlers": {
        "default": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "stream": "ext://sys.stderr",
        }
    },
    "loggers": {
        "uvicorn": {"level": "INFO", "handlers": ["default"], "propagate": False},
        "uvicorn.error": {"level": "INFO", "handlers": ["default"], "propagate": False},
        "uvicorn.access": {"level": "WARNING", "handlers": ["default"], "propagate": False},
    },
    "root": {
        "level": "WARNING",
        "handlers": ["default"],
    },
}

# ============================================================
# 定数: APIサーバーのURL
# ============================================================
API_URL = "http://127.0.0.1:8765"


# ============================================================
# start_api_in_thread: APIサーバーをバックグラウンドスレッドで起動
# ============================================================
def start_api_in_thread() -> uvicorn.Server:
    """
    FastAPIサーバーを別スレッドで起動する

    Returns:
        uvicorn.Server: 起動したサーバーインスタンス
    """
    config = uvicorn.Config(
        app=api_server.app,
        host="127.0.0.1",
        port=8765,
        log_level="warning",
        log_config=LOG_CONFIG,
        reload=False,
    )
    server = uvicorn.Server(config)
    # デーモンスレッドで起動(メインプロセス終了時に自動終了)
    threading.Thread(target=server.run, daemon=True).start()
    return server


# ============================================================
# wait_for_api: APIサーバーの起動を待機
# ============================================================
def wait_for_api(timeout: float = 10.0) -> bool:
    """
    APIサーバーが起動するまで待機する

    Args:
        timeout: タイムアウト時間(秒)

    Returns:
        bool: タイムアウト前に起動した場合True、それ以外False
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            # ヘルスチェックエンドポイントで起動確認
            response = requests.get(f"{API_URL}/health", timeout=1)
            if response.ok:
                return True
        except requests.RequestException:
            time.sleep(0.3)
    return False


# ============================================================
# WorkerThread: PDF生成処理を別スレッドで実行するクラス
# ============================================================
class WorkerThread(QtCore.QThread):
    """
    PDF生成APIリクエストをバックグラウンドで実行するワーカースレッド
    UIをブロックせずに処理を実行する
    """
    finishedWithResult = QtCore.Signal(dict)  # 成功時に結果辞書を送信
    failed = QtCore.Signal(str)               # 失敗時にエラーメッセージを送信

    def __init__(self, payload: dict[str, str], parent: QtCore.QObject | None = None) -> None:
        """
        Args:
            payload: /render APIに送信するペイロード
            parent: 親QObject
        """
        super().__init__(parent)
        self._payload = payload

    def run(self) -> None:
        """
        スレッドのメイン処理: /render APIを呼び出してPDFを生成
        """
        try:
            response = requests.post(f"{API_URL}/render", json=self._payload, timeout=600)
            response.raise_for_status()
            self.finishedWithResult.emit(response.json())
        except requests.HTTPError as exc:
            detail: str | None = None
            if exc.response is not None:
                try:
                    detail = exc.response.json().get("detail")
                except Exception:
                    detail = exc.response.text
            self.failed.emit(detail or str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))


# ============================================================
# PrintThread: 印刷処理を別スレッドで実行するクラス
# ============================================================
class PrintThread(QtCore.QThread):
    """
    印刷APIリクエストをバックグラウンドで実行するワーカースレッド
    UIをブロックせずに処理を実行する
    """
    finishedOk = QtCore.Signal()  # 成功時にシグナルを送信
    failed = QtCore.Signal(str)   # 失敗時にエラーメッセージを送信

    def __init__(
        self, payload: dict[str, str | None], parent: QtCore.QObject | None = None
    ) -> None:
        """
        Args:
            payload: /print APIに送信するペイロード
            parent: 親QObject
        """
        super().__init__(parent)
        self._payload = payload

    def run(self) -> None:
        """
        スレッドのメイン処理: /print APIを呼び出して印刷
        """
        try:
            response = requests.post(f"{API_URL}/print", json=self._payload, timeout=120)
            response.raise_for_status()
            self.finishedOk.emit()
        except requests.HTTPError as exc:
            detail: str | None = None
            if exc.response is not None:
                try:
                    detail = exc.response.json().get("detail")
                except Exception:
                    detail = exc.response.text
            self.failed.emit(detail or str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))


# ============================================================
# MainWindow: メインウィンドウクラス
# ============================================================
class MainWindow(QtWidgets.QMainWindow):
    """
    ピッキングシステムのGUIメインウィンドウ
    ファイル選択、PDF生成、印刷機能を提供
    """
    def __init__(self) -> None:
        """
        メインウィンドウを初期化し、UIを構築する
        """
        super().__init__()
        self.setWindowTitle("Picking System")
        self.resize(720, 480)

        # 中央ウィジェットとレイアウトの作成
        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)

        # ファイル選択フィールドの追加
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

        # ボタンレイアウトの作成
        button_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(button_layout)

        # 生成ボタン
        self.generate_btn = QtWidgets.QPushButton("生成")
        self.generate_btn.clicked.connect(self._on_generate)
        button_layout.addWidget(self.generate_btn)

        # 印刷ボタン (初期状態は無効)
        self.print_btn = QtWidgets.QPushButton("印刷")
        self.print_btn.clicked.connect(self._on_print)
        self.print_btn.setEnabled(False)
        button_layout.addWidget(self.print_btn)

        # プリンタ選択コンボボックス
        self.printer_combo = QtWidgets.QComboBox()
        button_layout.addWidget(self.printer_combo)
        self._refresh_printers()

        # ログ表示エリア
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, stretch=1)

        self.setCentralWidget(central)

        # 最後に生成されたPDFのパスを保持
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
        """
        ファイル/ディレクトリ選択フィールドをレイアウトに追加する

        Args:
            layout: 追加先のレイアウト
            label_text: ラベルテキスト
            directory: Trueの場合はディレクトリ選択、Falseの場合はファイル選択
            file_filter: ファイルフィルタ (ディレクトリ選択時は無視)
            dialog_title: ダイアログのタイトル

        Returns:
            QtWidgets.QLineEdit: パス入力用のテキストフィールド
        """
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
        """
        「生成」ボタンのクリックハンドラ
        入力ファイルの存在確認を行い、PDFのリクエストをWorkerThreadで実行
        """
        # 各フィールドからパスを取得
        shipment = self.ship_edit.text().strip()
        master = self.master_edit.text().strip()
        bom = self.bom_edit.text().strip()
        out_dir = self.output_edit.text().strip() or str(Path("output").resolve())

        # 入力ファイルの存在確認
        if not shipment or not Path(shipment).exists():
            self._log("出荷計画ファイルを指定してください。")
            return
        if not master or not Path(master).exists():
            self._log("品目マスタファイルを指定してください。")
            return
        if bom and not Path(bom).exists():
            self._log(f"BOM ファイルが見つかりません: {bom}")
            return

        # APIリクエスト用のペイロードを構築
        payload = {
            "shipment_path": shipment,
            "master_path": master,
            "template_dir": str(Path("src/templates").resolve()),
            "out_dir": out_dir,
        }
        if bom:
            payload["bom_path"] = bom

        # ワーカースレッドで生成処理を開始
        self._log("生成処理を開始します...")
        self.generate_btn.setEnabled(False)
        worker = WorkerThread(payload, self)
        worker.finishedWithResult.connect(self._on_generate_success)
        worker.failed.connect(self._on_generate_failed)
        worker.finished.connect(lambda: self.generate_btn.setEnabled(True))
        worker.start()
        self._worker = worker  # ワーカーの参照を保持

    def _on_generate_success(self, data: dict[str, object]) -> None:
        """
        PDF生成成功時のコールバック
        生成されたPDFのパスを保存し、印刷ボタンを有効化
        """
        self._last_pdf = str(data.get("pdf")) if data.get("pdf") else None
        self.print_btn.setEnabled(bool(self._last_pdf))
        self._log(
            f"PDF を生成しました。行数: {data.get('rows')} 件 / ページ数: {data.get('pages')}。 出力先: {data.get('pdf')}"
        )

    def _on_generate_failed(self, message: str) -> None:
        """
        PDF生成失敗時のコールバック
        エラーメッセージをログに表示
        """
        self._log(f"生成処理でエラー: {message}")

    def _on_print(self) -> None:
        """
        「印刷」ボタンのクリックハンドラ
        最後に生成されたPDFを指定プリンタで印刷
        """
        if not self._last_pdf:
            self._log("先に PDF を生成してください。")
            return

        # 選択されたプリンタ名を取得
        printer = self.printer_combo.currentText()
        payload = {"pdf_path": self._last_pdf, "printer_name": printer or None}

        # PrintThreadで印刷処理を開始
        self._log("印刷ジョブを送信します...")
        self.print_btn.setEnabled(False)
        worker = PrintThread(payload, self)
        worker.finishedOk.connect(self._on_print_success)
        worker.failed.connect(self._on_print_failed)
        worker.finished.connect(lambda: self.print_btn.setEnabled(True))
        worker.start()
        self._print_worker = worker  # ワーカーの参照を保持

    def _on_print_success(self) -> None:
        """
        印刷成功時のコールバック
        """
        self._log("印刷ジョブを受け付けました。プリンタ側で確認してください。")

    def _on_print_failed(self, message: str) -> None:
        """
        印刷失敗時のコールバック
        エラーメッセージをログに表示
        """
        self._log(f"印刷エラー: {message}")

    def _log(self, message: str) -> None:
        """
        ログエリアにメッセージを追加
        """
        self.log.appendPlainText(message)

    def _refresh_printers(self) -> None:
        """
        プリンタ一覧を更新してコンボボックスに設定
        """
        self.printer_combo.clear()
        printers = list_printers()
        if printers:
            self.printer_combo.addItems(printers)
        else:
            self.printer_combo.addItem("(プリンタ情報なし)")
            self.printer_combo.setEnabled(False)


# ============================================================
# run_auto_test: 自動テストモードで実行
# ============================================================
def run_auto_test() -> None:
    """
    自動テストモードでPDF生成と印刷を実行する
    環境変数からファイルパスを取得し、APIを経由して処理を実行
    """
    # 環境変数からファイルパスを取得
    shipment_env = os.environ.get("PICKING_AUTOTEST_SHIPMENT")
    master_env = os.environ.get("PICKING_AUTOTEST_MASTER")
    out_dir_env = os.environ.get("PICKING_AUTOTEST_OUT", "output/auto_test")

    # 環境変数が指定されていればそれを使用、なければサンプルデータを使用
    if shipment_env and master_env:
        shipment_path = Path(shipment_env)
        master_path = Path(master_env)
    else:
        sample_dir = Path("data") / "sample"
        shipment_path = sample_dir / "出荷計画_ダミー.xlsx"
        master_path = sample_dir / "品目マスタ_ダミー.xlsx"

    # PDF生成リクエストを送信
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

    # 印刷リクエストを送信
    printer = os.environ.get("PICKING_AUTOTEST_PRINTER")
    print_payload = {"pdf_path": data["pdf"], "printer_name": printer}
    print_response = requests.post(f"{API_URL}/print", json=print_payload, timeout=60)
    if print_response.ok:
        print("AUTO_TEST_PRINT", print_response.json())
    else:
        print("AUTO_TEST_PRINT_ERROR", print_response.text)


# ============================================================
# main: アプリケーションのエントリーポイント
# ============================================================
def main(argv: Sequence[str] | None = None) -> None:
    """
    アプリケーションのメイン処理
    - APIサーバーを起動
    - 自動テストモードまたはGUIモードで実行

    Args:
        argv: コマンドライン引数
    """
    args = list(argv or [])
    # 自動テストモードの判定
    auto_mode = os.environ.get("PICKING_AUTOTEST") == "1" or "--auto-test" in args

    # APIサーバーを起動して待機
    start_api_in_thread()
    if not wait_for_api():
        raise RuntimeError("API の起動に失敗しました。ログを確認してください。")

    # 自動テストモードの場合
    if auto_mode:
        run_auto_test()
        return

    # GUIモードの場合
    app = QtWidgets.QApplication([])
    window = MainWindow()
    window.show()
    app.exec()


# ============================================================
# スクリプトとして実行された場合のエントリーポイント
# ============================================================
if __name__ == "__main__":
    main()
