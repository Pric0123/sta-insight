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

# ─────────────────────────────────────────
# 0. 環境載入（多重 fallback）
# ─────────────────────────────────────────
def load_env():
    """嘗試多個路徑載入 .env，並給出明確錯誤訊息"""
    candidates = [
        Path(__file__).parent / ".env",   # script 同目錄
        Path.cwd() / ".env",              # 執行目錄
        Path.home() / "sta-insight" / ".env",  # 常用路徑
    ]
    for path in candidates:
        if path.exists():
            load_dotenv(dotenv_path=path)
            return str(path)
    # 沒找到 .env，但環境變數可能已經 export 了，不強制報錯
    return None

env_loaded = load_env()

# ─────────────────────────────────────────
# 1. Deterministic Parser（含靜默失敗偵測）
# ─────────────────────────────────────────
def extract_violated_paths(report_content: str) -> dict:
    """
    用 regex 從 STA report 抽出關鍵數據。
    包含 parse_confidence 指標，讓呼叫端知道解析品質。
    """
    result = {
        "design": None,
        "tool": None,
        "total_paths": 0,
        "violated_count": 0,
        "met_count": 0,
        "violated_paths": [],
        "met_paths": [],
        "parse_confidence": "high",  # high / medium / low
        "parse_warnings": []
    }

    # 抽取基本資訊
    design_match = re.search(r"Design:\s*(\S+)", report_content)
    tool_match = re.search(r"Tool:\s*(.+)", report_content)
    if design_match:
        result["design"] = design_match.group(1).strip()
    if tool_match:
        result["tool"] = tool_match.group(1).strip()

    # 抽取 Summary（最可靠的數字來源）
    total_match = re.search(r"Total Paths\s*:\s*(\d+)", report_content)
    violated_match = re.search(r"Violated\s*:\s*(\d+)", report_content)
    met_match = re.search(r"MET\s*:\s*(\d+)", report_content)

    if total_match:
        result["total_paths"] = int(total_match.group(1))
    else:
        result["parse_warnings"].append("找不到 Total Paths，可能不是標準 STA report 格式")

    if violated_match:
        result["violated_count"] = int(violated_match.group(1))
    if met_match:
        result["met_count"] = int(met_match.group(1))

    # 抽取 violated paths（多種格式 fallback）
    # 格式一：標準 PrimeTime 格式
    violated_pattern = re.finditer(
        r"PATH\s+\d+\s*[-–]\s*VIOLATED.*?Startpoint\s*:\s*(.+?)\n.*?Endpoint\s*:\s*(.+?)\n.*?slack\s*\(VIOLATED\)\s*:\s*([-\d.]+)\s*ns",
        report_content,
        re.DOTALL | re.IGNORECASE
    )
    for i, match in enumerate(violated_pattern):
        result["violated_paths"].append({
            "path_id": f"PATH {i+1}",
            "startpoint": match.group(1).strip(),
            "endpoint": match.group(2).strip(),
            "slack_ns": float(match.group(3))
        })

    # 格式二：只有 slack 行（fallback）
    if not result["violated_paths"]:
        slack_pattern = re.finditer(
            r"slack\s*\(VIOLATED\)\s*:\s*([-\d.]+)\s*ns",
            report_content,
            re.IGNORECASE
        )
        for i, match in enumerate(slack_pattern):
            result["violated_paths"].append({
                "path_id": f"PATH {i+1}",
                "startpoint": "未解析",
                "endpoint": "未解析",
                "slack_ns": float(match.group(1))
            })
        if result["violated_paths"]:
            result["parse_warnings"].append("使用 fallback 格式解析，startpoint/endpoint 資訊不完整")

    # met paths
    met_pattern = re.finditer(
        r"PATH\s+\d+\s*[-–]\s*MET.*?Startpoint\s*:\s*(.+?)\n.*?Endpoint\s*:\s*(.+?)\n.*?slack\s*\(MET\)\s*:\s*([\d.]+)\s*ns",
        report_content,
        re.DOTALL | re.IGNORECASE
    )
    for i, match in enumerate(met_pattern):
        result["met_paths"].append({
            "path_id": f"MET PATH {i+1}",
            "startpoint": match.group(1).strip(),
            "endpoint": match.group(2).strip(),
            "slack_ns": float(match.group(3))
        })

    # 評估解析信心度
    expected_violated = result["violated_count"]
    actual_violated = len(result["violated_paths"])

    if expected_violated > 0 and actual_violated == 0:
        result["parse_confidence"] = "low"
        result["parse_warnings"].append(
            f"Summary 顯示 {expected_violated} 條違規路徑，但 parser 一條都沒抓到，格式可能不相容"
        )
    elif expected_violated > 0 and actual_violated < expected_violated:
        result["parse_confidence"] = "medium"
        result["parse_warnings"].append(
            f"Summary 顯示 {expected_violated} 條，只抓到 {actual_violated} 條，可能有格式變異"
        )

    return result

