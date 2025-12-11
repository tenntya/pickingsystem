# Picking System (PySide6 + FastAPI)

## セットアップ
- Python 3.11 で動作を確認しています。
- 仮想環境を有効化したうえで `pip install -e .[dev]` を実行してください。
- Playwright を利用するため `playwright install chromium` を忘れずに。
- wkhtmltopdf が無い場合は自動的に Playwright が PDF 生成を引き受けます。

## 使い方
```bash
python src/ui_desktop/main.py
```
1. 出荷計画 Excel と 品目マスタ Excel を指定し、必要に応じて BOM TSV を選択します。
2. 「生成」で HTML/PDF と QR 画像を出力します。
3. 「印刷」で FastAPI 経由の印刷ジョブを送信します (Windows PrintTo を利用)。

生成物と配置:
- PDF / HTML: `output/picking.pdf`, `output/picking.html`
- QR コード: `output/qr/*.png`
- テンプレート: `src/templates/product_list_table.html`（この1か所のみ）

主な構成:
- `src/app_core/pipeline.py`: Excel 読み込み・JOIN・マッピング・ページング・HTML/PDF 生成・QR 出力を一括実行。
- `src/config/spec.yml`: 列マッピングと BOM 設定。`bom.path` は既定で `null` なので必要に応じて設定してください。
- `src/api/server.py`: FastAPI エンドポイント (生成・印刷)。
- `src/ui_desktop/main.py`: PySide6 デスクトップ UI と FastAPI を同一プロセスで起動。

## チェック
```bash
ruff check
black --check .
mypy src
pytest
```
自動検証モード:
```bash
PICKING_AUTOTEST=1 python src/ui_desktop/main.py
```
