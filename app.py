import streamlit as st
from streamlit_mic_recorder import mic_recorder
from openai import OpenAI
from google.cloud import storage
import gspread
from google.oauth2 import service_account
from datetime import datetime
import io

import json
import pandas as pd
import plotly.express as px

# --- 1. 認証設定（ここは変更なし！今の鍵がそのまま使えます） ---
api_key = st.secrets["OPENAI_API_KEY"]
gcp_info = dict(st.secrets["gcp_service_account"])
gcp_info["private_key"] = gcp_info["private_key"].replace("\\n", "\n")

client = OpenAI(api_key=api_key)

# スプレッドシート用の認証
scopes = [
    "https://www.googleapis.com/auth/spreadsheets", 
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/cloud-platform" 
]
creds = service_account.Credentials.from_service_account_info(gcp_info, scopes=scopes)
gc = gspread.authorize(creds)

# Cloud Storage用の認証
storage_client = storage.Client(credentials=creds, project=gcp_info["project_id"])

# --- 2. 保存先の設定（★ここを変更してください） ---
SHEET_NAME = "English_AI_Logs" # スプレッドシートの名前
BUCKET_NAME = "kentaengspeakingtest202605131619" # 例: "hamaguchi-thesis-audio"

# --- 3. アプリの設定 ---
st.set_page_config(page_title="English Level Checker", layout="centered")
st.title("🎓 英語レベル・化石化診断テスト")

if 'step' not in st.session_state:
    st.session_state.step = 0
if 'results' not in st.session_state:
    st.session_state.results = []
if 'attempt' not in st.session_state:
    st.session_state.attempt = 0

# サイドバー設定
with st.sidebar:
    st.header("⚙️ 実験管理")
    user_id = st.text_input("被験者ID", value="P001")
    
    # 👇 新しく「セット選択」のプルダウンを追加！
    selected_set = st.selectbox("テストセットを選択", ["Set A", "Set B", "Set C", "Set D"])
    
    if st.button("テストを最初からやり直す"):
        st.session_state.step = 0
        st.session_state.results = []
        st.session_state.attempt = 0
        st.rerun()

# --- 4. 質問リスト ---
ALL_QUESTIONS = {
    "Set A": [
        {"type": "TRANS", "q": "「私は3年間、ずっと英語を勉強しています。」を英語にしてください。"},
        {"type": "TRANS", "q": "「これは、私が昨日買った本です。」を英語にしてください。"},
        {"type": "FREE", "q": "Please introduce yourself in detail."},
        {"type": "FREE", "q": "What do you enjoy doing in your free time?"},
        {"type": "FREE", "q": "Tell me about what your best friend usually does on weekends."},
        {"type": "FREE", "q": "What did you do last weekend? Please explain in detail."},
        {"type": "FREE", "q": "How long have you lived in your current city or town?"},
        {"type": "FREE", "q": "Describe a person who has influenced your life."},
        {"type": "FREE", "q": "What is your favorite food and why?"},
        {"type": "FREE", "q": "What is something you want to achieve in the next 5 years?"}
    ],
    "Set B": [
        {"type": "TRANS", "q": "「私は小学生の時から、ピアノを習っています。」を英語にしてください。"},
        {"type": "TRANS", "q": "「あの人は、私が公園で会った男性です。」を英語にしてください。"},
        {"type": "FREE", "q": "Please describe your hometown."},
        {"type": "FREE", "q": "What are your favorite ways to relax after studying or working?"},
        {"type": "FREE", "q": "Describe a typical busy day for your mother or father."},
        {"type": "FREE", "q": "Where did you go for your last vacation? What did you do?"},
        {"type": "FREE", "q": "What is a hobby or activity you have been doing for a long time?"},
        {"type": "FREE", "q": "Talk about a movie or book that changed your way of thinking."},
        {"type": "FREE", "q": "Do you prefer living in a city or the countryside? Why?"},
        {"type": "FREE", "q": "If you had a lot of money, what would you like to build or create?"}
    ],
    "Set C": [
        {"type": "TRANS", "q": "「私は5年前から、この町に住んでいます。」を英語にしてください。"},
        {"type": "TRANS", "q": "「これは、母が私に作ってくれたケーキです。」を英語にしてください。"},
        {"type": "FREE", "q": "What are your main interests right now?"},
        {"type": "FREE", "q": "What are the benefits of learning a new language?"},
        {"type": "FREE", "q": "Tell me about a coworker or classmate and their daily habits."},
        {"type": "FREE", "q": "What was the most interesting thing you learned in high school?"},
        {"type": "FREE", "q": "How has your life changed since you entered university?"},
        {"type": "FREE", "q": "Describe a place that you really want to visit someday."},
        {"type": "FREE", "q": "Do you prefer reading books or watching YouTube? Why?"},
        {"type": "FREE", "q": "What kind of job do you want to try in the future?"}
    ],
    "Set D": [
        {"type": "TRANS", "q": "「私は2020年から、ギターを練習しています。」を英語にしてください。"},
        {"type": "TRANS", "q": "「あそこにあるのは、私が一番好きなレストランです。」を英語にしてください。"},
        {"type": "FREE", "q": "What is your favorite season and why?"},
        {"type": "FREE", "q": "What do you think is the best way to stay healthy?"},
        {"type": "FREE", "q": "Who is someone you admire, and what do they do every day?"},
        {"type": "FREE", "q": "What is the best memory from your childhood?"},
        {"type": "FREE", "q": "Have you ever taken up a new sport or habit recently?"},
        {"type": "FREE", "q": "Tell me about a problem that you recently solved."},
        {"type": "FREE", "q": "How do you usually relieve stress?"},
        {"type": "FREE", "q": "How do you think technology will change our lives in 10 years?"}
    ]
}

