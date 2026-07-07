import streamlit as st
import pandas as pd
import plotly.express as px
import json
import gspread
from google.oauth2 import service_account

st.set_page_config(page_title="管理者ダッシュボード", page_icon="🔐", layout="wide")
st.title("🔐 管理者ダッシュボード")

# --- 管理者認証 ---
if "admin_authenticated" not in st.session_state:
    st.session_state.admin_authenticated = False

if not st.session_state.admin_authenticated:
    st.markdown("### 管理者ログイン")
    st.write("このページは管理者専用です。パスワードを入力してください。")
    pwd = st.text_input("管理者パスワード", type="password")
    if st.button("ログイン"):
        if pwd == st.secrets.get("admin_password", ""):
            st.session_state.admin_authenticated = True
            st.rerun()
        else:
            st.error("パスワードが違います")
    st.stop()

if st.sidebar.button("🚪 ログアウト"):
    st.session_state.admin_authenticated = False
    st.rerun()
st.sidebar.success("✅ 管理者としてログイン中")

# --- スプレッドシートへの接続 ---
gcp_info = dict(st.secrets["gcp_service_account"])
gcp_info["private_key"] = gcp_info["private_key"].replace("\\n", "\n")
scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
creds = service_account.Credentials.from_service_account_info(gcp_info, scopes=scopes)
client_gspread = gspread.authorize(creds)

SHEET_NAME = "English_AI_Logs_Gemini"

try:
    sheet = client_gspread.open(SHEET_NAME).sheet1
except Exception:
    st.error("スプレッドシートの読み込みに失敗しました。")
    st.stop()

with st.spinner("全テスターのデータを集計中..."):
    rows = sheet.get_all_values()
    dashboard_data = []
    for row in rows:
        if len(row) >= 6 and row[2] == "FINAL":
            try:
                data = json.loads(row[5])
                dashboard_data.append({
                    "timestamp": row[0],
                    "user_id": row[1],
                    "data": data
                })
            except Exception:
                continue

if not dashboard_data:
    st.info("まだテスト結果がありません。")
    st.stop()

# CEFR判定ヘルパー
CEFR_DESCS = {
    "C2": ("C2 (熟練者レベル)", "#9C27B0", "驚異的な正確性です。母語話者と同等の文法コントロール力を持ち、いかなる負荷がかかっても化石化のエラーを起こしません。まさにマスターレベルです。"),
    "C1": ("C1 (上級・プロフェッショナル)", "#673AB7", "極めて高い正確性を誇ります。化石化の兆候は完全に払拭されており、複雑な文章でも文法的なミスを犯すことはほぼありません。"),
    "B2": ("B2 (実務対応レベル)", "#4CAF50", "素晴らしい文法コントロール力です。母語の干渉（化石化）もほぼ脱却しており、ビジネス環境でも十分に通用する正確性を備えています。"),
    "B1": ("B1 (日常会話レベル)", "#2196F3", "基礎的な文法は習得できていますが、認知的負荷がかかる自由発話では特定の化石化（L1干渉）が顔を出します。弱点を意識することでB2へ到達可能です。"),
    "A2": ("A2 (基礎レベル)", "#FF9800", "基本的な文章は構成できますが、時制や3単現など全体的にエラーが散見されます。特定の化石化を気にするより、全体的な文法ルールの定着が必要です。"),
    "A1": ("A1 (初学者レベル)", "#F44336", "英語の語順や基礎的なルールにまだ慣れていない状態です。まずは短い文章を正確に作るトレーニングから始めましょう。"),
}

def get_cefr_key(error_rate, fossilization_count):
    if error_rate <= 5 and fossilization_count == 0:
        return "C2"
    elif error_rate <= 10 and fossilization_count == 0:
        return "C1"
    elif error_rate <= 15 and fossilization_count <= 1:
        return "B2"
    elif error_rate <= 30 and fossilization_count <= 3:
        return "B1"
    elif error_rate <= 50:
        return "A2"
    else:
        return "A1"

# --- 全テスター一覧 ---
st.markdown("## 👥 全テスター 結果一覧")

user_ids = sorted(set([d["user_id"] for d in dashboard_data]))

