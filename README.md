# Picking System (PySide6 + FastAPI)

## セットアップ
- Python 3.11 を使用してください。
- 仮想環境を作成して有効化した後、`pip install -e .[dev]` を実行します。
  - Playwright を利用するため `playwright install chromium` を忘れずに。
  - QR コード生成には `qrcode[pil]` が必要ですが、上記コマンドに含まれています。
- wkhtmltopdf が存在しない環境では、自動的に Playwright で PDF を生成します。

## 起動方法
```bash
python src/ui_desktop/main.py
```
1. 出荷計画 Excel と 品目マスタ Excel を指定し、必要に応じて「BOM TSV (任意)」で BOM ファイルを選択。
2. `生成` ボタンで HTML/PDF と QR 画像を出力。
3. `印刷` ボタンで FastAPI 経由の印刷ジョブを送信できます（Windows PrintTo を利用）。

生成物・データ配置:
- 入力テンプレート等: `data/input/`, `data/master/`, `data/bom/`
- サンプルデータ: `data/sample/`
- PDF / HTML: `output/picking.pdf`, `output/picking.html`
- QR コード画像: `output/qr/*.png`

## テンプレート仕様
- A4 を縦 6 枠に分割（1 枠 49.5 mm）。
- プリンタ側の余白 5 mm を考慮し、枠内のパディングを段ごとに調整。
- QR コードは品目コードを内容として右端に配置します。
- 文字サイズは 11 px（ヘッダ 12 px）で、枠からはみ出さないよう余白を調整しています。

## 実装概要
- `src/app_core/pipeline.py`
  - Excel 読み込み → JOIN → マッピング → ページ分割 → HTML/PDF 生成 → QR 画像生成を一括実行。
  - 品目コードを `qrcode` で PNG に変換し `PickingRow.qr_path` に保持します。
- `src/templates/product_list_table.html`
  - Jinja2 で 6 枠をレンダリングするテンプレート。ルート直下の `product_list_table.html` と同内容です。
- `src/ui_desktop/main.py`
  - PySide6 のデスクトップ UI と FastAPI サーバを同一プロセスで起動します。

## テスト
```bash
ruff check
black --check .
mypy src
pytest
```
自動検証（PDF 生成 & 印刷 API）:
```bash
PICKING_AUTOTEST=1 python src/ui_desktop/main.py
```

## 今後の予定
- 追加機能の検討・実装（明日以降）。
- PyInstaller 等を用いた EXE 化と配布ドキュメントの整備。
  - `pyproject.toml` に PyInstaller 設定済み (`PickingSystem` エントリ)。
  - ビルド想定コマンド例: `pyinstaller --noconsole --name PickingSystem src/ui_desktop/main.py`。

詳細な進捗は `docs/DEV_STATUS.md` を参照してください。
