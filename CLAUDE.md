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

---

## 3. タスク設計

**Set A〜D の全4セット・各10問が実装済み**（`app.py`内 `ALL_QUESTIONS` 辞書）。サイドバーの `selectbox` でテスト実施者がセットを選択する。

- 各セット共通の構成：
  - Q1, Q2: **TRANS（低負荷）** — 日本語の指定フレーズを英語に翻訳
  - Q3〜Q10: **FREE（高負荷）** — 自由発話の質問

---

## 4. 評価指標の仕様（現行ロジック）

### 4.1 エラー率・化石化判定 — Python側で算出

Geminiが出力するのは各観点の**「必須文脈数」「エラー数」「具体例」のみ**。エラー率・全体平均エラー率・`is_fossilized`フラグは**すべて`app.py`内でPythonが計算**する（AIに計算させると桁数ミスが起こるため、プロンプトでも明示的に計算させない指示を入れている）。

```python
total_errors = sum(cat["error_count"] for cat in result_data["categories"])
total_contexts = sum(cat["obligatory_contexts"] for cat in result_data["categories"])
overall_average_error_rate = (total_errors / total_contexts * 100) if total_contexts > 0 else 0

for cat in result_data["categories"]:
    cat_rate = (cat["error_count"] / cat["obligatory_contexts"] * 100) if cat["obligatory_contexts"] > 0 else 0
    cat["error_rate"] = cat_rate
    cat["is_fossilized"] = bool(overall_average_error_rate <= 40.0 and cat_rate >= overall_average_error_rate + 30.0)
```

化石化条件は「全体平均 ≤ 40%」かつ「観点別エラー率 ≥ 全体平均 + 30ポイント」（加算方式）。この閾値自体はGPT-4o時代から変更していない。

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
app.py                 # テスト実施画面（録音→Gemini文字起こし→Gemini解析→Python側で計算→結果表示）
pages/dashboard.py     # 被験者ごとの統合分析ダッシュボード（CEFR判定・推移グラフ）
requirements.txt       # 依存パッケージ
```

### 5.1 Google Sheets（`English_AI_Logs_Gemini`）の行構成

固定スキーマは無く、**5列・2種類の行**が同じシートに混在する。

- **質問ごとの進捗行**（Q1〜Q10回答ごとに即時追記）：
  `[Timestamp, User, 質問番号(int), 質問文, 文字起こしテキスト]`
- **最終解析行**（全問完了後に1行追記）：
  `[Timestamp, User, "FINAL", "総合診断レポート", JSON文字列(result_data)]`

`dashboard.py` は `row[2] == "FINAL"` の行だけを抽出して `row[4]` をJSONパースする。質問番号(int)とステータス文字列("FINAL")が同じ列で型違いの2用途を兼ねている点に注意。

---

## 6. セットアップ

### 6.1 `.streamlit/secrets.toml`（ローカル）/ Streamlit Cloud Secrets

```toml
GEMINI_API_KEY = "発行されたGemini APIキー（Google AI Studioで無料発行）"

[gcp_service_account]
# GCS・Google Sheets用のサービスアカウントJSON情報をここに展開
```

`tester_password` / `admin_password` のようなアクセス制御用の値は不要（ログイン機構自体が存在しない）。`OPENAI_API_KEY`はもう使わないので削除してよい。

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

---

## 7. 既知の制約・リスク

- **Gemini無料枠のレート制限（RPM）**：1分あたりのリクエスト数に上限があるため、複数被験者が同時にテストを行うと429エラーが起こりうる。`call_gemini()`でリトライ（指数バックオフ）は実装済みだが、上限を大きく超える同時アクセスには無対応。
- **無料枠の利用規約**：Geminiの無料枠では入力データがGoogleのモデル改善に利用される可能性があるとされている。研究データの取り扱い上は認識しておく必要がある。
- **Self-Repair（言い直し）除外指示なし**：プロンプトに「言い直しは文法エラーとして数えない」旨の明示的な指示が無い。自由発話中の言い直しを誤って文法エラーとしてカウントする可能性がある。
- **生文字起こし／修正後テキストの二重保存なし**：書き起こし結果をそのまま解析対象にしており、タイポ修正前後の比較ができない。研究者が「AIの補正自体が妥当か」を検証する手段が無い。
- **アクセス制御なし**：被験者ID・テストセットはサイドバーで自由入力・選択可能。管理者用の検証画面も無く、`dashboard.py`は誰でも閲覧できる。
- **CEFR判定は被験者の全テスト履歴を累積**して算出されるため、1回のテストだけでは結果が安定しない可能性がある。
- Set A〜Dの質問内容は固定で、ランダム化・出題順シャッフルは無い。

---

## 8. 今後のタスク（検討候補・未着手）

優先度が高い順の候補。実装前に方針をすり合わせること。

1. Self-Repair除外指示のプロンプトへの追加
2. 人間（研究者）による手動添削データとの比較検証スクリプト
3. 化石化閾値（40%ゲート・+30ポイント）の感度分析・妥当性検証
4. アクセス制御（被験者/管理者ロール分離）の必要性検討
5. 複数被験者の同時アクセスに対するレート制限対策の強化（キューイング等）
