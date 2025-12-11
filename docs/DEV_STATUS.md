# 開発状況サマリ

- レイアウト: A4 を縦 6 枠で分割し、余白とパディングを調整済み。QR コードも右端に表示。
- テンプレート: `src/templates/product_list_table.html`（唯一のコピー）。枠ごとに Jinja2 で描画。
- パイプライン: Excel 読み込み → JOIN/マッピング → ページング → HTML/PDF 生成 → QR 出力まで通しで実装済み。
- API/UI: FastAPI で生成/印刷を提供し、PySide6 UI から同一プロセスで利用。
- 設定: `src/config/spec.yml` で列マッピングと BOM 設定を管理。`bom.path` は既定で未設定なので必要に応じて指定。
- チェック: `ruff`, `black --check`, `mypy`, `pytest`, `PICKING_AUTOTEST=1 python src/ui_desktop/main.py`.

## 今後のタスク案
- 追加機能検討と要件整理。
- PyInstaller での EXE 化と配布ドキュメント整備。
- 実機プリンタでの最終動作確認（余白・切り取り線・QR スキャン含む）。