summary_rows = []
for uid in user_ids:
    records = [d for d in dashboard_data if d["user_id"] == uid]
    flat = []
    for rec in records:
        for cat in rec["data"]["categories"]:
            flat.append({
                "観点": cat["name"],
                "エラー率": float(cat["error_rate"]),
                "化石化判定": cat["is_fossilized"]
            })
    df_u = pd.DataFrame(flat)
    avg_error = df_u["エラー率"].mean()
    fossil_count = int(df_u[df_u["化石化判定"] == True].shape[0])
    fossil_cats = df_u[df_u["化石化判定"] == True]["観点"].unique().tolist()
    cefr_key = get_cefr_key(avg_error, fossil_count)
    summary_rows.append({
        "テスターID": uid,
        "テスト回数": len(records),
        "平均エラー率": f"{avg_error:.1f}%",
        "化石化検知回数": fossil_count,
        "化石化カテゴリ": "、".join(fossil_cats) if fossil_cats else "なし",
        "推定CEFR": cefr_key,
        "最終受験日時": sorted([r["timestamp"] for r in records])[-1],
    })

df_summary = pd.DataFrame(summary_rows)
st.dataframe(df_summary, use_container_width=True, hide_index=True)

# --- テスター別詳細 ---
st.markdown("---")
st.markdown("## 🔍 テスター別 詳細分析")
selected_user = st.sidebar.selectbox("👤 分析するテスターを選択", user_ids)

user_records = [d for d in dashboard_data if d["user_id"] == selected_user]
st.markdown(f"### 👤 テスター: {selected_user}（テスト実施回数: {len(user_records)}回）")

flat_data = []
for rec in user_records:
    for cat in rec["data"]["categories"]:
        flat_data.append({
            "テスト日時": rec["timestamp"],
            "観点": cat["name"],
            "エラー率": float(cat["error_rate"]),
            "化石化判定": cat["is_fossilized"]
        })

df = pd.DataFrame(flat_data)

overall_error_rate = df["エラー率"].mean()
total_fossilizations = df[df["化石化判定"] == True].shape[0]
cefr_key = get_cefr_key(overall_error_rate, total_fossilizations)
cefr_level, cefr_color, cefr_desc = CEFR_DESCS[cefr_key]

st.markdown("---")
st.markdown("### 🏆 総合CEFR判定 (Grammar & Accuracy)")
st.markdown(
    f"""
    <div style="background-color: {cefr_color}20; padding: 20px; border-radius: 10px; border-left: 8px solid {cefr_color}; margin-bottom: 20px;">
        <h2 style="margin: 0; color: {cefr_color};">推定レベル: {cefr_level}</h2>
        <p style="margin-top: 10px; font-size: 16px;">
            <b>分析データ:</b> 平均エラー率 {overall_error_rate:.1f}% / 化石化検知 {total_fossilizations}回<br>
            <b>AI総評:</b> {cefr_desc}
        </p>
    </div>
    """,
    unsafe_allow_html=True
)

col1, col2 = st.columns(2)

with col1:
    st.markdown("#### 🕸️ 全テスト平均エラー率")
    df_mean = df.groupby("観点")["エラー率"].mean().reset_index()
    fig_radar = px.line_polar(df_mean, r="エラー率", theta="観点", line_close=True, range_r=[0, 100])
    fig_radar.update_traces(fill='toself', line_color='#4169E1')
    st.plotly_chart(fig_radar, use_container_width=True)

with col2:
    st.markdown("#### 🚨 観点別の「化石化」検知回数")
    df_fossil = df[df["化石化判定"] == True].groupby("観点").size().reset_index(name="回数")
    all_categories = pd.DataFrame({"観点": ["時制", "主語と動詞の一致", "名詞の境界", "構文・語順"]})
    df_fossil = pd.merge(all_categories, df_fossil, on="観点", how="left").fillna(0)
    fig_bar = px.bar(df_fossil, x="観点", y="回数", color="回数", color_continuous_scale="Reds")
    fig_bar.update_yaxes(tickformat="d")
    st.plotly_chart(fig_bar, use_container_width=True)

st.markdown("---")
st.markdown("#### 📈 テスト毎の推移（エラー率の変化）")
fig_line = px.line(df, x="テスト日時", y="エラー率", color="観点", markers=True)
fig_line.update_yaxes(range=[0, 100])
st.plotly_chart(fig_line, use_container_width=True)
