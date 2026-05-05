import os
import re
import sys
import time
import argparse
from groq import Groq
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from roles.prompts import ROLE_PROMPTS

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
console = Console()

def extract_facts(report_content):
    facts = {}
    pt_violated = re.findall(r'slack \(VIOLATED\)\s*:\s*(-[\d.]+)\s*ns', report_content)
    pt_met = re.findall(r'slack \(MET\)\s*:\s*([\d.]+)\s*ns', report_content)
    or_violated = re.findall(r'(-[\d.]+)\s+slack \(VIOLATED\)', report_content)
    or_met = re.findall(r'([\d.]+)\s+slack \(MET\)', report_content)
    facts["violated_slacks"] = pt_violated + or_violated
    facts["met_slacks"] = pt_met + or_met
    startpoints = re.findall(r'Startpoint[:\s]+(.+)', report_content)
    endpoints = re.findall(r'Endpoint[:\s]+(.+)', report_content)
    design = re.search(r'Design:\s*(\S+)', report_content)
    top = re.search(r'Top:\s*(\S+)', report_content)
    facts["startpoints"] = [s.strip() for s in startpoints]
    facts["endpoints"] = [s.strip() for s in endpoints]
    facts["design_name"] = design.group(1) if design else (top.group(1) if top else "Unknown")
    facts["total_paths"] = len(facts["violated_slacks"]) + len(facts["met_slacks"])
    facts["violated_count"] = len(facts["violated_slacks"])
    facts["met_count"] = len(facts["met_slacks"])
    return facts

def call_llm_with_retry(client, prompt, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                timeout=30
            )
            return response.choices[0].message.content
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                console.print(f"[yellow]API 錯誤，{wait} 秒後重試（第 {attempt+1} 次）：{e}[/yellow]")
                time.sleep(wait)
            else:
                raise e

def parse_sta_report(report_path, role="newbie"):
    if not os.path.exists(report_path):
        console.print(f"[red]錯誤：找不到檔案 {report_path}[/red]")
        sys.exit(1)

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        console.print("[red]錯誤：找不到 GROQ_API_KEY，請確認 .env 檔案存在[/red]")
        sys.exit(1)

    if role not in ROLE_PROMPTS:
        console.print(f"[red]錯誤：未知角色 {role}，可用角色：{list(ROLE_PROMPTS.keys())}[/red]")
        sys.exit(1)

    with open(report_path, "r") as f:
        report_content = f.read()

    facts = extract_facts(report_content)

    role_labels = {
        "newbie": "新人工程師",
        "rtl": "RTL 工程師",
        "backend": "後端工程師",
        "verification": "驗證工程師",
        "pm": "專案經理"
    }

    console.print(f"[cyan]設計名稱：{facts['design_name']}[/cyan]")
    console.print(f"[cyan]總路徑數：{facts['total_paths']}  violated：{facts['violated_count']}  met：{facts['met_count']}[/cyan]")
    console.print(f"[cyan]輸出角色：{role_labels.get(role, role)}[/cyan]")

    if facts["violated_count"] == 0:
        console.print("[green]✅ 所有路徑通過 timing 檢查！[/green]")
    else:
        console.print(f"[red]⚠️ 發現 {facts['violated_count']} 條違規路徑，最嚴重：{min(facts['violated_slacks'])} ns[/red]")

    facts_summary = f"""
設計名稱：{facts['design_name']}
總路徑數：{facts['total_paths']}
違規路徑數：{facts['violated_count']}，slack 值：{facts['violated_slacks']}
通過路徑數：{facts['met_count']}，slack 值：{facts['met_slacks']}
Startpoints：{facts['startpoints'][:5]}
Endpoints：{facts['endpoints'][:5]}
"""

    role_prompt = ROLE_PROMPTS[role]
    prompt = f"""{role_prompt}

以下是從 STA report 提取的確定事實（數字絕對正確，請勿更改）：
{facts_summary}

完整 STA report 原文（節錄）：
{report_content[:3000]}
"""

    client = Groq(api_key=api_key)
    console.print(f"\n[blue]🔄 正在以「{role_labels.get(role, role)}」視角分析...[/blue]\n")

    try:
        result = call_llm_with_retry(client, prompt)
        title = f"📋 ChipMentor — {role_labels.get(role, role)}視角"
        console.print(Panel(Markdown(result), title=title, style="bold green"))
    except Exception as e:
        console.print(f"[red]API 錯誤（已重試 3 次）：{e}[/red]")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ChipMentor - IC Design STA Report Analyzer")
    parser.add_argument("report", help="STA report 檔案路徑")
    parser.add_argument("--role", default="newbie",
                        choices=["newbie", "rtl", "backend", "verification", "pm"],
                        help="輸出角色（預設：newbie）")
    args = parser.parse_args()
    parse_sta_report(args.report, args.role)
