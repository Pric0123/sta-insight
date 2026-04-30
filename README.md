<div align="center">

<pre><code>
  ███████╗████████╗ █████╗     ██╗███╗   ██╗███████╗██╗ ██████╗ ██╗  ██╗████████╗
  ██╔════╝╚══██╔══╝██╔══██╗    ██║████╗  ██║██╔════╝██║██╔════╝ ██║  ██║╚══██╔══╝
  ███████╗   ██║   ███████║    ██║██╔██╗ ██║███████╗██║██║  ███╗███████║   ██║   
  ╚════██║   ██║   ██╔══██║    ██║██║╚██╗██║╚════██║██║██║   ██║██╔══██║   ██║   
  ███████║   ██║   ██║  ██║    ██║██║ ╚████║███████║██║╚██████╔╝██║  ██║   ██║   
  ╚══════╝   ╚═╝   ╚═╝  ╚═╝    ╚═╝╚═╝  ╚═══╝╚══════╝╚═╝ ╚═════╝╚═╝  ╚═╝   ╚═╝   
</code></pre>

### 把 IC 設計的「部落知識」翻譯成新人也能看懂的語言

**An AI-assisted translator that turns cryptic STA reports into onboarding-friendly knowledge cards.**

<p>
  <img src="https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/LLM-Llama_3.3_70B-orange" alt="LLM">
  <img src="https://img.shields.io/badge/Parser-Deterministic_Hybrid-red" alt="Parser">
  <img src="https://img.shields.io/badge/Domain-CAD%2FEDA-green" alt="Domain">
</p>

</div>

---

## 🎯 為什麼做這個？

在 IC 設計團隊裡，一份 5 萬行的 STA report，**資深工程師看 10 秒就知道哪裡要改，新人看 3 個月還在學語彙**[cite: 1]。Log 變成了「部落方言」，知識傳承靠肉身在旁邊看，老人離職就斷層[cite: 1]。

**STA Insight 透過「確定性解析 (Deterministic Parsing) + 大語言模型 (LLM)」的混合架構，精準提取關鍵數據並轉譯為易讀的知識卡片，解決 Log 密碼化與知識部落化的病灶**[cite: 1, 3]。

---

## 🔭 設計框架：觀點 → 策略 → 手法 → 驗證

### 觀點 (Perspective)
EDA 流程產生的所有資料，都是寫給資深工程師看的[cite: 1]。我們需要一個 **Audience-aware (分眾感知)** 的翻譯層[cite: 1]。

### 策略 (Strategy)
建立 **Deterministic Parser + LLM Hybrid** 架構[cite: 3]。利用程式邏輯確保數據 100% 準確，利用 AI 進行人性化翻譯並排除幻覺風險[cite: 3]。

### 手法 (Method)
1. **區塊化解析 (Block Parsing)**：將大型報告切割成獨立 Path 區塊，精準提取 Slack、Path Group 與 Setup/Hold 類型[cite: 3]。
2. **邏輯深度計算 (Logic Depth Calculation)**：自動統計 Standard Cell 數量，量化路徑複雜度以輔助診斷[cite: 3]。
3. **防幻覺護欄 (Guardrails)**：在 Prompt Level 建立物理規則，防止 LLM 在 Setup/Hold 判斷上產生錯誤建議（例如：禁止在 Hold violation 時建議減少邏輯）[cite: 3]。
4. **低溫控制 (Low Temp Inference)**：將推理溫度設為 `0.2`，確保輸出穩定嚴謹，減少模型發散[cite: 3]。

### 驗證 (Validation)
- ✅ **數據準確性**：對 sample report 的 Slack 與路徑數量能達到 100% 正確解析[cite: 1]。
- ✅ **防幻覺測試**：能精確區分 Max/Min 路徑並根據邏輯深度給予對應的物理修正建議[cite: 3]。
- 🚧 **擴展性測試**：針對 >1MB 大型 report 的效能優化與截斷策略驗證[cite: 1, 3]。

---

## 🎬 Before / After

### Before (原始報告)
```text
PATH 1 - VIOLATED
  Startpoint : clk_div/q_reg[3]
  Endpoint   : alu/result_reg[7]
  slack (VIOLATED) : -0.347 ns
  ... (數百行邏輯節點與延遲數據)
```

### After (STA Insight 產出的知識卡片)
```text
┌─ ChipMentor 知識卡片 ────────────────────────────────────┐
│  📋 Report Overview                                      │
│  Design: cpu_core_top | 2 paths violated                 │
│                                                          │
│  ❌ 違規路徑分析                                         │
│  • PATH 1 (Setup Time): Slack -0.347ns, 邏輯深度 4       │
│  • 推論: 深度較低但仍違規，應優先檢查 Fanout 與 Net Delay  │
│                                                          │
│  🔧 建議行動 (具體排查步驟)                              │
│  1. 使用 GUI 開啟 Schematic 檢查該路徑的負載狀況          │
│  2. 確認 Clock Tree 是否存在異常的 Skew                  │
└──────────────────────────────────────────────────────────┘
```

---

## 🚀 快速開始

### 環境需求
- Python 3.10+[cite: 1]
- Linux / WSL2[cite: 1]
- Groq API Key[cite: 1, 3]

### 安裝與執行
```bash
# Clone repo
git clone [https://github.com/Pric0123/sta-insight.git](https://github.com/Pric0123/sta-insight.git)
cd sta-insight

# 建立虛擬環境
python3 -m venv ~/sta-insight-env
source ~/sta-insight-env/bin/activate

# 安裝依賴
pip install groq python-dotenv rich

# 設定 API Key
echo "GROQ_API_KEY=your_key_here" > .env

# 執行啟動腳本
./run.sh sta_report_sample.txt
```

---

## 🛠 技術堆疊

| 層級 | 技術 |
|---|---|
| **解析引擎** | Regex-based Deterministic Block Parser[cite: 3] |
| **推理核心** | Llama 3.3 70B (via Groq Cloud Inference)[cite: 1, 3] |
| **防護機制** | Physical Rules Guardrails (Temperature=0.2)[cite: 3] |
| **UI 渲染** | Rich (Terminal-based Knowledge Cards)[cite: 1, 3] |

---

## 📍 目前限制 

- ❗ **單檔處理**：目前一次僅支援單份 report 解析[cite: 1]。
- ❗ **格式依賴**：目前的邏輯深度計算基於標準 cell 命名格式，非標準格式可能導致計數偏移[cite: 3]。
- ❗ **工具整合**：尚未直接與 EDA 工具 (如 OpenROAD/Yosys) 的 API 或資料庫連動[cite: 1]。

---

## 👤 關於作者

楊元蓁 (Price Yang) ｜ 中原大學 工業與系統工程學系 & 建築學系 雙主修[cite: 1]
📧 willyang2002@gmail.com[cite: 1]
🐙 [@Pric0123](https://github.com/Pric0123)[cite: 1]

---

<div align="center">


</div>
