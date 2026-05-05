# LEGACY: 此檔案保留作參考，正式版 call_llm 在 sta_parser.py
# validate_output 僅供 newbie role 使用，其他 role 不適用
# TODO: 未來統一時移除此檔案

import re

REQUIRED_SECTION_KEYWORDS = [
    "Report 總覽", "違規路徑", "通過路徑", "新人必知觀念", "建議行動"
]

def validate_output(text: str) -> tuple:
    """僅對 newbie role 有意義，其他 role 請勿使用"""
    missing = [
        kw for kw in REQUIRED_SECTION_KEYWORDS
        if not re.search(r"^#{1,3}\s*.*" + re.escape(kw), text, re.MULTILINE)
    ]
    return len(missing) == 0, missing
