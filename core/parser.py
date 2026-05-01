"""
core/parser.py
負責：格式偵測、Deterministic Parser、Smart Chunking
不依賴 LLM，純確定性解析。
"""
import re
from pathlib import Path
from rich.console import Console

console = Console()

# ─────────────────────────────────────────
# 格式偵測
# ─────────────────────────────────────────
def detect_format(report_content: str) -> str:
    if re.search(r"Design:\s*\S+", report_content):
        return "primetime"
    if re.search(r"[-\d.]+\s+slack\s*\((?:VIOLATED|MET)\)", report_content):
        return "openroad"
    if re.search(r"slack\s*\((?:VIOLATED|MET)\)", report_content):
        return "primetime"
    return "unknown"

# ─────────────────────────────────────────
# 檔案讀取
# ─────────────────────────────────────────
def read_report(report_path: str) -> str:
    path = Path(report_path)
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        console.print("[yellow]⚠️  UTF-8 解碼失敗，改用 latin-1[/yellow]")
        return path.read_text(encoding="latin-1")

# ─────────────────────────────────────────
# Logic Depth
# ─────────────────────────────────────────
CELL_LINE_PATTERNS = [
    re.compile(r"^\s+\S+/\S+\s+\(\w+\)\s+[\d.]+\s+[\d.]+"),
    re.compile(r"^\s+\w+\s+\(\w+\)\s+[\d.]+\s+[\d.]+"),
    re.compile(r"^\s+\d+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[v^]\s+\S+"),
]

def count_logic_depth(block: str) -> int:
    matched_lines = set()
    for pattern in CELL_LINE_PATTERNS:
        for line in block.split("\n"):
            if pattern.match(line):
                matched_lines.add(line)
    if not matched_lines:
        return -1
    return max(0, len(matched_lines) - 2)

# ─────────────────────────────────────────
# Slack / Startpoint / Endpoint 解析
# ─────────────────────────────────────────
def parse_slack(block: str, fmt: str) -> tuple:
    if fmt == "primetime":
        m = re.search(r"slack\s*\((VIOLATED|MET)\)\s*:\s*([-\d.]+)", block)
        if m:
            return float(m.group(2)), m.group(1) == "VIOLATED"
    elif fmt == "openroad":
        m = re.search(r"([-\d.]+)\s+slack\s*\((VIOLATED|MET)\)", block)
        if m:
            return float(m.group(1)), m.group(2) == "VIOLATED"
    # fallback
    m = re.search(r"slack\s*\((VIOLATED|MET)\)\s*:\s*([-\d.]+)", block)
    if m:
        return float(m.group(2)), m.group(1) == "VIOLATED"
    m = re.search(r"([-\d.]+)\s+slack\s*\((VIOLATED|MET)\)", block)
    if m:
        return float(m.group(1)), m.group(2) == "VIOLATED"
    return None, None

def parse_startpoint(block: str) -> str:
    for pattern in [r"Startpoint\s*:\s*(.+)", r"Startpoint:\s*(.+)"]:
        m = re.search(pattern, block)
        if m:
            return m.group(1).strip()
    return "未解析"

def parse_endpoint(block: str) -> str:
    for pattern in [r"Endpoint\s*:\s*(.+)", r"Endpoint:\s*(.+)"]:
        m = re.search(pattern, block)
        if m:
            return m.group(1).strip()
    return "未解析"

