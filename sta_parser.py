import os
import re
import sys
from groq import Groq
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
console = Console()

def extract_facts(report_content):
    facts = {}
    violated = re.findall(r'slack \(VIOLATED\)\s*:\s*(-[\d.]+)\s*ns', report_content)
    met = re.findall(r'slack \(MET\)\s*:\s*([\d.]+)\s*ns', report_content)
    startpoints = re.findall(r'Startpoint\s*:\s*(.+)', report_content)
    endpoints = re.findall(r'Endpoint\s*:\s*(.+)', report_content)
    design = re.search(r'Design:\s*(\S+)', report_content)
    facts["violated_slacks"] = violated
    facts["met_slacks"] = met
    facts["startpoints"] = [s.strip() for s in startpoints]
    facts["endpoints"] = [s.strip() for s in endpoints]
    facts["design_name"] = design.group(1) if design else "Unknown"
    facts["total_paths"] = len(violated) + len(met)
    facts["violated_count"] = len(violated)
    facts["met_count"] = len(met)
    return facts

def parse_sta_report(report_path):
    if not os.path.exists(report_path):
        console.print(f"[red]錯誤：找不到檔案 {report_path}[/red]")
        sys.exit(1)

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        console.print("[red]錯誤：找不到 GROQ_API_KEY，請確認 .env 檔案存在[/red]")
        sys.exit(1)

    with open(report_path, "r") as f:
        report_content = f.read()

    facts = extract_facts(report_content)

    console.print(f"[cyan]設計名稱：{facts['design_name']}[/cyan]")
    console.print(f"[cyan]總路徑數：{facts['total_paths']}  violated：{facts['violated_count']}  met：{facts['met_count']}[/cyan]")

    if facts["violated_count"] == 0:
        console.print("[green]✅ 所有路徑通過 timing 檢查！[/green]")
    else:
        console.print(f"[red]⚠️ 發現 {facts['violated_count']} 條違規路徑，最嚴重：{min(facts['violated_slacks'])} ns[/red]")

    facts_summary = f"""
設計名稱：{facts['design_name']}
總路徑數：{facts['total_paths']}
違規路徑數：{facts['violated_count']}，slack 值：{facts['violated_slacks']}
通過路徑數：{facts['met_count']}，slack 值：{facts['met_slacks']}
Startpoints：{facts['startpoints']}
Endpoints：{facts['endpoints']}
"""

    prompt = f"""你是一位資深 IC 設計工程師，請用繁體中文回答。

以下是從 STA report 提取的確定事實（數字絕對正確，請勿更改）：
{facts_summary}

完整 STA report 原文：
{report_content}

請根據以上資訊，用新人工程師能看懂的方式輸出：

## 🔍 Report 總覽
## ⚠️ 違規路徑分析（請使用上方提供的確定數字）
## ✅ 通過路徑
## 🧠 新人必知觀念（解釋 slack、startpoint/endpoint、clock skew）
## 🛠️ 建議行動
"""

    client = Groq(api_key=api_key)
    console.print("\n[blue]🔄 正在分析...[/blue]\n")

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            timeout=30
        )
        result = response.choices[0].message.content
        console.print(Panel(Markdown(result), title="📋 ChipMentor 知識卡片", style="bold green"))

    except Exception as e:
        console.print(f"[red]API 錯誤：{e}[/red]")
        console.print("[yellow]提示：請檢查網路連線或 API key 是否有效[/yellow]")
        sys.exit(1)

if __name__ == "__main__":
    report_path = sys.argv[1] if len(sys.argv) > 1 else "sta_report_sample.txt"
    parse_sta_report(report_path)