# 選択されたセットの10問を抽出して使用する
QUESTIONS = ALL_QUESTIONS[selected_set]

# --- 5. メインロジック ---
if st.session_state.step < len(QUESTIONS):
    current_q = QUESTIONS[st.session_state.step]
    
    st.subheader(f"第 {st.session_state.step + 1} 問 / {len(QUESTIONS)}")
    
    if current_q["type"] == "TRANS":
        st.warning(f"**指定フレーズを英語に直してください：**\n\n {current_q['q']}")
    else:
        st.info(f"**自由にお答えください：**\n\n {current_q['q']}")

    # keyに attempt を入れることで、やり直すたびにウィジェットが新品にリセットされます
    audio_data = mic_recorder(
        start_prompt=f"第{st.session_state.step + 1}問 録音開始 🎙️",
        stop_prompt="録音停止 ⏹️",
        key=f"recorder_{st.session_state.step}_{st.session_state.attempt}"
    )

    # 録音が終わったあとの確認画面
    if audio_data:
        st.write("▼ 録音した音声を確認できます")
        st.audio(audio_data['bytes']) 
        
        col1, col2 = st.columns(2)
        with col1:
            submit_btn = st.button("✅ この音声で提出する", type="primary", use_container_width=True)
        with col2:
            retry_btn = st.button("🔄 録音し直す", use_container_width=True)
            
        # 提出ボタンが押されたときの処理
        if submit_btn:
            with st.spinner("音声を処理・保存中..."):
                timestamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
                file_name = f"{user_id}_Q{st.session_state.step+1}_{timestamp.replace('/','').replace(':','').replace(' ','_')}.wav"
                audio_bytes = audio_data['bytes']
                
                # ① OpenAIで文字起こし
                with io.BytesIO(audio_bytes) as audio_file:
                    audio_file.name = "audio.wav"
                    transcript = client.audio.transcriptions.create(
                        model="whisper-1", 
                        file=audio_file
                    )
                
                # ② Google Cloud Storageに音声をアップロード
                bucket = storage_client.bucket(BUCKET_NAME)
                blob = bucket.blob(file_name)
                blob.upload_from_string(audio_bytes, content_type='audio/wav')

                # ③ スプレッドシートに記録
                sheet = gc.open(SHEET_NAME).sheet1
                sheet.append_row([timestamp, user_id, st.session_state.step + 1, current_q['q'], transcript.text])
                
                st.session_state.results.append({
                    "question": current_q['q'],
                    "type": current_q['type'],
                    "answer": transcript.text
                })
                
                # 次のステップへ進み、録音回数をリセット
                st.session_state.step += 1
                st.session_state.attempt = 0
                st.rerun()

        # やり直しボタンが押されたときの処理
        if retry_btn:
            st.session_state.attempt += 1 # 回数を増やすことで録音ウィジェットを強制リセット
            st.rerun()

