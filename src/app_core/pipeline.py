# ============================================================
# インポート: 必要なライブラリとモジュールをインポート
# ============================================================
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd
import qrcode
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import BomConfig, LoadedConfig, PipelineConfig, load_config
from .pdf import generate_pdf


# ============================================================
# _slugify: 文字列をファイル名に適した形式に変換
# ============================================================
def _slugify(value: str) -> str:
    """
    文字列をファイル名として安全な形式に変換する
    - NFKC正規化を適用
    - スラッシュをハイフンに置換
    - 英数字・アンダースコア・ハイフン以外をアンダースコアに変換
    """
    value = unicodedata.normalize("NFKC", value)
    value = value.strip().replace("/", "-")
    value = re.sub(r"[^0-9A-Za-z_-]+", "_", value)
    return value or "qr"


# ============================================================
# PickingRow: ピッキングリストの1行を表すデータクラス
# ============================================================
@dataclass(slots=True)
class PickingRow:
    """
    ピッキングリストの1行分のデータを保持する
    親部品と子部品(BOM展開された部品)の両方を表現できる
    """
    shipDate: str           # 出荷日
    clientCode: str         # 顧客コード
    notice: str             # 備考・注意事項
    productCode: str        # 品目コード
    location: str           # 保管場所
    quantity: str           # 数量
    itemType: str           # 品目タイプ
    productName: str        # 品目名
    orderNumber: str        # 注文番号
    no: str                 # 行番号(親は"1", "2"、子は"1-1", "1-2"など)
    sequence: int           # 全体での通し番号
    qr_path: str = ""       # QRコード画像のパス
    is_child: bool = False  # 子部品かどうか
    parent_no: str | None = None      # 親の行番号
    child_index: int | None = None    # 子部品の順序
    quantity_note: str = ""           # 数量の計算式メモ
    unit: str = ""                    # 単位
    parent_total: int = 0             # 親部品の総数


# ============================================================
# _clean_column: 列名をクリーンアップ(正規化・空白除去)
# ============================================================
def _clean_column(name: str) -> str:
    """
    列名をクリーンアップして統一する
    - NFKC正規化を適用
    - すべての空白文字を除去
    """
    normalized = unicodedata.normalize("NFKC", str(name).strip())
    return re.sub(r"\s+", "", normalized)


# ============================================================
# _expected_columns: 設定から期待される列名の集合を作成
# ============================================================
def _expected_columns(config: PipelineConfig) -> set[str]:
    """
    設定ファイルから期待される列名の集合を生成する
    join_keyとmappingで指定されたすべての列名をクリーンアップして集める
    """
    expected: set[str] = {_clean_column(config.join_key)}
    for values in config.mapping.values():
        for raw_key in values:
            key = _clean_column(raw_key)
            if key:
                expected.add(key)
    return expected


# ============================================================
# load_excel: Excelファイルを読み込む
# ============================================================
def load_excel(path: str, *, config: PipelineConfig | None = None) -> pd.DataFrame:
    """
    Excelファイルを読み込んでDataFrameを返す
    ヘッダー行の位置を自動的に検出する機能付き

    Args:
        path: Excelファイルのパス
        config: パイプライン設定 (指定時はヘッダー行を自動検出)

    Returns:
        pd.DataFrame: 読み込んだデータ

    Raises:
        ValueError: ファイルの読み込みまたは必要な列が見つからない場合
    """
    # 設定がない場合は0行目をヘッダーとして試す、ある場合は0-4行目を試す
    headers_to_try = [0] if config is None else [0, 1, 2, 3, 4]
    expected = _expected_columns(config) if config else set()
    last_df: pd.DataFrame | None = None

    # ヘッダー行の候補を順に試す
    for header in headers_to_try:
        df = pd.read_excel(path, header=header, dtype=str)
        # 列名をクリーンアップ
        df.columns = ["" if pd.isna(col) else _clean_column(col) for col in df.columns]
        last_df = df

        # 設定がない場合は最初に読めたものを返す
        if config is None:
            return df.fillna("")

        # join_keyまたは期待される列が含まれているかチェック
        join_key = _clean_column(config.join_key)
        if join_key in df.columns or expected.intersection(df.columns):
            # Unnamed列を除外してフィルタリング
            filtered = [col for col in df.columns if col and not col.startswith("Unnamed")]
            return df.loc[:, filtered].fillna("")

    # すべての試行が失敗した場合のエラー処理
    if config is None:
        if last_df is not None:
            return last_df.fillna("")
        raise ValueError(f"Excel の読み込みに失敗しました: {path}")

    if last_df is not None:
        raise ValueError(f"必要な列が見つかりません: {config.join_key}")
    raise ValueError(f"Excel の読み込みに失敗しました: {path}")


