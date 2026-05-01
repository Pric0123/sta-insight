"""
sta_parser.py
主程式：串接 core/ 各模組，處理 CLI 參數。
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.table import Table

from core.parser import read_report, extract_paths, smart_chunk
from core.llm import call_llm
from core.prompts.onboarding import build_prompt

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

def parse_sta_report(report_path: str, mode: str = "onboarding"):
    if not os.path.exists(report_path):
        console.print(f"[red]❌ 找不到檔案：{report_path}[/red]")
        sys.exit(1)

    console.print(f"[blue]📂 讀取：{report_path}[/blue]")
    report_content = read_report(report_path)

    if len(report_content.strip()) == 0:
        console.print("[red]❌ 檔案是空的[/red]")
        sys.exit(1)

    console.print("[blue]🔍 解析報告結構 (Deterministic Parser)...[/blue]")
    structured_data = extract_paths(report_content)

    table = Table(title="📊 Parser 萃取結果", style="cyan")
    table.add_column("項目", style="bold")
    table.add_column("數值")
    table.add_row("格式", structured_data.get("format", "unknown"))
    table.add_row("設計名稱", structured_data.get("design") or "未偵測到")
    table.add_row("總路徑數", str(structured_data.get("total_paths", 0)))
    table.add_row("違規路徑", f"[red]{structured_data.get('violated_count', 0)}[/red]")
    table.add_row("通過路徑", f"[green]{structured_data.get('met_count', 0)}[/green]")
    table.add_row("解析信心度", structured_data.get("parse_confidence", "unknown"))
    table.add_row("模式", mode)

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

    # 根據 mode 選擇 prompt
    if mode == "onboarding":
        prompt = build_prompt(structured_data, chunked)
    else:
        console.print(f"[red]❌ 未知模式：{mode}，目前支援：onboarding[/red]")
        sys.exit(1)

    console.print(f"[blue]🤖 送入 LLM（模式：{mode}）...[/blue]")
    try:
        result = call_llm(prompt)
    except Exception as e:
        console.print(f"[red]❌ 分析失敗：{e}[/red]")
        sys.exit(1)

    console.print(Panel(Markdown(result), title=f"📋 ChipMentor 知識卡片（{mode}）", style="bold green", expand=False))

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ChipMentor STA Report Analyzer")
    parser.add_argument("report", help="STA report 檔案路徑")
    parser.add_argument("--mode", default="onboarding",
                        choices=["onboarding"],  # 之後加 role, summary
                        help="分析模式（預設：onboarding）")
    args = parser.parse_args()
    parse_sta_report(args.report, args.mode)
