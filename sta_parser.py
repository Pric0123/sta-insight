import os
import sys
from groq import Groq
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

load_dotenv()
console = Console()

def parse_sta_report(report_path):
    with open(report_path, "r") as f:
        report_content = f.read()

    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    prompt = "You are a senior IC design engineer. Parse this STA report and explain it so a new engineer can understand. Cover: 1) Report Overview 2) Violated Paths 3) Met Paths 4) Key concepts (slack, startpoint/endpoint, clock skew) 5) Recommended actions\n\n" + report_content

    console.print("[blue]Analyzing STA Report...[/blue]")

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}]
    )

    result = response.choices[0].message.content
    console.print(Panel(Markdown(result), title="STA Insight", style="bold green"))

if __name__ == "__main__":
    report_path = sys.argv[1] if len(sys.argv) > 1 else "sta_report_sample.txt"
    parse_sta_report(report_path)