# ============================================================
# normalize_value: 値を文字列に正規化
# ============================================================
def normalize_value(value: Any) -> str:
    """
    任意の値を文字列に正規化する
    - None → 空文字列
    - 整数値のfloat → 整数文字列
    - その他のfloat → 小数点以下の不要な0を削除
    - その他 → 文字列に変換
    """
    if value is None:
        return ""
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


# ============================================================
# coalesce: 候補列から最初の非空値を取得
# ============================================================
def coalesce(row: dict[str, Any], candidates: Sequence[str]) -> str:
    """
    候補列のリストから最初に見つかった非空の値を返す
    すべて空またはNoneの場合は空文字列を返す
    """
    for key in candidates:
        if key in row and row[key] not in (None, ""):
            return normalize_value(row[key])
    return ""


# ============================================================
# resolve_field: 設定に基づいてフィールド値を解決
# ============================================================
def resolve_field(config: PipelineConfig, row: dict[str, Any], field: str) -> str:
    """
    設定のmappingに基づいて、行データからフィールドの値を解決する
    候補列名に "_in" と "_mst" のサフィックスを追加して検索
    """
    candidates: list[str] = []
    for base in config.mapping.get(field, []):
        cleaned = _clean_column(base)
        candidates.append(cleaned)
        candidates.append(f"{cleaned}_in")
        candidates.append(f"{cleaned}_mst")
    return coalesce(row, candidates)


# ============================================================
# _normalize_code_value: コード値を正規化(クリーンアップ)
# ============================================================
def _normalize_code_value(value: str) -> str:
    """
    コード値を正規化してキーとして使用できる形にする
    normalize_valueとclean_columnを組み合わせて適用
    """
    return _clean_column(normalize_value(value))


# ============================================================
# _parse_decimal: 文字列を10進数(Decimal)に変換
# ============================================================
def _parse_decimal(value: str) -> Decimal | None:
    """
    文字列を Decimal 型に変換する
    カンマを除去し、変換に失敗した場合は正規表現で数値を抽出して再試行

    Returns:
        Decimal | None: 変換成功時はDecimal、失敗時はNone
    """
    raw = normalize_value(value)
    text = raw.replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        import re
        # 数値パターンを抽出して変換を試行
        matches = re.findall(r"[-+]?\d+(?:\.\d+)?", text)
        for candidate in reversed(matches):
            try:
                return Decimal(candidate)
            except InvalidOperation:
                continue
        return None


# ============================================================
# _format_decimal: Decimalを文字列にフォーマット
# ============================================================
def _format_decimal(value: Decimal) -> str:
    """
    Decimal値を文字列にフォーマットする
    不要な末尾の0と小数点を除去
    """
    normalized = value.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


# ============================================================
# _display_quantity: 数量を表示用にフォーマット
# ============================================================
def _display_quantity(value: str) -> str:
    """
    数量値を表示用にフォーマットする
    Decimal変換可能な場合は整形し、不可能な場合はそのまま返す
    """
    decimal_value = _parse_decimal(value)
    if decimal_value is None:
        return normalize_value(value)
    return _format_decimal(decimal_value)


