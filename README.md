<div align="center">

```
  ███████╗████████╗ █████╗     ██╗███╗   ██╗███████╗██╗ ██████╗ ██╗  ██╗████████╗
  ██╔════╝╚══██╔══╝██╔══██╗    ██║████╗  ██║██╔════╝██║██╔════╝ ██║  ██║╚══██╔══╝
  ███████╗   ██║   ███████║    ██║██╔██╗ ██║███████╗██║██║  ███╗███████║   ██║   
  ╚════██║   ██║   ██╔══██║    ██║██║╚██╗██║╚════██║██║██║   ██║██╔══██║   ██║   
  ███████║   ██║   ██║  ██║    ██║██║ ╚████║███████║██║╚██████╔╝██║  ██║   ██║   
  ╚══════╝   ╚═╝   ╚═╝  ╚═╝    ╚═╝╚═╝  ╚═══╝╚══════╝╚═╝ ╚═════╝╚═╝  ╚═╝   ╚═╝   
```

### 把 IC 設計的「部落知識」翻譯成新人也能看懂的語言

**An AI-assisted translator that turns cryptic STA reports into onboarding-friendly knowledge cards.**

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![LLM](https://img.shields.io/badge/LLM-Llama_3.3_70B-orange)
![Status](https://img.shields.io/badge/Status-MVP-yellow)
![Domain](https://img.shields.io/badge/Domain-CAD%2FEDA-green)

</div>

---

## 🎯 為什麼做這個？

在 IC 設計團隊裡，一份 5 萬行的 STA report，**資深工程師看 10 秒就知道哪裡要改，新人看 3 個月還在學語彙**。Log 變成了「部落方言」，知識傳承靠肉身在旁邊看，老人離職就斷層。

這不只是學生想像出來的問題——產業數據都在說同一件事：

> 📊 當組織離職率超過 20%，平均損失 **42% 的專案專屬知識**；每位開發者每週浪費約 **10 小時**只是在找他們本來就需要的基本資訊。  
> — [CISIN, Knowledge Loss in Engineering Teams](https://www.cisin.com)

> 📊 「複雜度在上升，開發窗口在縮短，在這種壓力下，你得開始看哪裡可以走捷徑」——而跨團隊的溝通摩擦正是最常被走捷徑、卻代價最高的地方。  
> — [Semiconductor Engineering, Verification Challenges](https://semiengineering.com)

> 📊 IC 設計需要大型跨領域團隊合作多年完成，設計資料從概念到 tape-out 呈指數成長；**但目前所有工具都是給工程師用的，沒有一個工具把技術現狀「翻譯」給管理層看**。  
> — [Keysight, EDA Workflow Analysis](https://www.keysight.com)

**STA Insight 是針對「病灶一：Log 密碼化 / 知識部落化」的第一個原型。**

---

## 🔭 設計框架：觀點 → 策略 → 手法 → 驗證

### 觀點（Perspective）
> EDA 流程產生的所有資料，**都是寫給「同一個讀者」（資深 IC 工程師）看的**。但實際上有 N 種讀者——新人、PM、跨團隊夥伴——沒人在做翻譯。

### 策略（Strategy）
做一個 **audience-aware（分眾感知）的翻譯層**，從最痛的場景切入：**「讓任何人 30 秒內看懂一份 STA report 的關鍵問題」**。

### 手法（Method）
1. 讀取原始 STA report（純文字）
2. 用 LLM（Llama 3.3 70B via Groq）做語意理解
3. 結構化輸出五大區塊：
   - Report Overview
   - Violated Paths
   - Met Paths  
   - Key Concepts（slack / startpoint / clock skew）
   - Recommended Actions
4. 用 `rich` 在 terminal 渲染為易讀的卡片

### 驗證（Validation）
- ✅ 對 sample report 能產出結構化解釋
- 🚧 量化指標尚待補完（閱讀時間實驗、LLM 正確率抽樣）
- 🚧 邊界測試（>1MB 大型 report、LLM 幻覺防護）

---

## 🎬 Before / After

### Before（工程師看到的原始 STA report）
```
PATH 1 - VIOLATED
  Startpoint : clk_div/q_reg[3] (rising edge-triggered flip-flop clocked by CLK)
  Endpoint   : alu/result_reg[7] (rising edge-triggered flip-flop clocked by CLK)
  slack (VIOLATED) : -0.347 ns
  ... (數百行細節)
```

### After（STA Insight 產出的知識卡片）
```
┌─ STA Insight ────────────────────────────────────────────┐
│  📋 Report Overview                                       │
│  Design: cpu_core_top  |  3 paths analyzed  |  2 failed   │
│                                                           │
│  ❌ Violated Paths                                        │
│  • CLK group: 2 critical setup violations (-0.347, -0.892)│
│  • Likely root cause: combinational logic depth in ALU    │
│                                                           │
│  💡 Key Concepts (for new engineers)                     │
│  • slack: 訊號到達與需求時間的差，負值代表 timing 違反     │
│  • startpoint/endpoint: 訊號的起點與終點 flip-flop         │
│                                                           │
│  🔧 Recommended Actions                                   │
│  1. Re-pipeline ALU result path                          │
│  2. Check clock skew for io_ctrl domain                  │
└──────────────────────────────────────────────────────────┘
```

---

## 🚀 使用方式

### 環境需求
- Python 3.10+
- Linux / WSL2
- Groq API Key（[免費取得](https://console.groq.com)）

### 安裝
```bash
# Clone repo
git clone https://github.com/Pric0123/sta-insight.git
cd sta-insight

# 建立虛擬環境
python3 -m venv ~/sta-insight-env
source ~/sta-insight-env/bin/activate

# 安裝套件
pip install groq python-dotenv rich

# 設定 API Key
echo "GROQ_API_KEY=your_key_here" > .env
```

### 執行
```bash
python3 sta_parser.py sta_report_sample.txt
```

---

## 🛠 技術堆疊

| 層級 | 技術 |
|---|---|
| 語言 | Python 3 |
| LLM | Llama 3.3 70B (Groq inference) |
| Terminal UI | rich |
| 環境管理 | python-dotenv, venv |
| 版本控制 | Git / GitHub |
| 執行環境 | Linux (WSL2 Ubuntu) |

---

## 📍 目前限制（誠實揭露）

這是一個 **MVP**，刻意做小、做快、做對方向。已知限制：

- ❗ **完全依賴 LLM**：尚未加入 deterministic parser 做交叉驗證，存在幻覺風險
- ❗ **單檔處理**：目前一次只能解析一份 report
- ❗ **範例為自製**：尚未對接真實 OpenROAD / Yosys 流程產生的 log
- ❗ **無評估指標**：閱讀時間實驗、LLM 正確率抽樣尚未進行

---

## 🗺 Roadmap

### Phase 1（目前）
- [x] 單檔 STA report 解析 + LLM 翻譯
- [x] Terminal 友善輸出
- [ ] Streamlit Web UI（給非工程師讀者用）

### Phase 2
- [ ] 接 OpenROAD / Yosys 真實 log 來源
- [ ] Deterministic parser + LLM hybrid（防幻覺）
- [ ] 評估報告：閱讀時間、正確率、資訊壓縮率

### Phase 3
- [ ] 延伸到病灶三：自動寄送「給 PM 看的一頁摘要 email」
- [ ] CI 整合（每次 RTL 變更自動產出 insight）

---

## 👤 關於作者

楊元蓁（Price Yang）｜中原大學工業與系統工程學系 & 建築學系雙主修

跨域思維 × Python 自動化 × AI 工具實戰應用。本專案為 **2026 瑞昱半導體暑期實習【CAD/EDA 開發（AI 輔助設計）】** 申請作品。

📧 willyang2002@gmail.com  
🐙 [@Pric0123](https://github.com/Pric0123)

---

<div align="center">

**「真正的工程創新來自跨領域的視角。」**

</div>
