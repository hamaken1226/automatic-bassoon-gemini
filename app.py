import streamlit as st
from streamlit_mic_recorder import mic_recorder
from google import genai
from google.genai import types
from google.cloud import storage
import gspread
from google.oauth2 import service_account
from datetime import datetime
import time

import json
import pandas as pd
import plotly.express as px

# --- 1. 認証設定 ---
gemini_client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
GEMINI_MODEL = "gemini-2.5-flash"  # 無料枠で安定して使えるモデル

gcp_info = dict(st.secrets["gcp_service_account"])
gcp_info["private_key"] = gcp_info["private_key"].replace("\\n", "\n")

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
SHEET_NAME = "English_AI_Logs_Gemini" # スプレッドシートの名前（GPT版とはデータを分離）
BUCKET_NAME = "kentaengspeakingtest-gemini-202606192210" # GPT版とはデータを分離するため別バケット


# --- 2.5 Gemini呼び出しの共通ヘルパー（無料枠のレート制限429対策でリトライを入れる） ---
def call_gemini(contents, config=None, max_retries=3):
    for attempt in range(max_retries):
        try:
            return gemini_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config=config
            )
        except Exception:
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)  # 1秒, 2秒, 4秒...と間隔を空けて再試行


# --- 2.6 テスターの認証情報をスプレッドシート（Testersタブ）から取得 ---
@st.cache_data(ttl=300)
def get_tester_credentials():
    worksheet = gc.open(SHEET_NAME).worksheet("Testers")
    records = worksheet.get_all_records()
    return {str(r["username"]): str(r["password"]) for r in records if r.get("username")}


# --- 3. アプリの設定 ---
st.set_page_config(page_title="英語化石化診断テスト", layout="centered")
st.title("🎓 英語化石化診断テスト")

if 'step' not in st.session_state:
    st.session_state.step = 0
if 'results' not in st.session_state:
    st.session_state.results = []
if 'attempt' not in st.session_state:
    st.session_state.attempt = 0
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user_id' not in st.session_state:
    st.session_state.user_id = ""

# --- 3.5 テスターログイン（ユーザー名・パスワードはTestersタブで管理） ---
if not st.session_state.logged_in:
    st.subheader("🔐 テスターログイン")
    login_username = st.text_input("ユーザー名")
    login_password = st.text_input("パスワード", type="password")
    if st.button("ログイン"):
        try:
            testers = get_tester_credentials()
        except gspread.exceptions.WorksheetNotFound:
            st.error("Testersシートが見つかりません。管理者に連絡してください。")
            st.stop()
        if login_username and testers.get(login_username) == login_password:
            st.session_state.logged_in = True
            st.session_state.user_id = login_username
            st.rerun()
        else:
            st.error("ユーザー名またはパスワードが間違っています。")
    st.stop()

# サイドバー設定
with st.sidebar:
    st.header("⚙️ 実験管理")
    st.write(f"ログイン中: **{st.session_state.user_id}**")

    # 👇 新しく「セット選択」のプルダウンを追加！
    selected_set = st.selectbox("テストセットを選択", ["Set A", "Set B", "Set C", "Set D"])

    if st.button("テストを最初からやり直す"):
        st.session_state.step = 0
        st.session_state.results = []
        st.session_state.attempt = 0
        st.rerun()

    if st.button("ログアウト"):
        st.session_state.logged_in = False
        st.session_state.user_id = ""
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

