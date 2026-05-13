import streamlit as st
import pandas as pd
import streamlit as st
from openai import OpenAI
import gspread
from google.oauth2 import service_account
from googleapiclient.discovery import build
import json

# --- 1. 設定 & 認証 ---
# Secretsから情報を取得
api_key = st.secrets["OPENAI_API_KEY"]

# 👇 ここからが裏技（辞書に変換して、無理やり改行コードを本物の改行に置換する）
gcp_info = dict(st.secrets["gcp_service_account"])
gcp_info["private_key"] = gcp_info["private_key"].replace("\\n", "\n")
# 👆 ここまで

# OpenAIクライアント
client = OpenAI(api_key=api_key)

scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
creds = service_account.Credentials.from_service_account_info(gcp_info, scopes=scopes)
gc = gspread.authorize(creds)
# ...以降は元のまま

# --- スプレッドシート操作用の関数 ---
def save_log_to_sheets(data):
    # 名前でシートを開く
    sheet = gc.open("English_AI_Logs").sheet1
    sheet.append_row(data)

def get_user_history(user_id):
    # 過去のそのユーザーのデータを取得して分析に使う
    sheet = gc.open("English_AI_Logs").sheet1
    all_records = pd.DataFrame(sheet.get_all_records())
    if not all_records.empty:
        return all_records[all_records['user_id'] == user_id]
    return pd.DataFrame()

# --- メインロジック（ここにこれまでの10問テストのコードを入れる） ---
# st.session_state でステップ管理
# 録音が終わるたびに save_log_to_sheets() を呼び出す
