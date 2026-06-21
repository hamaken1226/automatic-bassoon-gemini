# プロジェクト指示書（生成AIを活用した英語スピーキング化石化検知システム）

このドキュメントは、Claude Codeなど別の開発環境に引き継ぐための統合コンテキストです。

**このリポジトリ（`hamaken1226/automatic-bassoon-gemini`）は性能比較実験用のGemini版。** 本番（GPT-4o版、`hamaken1226/automatic-bassoon`）とは完全に分離されたコード・データで運用する。本番アプリには一切手を加えない。次週からのテスター実験はこのGemini版で実施し、データが揃った時点でGPT版のデータと比較する計画。

---

## 1. プロジェクトの目的

第二言語習得（SLA）における「化石化（Fossilization）」、すなわちL1（母語）干渉による特定の文法エラーが、AIを使って実験的に検知・数値化されるWebアプリケーション。
翻訳タスク（低負荷）と自由発話タスク（高負荷）の認知的負荷の差を利用し、注意がリソースを奪われる際に無意識に顕在化する特定の文法エラー（化石化の兆候）を浮き出させることが目的。

---

## 2. システム構成（実態・2026-06時点）

| 役割 | 採用技術 |
|---|---|
| フロント/バックエンド | Python (Streamlit, マルチページ: `app.py` + `pages/dashboard.py`) |
| ホスティング | Streamlit Community Cloud（想定） |
| 音声録音 | `streamlit_mic_recorder`（`mic_recorder`、録音し直しUIあり） |
| 音声文字起こし | **Google Gemini API（無料枠）** `gemini-2.5-flash`、音声バイトを直接渡して書き起こし |
| SLA解析 | **Google Gemini API（無料枠）** `gemini-2.5-flash`、`response_mime_type="application/json"`でJSON強制 |
| 音声ストレージ | Google Cloud Storage（`.wav`保存） |
| データ保存 | Google Sheets API（`gspread`） |
| 可視化 | Plotly（レーダーチャート・棒グラフ・折れ線グラフ） |

**2026-06: OpenAI（Whisper-1 + GPT-4o）からGoogle Gemini API（無料枠）へ移行済み。** 併せて、エラー率・全体平均エラー率・化石化フラグの計算をAI任せにせず、**Python側で算出するように変更**した（詳細は4.1節）。無料枠はリクエスト数（RPM）に制限があるため、`call_gemini()`という共通関数でリトライ（指数バックオフ）を実装している。

**2026-06-19: GPT版の実データ（被験者本人がP001としてSet A〜D実施）を独立分析した結果、GPT版の自己採点には疑わしい点が見つかった**（Set B/C/Dで「時制」カテゴリの`obligatory_contexts`/`error_count`/`error_rate`が3回とも完全に同じ数値＝13/3/23.08%で一致しており、毎回まじめに数え直しているか疑わしい。また「名詞の境界（冠詞）」エラーを毎回過小評価している可能性が高い）。これを受けて以下の精度改善策を実装した。

- **被験者ログイン機能を追加**：被験者ごとの個別ユーザー名・パスワードで認証（後述6.4節）
- **Chain-of-Thought方式での数え上げ**：AIにいきなり個数を答えさせず、該当箇所を`obligatory_contexts_list`/`error_list`として全部書き出させてから、Pythonが`len()`で件数を算出する方式に変更（詳細は4.1節）。数え漏らし（サンプリングして目立つ箇所だけ拾う癖）対策。
- **Self-Repair除外のFew-Shot例をプロンプトに明記**
- **文字起こしを2段階パイプライン化**：①Geminiで音声から逐語書き起こし → ②テキストのみで音声認識ノイズ（"crab activity"→"club activity"等の文脈的に明らかな誤認識）を補正するクリーニング処理。文法エラーは2段目でも修正しないよう明示。生の書き起こしとクリーニング後の両方をスプレッドシートに保存し、後から検証可能にした

---

## 3. タスク設計

**Set A〜D の全4セット・各10問が実装済み**（`app.py`内 `ALL_QUESTIONS` 辞書）。サイドバーの `selectbox` でテスト実施者がセットを選択する。

- 各セット共通の構成：
  - Q1, Q2: **TRANS（低負荷）** — 日本語の指定フレーズを英語に翻訳
  - Q3〜Q10: **FREE（高負荷）** — 自由発話の質問

各問題で「録音」に加えて`st.file_uploader`による**音声ファイルのアップロード**にも対応している（2026-06-21追加）。GPT版で録音した過去の音声を使ってGemini版で同じ発話を再分析し、両者を直接比較する用途を想定。録音とアップロードが両方ある場合は録音を優先する。アップロードされたファイルのMIMEタイプ・拡張子をそのままGemini呼び出し・GCS保存に使う（wav/mp3/m4a/ogg/webmに対応）。

---

## 4. 評価指標の仕様（現行ロジック）

### 4.0 なぜ「必須文脈（Obligatory Contexts）方式」なのか