# 4つのミス観点の説明（フィードバック表示時に毎回提示する）
CATEGORY_DESCRIPTIONS = {
    "時制": "動詞の時制（過去形・進行形・完了形など）が、話している内容に合った正しい形で使えているかを評価します。",
    "主語と動詞の一致": "主語の人称・単数複数に応じて、動詞の形が正しく一致しているかを評価します（例: 3人称単数のsの抜け）。",
    "名詞の境界": "名詞が単数か複数か、冠詞（a/an/the）が必要な場面で適切に使えているかを評価します。",
    "構文・語順": "英語として自然な文の構造・語順になっているか（語順の崩れや不自然な文構造がないか）を評価します。",
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

    st.write("または、以前録音した音声ファイルをアップロードすることもできます（同じ発話で他のAIと結果を比較する場合など）。")
    uploaded_file = st.file_uploader(
        "音声ファイルをアップロード",
        type=["wav", "mp3", "m4a", "ogg", "webm"],
        key=f"uploader_{st.session_state.step}_{st.session_state.attempt}"
    )

    # 録音 or アップロードされたファイルのどちらかを採用する（録音が優先）
    if audio_data:
        audio_bytes_input = audio_data["bytes"]
        audio_mime_type = "audio/wav"
        audio_ext = "wav"
    elif uploaded_file is not None:
        audio_bytes_input = uploaded_file.read()
        audio_mime_type = uploaded_file.type or "audio/wav"
        audio_ext = uploaded_file.name.rsplit(".", 1)[-1] if "." in uploaded_file.name else "wav"
    else:
        audio_bytes_input = None

    # 録音/アップロードが終わったあとの確認画面
    if audio_bytes_input:
        st.write("▼ 音声を確認できます")
        st.audio(audio_bytes_input)

        col1, col2 = st.columns(2)
        with col1:
            submit_btn = st.button("✅ この音声で提出する", type="primary", use_container_width=True)
        with col2:
            retry_btn = st.button("🔄 録音し直す/選び直す", use_container_width=True)

        # 提出ボタンが押されたときの処理
        if submit_btn:
            with st.spinner("音声を処理・保存中..."):
                timestamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
                file_name = f"{st.session_state.user_id}_Q{st.session_state.step+1}_{timestamp.replace('/','').replace(':','').replace(' ','_')}.{audio_ext}"
                audio_bytes = audio_bytes_input

                # ① Geminiで文字起こし（音声バイトを直接渡す。文法エラーは一切修正しない）
                transcribe_prompt = (
                    "以下は英語学習者の発話音声です。発話された内容を一字一句そのまま書き起こしてください。"
                    "文法的な誤りや言い淀み、言い直し、フィラー(um, uhなど)も一切修正・省略せず、聞こえた通りに書き起こすこと。"
                    "出力は書き起こしテキストのみとし、前置きや説明は不要です。"
                )
                transcribe_response = call_gemini(
                    contents=[
                        transcribe_prompt,
                        types.Part.from_bytes(data=audio_bytes, mime_type=audio_mime_type)
                    ],
                    config=types.GenerateContentConfig(temperature=0.0)
                )
                raw_transcript = transcribe_response.text.strip()

                # ①.5 音声認識ノイズだけをテキストベースで補正（文法エラーは残す2段目のパス）
                cleanup_prompt = (
                    "以下は英語学習者の発話の音声認識結果です。文脈から考えて明らかな音声認識の誤り"
                    "（例: 'crab activity' は文脈上 'club activity' の誤認識、'play for' は 'prefer' の誤認識など）を、"
                    "文脈から判断して正しい単語に直してください。言い淀み(uh, umなど)は除去してかまいません。"
                    "ただし、学習者本人の文法的な誤り（3単現のsの脱落、時制の誤り、冠詞の誤りなど）は絶対に修正せず、そのまま残すこと。"
                    "出力はクリーニング済みのテキストのみとし、説明や前置きは不要です。"
                    f"\n\n【音声認識結果】\n{raw_transcript}"
                )
                cleanup_response = call_gemini(
                    contents=cleanup_prompt,
                    config=types.GenerateContentConfig(temperature=0.0)
                )
                cleaned_transcript = cleanup_response.text.strip()

                # ② Google Cloud Storageに音声をアップロード
                bucket = storage_client.bucket(BUCKET_NAME)
                blob = bucket.blob(file_name)
                blob.upload_from_string(audio_bytes, content_type=audio_mime_type)

                # ③ スプレッドシートに記録（生の書き起こしとクリーニング後の両方を保存し、後から検証できるようにする）
                sheet = gc.open(SHEET_NAME).sheet1
                sheet.append_row([timestamp, st.session_state.user_id, st.session_state.step + 1, current_q['q'], raw_transcript, cleaned_transcript])

                st.session_state.results.append({
                    "question": current_q['q'],
                    "type": current_q['type'],
                    "answer": cleaned_transcript
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
        # ★エラー率・全体平均・化石化判定の計算はAIにはやらせない（必須文脈数とエラー数の抽出のみ）。
        #   計算はこの後Python側で必ず行う（AIに計算させると桁数ミスが起こるため）。
        analysis_prompt = """
        あなたは第二言語習得（SLA）の専門家およびデータアナリストです。
        提供された発話データを分析し、以下のJSONスキーマに厳密に従ってデータを出力してください。
        （※Markdownなどの装飾は一切含めず、純粋なJSONオブジェクトのみを出力すること）

        【分析の4観点】
        1. 時制（Tense）
        2. 主語と動詞の一致（Agreement）
        3. 名詞の境界（Nouns & Articles）
        4. 構文・語順（Syntax）

        【重要・数え方のルール】
        各観点について、いきなり個数を答えてはいけない。まず本文の最初から最後まで漏れなく確認し、
        該当する箇所を一つずつ全て抜き出して obligatory_contexts_list に追加すること（「目立つエラー」だけを拾うのではなく、
        正しく使えている箇所も含めて、その文法規則が適用される場面を全部リストアップする）。
        そのうち実際に誤っていた箇所だけを error_list に追加すること。個数（件数）はこちら（Python側）でリストの長さから算出するので、
        あなたは個数を書く必要はない。

        【Self-Repair（自己修正）の除外ルール】
        学習者が発話中に言い直した箇所は、自己モニター機能が働いている証拠であり、エラーではない。
        obligatory_contexts_list・error_listのどちらにも含めないこと。
        例1: "I go... I went to the park." → 正しく自己修正できているため、カウントしない。
        例2: 単純な言い淀みや繰り返し（"I I love driving"など）、音声認識のノイズらしき箇所も、文法エラーとして数えない。

        【言語に関する重要な指示】
        "overall_summary"・"details"・"advice"の文章は、テスター（学習者本人）に直接渡すフィードバックです。
        必ず**日本語**で書くこと（英語で書いてはいけない）。obligatory_contexts_list・error_listの引用部分は元の発話のまま英語でよい。

        【出力JSONフォーマット】
        {
            "overall_summary": "学習者のスピーキング傾向についての総評（2〜3文、日本語）",
            "categories": [
                {
                    "name": "時制",
                    "obligatory_contexts_list": ["I have been studying (Q1)", "This is a book (Q2)"],
                    "error_list": ["go -> went (Q3)"],
                    "details": "エラーの具体例（元の発話の引用）と分析（日本語で記述）"
                }
            ],
            "advice": "今後の学習アドバイス（日本語）"
        }

        【対象発話ログ】
        """ + summary_text

        # Gemini APIの呼び出し（response_mime_typeでJSON出力を強制）
        response = call_gemini(
            contents=analysis_prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json"
            )
        )

        result_json_str = response.text.strip()
        # 念のためのフォールバック（Markdownコードブロックが混入した場合に剥がす）
        if result_json_str.startswith("```json"):
            result_json_str = result_json_str[7:]
        if result_json_str.endswith("```"):
            result_json_str = result_json_str[:-3]
        result_json_str = result_json_str.strip()

        # JSONデータをPythonの辞書に変換
        result_data = json.loads(result_json_str)

        # ★Python側で件数・エラー率・全体平均エラー率・化石化判定を正確に計算する
        # （件数はAIの自己申告の数字ではなく、AIが書き出したリストの長さから算出する＝数え漏らし対策）
        for cat in result_data["categories"]:
            cat["obligatory_contexts"] = len(cat["obligatory_contexts_list"])
            cat["error_count"] = len(cat["error_list"])

        total_errors = sum(cat["error_count"] for cat in result_data["categories"])
        total_contexts = sum(cat["obligatory_contexts"] for cat in result_data["categories"])
        overall_average_error_rate = (total_errors / total_contexts * 100) if total_contexts > 0 else 0

        for cat in result_data["categories"]:
            cat_rate = (cat["error_count"] / cat["obligatory_contexts"] * 100) if cat["obligatory_contexts"] > 0 else 0
            cat["error_rate"] = cat_rate
            # 化石化の定義：その観点のエラー率が全体平均+15ポイント以上（絶対値ゲートは撤廃）
            cat["is_fossilized"] = bool(cat_rate >= overall_average_error_rate + 15.0)

        result_data["overall_average_error_rate"] = overall_average_error_rate

        # ---------------------------------------------------------
        # 画面への描画（UI構築）
        # ---------------------------------------------------------
        st.success("分析が完了しました！")
        st.markdown(f"### 📊 全体総評\n{result_data['overall_summary']}")
        st.info(f"**全体平均エラー率: {result_data['overall_average_error_rate']:.1f}%**")

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
            st.markdown(f"#### {status_icon} {cat['name']} (エラー率: {cat['error_rate']:.1f}%)")
            st.caption(CATEGORY_DESCRIPTIONS.get(cat['name'], ""))
            st.markdown(f"- 必須文脈数: {cat['obligatory_contexts']} / エラー数: {cat['error_count']}")
            st.markdown(f"- **分析:** {cat['details']}")

        st.markdown("---")
        st.markdown(f"### 👩‍🏫 今後の学習アドバイス\n{result_data['advice']}")

        # 各問題への回答（文字起こし）の一覧
        st.markdown("---")
        st.markdown("### 📝 あなたの回答一覧")
        for i, res in enumerate(st.session_state.results):
            with st.expander(f"Q{i+1}: {res['question']}"):
                st.write(res['answer'])

        # スプレッドシートに記録
        timestamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        sheet = gc.open(SHEET_NAME).sheet1
        sheet.append_row([timestamp, st.session_state.user_id, "FINAL", "総合診断レポート", "", json.dumps(result_data, ensure_ascii=False)])

    st.balloons()
