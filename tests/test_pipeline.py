import pandas as pd

from src.app_core.config import load_config
from src.app_core.pipeline import build_bom_lookup, join_and_map, paginate


def test_paginate_and_numbering():
    shipment = pd.DataFrame(
        {
            "品目コード": ["A"] * 7,
            "出荷数量": list(range(1, 8)),
            "客先略号": ["CUST"] * 7,
            "出荷予定日": ["2025-10-01"] * 7,
            "保管場所": ["LOC"] * 7,
        }
    )
    master = pd.DataFrame(
        {
            "品目コード": ["A"],
            "品目テキストマスタ": ["サンプル製品"],
            "品目種別": ["完成品"],
            "得意先発注番号": ["ORD-001"],
            "備考": ["注意事項"],
            "ピッキング可能ロケ地": ["LOC-MST"],
        }
    )

    config = load_config().data
    rows = join_and_map(shipment, master, config)
    assert len(rows) == 7
    assert rows[0].notice == "注意事項"
    assert rows[0].no == "1"
    assert rows[0].sequence == 1
    assert rows[-1].no == "7"
    assert rows[-1].sequence == 7
    assert rows[0].productName == "サンプル製品"

    pages = paginate(rows, config.spec.items_per_page)
    assert len(pages) == 2
    assert len(pages[0]) == 6
    assert len(pages[1]) == 1


def test_join_and_map_with_bom_children():
    shipment = pd.DataFrame(
        {
            "品目コード": ["A"],
            "出荷数量": [2],
            "客先略号": ["CUST"],
            "出荷予定日": ["2025-10-01"],
            "保管場所": ["LOC"],
        }
    )
    master = pd.DataFrame(
        {
            "品目コード": ["A", "COMP-1", "COMP-2"],
            "品目テキストマスタ": ["完成品", "子部品1", "子部品2"],
            "品目種別": ["完成品", "子部品", "子部品"],
            "得意先発注番号": ["ORD-001", "", ""],
            "備考": ["指示あり", "", ""],
            "ピッキング可能ロケ地": ["LOC-PARENT", "LOC-CH1", "LOC-CH2"],
        }
    )

    bom_df = pd.DataFrame(
        {
            "★◎製造工程品目コード": ["A", "A"],
            "★◎明細番号": ["10", "20"],
            "★◎製造工程品目コード.1": ["COMP-1", "COMP-2"],
            "製造品目テキスト.1": ["部品1", "部品2"],
            "★○数量": ["3", "0.5"],
            "構成品目数量単位": ["PC", "PC"],
            "調達タイプ": ["子部品", ""],
        }
    )

    config = load_config().data
    assert config.bom is not None
    bom_lookup = build_bom_lookup(bom_df, config.bom)

    rows = join_and_map(shipment, master, config, bom_lookup=bom_lookup)
    assert len(rows) == 3
    assert rows[0].notice == "指示あり"

    parent, child_one, child_two = rows
    assert parent.no == "1"
    assert child_one.no == "1-1"
    assert child_one.is_child is True
    assert child_one.quantity == "6"
    assert child_one.unit == "PC"
    assert child_one.quantity_note == "2 × 3"
    assert child_one.itemType == "子部品"
    assert child_one.parent_no == "1"
    assert child_one.notice == "指示あり"
    assert child_one.location == "LOC-CH1"
    assert child_one.sequence == 2

    assert child_two.no == "1-2"
    assert child_two.quantity == "1"
    assert child_two.unit == "PC"
    assert child_two.itemType == "子部品"
    assert child_two.location == "LOC-CH2"
    assert child_two.sequence == 3
