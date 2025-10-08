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


def _slugify(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = value.strip().replace("/", "-")
    value = re.sub(r"[^0-9A-Za-z_-]+", "_", value)
    return value or "qr"


@dataclass(slots=True)
class PickingRow:
    shipDate: str
    clientCode: str
    notice: str
    productCode: str
    location: str
    quantity: str
    itemType: str
    productName: str
    orderNumber: str
    no: str
    sequence: int
    qr_path: str = ""
    is_child: bool = False
    parent_no: str | None = None
    child_index: int | None = None
    quantity_note: str = ""
    unit: str = ""


def _clean_column(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(name).strip())
    return re.sub(r"\s+", "", normalized)


def _expected_columns(config: PipelineConfig) -> set[str]:
    expected: set[str] = {_clean_column(config.join_key)}
    for values in config.mapping.values():
        for raw_key in values:
            key = _clean_column(raw_key)
            if key:
                expected.add(key)
    return expected


def load_excel(path: str, *, config: PipelineConfig | None = None) -> pd.DataFrame:
    headers_to_try = [0] if config is None else [0, 1, 2, 3, 4]
    expected = _expected_columns(config) if config else set()
    last_df: pd.DataFrame | None = None

    for header in headers_to_try:
        df = pd.read_excel(path, header=header, dtype=str)
        df.columns = ["" if pd.isna(col) else _clean_column(col) for col in df.columns]
        last_df = df
        if config is None:
            return df.fillna("")
        join_key = _clean_column(config.join_key)
        if join_key in df.columns or expected.intersection(df.columns):
            filtered = [col for col in df.columns if col and not col.startswith("Unnamed")]
            return df.loc[:, filtered].fillna("")

    if config is None:
        if last_df is not None:
            return last_df.fillna("")
        raise ValueError(f"Excel の読み込みに失敗しました: {path}")

    if last_df is not None:
        raise ValueError(f"必要な列が見つかりません: {config.join_key}")
    raise ValueError(f"Excel の読み込みに失敗しました: {path}")


def normalize_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def coalesce(row: dict[str, Any], candidates: Sequence[str]) -> str:
    for key in candidates:
        if key in row and row[key] not in (None, ""):
            return normalize_value(row[key])
    return ""


def resolve_field(config: PipelineConfig, row: dict[str, Any], field: str) -> str:
    candidates: list[str] = []
    for base in config.mapping.get(field, []):
        cleaned = _clean_column(base)
        candidates.append(cleaned)
        candidates.append(f"{cleaned}_in")
        candidates.append(f"{cleaned}_mst")
    return coalesce(row, candidates)


def _normalize_code_value(value: str) -> str:
    return _clean_column(normalize_value(value))


def _parse_decimal(value: str) -> Decimal | None:
    raw = normalize_value(value)
    text = raw.replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        import re

        matches = re.findall(r"[-+]?\d+(?:\.\d+)?", text)
        for candidate in reversed(matches):
            try:
                return Decimal(candidate)
            except InvalidOperation:
                continue
        return None


def _format_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _display_quantity(value: str) -> str:
    decimal_value = _parse_decimal(value)
    if decimal_value is None:
        return normalize_value(value)
    return _format_decimal(decimal_value)


def _build_master_lookup(master: pd.DataFrame, join_key: str) -> dict[str, dict[str, str]]:
    lookup: dict[str, dict[str, str]] = {}
    if master.empty:
        return lookup

    cleaned_join_key = _clean_column(join_key)
    filled = master.fillna("")
    for _, rec in filled.iterrows():
        row_dict: dict[str, str] = {}
        for col in filled.columns:
            value = normalize_value(rec[col])
            row_dict[col] = value
            row_dict[f"{col}_mst"] = value
        key = _normalize_code_value(row_dict.get(cleaned_join_key, ""))
        if key:
            lookup[key] = row_dict

    return lookup


def _compute_child_quantity(parent_qty: str, base_qty: str) -> tuple[str, str]:
    parent_dec = _parse_decimal(parent_qty)
    base_dec = _parse_decimal(base_qty)
    if parent_dec is not None and base_dec is not None:
        result = parent_dec * base_dec
        return _format_decimal(result), f"{_format_decimal(parent_dec)} × {_format_decimal(base_dec)}"
    if base_dec is not None:
        return _format_decimal(base_dec), ""
    return normalize_value(base_qty), ""


def load_bom(path: str | Path) -> pd.DataFrame:
    bom_path = Path(path)
    df = pd.read_csv(bom_path, sep="	", dtype=str)
    df = df.fillna("")
    df.columns = [_clean_column(col) for col in df.columns]
    return df


BomLookup = dict[str, list[dict[str, str]]]


def build_bom_lookup(data: pd.DataFrame, config: BomConfig) -> BomLookup:
    if data.empty:
        return {}

    parent_col = _clean_column(config.parent_key)
    child_code_col = _clean_column(config.child_key)
    child_name_col = _clean_column(config.child_name)
    quantity_col = _clean_column(config.quantity)
    sequence_col = _clean_column(config.sequence) if config.sequence else None
    unit_col = _clean_column(config.unit) if config.unit else None
    type_col = _clean_column(config.child_type) if config.child_type else None

    lookup: BomLookup = defaultdict(list)
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

    def _sort_key(entry: dict[str, str]) -> tuple[int, Any]:
        raw = entry.get("sequence", "")
        try:
            return (0, int(raw))
        except (TypeError, ValueError):
            return (1, raw)

    for entries in lookup.values():
        entries.sort(key=_sort_key)

    return lookup


def join_and_map(
    shipment: pd.DataFrame,
    master: pd.DataFrame,
    config: PipelineConfig,
    *,
    bom_lookup: BomLookup | None = None,
) -> list[PickingRow]:
    join_key = _clean_column(config.join_key)
    master_lookup = _build_master_lookup(master, join_key)
    merged = shipment.merge(
        master,
        how="left",
        left_on=join_key,
        right_on=join_key,
        suffixes=("_in", "_mst"),
    )

    lookup = bom_lookup or {}
    rows: list[PickingRow] = []
    parent_index = 1
    sequence_counter = 1

    master_location_column: str | None = None
    if len(master.columns) > 10:
        column_name = master.columns[10]
        if column_name:
            master_location_column = _clean_column(str(column_name))

    for _, record in merged.fillna("").iterrows():
        data = record.to_dict()
        product_code = resolve_field(config, data, "productCode") or normalize_value(data.get(join_key))
        raw_parent_quantity = resolve_field(config, data, "quantity")
        parent_quantity = _display_quantity(raw_parent_quantity)
        parent_location = ""
        if master_location_column:
            parent_location = normalize_value(
                data.get(master_location_column, "")
                or data.get(f"{master_location_column}_mst", "")
            )

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
            no=str(parent_index),
            sequence=sequence_counter,
        )
        rows.append(parent_row)
        sequence_counter += 1

        parent_code_key = _normalize_code_value(parent_row.productCode)
        children = lookup.get(parent_code_key, [])
        for child_idx, child in enumerate(children, start=1):
            child_code_raw = normalize_value(child.get("productCode", ""))
            child_code_key = _normalize_code_value(child_code_raw)
            child_master = master_lookup.get(child_code_key, {})
            child_product_name = (
                child.get("productName", "")
                or resolve_field(config, child_master, "productName")
                or child_code_raw
            )
            child_item_type = (
                child.get("itemType", "")
                or resolve_field(config, child_master, "itemType")
                or parent_row.itemType
            )
            child_location = ""
            if master_location_column:
                child_location = normalize_value(
                    child_master.get(master_location_column, "")
                    or child_master.get(f"{master_location_column}_mst", "")
                )
            child_notice = (
                resolve_field(config, child_master, "notice")
                or parent_row.notice
            )
            result_qty, note = _compute_child_quantity(
                parent_quantity, child.get("baseQuantity", "")
            )
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
                no=f"{parent_index}-{child_idx}",
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

        parent_index += 1

    return rows

