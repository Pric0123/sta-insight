from datetime import date

def generate_summary_prompt(facts):
    today = date.today().strftime("%Y-%m-%d")
    status = "🔴 無法 tape-out" if facts["violated_count"] > 0 else "🟢 可以 tape-out"
    
    prompt = f"""你是一位資深 IC 設計主管，請用繁體中文回答。

產生一份給管理層看的設計狀態週報，格式如下，請嚴格遵守：

【設計狀態週報】{facts['design_name']}
日期：{today}
狀態：{status}

關鍵問題：（一句話，不超過30字）
預估修復：（X-Y 天）
建議決策：（一句話行動建議）
風險評估：（低/中/高，加一句說明）

技術摘要（給有技術背景的主管）：
- violated 路徑數：{facts['violated_count']}
- 最嚴重 slack：{min(facts['violated_slacks']) if facts['violated_slacks'] else 'N/A'} ns
- 通過路徑數：{facts['met_count']}

以下是確定的技術事實：
違規路徑 slack 值：{facts['violated_slacks']}
通過路徑 slack 值：{facts['met_slacks']}
Startpoints：{facts['startpoints'][:3]}
Endpoints：{facts['endpoints'][:3]}

請根據以上資訊填寫週報，語言簡潔、不用技術術語，讓非工程師能理解。"""
    
    return prompt
