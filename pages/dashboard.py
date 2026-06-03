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
