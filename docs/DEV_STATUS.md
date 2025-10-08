# 開発状況サマリ

## 現在完了している内容
- レイアウト: A4 を縦 6 枠 (各 49.5 mm) に分割し、プリンタ余白を考慮した内部パディングを設定済み。
- テンプレート: `product_list_table.html` と `src/templates/product_list_table.html` を統一、Jinja2 で 6 枠描画。
- QR コード: `src/app_core/pipeline.py` で品目コードを QR 化 (`output/qr/*.png`) し、テンプレート右端に表示。
- 文字サイズ: ラベル/値 11 px、ヘッダ 12 px に調整し、枠からはみ出さないよう余白を最適化。
- パイプライン: Excel 読込・JOIN・マッピング・ページング・HTML/PDF 生成・QR 出力まで一貫処理。
- ツールチェーン: Playwright フォールバック、印刷 API、PySide6 UI、FastAPI サーバ連携を整備。
- テスト: `ruff`, `black --check`, `mypy`, `pytest`, `PICKING_AUTOTEST=1 python src/ui_desktop/main.py` の実行確認済み。

## 依存関係
- PySide6, FastAPI, pandas, qrcode[pil], Playwright, wkhtmltopdf (任意)
- セットアップ: `pip install -e .[dev]` → `playwright install chromium`

## 生成物
- PDF / HTML: `output/picking.pdf`, `output/picking.html`
- QR 画像: `output/qr/*.png`

## 今後のタスク
- 追加機能の要件整理と実装検討（明日以降着手）。
- PyInstaller を用いた EXE 化と配布用ドキュメント整備。
  - 参考コマンド: `pyinstaller --noconsole --name PickingSystem src/ui_desktop/main.py`
- 実機プリンタでの最終動作確認（余白・切り取り線・QR スキャン）。


## 明日作業時に確認するファイル
- `README.md`: 起動手順・データ配置・EXE 化メモ
- `docs/requirements_bom.md`: BOM 連携要件とタスク
- `src/app_core/pipeline.py`: QR 生成・パイプライン本体
- `src/templates/product_list_table.html`: 6 枠テンプレート / QR 表示
- `data/` 配下: 入力データ (input/master/bom) とサンプル
- `output/qr/`: 生成済み QR の配置確認 (必要なら削除して再生成)