# ============================================================
# _build_master_lookup: マスタデータから検索用辞書を構築
# ============================================================
def _build_master_lookup(master: pd.DataFrame, join_key: str) -> dict[str, dict[str, str]]:
    """
    マスタデータから品目コードをキーとした検索用辞書を構築する
    各列の値は元の列名と "_mst" サフィックス付きの両方でアクセス可能にする

    Args:
        master: マスタデータのDataFrame
        join_key: 結合キーとなる列名

    Returns:
        dict[str, dict[str, str]]: 品目コードをキーとした辞書
    """
    lookup: dict[str, dict[str, str]] = {}
    if master.empty:
        return lookup

    cleaned_join_key = _clean_column(join_key)
    filled = master.fillna("")

    # 各行を辞書に変換
    for _, rec in filled.iterrows():
        row_dict: dict[str, str] = {}
        for col in filled.columns:
            value = normalize_value(rec[col])
            row_dict[col] = value
            row_dict[f"{col}_mst"] = value  # "_mst"サフィックス付きでも参照可能に
        key = _normalize_code_value(row_dict.get(cleaned_join_key, ""))
        if key:
            lookup[key] = row_dict

    return lookup


# ============================================================
# _compute_child_quantity: 子部品の数量を計算
# ============================================================
def _compute_child_quantity(parent_qty: str, base_qty: str) -> tuple[str, str]:
    """
    親部品の数量と基準数量から子部品の必要数量を計算する

    Args:
        parent_qty: 親部品の数量
        base_qty: BOMでの基準数量

    Returns:
        tuple[str, str]: (計算後の数量, 計算式メモ)
    """
    parent_dec = _parse_decimal(parent_qty)
    base_dec = _parse_decimal(base_qty)

    # 両方の値が数値の場合は乗算
    if parent_dec is not None and base_dec is not None:
        result = parent_dec * base_dec
        return _format_decimal(result), f"{_format_decimal(parent_dec)} × {_format_decimal(base_dec)}"

    # 基準数量のみが数値の場合はそのまま使用
    if base_dec is not None:
        return _format_decimal(base_dec), ""

    # 両方とも数値でない場合は文字列をそのまま返す
    return normalize_value(base_qty), ""


# ============================================================
# load_bom: BOMファイル(TSV)を読み込む
# ============================================================
def load_bom(path: str | Path) -> pd.DataFrame:
    """
    BOM(部品表)ファイルをタブ区切りCSVとして読み込む

    Args:
        path: BOMファイルのパス

    Returns:
        pd.DataFrame: 読み込んだBOMデータ
    """
    bom_path = Path(path)
    df = pd.read_csv(bom_path, sep="	", dtype=str)  # タブ区切り
    df = df.fillna("")
    df.columns = [_clean_column(col) for col in df.columns]
    return df


# ============================================================
# BomLookup: BOM検索用の型エイリアス
# ============================================================
BomLookup = dict[str, list[dict[str, str]]]


# ============================================================
# build_bom_lookup: BOMデータから親コードをキーとした検索辞書を構築
# ============================================================
def build_bom_lookup(data: pd.DataFrame, config: BomConfig) -> BomLookup:
    """
    BOMデータから親部品コードをキーとした子部品リストの辞書を構築する
    子部品はsequence列の値でソートされる

    Args:
        data: BOMデータのDataFrame
        config: BOM設定

    Returns:
        BomLookup: 親コードをキーとした子部品リストの辞書
    """
    if data.empty:
        return {}

    # 設定から列名を取得してクリーンアップ
    parent_col = _clean_column(config.parent_key)
    child_code_col = _clean_column(config.child_key)
    child_name_col = _clean_column(config.child_name)
    quantity_col = _clean_column(config.quantity)
    sequence_col = _clean_column(config.sequence) if config.sequence else None
    unit_col = _clean_column(config.unit) if config.unit else None
    type_col = _clean_column(config.child_type) if config.child_type else None

    lookup: BomLookup = defaultdict(list)

    # 各行を処理して親コードごとに子部品をグループ化
    for _, record in data.iterrows():
        parent_code = _normalize_code_value(record.get(parent_col, ""))
        child_code = normalize_value(record.get(child_code_col, ""))
        if not parent_code or not child_code:
            continue
        entry = {
            "productCode": child_code,
            "productName": normalize_value(record.get(child_name_col, "")),
            "baseQuantity": normalize_value(record.get(quantity_col, "")),
            "unit": normalize_value(record.get(unit_col, "")) if unit_col else "",
            "itemType": normalize_value(record.get(type_col, "")) if type_col else "",
            "sequence": normalize_value(record.get(sequence_col, "")) if sequence_col else "",
        }
        lookup[parent_code].append(entry)

    # 子部品をsequence列の値でソート
    def _sort_key(entry: dict[str, str]) -> tuple[int, Any]:
        raw = entry.get("sequence", "")
        try:
            return (0, int(raw))  # 数値として解釈可能な場合
        except (TypeError, ValueError):
            return (1, raw)  # 文字列として扱う

    for entries in lookup.values():
        entries.sort(key=_sort_key)

    return lookup