def paginate(rows: Sequence[PickingRow], per_page: int) -> list[list[PickingRow]]:
    pages: list[list[PickingRow]] = []
    for idx in range(0, len(rows), per_page):
        pages.append(list(rows[idx : idx + per_page]))
    return pages


def render_html(
    pages: Sequence[Sequence[PickingRow]],
    template_dir: str | Path,
    output_path: str | Path,
) -> Path:
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("product_list_table.html")
    html = template.render(pages=[[asdict(row) for row in page] for page in pages])

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding="utf-8")
    return destination


@dataclass(slots=True)
class PipelineResult:
    rows: list[PickingRow]
    pages: list[list[PickingRow]]
    html_path: Path
    pdf_path: Path


def run_pipeline(
    shipment_path: str,
    master_path: str,
    template_dir: str,
    out_dir: str,
    bom_path: str | None = None,
    config_path: str | Path = "src/config/spec.yml",
) -> PipelineResult:
    config: LoadedConfig = load_config(config_path)
    shipment_df = load_excel(shipment_path, config=config.data)
    master_df = load_excel(master_path, config=config.data)

    bom_lookup: BomLookup | None = None
    effective_bom_config: BomConfig | None = config.data.bom

    candidate_bom_path: Path | None = None
    if bom_path:
        candidate_bom_path = Path(bom_path)
    elif effective_bom_config and effective_bom_config.path:
        candidate_bom_path = effective_bom_config.resolve_path(config.source.parent)

    if candidate_bom_path:
        if effective_bom_config is None:
            effective_bom_config = BomConfig(path=str(candidate_bom_path))
        if not candidate_bom_path.exists():
            raise FileNotFoundError(f"BOMファイルが見つかりません: {candidate_bom_path}")
        bom_df = load_bom(candidate_bom_path)
        bom_lookup = build_bom_lookup(bom_df, effective_bom_config)

    rows = join_and_map(shipment_df, master_df, config.data, bom_lookup=bom_lookup)
    pages = paginate(rows, config.data.spec.items_per_page)

    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)

    qr_dir = out_dir_path / "qr"
    qr_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        product_code = row.productCode.strip()
        if not product_code:
            row.qr_path = ""
            continue
        filename = f"{row.sequence:03}_" + _slugify(product_code) + ".png"
        img_path = qr_dir / filename
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

    html_path = render_html(pages, template_dir, out_dir_path / "picking.html")
    pdf_path = generate_pdf(html_path, out_dir_path / "picking.pdf")

    return PipelineResult(rows=rows, pages=pages, html_path=html_path, pdf_path=pdf_path)


__all__ = [
    "PickingRow",
    "PipelineResult",
    "build_bom_lookup",
    "join_and_map",
    "load_bom",
    "load_excel",
    "paginate",
    "render_html",
    "run_pipeline",
]