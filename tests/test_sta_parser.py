"""
ChipMentor Unit Tests
執行方式：pytest tests/test_sta_parser.py -v
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.parser import extract_paths, count_logic_depth
from core.llm import validate_output

# ─────────────────────────────────────────
# 測試用假資料
# ─────────────────────────────────────────
STANDARD_REPORT = """
========================================
  Static Timing Analysis Report
  Design: cpu_core_top
  Tool: PrimeTime vO-2018.06
  Date: 2026-04-29
========================================

PATH 1 - VIOLATED
  Startpoint : clk_div/q_reg[3] (rising edge-triggered flip-flop clocked by CLK)
  Endpoint   : alu/result_reg[7] (rising edge-triggered flip-flop clocked by CLK)
  Path Group : CLK
  Path Type  : max

  slack (VIOLATED) : -0.347 ns

  Point                                    Incr       Path
  -------------------------------------------------------
  clock CLK (rise edge)                   0.000      0.000
  clk_div/q_reg[3]/CK (DFFX1)            0.000      0.000
  clk_div/q_reg[3]/Q (DFFX1)             0.152      0.152
  U1234/Y (INVX2)                         0.043      0.195
  U1235/Y (AND2X1)                        0.078      0.273
  alu/result_reg[7]/D (DFFX1)            0.000      0.273
  data arrival time                                  0.273

PATH 2 - MET
  Startpoint : mem_ctrl/addr_reg[0]
  Endpoint   : cache/tag_reg[0]
  slack (MET) : 0.128 ns

PATH 3 - VIOLATED
  Startpoint : pll_out/clk_reg
  Endpoint   : io_ctrl/sync_reg[2]
  slack (VIOLATED) : -0.892 ns

========================================
  Summary
  Total Paths : 3
  Violated    : 2
  MET         : 1
========================================
"""

OPENROAD_REPORT = """
Startpoint: dpath.a_reg.out[8]$_DFFE_PP_
            (rising edge-triggered flip-flop clocked by core_clock)
Endpoint: dpath.a_reg.out[11]$_DFFE_PP_
          (rising edge-triggered flip-flop clocked by core_clock)
Path Group: core_clock
Path Type: max

                                   -57.638   slack (VIOLATED)
"""

MALFORMED_REPORT = """
This is not a standard STA report.
No paths here, just garbage text.
"""

# ─────────────────────────────────────────
# Test 1：PrimeTime 格式解析
# ─────────────────────────────────────────
class TestExtractPaths:

    def test_primetime_counts(self):
        result = extract_paths(STANDARD_REPORT)
        assert result["total_paths"] == 3
        assert result["violated_count"] == 2
        assert result["met_count"] == 1

    def test_primetime_design_name(self):
        result = extract_paths(STANDARD_REPORT)
        assert result["design"] == "cpu_core_top"

    def test_primetime_violated_paths_count(self):
        result = extract_paths(STANDARD_REPORT)
        assert len(result["violated_paths"]) == result["violated_count"]

    def test_primetime_met_paths_count(self):
        result = extract_paths(STANDARD_REPORT)
        assert len(result["met_paths"]) == result["met_count"]

    def test_primetime_confidence_high(self):
        result = extract_paths(STANDARD_REPORT)
        assert result["parse_confidence"] == "high"

    def test_primetime_slack_values(self):
        result = extract_paths(STANDARD_REPORT)
        slacks = [p["slack_ns"] for p in result["violated_paths"]]
        assert -0.347 in slacks
        assert -0.892 in slacks

    def test_primetime_path_type(self):
        result = extract_paths(STANDARD_REPORT)
        path1 = result["violated_paths"][0]
        assert "Setup Time" in path1["path_type"] or "max" in path1["path_type"]

    def test_primetime_startpoint(self):
        result = extract_paths(STANDARD_REPORT)
        startpoints = [p["startpoint"] for p in result["violated_paths"]]
        assert any("clk_div" in sp for sp in startpoints)

    def test_primetime_format_detected(self):
        result = extract_paths(STANDARD_REPORT)
        assert result["format"] == "primetime"

    def test_malformed_no_crash(self):
        result = extract_paths(MALFORMED_REPORT)
        assert result is not None
        assert "parse_confidence" in result

    def test_malformed_has_warning(self):
        result = extract_paths(MALFORMED_REPORT)
        assert len(result["parse_warnings"]) > 0

    # ─────────────────────────────────────────
    # OpenROAD 格式測試
    # ─────────────────────────────────────────
    def test_openroad_format_detected(self):
        result = extract_paths(OPENROAD_REPORT)
        assert result["format"] == "openroad"

    def test_openroad_violated_count(self):
        result = extract_paths(OPENROAD_REPORT)
        assert result["violated_count"] == 1

    def test_openroad_slack_value(self):
        result = extract_paths(OPENROAD_REPORT)
        assert len(result["violated_paths"]) == 1
        assert result["violated_paths"][0]["slack_ns"] == -57.638

# ─────────────────────────────────────────
# Test 2：logic_depth 計算
# ─────────────────────────────────────────
class TestCountLogicDepth:

    def test_standard_block_returns_positive(self):
        block = """PATH 1 - VIOLATED
  clk_div/q_reg[3]/CK (DFFX1)            0.000      0.000
  clk_div/q_reg[3]/Q (DFFX1)             0.152      0.152
  U1234/Y (INVX2)                         0.043      0.195
  U1235/Y (AND2X1)                        0.078      0.273
  alu/result_reg[7]/D (DFFX1)            0.000      0.273
"""
        depth = count_logic_depth(block)
        assert depth >= 0

    def test_empty_block_returns_minus_one(self):
        assert count_logic_depth("") == -1

    def test_no_cells_returns_minus_one(self):
        block = "PATH 1 - VIOLATED\n  slack (VIOLATED) : -0.347 ns\n"
        assert count_logic_depth(block) == -1

# ─────────────────────────────────────────
# Test 3：LLM 輸出驗證（使用正確的 validate_output）
# ─────────────────────────────────────────
class TestValidateOutput:

    def test_valid_output_passes(self):
        valid_output = """
## 🔍 Report 總覽
內容

## ⚠️ 違規路徑分析
內容

## ✅ 通過路徑
內容

## 🧠 新人必知觀念
內容

## 🛠️ 建議行動
內容
"""
        is_valid, missing = validate_output(valid_output)
        assert is_valid is True
        assert len(missing) == 0

    def test_missing_section_fails(self):
        incomplete_output = """
## 🔍 Report 總覽
內容

## ⚠️ 違規路徑分析
內容
"""
        is_valid, missing = validate_output(incomplete_output)
        assert is_valid is False
        assert len(missing) > 0

    def test_keyword_in_body_not_header_fails(self):
        tricky_output = """
## 🔍 Report 總覽
這份報告有違規路徑、通過路徑、新人必知觀念、建議行動的問題。

## ⚠️ 違規路徑分析
內容
"""
        is_valid, missing = validate_output(tricky_output)
        assert is_valid is False
        assert "通過路徑" in missing

    def test_empty_output_fails(self):
        is_valid, missing = validate_output("")
        assert is_valid is False
        assert len(missing) == 5
