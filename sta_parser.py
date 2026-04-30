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
    """載入環境變數設定檔"""
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
    """讀取 STA 報告內容，若 UTF-8 失敗則 fallback 到 latin-1"""
    path = Path(report_path)
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        console.print("[yellow]⚠️  UTF-8 解碼失敗，改用 latin-1[/yellow]")
        return path.read_text(encoding="latin-1")

def extract_violated_paths(report_content: str) -> dict:
    """
    確定性解析器 (Deterministic Parser)：
    負責精準萃取起終點、Slack、Path Group、Setup/Hold Type 以及邏輯深度
    """
    result = {
        "design": None, "tool": None,
        "total_paths": 0, "violated_count": 0, "met_count": 0,
        "violated_paths": [], "met_paths": [],
        "parse_confidence": "high", "parse_warnings": []
    }

    # 1. 解析 Header 資訊
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

    # 2. 區塊化解析 (避免 Regex 跨行亂抓)
    path_blocks = re.split(r'(?=PATH\s+\d+\s*-)', report_content)

    for block in path_blocks:
        if not block.strip() or not block.startswith("PATH"): 
            continue

        is_violated = "VIOLATED" in block.split('\n')[0]
        is_met = "MET" in block.split('\n')[0]

        if not (is_violated or is_met): 
            continue

        # 基礎資訊萃取
        startpoint_m = re.search(r"Startpoint\s*:\s*(.+)", block)
        endpoint_m = re.search(r"Endpoint\s*:\s*(.+)", block)
        slack_m = re.search(r"slack\s*\((?:VIOLATED|MET)\)\s*:\s*([-\d.]+)", block)
        
        # 進階 Timing 資訊萃取
        group_m = re.search(r"Path Group\s*:\s*(\S+)", block)
        type_m = re.search(r"Path Type\s*:\s*(\S+)", block)
        arrival_m = re.search(r"data arrival time\s+([-\d.]+)", block)

        # 防幻覺機制：明確標示 Setup 與 Hold，避免 LLM 搞混
        raw_type = type_m.group(1).strip().lower() if type_m else "未標示"
        if raw_type == "max":
            path_type = "max (Setup Time)"
        elif raw_type == "min":
            path_type = "min (Hold Time)"
        else:
            path_type = raw_type

        path_data = {
            "startpoint": startpoint_m.group(1).strip() if startpoint_m else "未解析",
            "endpoint": endpoint_m.group(1).strip() if endpoint_m else "未解析",
            "slack_ns": float(slack_m.group(1)) if slack_m else 0.0,
            "path_group": group_m.group(1).strip() if group_m else "未標示",
            "path_type": path_type,
            "data_arrival_time": float(arrival_m.group(1)) if arrival_m else None,
            "logic_depth": 0
        }

        # 3. 邏輯深度 (Logic Depth) 計算
        datapath_lines = re.findall(r"\s+\S+\s+\([A-Za-z0-9_]+\)\s+[\d.]+\s+[\d.]+", block)
        if datapath_lines:
            path_data["logic_depth"] = max(0, len(datapath_lines) - 2) # 扣除起終點 FF

        if is_violated:
            result["violated_paths"].append(path_data)
        elif is_met:
            result["met_paths"].append(path_data)

    # 4. 驗證與信心度檢查
    expected = result["violated_count"]
    actual = len(result["violated_paths"])
    if expected > 0 and actual == 0:
        result["parse_confidence"] = "low"
        result["parse_warnings"].append(f"Summary 顯示 {expected} 條違規，但正規化解析一條都沒抓到")
    elif expected > 0 and actual < expected:
        result["parse_confidence"] = "medium"
        result["parse_warnings"].append(f"Summary 顯示 {expected} 條，只成功抓到 {actual} 條")

    return result

def smart_chunk(report_content: str, max_chars: int = 8000) -> str:
    """智能截斷文本，確保喂給 LLM 的上下文不會爆掉，且保留關鍵段落"""
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
            if violated_count < 5: # 最多只送前 5 條 violated raw log 給 LLM
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

REQUIRED_SECTIONS = ["Report 總覽", "違規路徑分析", "通過路徑", "新人必知觀念", "建議行動"]

def validate_llm_output(text: str) -> tuple:
    """檢查 LLM 是否有依照規定輸出所有標題"""
    missing = [s for s in REQUIRED_SECTIONS
               if not re.search(r"^#{1,3}\s*.*" + re.escape(s), text, re.MULTILINE)]
    return len(missing) == 0, missing

