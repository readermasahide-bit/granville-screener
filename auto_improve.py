import io
import os
import re
import sys
import time
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
# 2026年現在のGoogle推奨である最新のGenAI SDKを使用します
from google import genai

# ==========================================
# ★ 設定パラメータ（取得したURLをここに貼り付けてください）
# ==========================================
CSV_URL_CAT = https://docs.google.com/spreadsheets/d/e/2PACX-1vQJlXSONBac6K6ZpuilefCRNcouFdcI97lu8HoRTRmSBAZwVB9gi1GpFi_ZJZGVoWmbtyL8DGSV8ray/pub?gid=825425309&single=true&output=csv
"ここに【判定カテゴリ用】CSV公開URLを貼り付け"
CSV_URL_SCORE = https://docs.google.com/spreadsheets/d/e/2PACX-1vQDcOnuC9hfa6BtMkI9ZJzLE_o9E__kCQTrnV8D8xlq6vvguK2gnDoAzaPgrNXPiQ9WagaqadfzEZ8v/pub?gid=1420276699&single=true&output=csv
"ここに【期待度（スコア）用】CSV公開URLを貼り付け"

# 修正対象となる現在のメインプログラムのファイル名
MAIN_CODE_FILE = "app.py" 
# ==========================================

# カラム自動検出用のヘルパー
def find_col(cols, keywords):
    for col in cols:
        if any(kw in str(col) for kw in keywords):
            return col
    return None

# 日付抽出ヘルパー
def extract_date(val):
    match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", str(val))
    if match:
        return f"{match.group(1)}-{match.group(2).zfill(2)}-{match.group(3).zfill(2)}"
    return None

