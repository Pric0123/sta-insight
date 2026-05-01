import os
import sys
import re
import json
import time
from pathlib import Path
from groq import Groq
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.table import Table

console = Console()

def load_env():
    candidates = [
        Path(__file__).parent / ".env",
        Path.cwd() / ".env",
        Path.home() / "sta-insight" / ".env",
    ]
    for path in candidates:
        if path.exists():
            load_dotenv(dotenv_path=path)
            return str(path)
    return None

load_env()

def read_report(report_path: str) -> str:
    path = Path(report_path)
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        console.print("[yellow]⚠️  UTF-8 解碼失敗，改用 latin-1[/yellow]")
        return path.read_text(encoding="latin-1")

# ─────────────────────────────────────────
# 格式偵測
# ─────────────────────────────────────────
def detect_format(report_content: str) -> str:
    """
    偵測 STA report 格式：
    - primetime：有 'Design:' header 和 'slack (VIOLATED) : -0.347 ns'
    - openroad：沒有 'Design:'，slack 在前面 '-57.638   slack (VIOLATED)'
    - unknown：無法判斷
    """
    if re.search(r"Design:\s*\S+", report_content):
        return "primetime"
    if re.search(r"[-\d.]+\s+slack\s*\((?:VIOLATED|MET)\)", report_content):
        return "openroad"
    # fallback：嘗試看有沒有任何 slack 行
    if re.search(r"slack\s*\((?:VIOLATED|MET)\)", report_content):
        return "primetime"
    return "unknown"