# ─────────────────────────────────────────
# 2. Smart Chunking（修正 bug）
# ─────────────────────────────────────────
def smart_chunk(report_content: str, max_chars: int = 8000) -> str:
    """
    抽取關鍵段落送進 LLM。
    修正：in_violated 的重置邏輯、violated_count break 不截斷 Summary。
    """
    lines = report_content.split("\n")
    header_lines = []
    violated_blocks = []
    summary_lines = []

    current_block = []
    in_violated = False
    in_summary = False
    violated_count = 0
    MAX_VIOLATED_BLOCKS = 5

    for line in lines:
        # 抓 header（設計資訊）
        if any(keyword in line for keyword in ["Design:", "Tool:", "Date:"]):
            header_lines.append(line)
            continue

        # 偵測 violated path 開始
        if re.search(r"PATH\s+\d+\s*[-–]\s*VIOLATED", line, re.IGNORECASE):
            if violated_count < MAX_VIOLATED_BLOCKS:
                in_violated = True
                in_summary = False
                current_block = [line]
                violated_count += 1
            continue

        # 偵測任何新 PATH 區塊（包含 MET），結束當前 violated block
        if re.search(r"PATH\s+\d+\s*[-–]", line, re.IGNORECASE) and in_violated:
            violated_blocks.append("\n".join(current_block))
            current_block = []
            in_violated = False

        # 收集 violated block 內容
        if in_violated:
            current_block.append(line)

        # 抓 Summary
        if "Summary" in line:
            in_summary = True
            in_violated = False
            if current_block:
                violated_blocks.append("\n".join(current_block))
                current_block = []
        if in_summary:
            summary_lines.append(line)

    # 收尾
    if current_block and in_violated:
        violated_blocks.append("\n".join(current_block))

    # 組合
    chunked_parts = []
    if header_lines:
        chunked_parts.append("\n".join(header_lines))
    if violated_blocks:
        chunked_parts.append("\n\n".join(violated_blocks))
    if summary_lines:
        chunked_parts.append("\n".join(summary_lines))

    chunked = "\n\n".join(chunked_parts)

    if len(chunked) > max_chars:
        chunked = chunked[:max_chars] + "\n...(已截斷，僅分析前段)"

    return chunked

# ─────────────────────────────────────────
# 3. LLM 輸出驗證
# ─────────────────────────────────────────
REQUIRED_SECTIONS = [
    "Report 總覽",
    "違規路徑",
    "通過路徑",
    "新人必知觀念",
    "建議行動"
]

def validate_llm_output(text: str) -> tuple[bool, list]:
    """檢查 LLM 輸出是否包含所有必要段落"""
    missing = []
    for section in REQUIRED_SECTIONS:
        if section not in text:
            missing.append(section)
    return len(missing) == 0, missing