# 各CSVデータをダウンロードして分析事例テキストを生成する関数
def analyze_feedback_csv(csv_url, label_name):
    print(f"📥 {label_name} のCSVデータを取得中...")
    try:
        response = requests.get(csv_url)
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.text))
    except Exception as e:
        print(f"❌ CSVの取得に失敗しました ({label_name}): {e}")
        return ""

    cols = df.columns
    col_time = find_col(cols, ["タイムスタンプ", "Timestamp", "時間"])
    col_code = find_col(cols, ["コード", "証券", "Ticker"])
    col_name = find_col(cols, ["銘柄", "Name"])
    col_sys  = find_col(cols, ["システム", "System"])
    col_cat  = find_col(cols, ["カテゴリ", "期待度", "Score", "星"])
    col_memo = find_col(cols, ["理由", "フィードバック", "コメント", "メモ"])

    if not col_time or not col_code:
        print(f"⚠️ 警告: {label_name} CSV内に必須カラムが見つかりません。")
        return ""

    analyzed_cases = []

    # 各フィードバック行の技術分析
    for idx, row in df.iterrows():
        raw_time = row[col_time]
        target_date = extract_date(raw_time)
        code = str(row[col_code]).strip().split('.')[0]
        ticker = f"{code}.T"
        name = row[col_name] if col_name else "不明"
        sys_type = row[col_sys] if col_sys else "中期(25/75)"
        cat_or_score = row[col_cat] if col_cat else "未記入"
        user_memo = row[col_memo] if col_memo else "未記入"

        if not target_date:
            continue

        target_dt = datetime.strptime(target_date, "%Y-%m-%d")
        start_str = (target_dt - timedelta(days=365)).strftime("%Y-%m-%d")
        end_str = (target_dt + timedelta(days=5)).strftime("%Y-%m-%d")

        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            req = requests.get(f"https://query1.finance.yahoo.com/v7/finance/download/{ticker}?period1=0&period2=9999999999&interval=1d&events=history", headers=headers)
            df_stock = pd.read_csv(io.StringIO(req.text), parse_dates=['Date'])
            df_stock = df_stock[(df_stock['Date'] >= start_str) & (df_stock['Date'] <= end_str)].copy()
            df_stock = df_stock.dropna().reset_index(drop=True)

            if df_stock.empty or len(df_stock) < 130:
                continue

            df_stock['ma5'] = df_stock['Close'].rolling(window=5).mean()
            df_stock['ma25'] = df_stock['Close'].rolling(window=25).mean()
            df_stock['ma75'] = df_stock['Close'].rolling(window=75).mean()

            df_stock['Date_str'] = df_stock['Date'].dt.strftime("%Y-%m-%d")
            match_rows = df_stock[df_stock['Date_str'] == target_date]

            if match_rows.empty:
                df_past = df_stock[df_stock['Date_str'] < target_date]
                if df_past.empty: continue
                target_idx = df_past.index[-1]
            else:
                target_idx = match_rows.index[0]

            df_target = df_stock.loc[:target_idx]
            day_data = df_target.iloc[-1]
            day_prev = df_target.iloc[-2]

            price = float(day_data['Close'])
            price_prev = float(day_prev['Close'])
            open_p = float(day_data['Open'])
            high_p = float(day_data['High'])
            low_p = float(day_data['Low'])

            ma25_val = float(day_data['ma25'])
            ma75_val = float(day_data['ma75'])

            diff_rate_25 = ((price - ma25_val) / ma25_val) * 100
            diff_rate_75 = ((price - ma75_val) / ma75_val) * 100

            recent_vols = df_target.iloc[-26:-1]['Volume']
            ma_vol = recent_vols.mean() if len(recent_vols) > 0 else 1
            vol_ratio = day_data['Volume'] / ma_vol

            ma_change_series = df_target['ma75'].pct_change()
            ma_change_today = ma_change_series.iloc[-1]
            baseline_change_120d = ma_change_series.abs().tail(120).mean()

            candle_body = ((price - open_p) / open_p) * 100 if open_p > 0 else 0
            max_body = max(price, open_p)
            total_range = high_p - low_p
            upper_shadow_pct = ((high_p - max_body) / total_range) * 100 if total_range > 0 else 0

            df_40d = df_target.tail(40)
            is_surged = (df_40d['Close'].max() / df_40d['Close'].min()) >= 1.50

            case_info = f"""
### 📁 事例：{ticker} ({name})
- **発生日:** {target_date} ({sys_type})
- **現在のプログラムの出力:** {cat_or_score}
- **ユーザーのフィードバック:** 「{user_memo}」
- **[再現された当日のテクニカル生データ]**
  - 当日株価(終値): {price:,.0f}円 (前日比: {price - price_prev:+,.0f}円, 始値: {open_p:,.0f}円)
  - 25日線乖離率: {diff_rate_25:.2f}% (25日線値: {ma25_val:,.1f}円)
  - 75日線乖離率: {diff_rate_75:.2f}% (75日線値: {ma75_val:,.1f}円)
  - 25日平均比出来高: {vol_ratio:.2f}倍 (当日: {day_data['Volume']:,}, 25日平均: {ma_vol:,.0f})
  - 長期線(75日線)の当日変化率: {ma_change_today:.6f} (過去半年平均: {baseline_change_120d:.6f})
  - ローソク足実体率: {candle_body:.2f}% / 上髭割合: {upper_shadow_pct:.1f}%
  - 直近2ヶ月急騰フラグ: {"あり(ボラ激増)" if is_surged else "なし(通常)"}
"""
            analyzed_cases.append(case_info)
            time.sleep(0.1)

        except Exception as e:
            print(f" -> {ticker} の分析中にエラーが発生しました: {e}")

    return "".join(analyzed_cases)

def main():
    # 1. 2つのCSVをそれぞれ読み込み、再現データを組み立てる
    print("🚀 フィードバックデータの分析を開始します...")
    cat_cases_text = analyze_feedback_csv(CSV_URL_CAT, "判定カテゴリ改善用")
    score_cases_text = analyze_feedback_csv(CSV_URL_SCORE, "期待度改善用")

    if not cat_cases_text and not score_cases_text:
        print("ℹ️ 分析すべき新しい事例データが見つかりませんでした。処理を終了します。")
        sys.exit(0)

    # 2. 現在のメインプログラムコードの読み込み
    if not os.path.exists(MAIN_CODE_FILE):
        print(f"❌ エラー: 対象ファイル {MAIN_CODE_FILE} が見つかりません。")
        sys.exit(1)
        
    with open(MAIN_CODE_FILE, "r", encoding="utf-8") as f:
        current_code = f.read()

    # 3. プロンプトの組み立て
    prompt_template = f"""
【プログラミング改善依頼プロンプト】

あなたは「グランビル法則スクリーナー（Python + HTML/JS製）」を改善するプロの金融クオンツ・エンジニアです。
ユーザーから寄せられた「実際の誤判定（ダマシ）のデータ（Googleスプレッドシートから復元）」をもとに、
判定ロジックを最適化し、より人間の視覚的判断に極限まで近づけた、新しい完成版のコードを作成してください。

---

### 1. 現在のシステム仕様（改善のベースとなるソースコード）
以下に、現在のプログラムのソースコードを提示します。

```python
{current_code}