# ============================================================
# フィルタリング用定数: F列から除外するキーワード
# ============================================================
EXCLUDE_F_COLUMN_KEYWORDS = ("モーター組立品", "減速機組立品", "ﾓｰﾀｰ組立品")


# ============================================================
# filter_shipment_rows: 出荷計画から特定キーワードを含む行を除外
# ============================================================
def filter_shipment_rows(shipment: pd.DataFrame) -> pd.DataFrame:
    """
    出荷計画のF列(6列目)に除外キーワードが含まれる行を削除する
    EXCLUDE_F_COLUMN_KEYWORDSで定義されたキーワードが対象

    Args:
        shipment: 出荷計画のDataFrame

    Returns:
        pd.DataFrame: フィルタリング後のDataFrame
    """
    if shipment.empty:
        return shipment
    column_index = 5  # F列 (0始まりで5番目)
    if shipment.shape[1] <= column_index:
        return shipment

    # 除外キーワードの正規表現パターンを作成
    pattern = "|".join(re.escape(unicodedata.normalize("NFKC", keyword)) for keyword in EXCLUDE_F_COLUMN_KEYWORDS)
    # F列の値を正規化してチェック
    target = shipment.iloc[:, column_index].astype(str).map(lambda x: unicodedata.normalize("NFKC", x).strip())
    mask = ~target.str.contains(pattern, na=False, regex=True)
    return shipment.loc[mask].reset_index(drop=True)


# ============================================================
# sort_shipment_rows: 出荷計画を12列目・13列目でソート
# ============================================================
def sort_shipment_rows(shipment: pd.DataFrame) -> pd.DataFrame:
    """
    出荷計画を12列目(インデックス11)、次に13列目(インデックス12)でソートする
    処理前のデータ整列により、ピッキングリストの順序を最適化

    Args:
        shipment: 出荷計画のDataFrame

    Returns:
        pd.DataFrame: ソート後のDataFrame
    """
    if shipment.empty:
        return shipment
    first_idx, second_idx = 11, 12  # 12列目と13列目(0始まり)
    if shipment.shape[1] <= first_idx:
        return shipment

    # ソートキーの列名を取得
    columns = list(shipment.columns)
    sort_keys = [columns[first_idx]]
    if len(columns) > second_idx:
        sort_keys.append(columns[second_idx])

    # マージソートで安定ソート
    return shipment.sort_values(by=sort_keys, kind="mergesort").reset_index(drop=True)


