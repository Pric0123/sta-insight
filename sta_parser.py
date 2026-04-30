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

    violated_pattern = re.finditer(
        r"PATH\s+\d+\s*[-]\s*VIOLATED.*?Startpoint\s*:\s*(.+?)\n.*?Endpoint\s*:\s*(.+?)\n.*?slack\s*\(VIOLATED\)\s*:\s*([-\d.]+)\s*ns",
        report_content, re.DOTALL | re.IGNORECASE
    )
    for i, match in enumerate(violated_pattern):
        result["violated_paths"].append({
            "path_id": f"PATH {i+1}",
            "startpoint": match.group(1).strip(),
            "endpoint": match.group(2).strip(),
            "slack_ns": float(match.group(3))
        })

    if not result["violated_paths"]:
        for i, match in enumerate(re.finditer(r"slack\s*\(VIOLATED\)\s*:\s*([-\d.]+)\s*ns", report_content, re.IGNORECASE)):
            result["violated_paths"].append({
                "path_id": f"PATH {i+1}", "startpoint": "未解析",
                "endpoint": "未解析", "slack_ns": float(match.group(1))
            })
        if result["violated_paths"]:
            result["parse_warnings"].append("使用 fallback 格式，startpoint/endpoint 不完整")

    met_pattern = re.finditer(
        r"PATH\s+\d+\s*[-]\s*MET.*?Startpoint\s*:\s*(.+?)\n.*?Endpoint\s*:\s*(.+?)\n.*?slack\s*\(MET\)\s*:\s*([\d.]+)\s*ns",
        report_content, re.DOTALL | re.IGNORECASE
    )
    for i, match in enumerate(met_pattern):
        result["met_paths"].append({
            "path_id": f"MET PATH {i+1}",
            "startpoint": match.group(1).strip(),
            "endpoint": match.group(2).strip(),
            "slack_ns": float(match.group(3))
        })

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

REQUIRED_SECTIONS = ["Report 總覽", "違規路徑", "通過路徑", "新人必知觀念", "建議行動"]

def validate_llm_output(text: str) -> tuple:
    missing = [s for s in REQUIRED_SECTIONS
               if not re.search(r"^#{1,3}\s*.*" + re.escape(s), text, re.MULTILINE)]
    return len(missing) == 0, missing

def build_prompt(structured_data: dict, chunked_report: str) -> str:
    """
    職責分離：
    - parse_confidence == high → LLM 只收結構化資料，強迫它當翻譯員
    - parse_confidence == low/medium → 加入原始片段作為補救
    """
    confidence = structured_data.get("parse_confidence", "high")

    base = f"""你是一位資深 IC 設計工程師，正在幫助新人理解 STA report。請用**繁體中文**回答。

以下是由程式自動解析的結構化資料，這是 ground truth，請嚴格依照這些數字作答：

- 設計名稱：{structured_data.get('design', '未知')}
- 分析工具：{structured_data.get('tool', '未知')}
- 總路徑數：{structured_data.get('total_paths', 0)}
- 違規路徑數：{structured_data.get('violated_count', 0)} 條
- 通過路徑數：{structured_data.get('met_count', 0)} 條
- 違規路徑詳細：
{json.dumps(structured_data.get('violated_paths', []), ensure_ascii=False, indent=2)}
- 通過路徑詳細：
{json.dumps(structured_data.get('met_paths', []), ensure_ascii=False, indent=2)}"""

    if confidence in ("low", "medium"):
        base += f"""

⚠️  注意：parser 解析信心度為 {confidence}，以下提供原始片段供你補充判斷（但數字以上方結構化資料為準）：
{chunked_report}"""

    base += """

請**嚴格**依照以下格式輸出，每個 ## 標題必須完整出現：

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
        raise ValueError(
            "找不到 GROQ_API_KEY。\n"
            "請確認：\n"
            "  1. 執行目錄有 .env，內含 GROQ_API_KEY=your_key\n"
            "  2. 或執行 export GROQ_API_KEY=your_key"
        )

    client = Groq(api_key=api_key)
    prompt = build_prompt(structured_data, chunked_report)
    last_error = None

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
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
        console.print("[yellow]用法：python3 sta_parser.py <report_path>[/yellow]")
        sys.exit(1)

    console.print(f"[blue]📂 讀取：{report_path}[/blue]")
    report_content = read_report(report_path)

    if len(report_content.strip()) == 0:
        console.print("[red]❌ 檔案是空的[/red]")
        sys.exit(1)

    console.print("[blue]🔍 解析報告結構...[/blue]")
    structured_data = extract_violated_paths(report_content)

    table = Table(title="📊 Parser 結果", style="cyan")
    table.add_column("項目", style="bold")
    table.add_column("數值")
    table.add_row("設計名稱", structured_data.get("design") or "未偵測到")
    table.add_row("總路徑數", str(structured_data.get("total_paths", 0)))
    table.add_row("違規路徑", f"[red]{structured_data.get('violated_count', 0)}[/red]")
    table.add_row("通過路徑", f"[green]{structured_data.get('met_count', 0)}[/green]")
    table.add_row("解析信心度", structured_data.get("parse_confidence", "unknown"))
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

    console.print(Panel(Markdown(result), title="📋 ChipMentor 知識卡片", style="bold green"))

if __name__ == "__main__":
    report_path = sys.argv[1] if len(sys.argv) > 1 else "sta_report_sample.txt"
    parse_sta_report(report_path)