# --- 6. 最終診断 ---
else:
    st.subheader("🏁 全10問完了！総合診断中...")
    with st.spinner("AI先生が全ての回答を分析し、グラフを生成しています..."):
        summary_text = ""
        for i, res in enumerate(st.session_state.results):
            summary_text += f"Q{i+1}: {res['question']}\n回答: {res['answer']}\n\n"

        # AIにJSON形式で返答させるためのプロンプト
        analysis_prompt = """
        あなたは第二言語習得（SLA）の専門家およびデータアナリストです。
        提供された発話データを分析し、以下のJSONスキーマに厳密に従ってデータを出力してください。
        （※Markdownなどの装飾は一切含めず、純粋なJSONオブジェクトのみを出力すること）

        【分析の4観点】
        1. 時制（Tense）
        2. 主語と動詞の一致（Agreement）
        3. 名詞の境界（Nouns & Articles）
        4. 構文・語順（Syntax）

        【計算ルール】
        - エラー率(%) = (エラー数 / 必須文脈数) × 100
        - 全体平均エラー率(%) = (全エラー数合計 / 全必須文脈数合計) × 100
        - 化石化判定（is_fossilized）: 全体平均エラー率が40%以下、かつ、その観点のエラー率が全体平均より30%以上高い場合に true とすること。

        【出力JSONフォーマット】
        {
            "overall_summary": "学習者のスピーキング傾向についての総評（2〜3文）",
            "overall_average_error_rate": 25.5,
            "categories": [
                {
                    "name": "時制",
                    "obligatory_contexts": 10,
                    "error_count": 2,
                    "error_rate": 20.0,
                    "is_fossilized": false,
                    "details": "エラーの具体例（元の発話の引用）と分析"
                }
            ],
            "advice": "今後の学習アドバイス"
        }
        """

        # GPT-4o APIの呼び出し（JSONモードを有効化）
        response = client.chat.completions.create(
            model="gpt-4o",
            response_format={ "type": "json_object" },
            messages=[{"role": "system", "content": analysis_prompt}, {"role": "user", "content": summary_text}],
            temperature=0
        )
        
        # JSONデータをPythonの辞書に変換
        result_data = json.loads(response.choices[0].message.content)

        # ---------------------------------------------------------
        # 画面への描画（UI構築）
        # ---------------------------------------------------------
        st.success("分析が完了しました！")
        st.markdown(f"### 📊 全体総評\n{result_data['overall_summary']}")
        st.info(f"**全体平均エラー率: {result_data['overall_average_error_rate']}%**")

        # データをPandasのデータフレームに変換してグラフ化
        df = pd.DataFrame(result_data['categories'])

        # グラフを2列に分けて表示
        col_chart1, col_chart2 = st.columns(2)
        
        with col_chart1:
            st.markdown("#### 🕸️ エラー率レーダーチャート")
            fig_radar = px.line_polar(df, r='error_rate', theta='name', line_close=True, range_r=[0, 100])
            fig_radar.update_traces(fill='toself', line_color='#FF4B4B')
            st.plotly_chart(fig_radar, use_container_width=True)

        with col_chart2:
            st.markdown("#### 📊 観点別エラー率（棒グラフ）")
            fig_bar = px.bar(df, x='name', y='error_rate', color='is_fossilized',
                             color_discrete_map={True: 'red', False: 'blue'},
                             labels={'name': '観点', 'error_rate': 'エラー率 (%)', 'is_fossilized': '化石化の兆候'})
            fig_bar.update_yaxes(range=[0, 100])
            st.plotly_chart(fig_bar, use_container_width=True)

        # 各観点の詳細とアドバイスを表示
        st.markdown("### 🚨 詳細分析")
        for cat in result_data['categories']:
            # 化石化フラグが立っていたら警告アイコンをつける
            status_icon = "⚠️ **【化石化の兆候あり】**" if cat['is_fossilized'] else "✅"
            st.markdown(f"#### {status_icon} {cat['name']} (エラー率: {cat['error_rate']}%)")
            st.markdown(f"- 必須文脈数: {cat['obligatory_contexts']} / エラー数: {cat['error_count']}")
            st.markdown(f"- **分析:** {cat['details']}")

        st.markdown("---")
        st.markdown(f"### 👩‍🏫 今後の学習アドバイス\n{result_data['advice']}")

        # スプレッドシートに記録
        timestamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        sheet = gc.open(SHEET_NAME).sheet1
        sheet.append_row([timestamp, user_id, "FINAL", "総合診断レポート", json.dumps(result_data, ensure_ascii=False)])

    st.balloons()