# ============================================================
# join_and_map: 出荷計画とマスタを結合してピッキング行リストを生成
# ============================================================
def join_and_map(
    shipment: pd.DataFrame,
    master: pd.DataFrame,
    config: PipelineConfig,
    *,
    bom_lookup: BomLookup | None = None,
) -> list[PickingRow]:
    """
    出荷計画とマスタデータを結合し、BOM展開を行ってピッキング行リストを生成する
    親部品に対してBOMが存在する場合、子部品を再帰的に展開する

    Args:
        shipment: 出荷計画のDataFrame
        master: マスタデータのDataFrame
        config: パイプライン設定
        bom_lookup: BOM検索辞書(オプション)

    Returns:
        list[PickingRow]: ピッキング行のリスト
    """
    # 結合キーをクリーンアップしてマスタ検索辞書を構築
    join_key = _clean_column(config.join_key)
    master_lookup = _build_master_lookup(master, join_key)

    # 出荷計画とマスタをleft joinで結合
    merged = shipment.merge(
        master,
        how="left",
        left_on=join_key,
        right_on=join_key,
        suffixes=("_in", "_mst"),  # 重複列名に接尾辞を追加
    )

    # BOM検索辞書の準備
    lookup = bom_lookup or {}
    rows: list[PickingRow] = []
    parent_index = 1          # 親部品の番号(1, 2, 3...)
    sequence_counter = 1      # 全体通し番号

    # マスタのK列(11列目)をロケーション列として使用
    master_location_column: str | None = None
    if len(master.columns) > 10:
        column_name = master.columns[10]
        if column_name:
            master_location_column = _clean_column(str(column_name))

    # ============================================================
    # 内部関数: _append_children - 子部品を再帰的に追加
    # ============================================================
    def _append_children(
        parent_row: PickingRow,
        parent_quantity_value: str,
        index_prefix: list[str],
        parent_code_key: str,
        path: tuple[str, ...],
    ) -> None:
        """
        親部品に対してBOMで定義された子部品を再帰的に追加する
        循環参照を防ぐためにpathで既訪問の品目コードを追跡

        Args:
            parent_row: 親部品の行
            parent_quantity_value: 親部品の数量
            index_prefix: 番号のプレフィックス (例: ["1", "2"] → "1-2-x")
            parent_code_key: 親部品のコード(正規化済み)
            path: 循環参照防止用の訪問済みコードのパス
        """
        nonlocal sequence_counter

        # 親コードが空の場合は処理しない
        if not parent_code_key:
            return

        # BOM検索辞書から子部品リストを取得
        children = lookup.get(parent_code_key, [])
        if not children:
            return

        # 各子部品を処理
        for child_idx, child in enumerate(children, start=1):
            # 子部品コードの取得と正規化
            child_code_raw = normalize_value(child.get("productCode", ""))
            child_code_key = _normalize_code_value(child_code_raw)

            # 子部品のマスタ情報を取得
            child_master = master_lookup.get(child_code_key, {})

            # 子部品名: BOM → マスタ → コードの順で優先
            child_product_name = (
                child.get("productName", "")
                or resolve_field(config, child_master, "productName")
                or child_code_raw
            )

            # 子部品タイプ: BOM → マスタ → 親のタイプの順で優先
            child_item_type = (
                child.get("itemType", "")
                or resolve_field(config, child_master, "itemType")
                or parent_row.itemType
            )

            # 子部品のロケーション: マスタから取得
            child_location = resolve_field(config, child_master, "location")
            if not child_location and master_location_column:
                child_location = normalize_value(
                    child_master.get(master_location_column, "")
                    or child_master.get(f"{master_location_column}_mst", "")
                )

            # 備考: マスタ → 親の備考の順で優先
            child_notice = resolve_field(config, child_master, "notice") or parent_row.notice

            # 子部品の数量を計算 (親数量 × BOM基準数量)
            result_qty, note = _compute_child_quantity(
                parent_quantity_value, child.get("baseQuantity", "")
            )

            # 子部品の行番号を生成 (例: "1-1", "1-2-1")
            child_no = "-".join(index_prefix + [str(child_idx)])

            # 子部品のPickingRowを作成
            child_row = PickingRow(
                shipDate=parent_row.shipDate,
                clientCode=parent_row.clientCode,
                notice=child_notice,
                productCode=child_code_raw,
                location=child_location,
                quantity=_display_quantity(result_qty),
                itemType=child_item_type,
                productName=child_product_name,
                orderNumber=parent_row.orderNumber,
                no=child_no,
                sequence=sequence_counter,
                qr_path="",
                is_child=True,
                parent_no=parent_row.no,
                child_index=child_idx,
                quantity_note=note,
                unit=child.get("unit", ""),
            )
            rows.append(child_row)
            sequence_counter += 1

            # 子部品がさらに子を持つ場合、再帰的に追加 (循環参照を防ぐ)
            if child_code_key and child_code_key not in path:
                _append_children(
                    child_row,
                    child_row.quantity,
                    index_prefix + [str(child_idx)],
                    child_code_key,
                    path + (child_code_key,),  # 訪問済みパスに追加
                )

    # 結合済みデータの各行を処理して親部品の行を作成
    for _, record in merged.fillna("").iterrows():
        data = record.to_dict()

        # 品目コードの取得: productCodeフィールド → join_keyの順で優先
        product_code = resolve_field(config, data, "productCode") or normalize_value(data.get(join_key))

        # 親部品の数量を取得してフォーマット
        raw_parent_quantity = resolve_field(config, data, "quantity")
        parent_quantity = _display_quantity(raw_parent_quantity)

        # 親部品のロケーション: locationフィールド → マスタK列の順で優先
        parent_location = resolve_field(config, data, "location")
        if not parent_location and master_location_column:
            parent_location = normalize_value(
                data.get(master_location_column, "")
                or data.get(f"{master_location_column}_mst", "")
            )

        # 親部品のPickingRowを作成
        parent_row = PickingRow(
            shipDate=resolve_field(config, data, "shipDate"),
            clientCode=resolve_field(config, data, "clientCode"),
            notice=resolve_field(config, data, "notice"),
            productCode=product_code,
            location=parent_location,
            quantity=parent_quantity,
            itemType=resolve_field(config, data, "itemType"),
            productName=resolve_field(config, data, "productName"),
            orderNumber=resolve_field(config, data, "orderNumber"),
            no=str(parent_index),  # 行番号: "1", "2", "3"...
            sequence=sequence_counter,
        )
        rows.append(parent_row)
        sequence_counter += 1

        # 親部品にBOMが存在する場合、子部品を再帰的に追加
        parent_code_key = _normalize_code_value(parent_row.productCode)
        if parent_code_key:
            _append_children(
                parent_row,
                parent_row.quantity,
                parent_row.no.split("-"),  # 番号プレフィックスのリスト
                parent_code_key,
                (parent_code_key,),  # 訪問済みパス(循環参照防止)
            )

        parent_index += 1

    # すべての行に親部品の総数を設定
    total_parents = parent_index - 1
    for row in rows:
        row.parent_total = total_parents

    return rows

