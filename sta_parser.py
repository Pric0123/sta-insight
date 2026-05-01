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
# Logic Depth 計算（多格式 fallback）
# ─────────────────────────────────────────
# PrimeTime cell 行的幾種常見格式：
#   U1234/Y (INVX2)          0.043      0.195
#   clk_div/q_reg[3]/Q (DFFX1)  0.152   0.152
#   net_name                 0.000      0.273  ← 這種沒有括號，是 net，不算
CELL_LINE_PATTERNS = [
    # 格式1：標準 cell instance，有 (CELL_TYPE)
    re.compile(r"^\s+\S+/\S+\s+\(\w+\)\s+[\d.]+\s+[\d.]+"),
    # 格式2：頂層 cell，無斜線但有括號
    re.compile(r"^\s+\w+\s+\(\w+\)\s+[\d.]+\s+[\d.]+"),
]

def count_logic_depth(block: str) -> int:
    """
    計算路徑的邏輯深度（cell 數）。
    使用多個 pattern fallback，避免單一 regex 脆弱性。
    回傳 -1 表示無法解析（讓呼叫端決定怎麼處理）。
    """
    matched_lines = set()
    for pattern in CELL_LINE_PATTERNS:
        for line in block.split("\n"):
            if pattern.match(line):
                matched_lines.add(line)

    if not matched_lines:
        return -1  # 明確表示「無法解析」，不回傳 0 避免誤導

    # 扣除起終點 FF（通常是第一行和最後一行 cell）
    depth = max(0, len(matched_lines) - 2)
    return depth

# ─────────────────────────────────────────
# Deterministic Parser
# ─────────────────────────────────────────
def extract_violated_paths(report_content: str) -> dict:
    result = {
        "design": None, "tool": None,
        "total_paths": 0, "violated_count": 0, "met_count": 0,
        "violated_paths": [], "met_paths": [],
        "parse_confidence": "high", "parse_warnings": []
    }

    design_match = re.search(r"Design:\s*(\S+)", report_content)
    tool_match = re.search(r"Tool:\s*(.+)", report_content)
    if design_match: result["design"] = design_match.group(1).strip()
    if tool_match: result["tool"] = tool_match.group(1).strip()

    total_match = re.search(r"Total Paths\s*:\s*(\d+)", report_content)
    violated_match = re.search(r"Violated\s*:\s*(\d+)", report_content)
    met_match = re.search(r"MET\s*:\s*(\d+)", report_content)

    if total_match: result["total_paths"] = int(total_match.group(1))
    else: result["parse_warnings"].append("找不到 Total Paths，可能不是標準格式")
    if violated_match: result["violated_count"] = int(violated_match.group(1))
    if met_match: result["met_count"] = int(met_match.group(1))

    path_blocks = re.split(r'(?=PATH\s+\d+\s*-)', report_content)

    for block in path_blocks:
        if not block.strip() or not block.startswith("PATH"):
            continue

        first_line = block.split('\n')[0]
        is_violated = "VIOLATED" in first_line
        is_met = "MET" in first_line
        if not (is_violated or is_met):
            continue

        startpoint_m = re.search(r"Startpoint\s*:\s*(.+)", block)
        endpoint_m = re.search(r"Endpoint\s*:\s*(.+)", block)
        slack_m = re.search(r"slack\s*\((?:VIOLATED|MET)\)\s*:\s*([-\d.]+)", block)
        group_m = re.search(r"Path Group\s*:\s*(\S+)", block)
        type_m = re.search(r"Path Type\s*:\s*(\S+)", block)
        arrival_m = re.search(r"data arrival time\s+([-\d.]+)", block)

        raw_type = type_m.group(1).strip().lower() if type_m else "未標示"
        if raw_type == "max":
            path_type = "max (Setup Time)"
        elif raw_type == "min":
            path_type = "min (Hold Time)"
        else:
            path_type = raw_type

        logic_depth = count_logic_depth(block)
        depth_display = f"{logic_depth} gates" if logic_depth >= 0 else "無法解析"

        path_data = {
            "startpoint": startpoint_m.group(1).strip() if startpoint_m else "未解析",
            "endpoint": endpoint_m.group(1).strip() if endpoint_m else "未解析",
            "slack_ns": float(slack_m.group(1)) if slack_m else 0.0,
            "path_group": group_m.group(1).strip() if group_m else "未標示",
            "path_type": path_type,
            "data_arrival_time": float(arrival_m.group(1)) if arrival_m else None,
            "logic_depth": logic_depth,
            "logic_depth_display": depth_display
        }

        if is_violated:
            result["violated_paths"].append(path_data)
        elif is_met:
            result["met_paths"].append(path_data)

    expected = result["violated_count"]
    actual = len(result["violated_paths"])
    if expected > 0 and actual == 0:
        result["parse_confidence"] = "low"
        result["parse_warnings"].append(f"Summary 顯示 {expected} 條違規，parser 一條都沒抓到")
    elif expected > 0 and actual < expected:
        result["parse_confidence"] = "medium"
        result["parse_warnings"].append(f"Summary 顯示 {expected} 條，只抓到 {actual} 條")

    return result

