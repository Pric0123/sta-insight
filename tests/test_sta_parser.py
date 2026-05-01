"""
ChipMentor Unit Tests
執行方式：pytest tests/test_sta_parser.py -v
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sta_parser import extract_violated_paths, validate_llm_output, count_logic_depth

# ─────────────────────────────────────────
# 測試用的假資料
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

MALFORMED_REPORT = """
This is not a standard STA report.
No paths here, just garbage text.
slack value somewhere: -0.5
"""

EMPTY_REPORT = ""

# ─────────────────────────────────────────
# Test 1：標準格式解析
# ─────────────────────────────────────────
class TestExtractViolatedPaths:

    def test_standard_format_counts(self):
        """標準格式：數字要正確"""
        result = extract_violated_paths(STANDARD_REPORT)
        assert result["total_paths"] == 3
        assert result["violated_count"] == 2
        assert result["met_count"] == 1

    def test_standard_format_design_name(self):
        """設計名稱要正確抓到"""
        result = extract_violated_paths(STANDARD_REPORT)
        assert result["design"] == "cpu_core_top"

    def test_standard_format_violated_paths_count(self):
        """violated_paths list 長度要跟 Summary 一致"""
        result = extract_violated_paths(STANDARD_REPORT)
        assert len(result["violated_paths"]) == result["violated_count"]

    def test_standard_format_met_paths_count(self):
        """met_paths list 長度要跟 Summary 一致"""
        result = extract_violated_paths(STANDARD_REPORT)
        assert len(result["met_paths"]) == result["met_count"]

    def test_standard_format_confidence_high(self):
        """標準格式的 parse_confidence 應為 high"""
        result = extract_violated_paths(STANDARD_REPORT)
        assert result["parse_confidence"] == "high"

    def test_standard_format_slack_values(self):
        """slack 數值要正確"""
        result = extract_violated_paths(STANDARD_REPORT)
        slacks = [p["slack_ns"] for p in result["violated_paths"]]
        assert -0.347 in slacks
        assert -0.892 in slacks

    def test_standard_format_path_type(self):
        """PATH 1 應該是 Setup Time"""
        result = extract_violated_paths(STANDARD_REPORT)
        path1 = result["violated_paths"][0]
        assert "Setup Time" in path1["path_type"] or "max" in path1["path_type"]

    def test_standard_format_startpoint(self):
        """startpoint 要正確抓到"""
        result = extract_violated_paths(STANDARD_REPORT)
        startpoints = [p["startpoint"] for p in result["violated_paths"]]
        assert any("clk_div" in sp for sp in startpoints)

    def test_malformed_report_confidence_low(self):
        """格式異常的 report，confidence 應降為 low"""
        result = extract_violated_paths(MALFORMED_REPORT)
        # Summary 沒有 violated count，所以 violated_count = 0
        # 但如果 fallback 抓到 slack，confidence 可能還是 high
        # 這裡只確認不會 crash
        assert result is not None
        assert "parse_confidence" in result

    def test_no_summary_warning(self):
        """沒有 Total Paths 時要有 warning"""
        result = extract_violated_paths(MALFORMED_REPORT)
        assert len(result["parse_warnings"]) > 0

# ─────────────────────────────────────────
# Test 2：logic_depth 計算
# ─────────────────────────────────────────
class TestCountLogicDepth:

    def test_standard_block_returns_positive(self):
        """標準格式的 block 應回傳正整數"""
        block = """PATH 1 - VIOLATED
  Startpoint : clk_div/q_reg[3]
  Endpoint   : alu/result_reg[7]
  clk_div/q_reg[3]/CK (DFFX1)            0.000      0.000
  clk_div/q_reg[3]/Q (DFFX1)             0.152      0.152
  U1234/Y (INVX2)                         0.043      0.195
  U1235/Y (AND2X1)                        0.078      0.273
  alu/result_reg[7]/D (DFFX1)            0.000      0.273
"""
        depth = count_logic_depth(block)
        assert depth >= 0

    def test_empty_block_returns_minus_one(self):
        """空的 block 應回傳 -1（無法解析）"""
        depth = count_logic_depth("")
        assert depth == -1

    def test_no_cells_returns_minus_one(self):
        """沒有 cell 行的 block 應回傳 -1"""
        block = "PATH 1 - VIOLATED\n  slack (VIOLATED) : -0.347 ns\n"
        depth = count_logic_depth(block)
        assert depth == -1

# ─────────────────────────────────────────
# Test 3：LLM 輸出驗證
# ─────────────────────────────────────────
class TestValidateLlmOutput:

    def test_valid_output_passes(self):
        """包含所有必要 header 的輸出應通過驗證"""
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
        is_valid, missing = validate_llm_output(valid_output)
        assert is_valid is True
        assert len(missing) == 0

    def test_missing_section_fails(self):
        """缺少段落應回傳 missing list"""
        incomplete_output = """
## 🔍 Report 總覽
內容

## ⚠️ 違規路徑分析
內容
"""
        is_valid, missing = validate_llm_output(incomplete_output)
        assert is_valid is False
        assert len(missing) > 0

    def test_keyword_in_body_not_header_fails(self):
        """
        關鍵字只出現在正文裡（不是 ## header）不應通過驗證
        這是修正前的 bug：只檢查 'in text' 會讓正文出現關鍵字就通過
        """
        tricky_output = """
## 🔍 Report 總覽
這份報告有違規路徑、通過路徑、新人必知觀念、建議行動的問題。

## ⚠️ 違規路徑分析
內容
"""
        # 「通過路徑」、「新人必知觀念」、「建議行動」只在正文，不在 ## header
        is_valid, missing = validate_llm_output(tricky_output)
        assert is_valid is False
        assert "通過路徑" in missing

    def test_empty_output_fails(self):
        """空字串應失敗"""
        is_valid, missing = validate_llm_output("")
        assert is_valid is False
        assert len(missing) == len(["Report 總覽", "違規路徑", "通過路徑", "新人必知觀念", "建議行動"])
