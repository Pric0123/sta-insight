"""
core/llm.py
負責：LLM API 呼叫、輸出驗證、retry 機制
不包含 prompt 內容，prompt 由各病灶的 prompts/ 模組提供。
"""
import os
import re
import time
from groq import Groq
from rich.console import Console

console = Console()

REQUIRED_SECTION_KEYWORDS = [
    "Report 總覽", "違規路徑", "通過路徑", "新人必知觀念", "建議行動"
]

def validate_output(text: str) -> tuple:
    missing = [
        kw for kw in REQUIRED_SECTION_KEYWORDS
        if not re.search(r"^#{1,3}\s*.*" + re.escape(kw), text, re.MULTILINE)
    ]
    return len(missing) == 0, missing

def call_llm(prompt: str, max_retries: int = 3) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "找不到 GROQ_API_KEY。\n"
            "請確認：\n"
            "  1. 執行目錄有 .env，內含 GROQ_API_KEY=your_key\n"
            "  2. 或執行 export GROQ_API_KEY=your_key"
        )

    client = Groq(api_key=api_key)
    last_error = None

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2
            )
            result = response.choices[0].message.content
            is_valid, missing = validate_output(result)
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