# ============================================================
# paginate: ピッキング行をページごとに分割
# ============================================================
def paginate(rows: Sequence[PickingRow], per_page: int) -> list[list[PickingRow]]:
    """
    ピッキング行のリストをページごとに分割する

    Args:
        rows: ピッキング行のリスト
        per_page: 1ページあたりの行数

    Returns:
        list[list[PickingRow]]: ページごとに分割された行のリスト
    """
    pages: list[list[PickingRow]] = []
    for idx in range(0, len(rows), per_page):
        pages.append(list(rows[idx : idx + per_page]))
    return pages


# ============================================================
# render_html: Jinja2テンプレートを使用してHTMLを生成
# ============================================================
def render_html(
    pages: Sequence[Sequence[PickingRow]],
    template_dir: str | Path,
    output_path: str | Path,
) -> Path:
    """
    ピッキングリストのHTMLを生成する

    Args:
        pages: ページごとに分割されたピッキング行
        template_dir: テンプレートディレクトリ
        output_path: 出力HTMLファイルのパス

    Returns:
        Path: 生成されたHTMLファイルのパス
    """
    # Jinja2環境の構築
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("product_list_table.html")

    # テンプレートをレンダリング (PickingRowを辞書に変換)
    html = template.render(pages=[[asdict(row) for row in page] for page in pages])

    # HTMLファイルを書き込み
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding="utf-8")
    return destination


# ============================================================
# PipelineResult: パイプライン実行結果を保持するデータクラス
# ============================================================
@dataclass(slots=True)
class PipelineResult:
    """
    パイプライン実行の結果を保持する
    - rows: すべてのピッキング行
    - pages: ページごとに分割された行
    - html_path: 生成されたHTMLファイルのパス
    - pdf_path: 生成されたPDFファイルのパス
    """
    rows: list[PickingRow]
    pages: list[list[PickingRow]]
    html_path: Path
    pdf_path: Path


