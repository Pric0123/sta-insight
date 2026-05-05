import os
import re
import sys
import time
import json
import argparse
from groq import Groq
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from core.parser import extract_paths, smart_chunk, read_report
from roles.prompts import ROLE_PROMPTS
from roles.summary import generate_summary_prompt
from core.prompts.onboarding import build_prompt

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
console = Console()

ROLE_LABELS = {
    "newbie": "新人工程師",
    "rtl": "RTL 工程師",
    "backend": "後端工程師",
    "verification": "驗證工程師",
    "pm": "專案經理"
}

def call_llm(prompt, role="newbie", max_retries=3):
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        console.print("[red]錯誤：找不到 GROQ_API_KEY[/red]")
        sys.exit(1)
    client = Groq(api_key=api_key)
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                timeout=30
            )
            result = response.choices[0].message.content
            if role == "newbie":
                required = ["Report 總覽", "違規路徑", "通過路徑", "新人必知觀念", "建議行動"]
                missing = [k for k in required if k not in result]
                if missing and attempt < max_retries - 1:
                    console.print(f"[yellow]輸出缺少段落 {missing}，重試...[/yellow]")
                    time.sleep(2)
                    continue
            return result
        except Exception as e:
            err = str(e)
            if "429" in err or "rate_limit" in err.lower():
                wait = (attempt + 1) * 10
                console.print(f"[yellow]Rate limit，等待 {wait} 秒...[/yellow]")
                time.sleep(wait)
            elif attempt < max_retries - 1:
                console.print(f"[yellow]第 {attempt+1} 次失敗，重試...[/yellow]")
                time.sleep(3)
            else:
                console.print(f"[red]API 錯誤：{e}[/red]")
                sys.exit(1)

def print_facts(data):
    console.print(f"[cyan]設計名稱：{data['design'] or 'Unknown'}[/cyan]")
    console.print(f"[cyan]格式：{data['format']}  總路徑：{data['total_paths']}  violated：{data['violated_count']}  met：{data['met_count']}[/cyan]")
    if data["parse_warnings"]:
        for w in data["parse_warnings"]:
            console.print(f"[yellow]⚠️  {w}[/yellow]")
    if data["violated_count"] == 0:
        console.print("[green]✅ 所有路徑通過 timing 檢查！[/green]")
    else:
        worst = min(p["slack_ns"] for p in data["violated_paths"]) if data["violated_paths"] else "N/A"
        console.print(f"[red]⚠️ 發現 {data['violated_count']} 條違規路徑，最嚴重：{worst} ns[/red]")

def parse_sta_report(report_path, role="newbie", summary=False):
    if not os.path.exists(report_path):
        console.print(f"[red]錯誤：找不到檔案 {report_path}[/red]")
        sys.exit(1)

    report_content = read_report(report_path)
    data = extract_paths(report_content)
    print_facts(data)

    chunked = smart_chunk(report_content, data["format"])

    if summary:
        facts_for_summary = {
            "design_name": data["design"] or "Unknown",
            "total_paths": data["total_paths"],
            "violated_count": data["violated_count"],
            "met_count": data["met_count"],
            "violated_slacks": [str(p["slack_ns"]) for p in data["violated_paths"]],
            "met_slacks": [str(p["slack_ns"]) for p in data["met_paths"]],
            "startpoints": [p["startpoint"] for p in data["violated_paths"]],
            "endpoints": [p["endpoint"] for p in data["violated_paths"]],
        }
        console.print("\n[blue]🔄 正在產生管理層週報...[/blue]\n")
        prompt = generate_summary_prompt(facts_for_summary)
        result = call_llm(prompt, role="pm")
        console.print(Panel(result, title="📊 設計狀態週報", style="bold yellow"))
        return

    if role == "newbie":
        console.print(f"\n[blue]🔄 正在以「新人工程師」視角分析...[/blue]\n")
        prompt = build_prompt(data, chunked)
    else:
        if role not in ROLE_PROMPTS:
            console.print(f"[red]未知角色：{role}[/red]")
            sys.exit(1)
        console.print(f"\n[blue]🔄 正在以「{ROLE_LABELS[role]}」視角分析...[/blue]\n")
        facts_summary = f"""
設計名稱：{data['design'] or 'Unknown'}
違規路徑數：{data['violated_count']}
violated slacks：{[p['slack_ns'] for p in data['violated_paths']]}
met slacks：{[p['slack_ns'] for p in data['met_paths']]}
startpoints：{[p['startpoint'] for p in data['violated_paths'][:5]]}
endpoints：{[p['endpoint'] for p in data['violated_paths'][:5]]}
"""
        prompt = f"{ROLE_PROMPTS[role]}\n\n確定事實：{facts_summary}\n\nReport 原文：{chunked}"

    result = call_llm(prompt, role=role)
    title = f"📋 ChipMentor — {ROLE_LABELS.get(role, role)}視角"
    console.print(Panel(Markdown(result), title=title, style="bold green"))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ChipMentor - IC Design STA Report Analyzer")
    parser.add_argument("report", help="STA report 檔案路徑")
    parser.add_argument("--role", default="newbie",
                        choices=list(ROLE_LABELS.keys()),
                        help="輸出角色（預設：newbie）")
    parser.add_argument("--summary", action="store_true",
                        help="產生管理層週報")
    args = parser.parse_args()
    parse_sta_report(args.report, args.role, args.summary)
