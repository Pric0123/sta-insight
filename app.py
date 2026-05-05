import streamlit as st
import os
import re
import time
from groq import Groq
from dotenv import load_dotenv
from core.parser import extract_paths, smart_chunk, read_report
from roles.prompts import ROLE_PROMPTS
from roles.summary import generate_summary_prompt
from core.prompts.onboarding import build_prompt

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

ROLE_LABELS = {
    "newbie": "新人工程師",
    "rtl": "RTL 工程師",
    "backend": "後端工程師",
    "verification": "驗證工程師",
    "pm": "專案經理"
}

def call_llm(prompt, role="newbie"):
    api_key = os.environ.get("GROQ_API_KEY")
    client = Groq(api_key=api_key)
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                timeout=30
            )
            return response.choices[0].message.content
        except Exception as e:
            if attempt < 2:
                time.sleep(3)
            else:
                raise e

st.set_page_config(page_title="ChipMentor", page_icon="🔬", layout="wide")
st.title("🔬 ChipMentor")
st.caption("IC 設計 STA Report 知識結構化系統")

with st.sidebar:
    st.header("設定")
    mode = st.radio("模式", ["角色分析", "管理層週報"])
    if mode == "角色分析":
        role = st.selectbox("選擇角色", list(ROLE_LABELS.keys()), format_func=lambda x: ROLE_LABELS[x])
    else:
        role = "pm"

uploaded_file = st.file_uploader("上傳 STA Report", type=["txt", "rpt", "log"])

if uploaded_file:
    report_content = uploaded_file.read().decode("utf-8")
    data = extract_paths(report_content)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("設計名稱", data["design"] or "Unknown")
    col2.metric("總路徑數", data["total_paths"])
    col3.metric("違規路徑", data["violated_count"])
    col4.metric("通過路徑", data["met_count"])

    if data["violated_count"] > 0:
        worst = min(p["slack_ns"] for p in data["violated_paths"])
        st.error(f"發現 {data['violated_count']} 條違規路徑，最嚴重：{worst} ns")
    else:
        st.success("所有路徑通過 timing 檢查！")

    if data["parse_warnings"]:
        for w in data["parse_warnings"]:
            st.warning(w)

    if st.button("開始分析", type="primary"):
        with st.spinner("AI 分析中..."):
            try:
                chunked = smart_chunk(report_content, data["format"])
                if mode == "管理層週報":
                    facts = {
                        "design_name": data["design"] or "Unknown",
                        "total_paths": data["total_paths"],
                        "violated_count": data["violated_count"],
                        "met_count": data["met_count"],
                        "violated_slacks": [str(p["slack_ns"]) for p in data["violated_paths"]],
                        "met_slacks": [str(p["slack_ns"]) for p in data["met_paths"]],
                        "startpoints": [p["startpoint"] for p in data["violated_paths"]],
                        "endpoints": [p["endpoint"] for p in data["violated_paths"]],
                    }
                    prompt = generate_summary_prompt(facts)
                    result = call_llm(prompt, role="pm")
                    st.subheader("設計狀態週報")
                    st.text(result)
                else:
                    if role == "newbie":
                        prompt = build_prompt(data, chunked)
                    else:
                        facts_summary = f"設計：{data['design']}，violated：{data['violated_count']}，slacks：{[p['slack_ns'] for p in data['violated_paths']]}"
                        prompt = f"{ROLE_PROMPTS[role]}\n\n確定事實：{facts_summary}\n\nReport：{chunked}"
                    result = call_llm(prompt, role=role)
                    st.subheader(f"{ROLE_LABELS[role]}視角分析")
                    st.markdown(result)
            except Exception as e:
                st.error(f"分析失敗：{e}")
else:
    st.info("請上傳 STA report 檔案開始分析")
