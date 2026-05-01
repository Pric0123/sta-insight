"""
core/prompts/onboarding.py
病灶一：新人 onboarding prompt
目標讀者：剛入職的 IC 設計新人
"""
import json

def build_prompt(structured_data: dict, chunked_report: str) -> str:
    confidence = structured_data.get("parse_confidence", "high")
    fmt = structured_data.get("format", "unknown")

    violated_display = []
    for p in structured_data.get("violated_paths", []):
        violated_display.append({
            "startpoint": p["startpoint"],
            "endpoint": p["endpoint"],
            "slack_ns": p["slack_ns"],
            "path_type": p["path_type"],
            "path_group": p["path_group"],
            "logic_depth": p.get("logic_depth_display", "未知")
        })

    base = f"""你是一位資深 IC 設計工程師，正在幫助**剛入職的新人**理解 STA report。請用**繁體中文**回答，語氣親切，術語要有白話解釋。

Report 格式：{fmt}
以下是 ground truth（Deterministic Parser 解析結果）：

- 設計名稱：{structured_data.get('design') or '未偵測到'}
- 總路徑數：{structured_data.get('total_paths', 0)}
- 違規路徑數：{structured_data.get('violated_count', 0)} 條
- 通過路徑數：{structured_data.get('met_count', 0)} 條
- 違規路徑詳細：
{json.dumps(violated_display, ensure_ascii=False, indent=2)}

🚨 【防幻覺守則】🚨
1. path_type 'max (Setup Time)'：建議減少邏輯深度、換大 driving cell。
2. path_type 'min (Hold Time)'：禁止建議減少邏輯！必須建議增加 Delay。
3. logic_depth「無法解析」：禁止推測深度。
4. 資訊不足時寫「資訊不足，無法判斷」。
5. 建議行動要具體，給下一步排查指令。
"""

    if confidence in ("low", "medium"):
        base += f"\n⚠️  Parser 信心度為 {confidence}，提供原始片段：\n{chunked_report}"

    base += """

請**嚴格**依照以下格式輸出：

## 🔍 Report 總覽
## ⚠️ 違規路徑分析
## ✅ 通過路徑
## 🧠 新人必知觀念
1. **Slack**：
2. **Startpoint / Endpoint**：
3. **Clock Skew**：
## 🛠️ 建議行動
"""
    return base