エラー率の算出方法には他に2つの候補があり得るが、いずれもSLA研究の目的には不適切なため採用していない。

- **文単位の合否判定**（1文に1つでもミスがあれば0点）は、長く複雑な文を話す上級者ほど「どこかでミスする確率」が上がるため不利になる。流暢さへのペナルティになってしまう。
- **エラーの絶対数カウント**（間違えた回数だけを数える）は、発話量や文の複雑さで結果が変わってしまう。簡単な文（"I have a pen."等）だけを話して難しい文法から逃げた人が「エラー0回」で高評価になる欠陥がある。

**必須文脈方式**（その文法を使うべき場面の総数を分母、誤った回数を分子にする）は、発話量や文の複雑さというノイズに左右されず、「その文法項目の定着度」だけを純粋に抽出できる。これが本システムが一貫してこの方式を採用している理由。

### 4.1 件数・エラー率・化石化判定 — Python側で算出（Chain-of-Thought方式）

Geminiには各観点の**該当箇所そのもの**を全部書き出させる（`obligatory_contexts_list`・`error_list`）。
「いきなり個数を答えさせる」と、AIが本文を最後まで確認せず目立つ箇所だけ拾って数え漏らす傾向があるため、
先にリストを全部書かせてからPythonが`len()`で件数を出す方式にしている（2026-06-19変更）。
件数・エラー率・全体平均エラー率・`is_fossilized`フラグは**すべて`app.py`内でPythonが計算**する。

```python
for cat in result_data["categories"]:
    cat["obligatory_contexts"] = len(cat["obligatory_contexts_list"])
    cat["error_count"] = len(cat["error_list"])

total_errors = sum(cat["error_count"] for cat in result_data["categories"])
total_contexts = sum(cat["obligatory_contexts"] for cat in result_data["categories"])
overall_average_error_rate = (total_errors / total_contexts * 100) if total_contexts > 0 else 0

for cat in result_data["categories"]:
    cat_rate = (cat["error_count"] / cat["obligatory_contexts"] * 100) if cat["obligatory_contexts"] > 0 else 0
    cat["error_rate"] = cat_rate
    cat["is_fossilized"] = bool(overall_average_error_rate <= 40.0 and cat_rate >= overall_average_error_rate + 30.0)
```

化石化条件は「全体平均 ≤ 40%」かつ「観点別エラー率 ≥ 全体平均 + 30ポイント」（加算方式）。この閾値自体はGPT-4o時代から変更していない。

プロンプトには、言い直し（Self-Repair）をどちらのリストにも含めないことをFew-Shot例付きで明記している（例: "I go... I went to the park." は自己修正できているためカウントしない）。

### 4.2 評価の4観点

1. 時制（Tense）
2. 主語と動詞の一致（Agreement）
3. 名詞の境界（Nouns & Articles）
4. 構文・語順（Syntax）

### 4.3 CEFR総合判定（`pages/dashboard.py`）

スプレッドシートに蓄積された、ある被験者IDの**全テスト・全セットを横断して集計**し、以下のルールでCEFRレベルを推定する。

| レベル | 条件（全体平均エラー率 / 化石化検知の延べ回数） |
|---|---|
| C2 | ≤5% かつ 0回 |
| C1 | ≤10% かつ 0回 |
| B2 | ≤15% かつ ≤1回 |
| B1 | ≤30% かつ ≤3回 |
| A2 | ≤50%（化石化回数の条件なし） |
| A1 | それ以外 |

---

## 5. ファイル構成

```
app.py                              # テスト実施画面（ログイン→録音→Gemini文字起こし→ノイズ補正→Gemini解析→Python側で計算→結果表示）
pages/dashboard.py                  # 被験者ごとの統合分析ダッシュボード（CEFR判定・推移グラフ）
requirements.txt                    # 依存パッケージ
.github/workflows/keep-awake.yml    # Streamlit Community Cloudのスリープ防止（6時間おきにping）
```

### 5.1 Google Sheets（`English_AI_Logs_Gemini`）の構成

スプレッドシート内に2つのタブがある。

**シート1（メインログ）**：固定スキーマは無く、**6列・2種類の行**が混在する（2026-06-19にraw/cleaned分離のため5列→6列に変更）。

- **質問ごとの進捗行**（Q1〜Q10回答ごとに即時追記）：
  `[Timestamp, User, 質問番号(int), 質問文, 生の書き起こし(raw), ノイズ補正後の書き起こし(cleaned)]`
- **最終解析行**（全問完了後に1行追記）：
  `[Timestamp, User, "FINAL", "総合診断レポート", "", JSON文字列(result_data)]`

`dashboard.py` は `row[2] == "FINAL"` の行だけを抽出して `row[5]` をJSONパースする。質問番号(int)とステータス文字列("FINAL")が同じ列で型違いの2用途を兼ねている点に注意。SLA解析（`summary_text`）は`cleaned`列の値を使う。