def build_prompt(structured_data: dict, chunked_report: str) -> str:
    """建立帶有防幻覺護欄的 LLM Prompt"""
    confidence = structured_data.get("parse_confidence", "high")

    base = f"""你是一位資深 IC 設計工程師，正在幫助新人理解 STA report。請用**繁體中文**回答。

以下是由 Deterministic Parser 自動解析的結構化資料，這是絕對準確的 ground truth：

- 設計名稱：{structured_data.get('design', '未知')}
- 總路徑數：{structured_data.get('total_paths', 0)}
- 違規路徑數：{structured_data.get('violated_count', 0)} 條
- 違規路徑詳細資料：
{json.dumps(structured_data.get('violated_paths', []), ensure_ascii=False, indent=2)}

🚨 【防幻覺嚴格守則 - 違反將導致晶片失效】🚨
1. **Setup vs Hold 絕對限制**：
   - 若 path_type 為 'max (Setup Time)'：解法方向為減少邏輯深度、換大 driving cell、降低 net delay。
   - 若 path_type 為 'min (Hold Time)'：**絕對禁止**建議減少邏輯！必須建議「增加 Delay」（例如插入 Buffer / Delay cell）。
2. **禁止過度推論肇因**：
   - 分析 logic_depth 時：若深度很高 (例如 > 10)，可以合理推測是邏輯過深導致 Setup Violation。
   - 若 logic_depth 很低 (例如 < 5) 卻仍發生 Setup Violation，**禁止瞎掰是因為邏輯太深**。請指出可能原因為：高 Fanout、Net delay 過大、或遇到了嚴重的 Clock Skew。
3. **資訊不足時必須承認**：
   - 如果遇到被截斷的 Log，或者 JSON 中缺失起終點，請直接在報告中寫明「Log 資訊不足，無法判斷」，絕對禁止通靈捏造電路結構。
4. **提供具體的「排查方向」而非空泛建議**：
   - 因為你看不到 RTL 與 Netlist topology，你的「建議行動」不能只有「加 Pipeline」這種空話。請給出工程上的**下一步排查指令**（例如：「請去 GUI 打開 schematic 檢查這條 path 的 fanout」、「確認該 endpoint 的 clock tree 是否長歪」）。
"""

    if confidence in ("low", "medium"):
        base += f"""
⚠️  注意：由於 Log 格式異常，部分資料可能遺失，請依賴以下原始片段保守推測：
{chunked_report}"""

    base += """
請**嚴格**依照以下格式輸出，每個 ## 標題必須完整出現：

## 🔍 Report 總覽
## ⚠️ 違規路徑分析 (請標明是 Setup 還是 Hold 違規，並依據邏輯深度合理推論)
## ✅ 通過路徑
## 🧠 新人必知觀念
1. **Slack**：
2. **Startpoint / Endpoint**：
3. **Clock Skew**：
## 🛠️ 建議行動 (請給出具體的「下一步排查動作」)
"""
    return base

def analyze_with_llm(structured_data: dict, chunked_report: str, max_retries: int = 3) -> str:
    """呼叫 Groq API 進行分析，帶有 Retry 與驗證機制"""
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
                temperature=0.2 # 降低溫度以減少幻覺
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
    """主流程控制"""
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

    # 終端機顯示 Parser 結果，確認 Parser 有正常工作
    table = Table(title="📊 Parser 萃取結果", style="cyan")
    table.add_column("項目", style="bold")
    table.add_column("數值")
    table.add_row("設計名稱", structured_data.get("design") or "未偵測到")
    table.add_row("總路徑數", str(structured_data.get("total_paths", 0)))
    table.add_row("違規路徑", f"[red]{structured_data.get('violated_count', 0)}[/red]")
    
    if structured_data.get("violated_paths"):
        first_path = structured_data["violated_paths"][0]
        table.add_row("Path 1 類型", first_path.get("path_type"))
        table.add_row("Path 1 深度", f"{first_path.get('logic_depth')} gates")

    console.print(table)

    for warning in structured_data.get("parse_warnings", []):
        console.print(f"[yellow]⚠️  {warning}[/yellow]")

    console.print("[blue]✂️  智能截取關鍵段落...[/blue]")
    chunked = smart_chunk(report_content)

    console.print("[blue]🤖 送入 LLM 進行語意分析與除錯建議...[/blue]")
    try:
        result = analyze_with_llm(structured_data, chunked)
    except Exception as e:
        console.print(f"[red]❌ 分析失敗：{e}[/red]")
        sys.exit(1)

    console.print(Panel(Markdown(result), title="📋 ChipMentor 知識卡片", style="bold green", expand=False))

if __name__ == "__main__":
    report_path = sys.argv[1] if len(sys.argv) > 1 else "sta_report_sample.txt"
    parse_sta_report(report_path)