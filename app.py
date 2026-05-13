import streamlit as st
from openai import OpenAI
import gspread
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io
import json
from datetime import datetime
from streamlit_mic_recorder import mic_recorder

# --- 1. 認証設定（この部分はもう完璧に動いています！） ---
api_key = st.secrets["OPENAI_API_KEY"]
gcp_info = dict(st.secrets["gcp_service_account"])
gcp_info["private_key"] = gcp_info["private_key"].replace("\\n", "\n")

client = OpenAI(api_key=api_key)

scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
creds = service_account.Credentials.from_service_account_info(gcp_info, scopes=scopes)
gc = gspread.authorize(creds)
drive_service = build('drive', 'v3', credentials=creds)

# --- 2. 保存先の設定（★ここを自分のものに変更してください） ---
SHEET_NAME = "English_AI_Logs" # スプレッドシートの名前
DRIVE_FOLDER_ID = "1Q61NT7q7gSTd6gqmykyO46DBiU9KR5IU" # 例: "1A2b3C4d5E6f7G8h9I0j..."

# --- 3. アプリの設定 ---
st.set_page_config(page_title="English Level Checker", layout="centered")
st.title("🎓 英語レベル・化石化診断テスト")

if 'step' not in st.session_state:
    st.session_state.step = 0
    st.session_state.results = []

def move_to_next():
    st.session_state.step += 1

# サイドバー設定
with st.sidebar:
    st.header("⚙️ 実験管理")
    user_id = st.text_input("被験者ID", value="P001")
    if st.button("テストを最初からやり直す"):
        st.session_state.step = 0
        st.session_state.results = []
        st.rerun()

# --- 4. 質問リスト ---
QUESTIONS = [
    {"type": "TRANS", "q": "「昨日、友達と映画を見に行きました。」を英語にしてください。"},
    {"type": "TRANS", "q": "「私は3年間、ずっと英語を勉強しています。」を英語にしてください。"},
    {"type": "TRANS", "q": "「もし明日晴れたら、公園に行きたいです。」を英語にしてください。"},
    {"type": "TRANS", "q": "「これは、私が先週買った本です。」を英語にしてください。"},
    {"type": "TRANS", "q": "「コーヒーを飲むことと、本を読むことが好きです。」を英語にしてください。"},
    {"type": "FREE", "q": "Please introduce yourself in detail."},
    {"type": "FREE", "q": "What is your favorite food and why?"},
    {"type": "FREE", "q": "What did you do last weekend?"},
    {"type": "FREE", "q": "What are your thoughts on using AI for learning?"},
    {"type": "FREE", "q": "What is your dream for the future?"}
]

# --- 5. メインロジック ---
if st.session_state.step < len(QUESTIONS):
    current_q = QUESTIONS[st.session_state.step]
    st.subheader(f"第 {st.session_state.step + 1} 問 / {len(QUESTIONS)}")
    
    if current_q["type"] == "TRANS":
        st.warning(f"**指定フレーズを英語に直してください：**\n\n {current_q['q']}")
    else:
        st.info(f"**自由にお答えください：**\n\n {current_q['q']}")

    audio_data = mic_recorder(
        start_prompt=f"第{st.session_state.step + 1}問 録音開始 🎙️",
        stop_prompt="録音停止 ⏹️",
        key=f'recorder_{st.session_state.step}'
    )

    if audio_data:
        if len(st.session_state.results) <= st.session_state.step:
            with st.spinner("音声を処理・保存中..."):
                timestamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
                file_name = f"{user_id}_Q{st.session_state.step+1}_{timestamp.replace('/','').replace(':','').replace(' ','_')}.wav"
                
                # ① OpenAIで文字起こし
                audio_bytes = audio_data['bytes']
                with io.BytesIO(audio_bytes) as audio_file:
                    audio_file.name = "audio.wav"
                    transcript = client.audio.transcriptions.create(
                        model="whisper-1", 
                        file=audio_file
                    )
                
                # ② Googleドライブに音声をアップロード
                file_metadata = {'name': file_name, 'parents': [DRIVE_FOLDER_ID]}
                media = MediaIoBaseUpload(io.BytesIO(audio_bytes), mimetype='audio/wav', resumable=True)
              　drive_service.files().create(body=file_metadata, media_body=media, fields='id', supportsAllDrives=True).execute()
                # ③ スプレッドシートに記録
                sheet = gc.open(SHEET_NAME).sheet1
                sheet.append_row([timestamp, user_id, st.session_state.step + 1, current_q['q'], transcript.text])
                
                st.session_state.results.append({
                    "question": current_q['q'],
                    "type": current_q['type'],
                    "answer": transcript.text
                })
        
        st.success(f"回答を記録しました： {st.session_state.results[st.session_state.step]['answer']}")
        st.button("次の問題へ進む ➡️", on_click=move_to_next)

# --- 6. 最終診断 ---
else:
    st.subheader("🏁 全10問完了！総合診断中...")
    with st.spinner("AI先生が全ての回答を分析しています..."):
        summary_text = ""
        for i, res in enumerate(st.session_state.results):
            summary_text += f"Q{i+1}: {res['question']}\n回答: {res['answer']}\n\n"

        analysis_prompt = """
        あなたは英語教育の専門家です。10問の回答データを基に、詳細な英語能力診断を行ってください。
        
        【出力フォーマット】
        ## 📊 総合診断レポート
        ### 🌟 推定レベル: [CEFRレベル]
        ### 🚨 検出された「化石化」の兆候
        ### 👩‍🏫 今後の学習アドバイス
        """

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": analysis_prompt}, {"role": "user", "content": summary_text}],
            temperature=0
        )
        final_report = response.choices[0].message.content
        st.markdown(final_report)
        
        # 最終結果もスプレッドシートに保存
        timestamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        sheet = gc.open(SHEET_NAME).sheet1
        sheet.append_row([timestamp, user_id, "FINAL", "総合診断レポート", final_report])

    st.balloons()