def smart_chunk(report_content: str, max_chars: int = 8000) -> str:
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
    return chunked[:max_chars] + "\n...(已截斷)" if len(chunked) > max_chars else chunked

# ─────────────────────────────────────────
# LLM 輸出驗證（修正：用關鍵字而非完整字串）
# ─────────────────────────────────────────
# 只存「關鍵字」，不存完整 header 字串
# 這樣 prompt 裡的 header 可以有附加說明（例如括號內的提示）
# 而不會讓 validate 失敗
REQUIRED_SECTION_KEYWORDS = [
    "Report 總覽",
    "違規路徑",   # 不是「違規路徑分析」，避免 prompt header 有括號時比對失敗
    "通過路徑",
    "新人必知觀念",
    "建議行動"
]

def validate_llm_output(text: str) -> tuple:
    """
    檢查 LLM 是否輸出了所有必要段落。
    用關鍵字比對而非完整字串，避免 prompt header 附加說明導致驗證失敗。
    """
    missing = [
        kw for kw in REQUIRED_SECTION_KEYWORDS
        if not re.search(r"^#{1,3}\s*.*" + re.escape(kw), text, re.MULTILINE)
    ]
    return len(missing) == 0, missing

def build_prompt(structured_data: dict, chunked_report: str) -> str:
    confidence = structured_data.get("parse_confidence", "high")

    # 整理違規路徑顯示（用 logic_depth_display 而非原始數字）
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

以下是由 Deterministic Parser 自動解析的結構化資料，這是 ground truth：

- 設計名稱：{structured_data.get('design', '未知')}
- 總路徑數：{structured_data.get('total_paths', 0)}
- 違規路徑數：{structured_data.get('violated_count', 0)} 條
- 通過路徑數：{structured_data.get('met_count', 0)} 條
- 違規路徑詳細：
{json.dumps(violated_display, ensure_ascii=False, indent=2)}

🚨 【防幻覺嚴格守則】🚨
1. **Setup vs Hold 絕對限制**：
   - path_type 為 'max (Setup Time)'：建議減少邏輯深度、換大 driving cell、降低 net delay。
   - path_type 為 'min (Hold Time)'：**絕對禁止**建議減少邏輯！必須建議「增加 Delay」。
2. **logic_depth 推論限制**：
   - 若 logic_depth 顯示「無法解析」：禁止推測邏輯深度，只能說「Log 資訊不足」。
   - 若深度高（> 10）：可合理推測邏輯過深。
   - 若深度低（< 5）卻仍違規：可能是高 Fanout、Net delay 或 Clock Skew，禁止說是邏輯太深。
3. **資訊不足時承認**：遇到缺失欄位，直接寫「資訊不足，無法判斷」。
4. **建議行動要具體**：給工程師下一步的排查指令，不能只說「加 Pipeline」。
"""

    if confidence in ("low", "medium"):
        base += f"""
⚠️  Parser 信心度為 {confidence}，提供原始片段供補充（數字以上方資料為準）：
{chunked_report}"""

    base += """

請**嚴格**依照以下格式輸出，每個 ## 標題必須完整出現：

## 🔍 Report 總覽
## ⚠️ 違規路徑分析 (標明 Setup 或 Hold 違規，依邏輯深度合理推論)
## ✅ 通過路徑
## 🧠 新人必知觀念
1. **Slack**：
2. **Startpoint / Endpoint**：
3. **Clock Skew**：
## 🛠️ 建議行動 (給出具體的下一步排查動作)
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
    chunked = smart_chunk(report_content)

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