**Testers タブ**：被験者ログイン用の認証情報。`username` / `password` の2列（ヘッダー行あり）。`app.py`の`get_tester_credentials()`が`st.cache_data(ttl=300)`で5分キャッシュして読む。被験者を追加する際は、このタブに直接行を追記すればよい（コード変更不要）。

---

## 6. セットアップ

### 6.1 `.streamlit/secrets.toml`（ローカル）/ Streamlit Cloud Secrets

```toml
GEMINI_API_KEY = "発行されたGemini APIキー（Google AI Studioで無料発行）"

[gcp_service_account]
# GCS・Google Sheets用のサービスアカウントJSON情報をここに展開
```

`tester_password` / `admin_password` のような共通パスワードは使わない（被験者ごとの個別ユーザー名・パスワードはsecretsではなくSheetsの`Testers`タブで管理。6.4節）。`OPENAI_API_KEY`はもう使わないので削除してよい。

### 6.2 依存パッケージ（`requirements.txt`）

```
streamlit
streamlit-mic-recorder
google-genai
google-cloud-storage
gspread
google-auth
pandas
plotly
```

### 6.3 保存先設定（`app.py`内で直接指定）

- `SHEET_NAME = "English_AI_Logs_Gemini"`（本番GPT版の`English_AI_Logs`とは別物。比較実験のためデータを分離）
- `BUCKET_NAME = "kentaengspeakingtest-gemini-202606192210"`（同様にGPT版とは別バケット）

シート・バケットはどちらも事前に手動作成が必要（サービスアカウントはDrive容量を持たないため`gspread`からの新規シート作成は失敗する。ユーザー個人のGoogleアカウントでシートを作成し、サービスアカウントの`client_email`に編集者権限で共有すること）。

### 6.4 被験者ログイン（アクセス制御）

`English_AI_Logs_Gemini`内の`Testers`タブ（A列`username`/B列`password`、ヘッダー行あり）に行を追加するだけで被験者を登録できる。コード変更・再デプロイは不要。ログインすると、そのユーザー名がそのまま被験者ID（`st.session_state.user_id`）として使われる（自由入力の被験者ID欄は廃止）。パスワードは平文でシートに保存される簡易的な仕組みであり、外部の無関係なアクセスを防ぐためのものであって、強固な認証ではない。

### 6.5 デプロイ済みURL・スリープ対策

- 本番URL: `https://automatic-baappon-gemini-nynm4jzbuqzvgooschesew.streamlit.app/`（Streamlit Community Cloud、`automatic-bassoon-gemini`リポジトリのmainブランチから自動デプロイ）
- Streamlit Cloudへの初回デプロイ時、GitHub連携が「public_repo」スコープのOAuthだったためPrivateリポジトリが見えない問題が発生 → リポジトリをPublicに変更して解決（このリポジトリにシークレットはコミットされていないため問題なし）
- Community Cloud無料枠は一定時間アクセスが無いとスリープするため、`.github/workflows/keep-awake.yml`で6時間おきにアプリURLへpingして起こし続けている

---

## 7. 既知の制約・リスク

- **Gemini無料枠のレート制限（RPM）**：1分あたりのリクエスト数に上限があるため、複数被験者が同時にテストを行うと429エラーが起こりうる。1問あたりのGemini呼び出しが2段階パイプライン化により2回（文字起こし＋ノイズ補正）に増えたため、従来よりRPMを消費しやすい。`call_gemini()`でリトライ（指数バックオフ）は実装済みだが、上限を大きく超える同時アクセスには無対応。
- **無料枠の利用規約**：Geminiの無料枠では入力データがGoogleのモデル改善に利用される可能性があるとされている。研究データの取り扱い上は認識しておく必要がある。
- **件数のリスト化（CoT）でも数え漏らしが完全には無くならない**：`obligatory_contexts_list`/`error_list`を書き出させる方式に変えたことで改善したはずだが、これはAIの出力品質に依存する対策であり、保証ではない。同一入力を複数回実行して結果が安定するかのチェックはまだ行っていない。
- **被験者ログインのパスワードは平文**：`Testers`タブにそのまま平文で保存している。第三者の不正利用を防ぐための簡易的な仕組みであり、強固な認証ではない。
- **CEFR判定は被験者の全テスト履歴を累積**して算出されるため、1回のテストだけでは結果が安定しない可能性がある。
- Set A〜Dの質問内容は固定で、ランダム化・出題順シャッフルは無い。

---

## 8. 今後のタスク（検討候補・未着手）

優先度が高い順の候補。実装前に方針をすり合わせること。

1. 同一発話ログをAIに複数回分析させて、`obligatory_contexts_list`/`error_list`の件数がブレないか検証するスクリプト（2026-06-19にGPT版実データで「3回とも数値が完全一致」という不自然な再現性を発見したのがきっかけ。Gemini版でも同様の問題が起きていないか確認したい）
2. 人間（研究者）による手動添削データとの比較検証スクリプト
3. 化石化閾値（40%ゲート・+30ポイント）の感度分析・妥当性検証
4. 複数被験者の同時アクセスに対するレート制限対策の強化（キューイング等）