# ─────────────────────────────────────────
# Logic Depth 計算
# ─────────────────────────────────────────
CELL_LINE_PATTERNS = [
    re.compile(r"^\s+\S+/\S+\s+\(\w+\)\s+[\d.]+\s+[\d.]+"),
    re.compile(r"^\s+\w+\s+\(\w+\)\s+[\d.]+\s+[\d.]+"),
    # OpenROAD 格式：有 Fanout Cap Slew Delay Time 欄位
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
# Slack 解析（支援兩種格式）
# ─────────────────────────────────────────
def parse_slack(block: str, fmt: str) -> tuple:
    """
    回傳 (slack_value, is_violated)
    支援：
    - PrimeTime: slack (VIOLATED) : -0.347 ns
    - OpenROAD:  -57.638   slack (VIOLATED)
    """
    if fmt == "primetime":
        m = re.search(r"slack\s*\((VIOLATED|MET)\)\s*:\s*([-\d.]+)", block)
        if m:
            return float(m.group(2)), m.group(1) == "VIOLATED"
    elif fmt == "openroad":
        m = re.search(r"([-\d.]+)\s+slack\s*\((VIOLATED|MET)\)", block)
        if m:
            return float(m.group(1)), m.group(2) == "VIOLATED"
    # 通用 fallback：兩種都試
    m = re.search(r"slack\s*\((VIOLATED|MET)\)\s*:\s*([-\d.]+)", block)
    if m:
        return float(m.group(2)), m.group(1) == "VIOLATED"
    m = re.search(r"([-\d.]+)\s+slack\s*\((VIOLATED|MET)\)", block)
    if m:
        return float(m.group(1)), m.group(2) == "VIOLATED"
    return None, None

# ─────────────────────────────────────────
# Startpoint / Endpoint 解析（支援兩種格式）
# ─────────────────────────────────────────
def parse_startpoint(block: str) -> str:
    # PrimeTime: "  Startpoint : clk_div/..."
    m = re.search(r"Startpoint\s*:\s*(.+)", block)
    if m:
        return m.group(1).strip()
    # OpenROAD: "Startpoint: dpath.a_reg..."
    m = re.search(r"Startpoint:\s*(.+)", block)
    if m:
        return m.group(1).strip()
    return "未解析"

def parse_endpoint(block: str) -> str:
    m = re.search(r"Endpoint\s*:\s*(.+)", block)
    if m:
        return m.group(1).strip()
    m = re.search(r"Endpoint:\s*(.+)", block)
    if m:
        return m.group(1).strip()
    return "未解析"

# ─────────────────────────────────────────
# Deterministic Parser（支援兩種格式）
# ─────────────────────────────────────────
def extract_violated_paths(report_content: str) -> dict:
    result = {
        "design": None, "tool": None,
        "total_paths": 0, "violated_count": 0, "met_count": 0,
        "violated_paths": [], "met_paths": [],
        "parse_confidence": "high", "parse_warnings": [],
        "format": "unknown"
    }

    # 偵測格式
    fmt = detect_format(report_content)
    result["format"] = fmt
    if fmt == "unknown":
        result["parse_warnings"].append("無法識別 report 格式，嘗試通用解析")
    else:
        console.print(f"[blue]🔎 偵測到格式：{fmt}[/blue]")

    # PrimeTime 專有 header
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

    # OpenROAD 格式：直接從 slack 行統計
    elif fmt == "openroad":
        result["parse_warnings"].append("OpenROAD 格式：無 Summary，路徑數從 slack 行統計")
        violated_count = len(re.findall(r"[-\d.]+\s+slack\s*\(VIOLATED\)", report_content))
        met_count = len(re.findall(r"[-\d.]+\s+slack\s*\(MET\)", report_content))
        result["violated_count"] = violated_count
        result["met_count"] = met_count
        result["total_paths"] = violated_count + met_count

    # 區塊化解析（兩種格式都適用）
    # PrimeTime 用 "PATH N -" 分割，OpenROAD 用 "Startpoint:" 分割
    if fmt == "primetime":
        path_blocks = re.split(r'(?=PATH\s+\d+\s*-)', report_content)
    else:
        # OpenROAD：每個 Startpoint 開始是一個新 path
        path_blocks = re.split(r'(?=^Startpoint:)', report_content, flags=re.MULTILINE)

    for block in path_blocks:
        if not block.strip():
            continue

        slack_val, is_violated = parse_slack(block, fmt)
        if slack_val is None:
            continue

        startpoint = parse_startpoint(block)
        endpoint = parse_endpoint(block)

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
            "startpoint": startpoint,
            "endpoint": endpoint,
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

    # 信心度評估
    expected = result["violated_count"]
    actual = len(result["violated_paths"])
    if expected > 0 and actual == 0:
        result["parse_confidence"] = "low"
        result["parse_warnings"].append(f"預期 {expected} 條違規，parser 一條都沒抓到")
    elif expected > 0 and actual < expected:
        result["parse_confidence"] = "medium"
        result["parse_warnings"].append(f"預期 {expected} 條，只抓到 {actual} 條")

    return result

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
        # OpenROAD：直接截取前 max_chars 字元
        chunked = report_content

    return chunked[:max_chars] + "\n...(已截斷)" if len(chunked) > max_chars else chunked

REQUIRED_SECTION_KEYWORDS = [
    "Report 總覽", "違規路徑", "通過路徑", "新人必知觀念", "建議行動"
]

def validate_llm_output(text: str) -> tuple:
    missing = [
        kw for kw in REQUIRED_SECTION_KEYWORDS
        if not re.search(r"^#{1,3}\s*.*" + re.escape(kw), text, re.MULTILINE)
    ]
    return len(missing) == 0, missing

def build_prompt(structured_data: dict, chunked_report: str) -> str:
    confidence = structured_data.get("parse_confidence", "high")
    fmt = structured_data.get("format", "unknown")

    violated_display = []
    for p in structured_data.get("violated_paths", []):
        violated_display.append({
            "startpoint": p["startpoint"],
            "endpoint": p["endpoint"],
            "slack_ns": p["slack_ns"],
            "path_type": p["path_type"],
            "path_group": p["path_group"],
            "logic_depth": p.get("logic_depth_display", "未知")
        })

    base = f"""你是一位資深 IC 設計工程師，正在幫助新人理解 STA report。請用**繁體中文**回答。

Report 格式：{fmt}
以下是由 Deterministic Parser 自動解析的結構化資料（ground truth）：

- 設計名稱：{structured_data.get('design') or '未偵測到（OpenROAD 格式無此欄位）'}
- 總路徑數：{structured_data.get('total_paths', 0)}
- 違規路徑數：{structured_data.get('violated_count', 0)} 條
- 通過路徑數：{structured_data.get('met_count', 0)} 條
- 違規路徑詳細：
{json.dumps(violated_display, ensure_ascii=False, indent=2)}

🚨 【防幻覺嚴格守則】🚨
1. path_type 為 'max (Setup Time)'：建議減少邏輯深度、換大 driving cell。
2. path_type 為 'min (Hold Time)'：**禁止**建議減少邏輯！必須建議增加 Delay。
3. logic_depth 顯示「無法解析」：禁止推測深度。
4. 資訊不足時直接寫「資訊不足，無法判斷」。
5. 建議行動要具體，給下一步排查指令。
"""

    if confidence in ("low", "medium"):
        base += f"""
⚠️  Parser 信心度為 {confidence}，提供原始片段供補充：
{chunked_report}"""

    base += """

請**嚴格**依照以下格式輸出：

## 🔍 Report 總覽
## ⚠️ 違規路徑分析
## ✅ 通過路徑
## 🧠 新人必知觀念
1. **Slack**：
2. **Startpoint / Endpoint**：
3. **Clock Skew**：
## 🛠️ 建議行動
"""
    return base

def analyze_with_llm(structured_data: dict, chunked_report: str, max_retries: int = 3) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("找不到 GROQ_API_KEY，請確認 .env 設定檔。")

    client = Groq(api_key=api_key)
    prompt = build_prompt(structured_data, chunked_report)
    last_error = None

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2
            )
            result = response.choices[0].message.content
            is_valid, missing = validate_llm_output(result)
            if not is_valid:
                console.print(f"[yellow]⚠️  LLM 輸出缺少段落：{missing}，重試中...[/yellow]")
                last_error = f"缺少段落：{missing}"
                time.sleep(2)
                continue
            return result
        except Exception as e:
            error_msg = str(e)
            last_error = error_msg
            if "rate_limit" in error_msg.lower() or "429" in error_msg:
                wait_time = (attempt + 1) * 10
                console.print(f"[yellow]⏳ Rate limit，等待 {wait_time} 秒...[/yellow]")
                time.sleep(wait_time)
            elif attempt < max_retries - 1:
                console.print(f"[yellow]⚠️  第 {attempt+1} 次失敗，重試中...[/yellow]")
                time.sleep(3)

    raise RuntimeError(f"LLM 分析失敗（已重試 {max_retries} 次）：{last_error}")