# ─────────────────────────────────────────
# Deterministic Parser
# ─────────────────────────────────────────
def extract_paths(report_content: str) -> dict:
    result = {
        "design": None, "tool": None,
        "total_paths": 0, "violated_count": 0, "met_count": 0,
        "violated_paths": [], "met_paths": [],
        "parse_confidence": "high", "parse_warnings": [],
        "format": "unknown"
    }

    fmt = detect_format(report_content)
    result["format"] = fmt

    if fmt == "unknown":
        result["parse_warnings"].append("無法識別 report 格式，嘗試通用解析")
    else:
        console.print(f"[blue]🔎 偵測到格式：{fmt}[/blue]")

    if fmt == "primetime":
        design_match = re.search(r"Design:\s*(\S+)", report_content)
        tool_match = re.search(r"Tool:\s*(.+)", report_content)
        if design_match: result["design"] = design_match.group(1).strip()
        if tool_match: result["tool"] = tool_match.group(1).strip()

        total_match = re.search(r"Total Paths\s*:\s*(\d+)", report_content)
        violated_match = re.search(r"Violated\s*:\s*(\d+)", report_content)
        met_match = re.search(r"MET\s*:\s*(\d+)", report_content)

        if total_match: result["total_paths"] = int(total_match.group(1))
        else: result["parse_warnings"].append("找不到 Total Paths")
        if violated_match: result["violated_count"] = int(violated_match.group(1))
        if met_match: result["met_count"] = int(met_match.group(1))

    elif fmt == "openroad":
        result["parse_warnings"].append("OpenROAD 格式：無 Summary，路徑數從 slack 行統計")
        violated_count = len(re.findall(r"[-\d.]+\s+slack\s*\(VIOLATED\)", report_content))
        met_count = len(re.findall(r"[-\d.]+\s+slack\s*\(MET\)", report_content))
        result["violated_count"] = violated_count
        result["met_count"] = met_count
        result["total_paths"] = violated_count + met_count

    if fmt == "primetime":
        path_blocks = re.split(r'(?=PATH\s+\d+\s*-)', report_content)
    else:
        path_blocks = re.split(r'(?=^Startpoint:)', report_content, flags=re.MULTILINE)

    for block in path_blocks:
        if not block.strip():
            continue
        slack_val, is_violated = parse_slack(block, fmt)
        if slack_val is None:
            continue

        group_m = re.search(r"Path Group\s*:?\s*(\S+)", block)
        type_m = re.search(r"Path Type\s*:?\s*(\S+)", block)

        raw_type = type_m.group(1).strip().lower() if type_m else "未標示"
        if raw_type == "max":
            path_type = "max (Setup Time)"
        elif raw_type == "min":
            path_type = "min (Hold Time)"
        else:
            path_type = raw_type

        logic_depth = count_logic_depth(block)

        path_data = {
            "startpoint": parse_startpoint(block),
            "endpoint": parse_endpoint(block),
            "slack_ns": slack_val,
            "path_group": group_m.group(1).strip() if group_m else "未標示",
            "path_type": path_type,
            "logic_depth": logic_depth,
            "logic_depth_display": f"{logic_depth} gates" if logic_depth >= 0 else "無法解析"
        }

        if is_violated:
            result["violated_paths"].append(path_data)
        else:
            result["met_paths"].append(path_data)

    expected = result["violated_count"]
    actual = len(result["violated_paths"])
    if expected > 0 and actual == 0:
        result["parse_confidence"] = "low"
        result["parse_warnings"].append(f"預期 {expected} 條違規，parser 一條都沒抓到")
    elif expected > 0 and actual < expected:
        result["parse_confidence"] = "medium"
        result["parse_warnings"].append(f"預期 {expected} 條，只抓到 {actual} 條")

    return result

# ─────────────────────────────────────────
# Smart Chunking
# ─────────────────────────────────────────
def smart_chunk(report_content: str, fmt: str, max_chars: int = 8000) -> str:
    if fmt == "primetime":
        lines = report_content.split("\n")
        header_lines, violated_blocks, met_lines, summary_lines = [], [], [], []
        current_block, in_violated, in_met, in_summary = [], False, False, False
        violated_count = 0

        for line in lines:
            if any(k in line for k in ["Design:", "Tool:", "Date:"]):
                header_lines.append(line)
                continue
            if re.search(r"PATH\s+\d+\s*[-]\s*VIOLATED", line, re.IGNORECASE):
                if in_violated and current_block:
                    violated_blocks.append("\n".join(current_block))
                if violated_count < 5:
                    in_violated, in_met, in_summary = True, False, False
                    current_block = [line]
                    violated_count += 1
                else:
                    in_violated = False
                continue
            if re.search(r"PATH\s+\d+\s*[-]\s*MET", line, re.IGNORECASE):
                if in_violated and current_block:
                    violated_blocks.append("\n".join(current_block))
                    current_block = []
                in_violated, in_met, in_summary = False, True, False
                met_lines.append(line)
                continue
            if "Summary" in line:
                if in_violated and current_block:
                    violated_blocks.append("\n".join(current_block))
                    current_block = []
                in_violated, in_met, in_summary = False, False, True
                summary_lines.append(line)
                continue
            if in_violated: current_block.append(line)
            elif in_met: met_lines.append(line)
            elif in_summary: summary_lines.append(line)

        if in_violated and current_block:
            violated_blocks.append("\n".join(current_block))

        parts = []
        if header_lines: parts.append("\n".join(header_lines))
        if violated_blocks: parts.append("\n\n".join(violated_blocks))
        if met_lines: parts.append("\n".join(met_lines))
        if summary_lines: parts.append("\n".join(summary_lines))
        chunked = "\n\n".join(parts)
    else:
        chunked = report_content

    return chunked[:max_chars] + "\n...(已截斷)" if len(chunked) > max_chars else chunked
