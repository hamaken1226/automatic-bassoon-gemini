import streamlit as st
import pandas as pd
import plotly.express as px
import json
import gspread
from google.oauth2 import service_account

# ページの設定
st.set_page_config(page_title="化石化分析ダッシュボード", page_icon="📊", layout="wide")
st.title("📊 化石化 統合分析ダッシュボード")
st.write("スプレッドシートに蓄積された全テストの最終結果を統合・分析します。")

# --- 1. スプレッドシートへの接続 ---
gcp_info = dict(st.secrets["gcp_service_account"])
gcp_info["private_key"] = gcp_info["private_key"].replace("\\n", "\n")
scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
creds = service_account.Credentials.from_service_account_info(gcp_info, scopes=scopes)
client_gspread = gspread.authorize(creds)

# ※app.pyで設定したのと同じシート名にしてください
SHEET_NAME = "English_AI_Logs" 

# --- 2. データの取得と整形 ---
try:
    sheet = client_gspread.open(SHEET_NAME).sheet1
except Exception as e:
    st.error("スプレッドシートの読み込みに失敗しました。連携設定やシート名を確認してください。")
    st.stop()

with st.spinner("データベースから過去の全テスト結果を集計中..."):
    rows = sheet.get_all_values()
    
    dashboard_data = []
    # 最初の行から順番に見て、「FINAL」と記録された行だけを抽出
    for row in rows:
        if len(row) >= 5 and row[2] == "FINAL":
            try:
                # 5列目（インデックス4）にあるJSON文字列をPythonの辞書に変換
                data = json.loads(row[4])
                dashboard_data.append({
                    "timestamp": row[0],
                    "user_id": row[1],
                    "data": data
                })
            except Exception:
                continue

if not dashboard_data:
    st.info("まだテスト結果がありません。テスト画面から10問完了させてください。")
    st.stop()

# --- 3. ユーザー選択 ---
user_ids = list(set([d["user_id"] for d in dashboard_data]))
selected_user = st.sidebar.selectbox("👤 分析する被験者IDを選択", user_ids)

# 選択されたユーザーのデータだけを抽出
user_records = [d for d in dashboard_data if d["user_id"] == selected_user]
st.markdown(f"### 👤 被験者: {selected_user} (合計テスト実施回数: {len(user_records)}回)")

# グラフで使いやすいようにデータを平らにする（データフレーム化）
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

# --- 🌟 追加実装：総合CEFR判定 (Grammar & Accuracy) 🌟 ---
st.markdown("---")
st.markdown("### 🏆 総合CEFR判定 (Grammar & Accuracy)")

# 1. 全テストの平均エラー率を算出
overall_error_rate = df["エラー率"].mean()

# 2. 化石化フラグが立った総回数をカウント
total_fossilizations = df[df["化石化判定"] == True].shape[0]

# 3. CEFRランクの判定ロジック（C1・C2追加版）
if overall_error_rate <= 5 and total_fossilizations == 0:
    cefr_level = "C2 (熟練者レベル)"
    cefr_color = "#9C27B0" # Purple
    cefr_desc = "驚異的な正確性です。母語話者と同等の文法コントロール力を持ち、いかなる負荷がかかっても化石化のエラーを起こしません。まさにマスターレベルです。"
elif overall_error_rate <= 10 and total_fossilizations == 0:
    cefr_level = "C1 (上級・プロフェッショナル)"
    cefr_color = "#673AB7" # Deep Purple
    cefr_desc = "極めて高い正確性を誇ります。化石化の兆候は完全に払拭されており、複雑な文章でも文法的なミスを犯すことはほぼありません。"
elif overall_error_rate <= 15 and total_fossilizations <= 1:
    cefr_level = "B2 (実務対応レベル)"
    cefr_color = "#4CAF50" # Green
    cefr_desc = "素晴らしい文法コントロール力です。母語の干渉（化石化）もほぼ脱却しており、ビジネス環境でも十分に通用する正確性を備えています。"
elif overall_error_rate <= 30 and total_fossilizations <= 3:
    cefr_level = "B1 (日常会話レベル)"
    cefr_color = "#2196F3" # Blue
    cefr_desc = "基礎的な文法は習得できていますが、認知的負荷がかかる自由発話では特定の化石化（L1干渉）が顔を出します。弱点を意識することでB2へ到達可能です。"
elif overall_error_rate <= 50:
    cefr_level = "A2 (基礎レベル)"
    cefr_color = "#FF9800" # Orange
    cefr_desc = "基本的な文章は構成できますが、時制や3単現など全体的にエラーが散見されます。特定の化石化を気にするより、全体的な文法ルールの定着が必要です。"
else:
    cefr_level = "A1 (初学者レベル)"
    cefr_color = "#F44336" # Red
    cefr_desc = "英語の語順や基礎的なルールにまだ慣れていない状態です。まずは短い文章を正確に作るトレーニングから始めましょう。"

# 4. 画面に美しく描画
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

# --- 4. グラフの描画 ---
col1, col2 = st.columns(2)

with col1:
    st.markdown("#### 🕸️ 全テスト平均エラー率")
    # 観点ごとの平均エラー率を計算
    df_mean = df.groupby("観点")["エラー率"].mean().reset_index()
    fig_radar = px.line_polar(df_mean, r="エラー率", theta="観点", line_close=True, range_r=[0, 100])
    fig_radar.update_traces(fill='toself', line_color='#4169E1')
    st.plotly_chart(fig_radar, use_container_width=True)

with col2:
    st.markdown("#### 🚨 観点別の「化石化」検知回数")
    # 化石化判定がTrueになった回数をカウント
    df_fossil = df[df["化石化判定"] == True].groupby("観点").size().reset_index(name="回数")
    
    # 0回の観点もグラフに表示するための補完処理
    all_categories = pd.DataFrame({"観点": ["時制", "主語と動詞の一致", "名詞の境界", "構文・語順"]})
    df_fossil = pd.merge(all_categories, df_fossil, on="観点", how="left").fillna(0)
    
    # 棒グラフの作成
    fig_bar = px.bar(df_fossil, x="観点", y="回数", color="回数", color_continuous_scale="Reds")
    # 縦軸のメモリを整数にする
    fig_bar.update_yaxes(tickformat="d")
    st.plotly_chart(fig_bar, use_container_width=True)

st.markdown("---")
st.markdown("#### 📈 テスト毎の推移（エラー率の変化）")
# 時間経過によるエラー率の推移を折れ線グラフで表示
fig_line = px.line(df, x="テスト日時", y="エラー率", color="観点", markers=True)
fig_line.update_yaxes(range=[0, 100])
st.plotly_chart(fig_line, use_container_width=True)
