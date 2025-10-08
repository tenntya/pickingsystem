from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


class SpecModel(BaseModel):
    name: str
    numbering: str = Field(default="continuous")
    items_per_page: int = Field(default=6, ge=1)


class BomConfig(BaseModel):
    path: str | None = None
    parent_key: str = "★◎製造工程品目コード"
    child_key: str = "★◎製造工程品目コード.1"
    child_name: str = "製造品目テキスト.1"
    quantity: str = "★○数量"
    sequence: str | None = "★◎明細番号"
    unit: str | None = "構成品目数量単位"
    child_type: str | None = "調達タイプ"

    def resolve_path(self, base: Path) -> Path | None:
        if not self.path:
            return None
        candidate = Path(self.path)
        if not candidate.is_absolute():
            candidate = base / candidate
        return candidate.resolve()


class PipelineConfig(BaseModel):
    spec: SpecModel
    join_key: str = Field(alias="join_key")
    mapping: dict[str, list[str]] = Field(default_factory=dict)
    bom: BomConfig | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_mapping(cls, values: dict[str, Any]) -> dict[str, Any]:
        mapping: dict[str, Any] = values.get("mapping", {})
        normalized: dict[str, list[str]] = {}
        for key, raw in mapping.items():
            if raw is None:
                normalized[key] = []
            elif isinstance(raw, str):
                normalized[key] = [raw]
            else:
                normalized[key] = [str(item) for item in raw]
        values["mapping"] = normalized
        return values

    def resolve(self, row: dict[str, Any], field: str, default: str = "") -> str:
        keys = self.mapping.get(field, [])
        for key in keys:
            value = row.get(key)
            if value not in (None, ""):
                return str(value)
        return default


@dataclass(slots=True)
class LoadedConfig:
    source: Path
    data: PipelineConfig


def load_config(path: str | Path = "src/config/spec.yml") -> LoadedConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"設定ファイルが見つかりません: {config_path}")
    with config_path.open("r", encoding="utf-8") as fp:
        raw: dict[str, Any] = yaml.safe_load(fp)
    data = PipelineConfig.model_validate(raw)
    return LoadedConfig(source=config_path, data=data)


__all__ = ["BomConfig", "LoadedConfig", "PipelineConfig", "load_config"]