# ============================================================
# run_pipeline: ピッキングリスト生成パイプラインのメイン関数
# ============================================================
def run_pipeline(
    shipment_path: str,
    master_path: str,
    template_dir: str,
    out_dir: str,
    bom_path: str | None = None,
    config_path: str | Path = "src/config/spec.yml",
) -> PipelineResult:
    """
    ピッキングリスト生成の全工程を実行する

    処理フロー:
    1. 設定ファイルの読み込み
    2. 出荷計画とマスタデータのExcelファイル読み込み
    3. 出荷計画のフィルタリングとソート
    4. BOMファイルの読み込み(指定時)
    5. データ結合とBOM展開
    6. ページ分割
    7. QRコード生成
    8. HTML/PDF生成

    Args:
        shipment_path: 出荷計画Excelファイルのパス
        master_path: マスタExcelファイルのパス
        template_dir: HTMLテンプレートディレクトリ
        out_dir: 出力ディレクトリ
        bom_path: BOMファイルのパス(オプション)
        config_path: 設定ファイルのパス

    Returns:
        PipelineResult: 実行結果(行、ページ、ファイルパス)

    Raises:
        FileNotFoundError: 必要なファイルが見つからない場合
        ValueError: データの読み込みや処理に失敗した場合
    """
    # 1. 設定ファイルの読み込み
    config: LoadedConfig = load_config(config_path)

    # 2. 出荷計画の読み込み、フィルタリング、ソート
    shipment_df = load_excel(shipment_path, config=config.data)
    shipment_df = filter_shipment_rows(shipment_df)  # 除外キーワードを含む行を削除
    shipment_df = sort_shipment_rows(shipment_df)    # 12列目・13列目でソート

    # 3. マスタデータの読み込み
    master_df = load_excel(master_path, config=config.data)

    # 4. BOMファイルの読み込み(指定がある場合)
    bom_lookup: BomLookup | None = None
    effective_bom_config: BomConfig | None = config.data.bom

    # BOMパスの決定: 引数 → 設定ファイルの順で優先
    candidate_bom_path: Path | None = None
    if bom_path:
        candidate_bom_path = Path(bom_path)
    elif effective_bom_config and effective_bom_config.path:
        candidate_bom_path = effective_bom_config.resolve_path(config.source.parent)

    # BOMファイルが指定されている場合は読み込んで検索辞書を構築
    if candidate_bom_path:
        if effective_bom_config is None:
            effective_bom_config = BomConfig(path=str(candidate_bom_path))
        if not candidate_bom_path.exists():
            raise FileNotFoundError(f"BOMファイルが見つかりません: {candidate_bom_path}")
        bom_df = load_bom(candidate_bom_path)
        bom_lookup = build_bom_lookup(bom_df, effective_bom_config)

    # 5. データ結合とBOM展開でピッキング行を生成
    rows = join_and_map(shipment_df, master_df, config.data, bom_lookup=bom_lookup)

    # 6. ページ分割
    pages = paginate(rows, config.data.spec.items_per_page)

    # 7. 出力ディレクトリの作成
    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)

    # 8. QRコード生成
    qr_dir = out_dir_path / "qr"
    qr_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        product_code = row.productCode.strip()
        if not product_code:
            row.qr_path = ""
            continue
        # QRコード画像ファイル名を生成
        filename = f"{row.sequence:03}_" + _slugify(product_code) + ".png"
        img_path = qr_dir / filename

        # QRコードを生成して保存
        qr = qrcode.QRCode(
            version=2,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=4,
            border=1,
        )
        qr.add_data(product_code)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(img_path)
        row.qr_path = img_path.as_posix()

    # 9. HTML/PDF生成
    html_path = render_html(pages, template_dir, out_dir_path / "picking.html")
    pdf_path = generate_pdf(html_path, out_dir_path / "picking.pdf")

    # 10. 結果を返す
    return PipelineResult(rows=rows, pages=pages, html_path=html_path, pdf_path=pdf_path)


# ============================================================
# エクスポート: 外部から利用可能なシンボル
# ============================================================
__all__ = [
    "PickingRow",
    "PipelineResult",
    "build_bom_lookup",
    "filter_shipment_rows",
    "join_and_map",
    "load_bom",
    "load_excel",
    "paginate",
    "render_html",
    "run_pipeline",
]