# ─────────────────────────────────────────
# 4. LLM 分析（帶 retry + 輸出驗證）
# ─────────────────────────────────────────
def analyze_with_llm(structured_data: dict, chunked_report: str, max_retries: int = 3) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "找不到 GROQ_API_KEY。\n"
            "請確認以下其中一項：\n"
            "  1. 執行目錄有 .env 檔案，內含 GROQ_API_KEY=your_key\n"
            "  2. 已執行 export GROQ_API_KEY=your_key"
        )

    client = Groq(api_key=api_key)

    prompt = f"""你是一位資深 IC 設計工程師，正在幫助新人理解 STA report。請用**繁體中文**回答。

結構化摘要（由程式自動解析）：
- 設計：{structured_data.get('design', '未知')}
- 違規路徑數：{structured_data.get('violated_count', 0)} 條
- 通過路徑數：{structured_data.get('met_count', 0)} 條
- 違規清單：{json.dumps(structured_data.get('violated_paths', []), ensure_ascii=False)}

原始 report 片段：
{chunked_report}

請**嚴格**依照以下格式輸出，每個段落標題必須完整出現：

## 🔍 Report 總覽
（一句話說明這份設計的狀況）

## ⚠️ 違規路徑分析
（針對每條 violated path，解釋從哪個模組到哪個模組、slack 是多少、代表什麼問題）

## ✅ 通過路徑
（說明通過的路徑狀況）

## 🧠 新人必知觀念
1. **Slack**：
2. **Startpoint / Endpoint**：
3. **Clock Skew**：

## 🛠️ 建議行動
（具體的下一步，按優先順序列出）
"""

    last_error = None
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            result = response.choices[0].message.content

            # 驗證輸出
            is_valid, missing = validate_llm_output(result)
            if not is_valid:
                console.print(f"[yellow]⚠️  LLM 輸出缺少段落：{missing}，重試中...[/yellow]")
                last_error = f"輸出缺少段落：{missing}"
                time.sleep(2)
                continue

            return result

        except Exception as e:
            error_msg = str(e)
            last_error = error_msg
            if "rate_limit" in error_msg.lower() or "429" in error_msg:
                wait_time = (attempt + 1) * 10
                console.print(f"[yellow]⏳ Rate limit，等待 {wait_time} 秒後重試...[/yellow]")
                time.sleep(wait_time)
            elif attempt < max_retries - 1:
                console.print(f"[yellow]⚠️  第 {attempt + 1} 次失敗，重試中...[/yellow]")
                time.sleep(3)

    raise RuntimeError(f"LLM 分析失敗（已重試 {max_retries} 次）：{last_error}")

# ─────────────────────────────────────────
# 5. 主程式
# ─────────────────────────────────────────
def parse_sta_report(report_path: str):
    if not os.path.exists(report_path):
        console.print(f"[red]❌ 找不到檔案：{report_path}[/red]")
        console.print("[yellow]用法：python3 sta_parser.py <report_path>[/yellow]")
        sys.exit(1)

    console.print(f"[blue]📂 讀取：{report_path}[/blue]")

    with open(report_path, "r", encoding="utf-8", errors="replace") as f:
        report_content = f.read()

    if len(report_content.strip()) == 0:
        console.print("[red]❌ 檔案是空的[/red]")
        sys.exit(1)

    # Step 1: Deterministic parsing
    console.print("[blue]🔍 解析報告結構...[/blue]")
    structured_data = extract_violated_paths(report_content)

    # 顯示解析結果
    table = Table(title="📊 Parser 結果", style="cyan")
    table.add_column("項目", style="bold")
    table.add_column("數值")
    table.add_row("設計名稱", structured_data.get("design") or "未偵測到")
    table.add_row("總路徑數", str(structured_data.get("total_paths", 0)))
    table.add_row("違規路徑", f"[red]{structured_data.get('violated_count', 0)}[/red]")
    table.add_row("通過路徑", f"[green]{structured_data.get('met_count', 0)}[/green]")
    table.add_row("解析信心度", structured_data.get("parse_confidence", "unknown"))
    console.print(table)

    # 顯示 parse warnings
    for warning in structured_data.get("parse_warnings", []):
        console.print(f"[yellow]⚠️  {warning}[/yellow]")

    # Step 2: Smart chunking
    console.print("[blue]✂️  智能截取關鍵段落...[/blue]")
    chunked = smart_chunk(report_content)

    # Step 3: LLM 分析
    console.print("[blue]🤖 送入 LLM 進行語意分析...[/blue]")
    try:
        result = analyze_with_llm(structured_data, chunked)
    except Exception as e:
        console.print(f"[red]❌ 分析失敗：{e}[/red]")
        sys.exit(1)

    # Step 4: 輸出知識卡片
    console.print(Panel(
        Markdown(result),
        title="📋 ChipMentor 知識卡片",
        style="bold green"
    ))

if __name__ == "__main__":
    report_path = sys.argv[1] if len(sys.argv) > 1 else "sta_report_sample.txt"
    parse_sta_report(report_path)
