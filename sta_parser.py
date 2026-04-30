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

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

console = Console()

def extract_violated_paths(report_content: str) -> dict:
    result = {
        "design": None, "tool": None, "date": None,
        "total_paths": 0, "violated_count": 0, "met_count": 0,
        "violated_paths": [], "met_paths": []
    }
    design_match = re.search(r"Design:\s*(\S+)", report_content)
    tool_match = re.search(r"Tool:\s*(.+)", report_content)
    if design_match: result["design"] = design_match.group(1).strip()
    if tool_match: result["tool"] = tool_match.group(1).strip()
    total_match = re.search(r"Total Paths\s*:\s*(\d+)", report_content)
    violated_match = re.search(r"Violated\s*:\s*(\d+)", report_content)
    met_match = re.search(r"MET\s*:\s*(\d+)", report_content)
    if total_match: result["total_paths"] = int(total_match.group(1))
    if violated_match: result["violated_count"] = int(violated_match.group(1))
    if met_match: result["met_count"] = int(met_match.group(1))
    violated_pattern = re.finditer(
        r"(PATH\s+\d+)\s*-\s*VIOLATED.*?Startpoint\s*:\s*(.+?)\n.*?Endpoint\s*:\s*(.+?)\n.*?slack\s*\(VIOLATED\)\s*:\s*([-\d.]+)\s*ns",
        report_content, re.DOTALL)
    for match in violated_pattern:
        result["violated_paths"].append({
            "path_id": match.group(1).strip(),
            "startpoint": match.group(2).strip(),
            "endpoint": match.group(3).strip(),
            "slack_ns": float(match.group(4))
        })
    met_pattern = re.finditer(
        r"(PATH\s+\d+)\s*-\s*MET.*?Startpoint\s*:\s*(.+?)\n.*?Endpoint\s*:\s*(.+?)\n.*?slack\s*\(MET\)\s*:\s*([\d.]+)\s*ns",
        report_content, re.DOTALL)
    for match in met_pattern:
        result["met_paths"].append({
            "path_id": match.group(1).strip(),
            "startpoint": match.group(2).strip(),
            "endpoint": match.group(3).strip(),
            "slack_ns": float(match.group(4))
        })
    return result

def smart_chunk(report_content: str, max_chars: int = 8000) -> str:
    lines = report_content.split("\n")
    important_lines = []
    in_violated = False
    violated_count = 0
    for line in lines:
        if "VIOLATED" in line and "PATH" in line:
            in_violated = True
            violated_count += 1
        if "MET" in line and "PATH" in line:
            in_violated = False
        if in_violated or "Summary" in line or "Design:" in line or "Tool:" in line:
            important_lines.append(line)
        if violated_count > 5:
            break
    chunked = "\n".join(important_lines)
    if len(chunked) > max_chars:
        chunked = chunked[:max_chars] + "\n...(已截斷)"
    return chunked

def analyze_with_llm(structured_data: dict, chunked_report: str, max_retries: int = 3) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("找不到 GROQ_API_KEY，請確認 .env 檔案存在且格式正確")
    client = Groq(api_key=api_key)
    prompt = f"""你是一位資深 IC 設計工程師，正在幫助新人理解 STA report。請用繁體中文回答。

結構化摘要：
- 設計：{structured_data.get('design', '未知')}
- 違規路徑：{structured_data.get('violated_count', 0)} 條
- 通過路徑：{structured_data.get('met_count', 0)} 條
- 違規清單：{json.dumps(structured_data.get('violated_paths', []), ensure_ascii=False)}

原始片段：
{chunked_report}

請依照以下格式輸出：

## 🔍 Report 總覽
## ⚠️ 違規路徑分析
## ✅ 通過路徑
## 🧠 新人必知觀念（解釋 Slack、Startpoint/Endpoint、Clock Skew）
## 🛠️ 建議行動
"""
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            return response.choices[0].message.content
        except Exception as e:
            error_msg = str(e)
            if "rate_limit" in error_msg.lower() or "429" in error_msg:
                wait_time = (attempt + 1) * 10
                console.print(f"[yellow]Rate limit，等待 {wait_time} 秒...[/yellow]")
                time.sleep(wait_time)
            elif attempt < max_retries - 1:
                time.sleep(3)
            else:
                raise RuntimeError(f"LLM 失敗（已重試 {max_retries} 次）：{error_msg}")

def parse_sta_report(report_path: str):
    if not os.path.exists(report_path):
        console.print(f"[red]找不到檔案：{report_path}[/red]")
        sys.exit(1)
    console.print(f"[blue]讀取：{report_path}[/blue]")
    with open(report_path, "r", encoding="utf-8") as f:
        report_content = f.read()
    console.print("[blue]解析結構...[/blue]")
    structured_data = extract_violated_paths(report_content)
    table = Table(title="Parser 結果", style="cyan")
    table.add_column("項目", style="bold")
    table.add_column("數值")
    table.add_row("設計", structured_data.get("design") or "未偵測")
    table.add_row("總路徑", str(structured_data.get("total_paths", 0)))
    table.add_row("違規", f"[red]{structured_data.get('violated_count', 0)}[/red]")
    table.add_row("通過", f"[green]{structured_data.get('met_count', 0)}[/green]")
    console.print(table)
    chunked = smart_chunk(report_content)
    console.print("[blue]送入 LLM 分析...[/blue]")
    try:
        result = analyze_with_llm(structured_data, chunked)
    except Exception as e:
        console.print(f"[red]分析失敗：{e}[/red]")
        sys.exit(1)
    console.print(Panel(Markdown(result), title="ChipMentor 知識卡片", style="bold green"))

if __name__ == "__main__":
    report_path = sys.argv[1] if len(sys.argv) > 1 else "sta_report_sample.txt"
    parse_sta_report(report_path)