def parse_sta_report(report_path: str):
    if not os.path.exists(report_path):
        console.print(f"[red]❌ 找不到檔案：{report_path}[/red]")
        sys.exit(1)

    console.print(f"[blue]📂 讀取：{report_path}[/blue]")
    report_content = read_report(report_path)

    if len(report_content.strip()) == 0:
        console.print("[red]❌ 檔案是空的[/red]")
        sys.exit(1)

    console.print("[blue]🔍 解析報告結構 (Deterministic Parser)...[/blue]")
    structured_data = extract_violated_paths(report_content)

    table = Table(title="📊 Parser 萃取結果", style="cyan")
    table.add_column("項目", style="bold")
    table.add_column("數值")
    table.add_row("格式", structured_data.get("format", "unknown"))
    table.add_row("設計名稱", structured_data.get("design") or "未偵測到")
    table.add_row("總路徑數", str(structured_data.get("total_paths", 0)))
    table.add_row("違規路徑", f"[red]{structured_data.get('violated_count', 0)}[/red]")
    table.add_row("通過路徑", f"[green]{structured_data.get('met_count', 0)}[/green]")
    table.add_row("解析信心度", structured_data.get("parse_confidence", "unknown"))

    if structured_data.get("violated_paths"):
        first = structured_data["violated_paths"][0]
        table.add_row("Path 1 類型", first.get("path_type", "未知"))
        table.add_row("Path 1 深度", first.get("logic_depth_display", "未知"))

    console.print(table)

    for warning in structured_data.get("parse_warnings", []):
        console.print(f"[yellow]⚠️  {warning}[/yellow]")

    console.print("[blue]✂️  智能截取關鍵段落...[/blue]")
    fmt = structured_data.get("format", "unknown")
    chunked = smart_chunk(report_content, fmt)

    console.print("[blue]🤖 送入 LLM 進行語意分析...[/blue]")
    try:
        result = analyze_with_llm(structured_data, chunked)
    except Exception as e:
        console.print(f"[red]❌ 分析失敗：{e}[/red]")
        sys.exit(1)

    console.print(Panel(Markdown(result), title="📋 ChipMentor 知識卡片", style="bold green", expand=False))

if __name__ == "__main__":
    report_path = sys.argv[1] if len(sys.argv) > 1 else "sta_report_sample.txt"
    parse_sta_report(report_path)
