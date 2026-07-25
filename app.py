ユーザーから提示された「ダマシ」事例を詳細に分析し、グランビル法則スクリーナーの判定ロジックを最適化しました。特に、移動平均線の「傾き」に関する判定をより厳密にし、各シグナルの本来の意図に合致するよう条件を強化しています。

---

### 1. 誤判定（ダマシ）の実例データ分析と改善提案

#### 全体的な問題点

提示された4つの事例はすべて中期（25日線/75日線）システムでの誤判定であり、主に「買い2」と「買い3」に関するものでした。共通する問題は以下の2点です。

1.  **移動平均線の「傾き」の判定が甘い:**
    *   `long_ma_slope_10d > 0` や `long_ma_slope_15d > 0` といった条件が、わずかなプラス傾きでも成立してしまうため、ユーザーが期待するような「安定した上昇トレンド」や「強力な右肩上がりトレンド」ではない状況でもシグナルが点灯していました。
    *   特に「買い3（押し目反発）」は、明確な上昇トレンド中での一時的な調整からの反発を狙うものですが、トレンドが弱かったり、下降から転換したばかりの銘柄を拾ってしまう原因となっていました。

2.  **「買い1」と「買い2」「買い3」の区別があいまい:**
    *   ユーザーのフィードバックでは、「買い2」や「買い3」と判定された銘柄が、実際には「買い1（新規買い初動）」に近い状況だと指摘されています。これは、株価が長期線の下に長期間沈んでいた後の上抜けを適切に「買い1」として識別できておらず、他のシグナルに誤分類されたためと考えられます。

これらの問題に対処するため、主に`evaluate_logic`関数内の判定条件を以下の通り修正・強化します。

---

#### ▼ 判定カテゴリ（買い1〜4）に関する誤判定・改善要望の個別分析

### 📁 事例：4743.T (アイティフォー)
- **発生日:** 2026-07-21 (中期(25/75))
- **現在のプログラムの出力:** 買い2
- **ユーザーのフィードバック:** 「2か月間下向きの75日線に伴って下落した株価が初めて75日線を上抜けたので少なくとも買い2ではなく買い1と判断できる。」

**分析:**
*   現在の「買い2」は `is_long_ma_rising` (`long_ma_slope_10d > 0 and (long_ma_today > long_ma_yesterday)`) と `is_temp_dip` (`1 <= below_count_10d <= 4`) が成立したと推測されます。
*   ユーザーの指摘の通り、2ヶ月間下向きの75日線だったにもかかわらず「買い2」になったのは、`is_long_ma_rising` の条件が緩すぎたためです。本来「買い2」は**安定した上昇トレンド**中の押し目を意図します。
*   「初めて75日線を上抜けた」という状況は「買い1」の新規買い初動に該当します。現在のロジックでは「長らく下にあった」ことを示す`is_new_crossover`（買い1の条件）と、「一時的に下抜け」を示す`is_temp_dip`（買い2の条件）が排他的に機能していなかったか、`is_new_crossover`の条件が厳しすぎた可能性があります。

**改善提案:**
1.  **「買い1」条件の強化:** 長期間（例: 20日間）長期線の下に株価が沈んでおり、かつその間の長期線が下降または横ばいだったものが、本日、長期線が上向きに転換しつつ、株価が長期線を明確に上抜けた場合に「買い1」とする条件を導入します。
2.  **「買い2」条件の強化:** `is_long_ma_rising` をより厳密にし、「安定した上昇トレンド」を定義するために、より長い期間（例: 10日/20日）での長期線の傾きが明確にプラスであること、かつ「買い1」の長期間沈んでいた銘柄とは排他的に判定されるようにします。

---

### 📁 事例：155A.T (情報戦略テクノロジー)
- **発生日:** 2026-07-23 (中期(25/75))
- **現在のプログラムの出力:** 買い3
- **ユーザーのフィードバック:** 「判定日の株価は75日線に上から触れているが、それ以前に75日線の上昇を伴って大きく株価が上昇するという前提を満たしておらず、買い3として不適。6月中に75日線を下から上に抜けていることから買い1か買い2とも考えられるが、75日線の上向きの角度がほぼないため買いタイミングですらないともいえる。」

**分析:**
*   「買い3」は`is_long_ma_rising_strong` (`long_ma_slope_15d > 0`) が主要な前提条件ですが、今回のデータでは「75日線の上向きの角度がほぼない」とあり、この条件がユーザーの意図する「強力な右肩上がり」には不十分であったことが原因です。
*   `max_diff_15d >= 4.0` (過去15日で長期線から4%以上上放れた実績) は満たされたものの、肝心のトレンドの勢いが足りなかったようです。

**改善提案:**
1.  **「買い3」の長期線傾き強化:** `is_long_ma_rising_strong` の条件を大幅に厳しくし、15日だけでなく30日程度の期間でも長期線が明確な上昇トレンドであること（例: 一定のパーセンテージ以上の上昇率）を求めます。
2.  **「買い3」の短期線位置関係追加:** 「短期線が長期線の上で継続的に推移していること」という、安定した上昇トレンドの必須条件をコードに反映します。

---

### 📁 事例：2130.T (メンバーズ)
- **発生日:** 2026-07-23 (中期(25/75))
- **現在のプログラムの出力:** 買い3
- **ユーザーのフィードバック:** 「今回の判定に至る前にMAが大きく上を向いての上昇がなく、株価の上昇と下落しか経験できていないため、買い3としては×。75日線がマイナスからプラスに転換しそうなタイミングなので買い1ではないか。」

**分析:**
*   事例2と類似しており、「MAが大きく上を向いての上昇がない」というフィードバックは、やはり`is_long_ma_rising_strong`の条件の甘さが原因です。
*   「75日線がマイナスからプラスに転換しそうなタイミング」という状況は、「買い1」の定義に合致する可能性を示唆しています。

**改善提案:**
*   事例2と同様に、「買い3」の長期線傾き条件と短期線位置関係条件を強化します。
*   「買い1」のトレンド転換初動を捉える新条件によって、このような銘柄が適切に「買い1」として判定されるか、「NONE」となるかを明確化します。

---

### 📁 事例：3064.T (ＭｏｎｏｔａＲＯ)
- **発生日:** 2026-07-24 (中期(25/75))
- **現在のプログラムの出力:** 買い3
- **ユーザーのフィードバック:** 「株価が長らく75日線の下をヨコヨコで移動してからのローソク全体がやっと75日線の上で停滞するようになったので買い1と判断できる。」

**分析:**
*   これも事例2、3と同様に「買い3」の誤判定です。「長らく75日線の下をヨコヨコで移動」という状況は、典型的な「買い1」の前提条件（長期間下で推移していたこと、長期線が横ばい〜下降から転換したこと）に合致します。
*   現在の「買い3」の条件が、トレンドの初動と押し目トレンドの区別を明確にできていなかったことが原因です。

**改善提案:**
*   事例2、3と同様に「買い3」の長期線傾き条件を強化します。
*   「買い1」のトレンド転換初動を捉える新条件によって、このような銘柄が「買い1」として適切に判定されるようにします。

---

#### ▼ 期待度スコア（★1〜5）に関する誤判定・改善要望
（新規のデータなし） -> 今回はロジック変更なし。

---

### 2. 新たな数式条件とロジックの最適化提案

上記の分析に基づき、`evaluate_logic`関数に対して以下の修正を提案します。

#### 新規導入する判定変数

各シグナルの本来の意図に合わせるため、移動平均線の「傾き」や「位置関係」をより定量的に評価する新しい変数を導入します。

1.  **`long_ma_slope_N_days_pct` (長期線N日変化率):**
    *   長期線がN日間でどれだけパーセンテージ変化したかを計算。これにより、株価水準に依存しない「傾きの強さ」を評価します。
    *   例: `long_ma_slope_3d_pct`, `long_ma_slope_10d_pct`, `long_ma_slope_15d_pct`, `long_ma_slope_20d_pct`, `long_ma_slope_30d_pct`

2.  **`short_ma_slope_3d_pct` (短期線3日変化率):**
    *   短期線が直近3日間でどれだけパーセンテージ変化したかを計算。反発の勢いや押し目での下支えを評価します。

3.  **`is_long_period_below_ma` (長期間長期線の下):**
    *   過去20日間のうち12日以上、終値が長期線の下にあったかを示すフラグ。これは「買い1」の根拠となります。

4.  **`was_long_ma_flat_or_down_recent` (長期線が直近で下降/横ばいだった):**
    *   過去20日間の長期線の平均傾きがほぼ0以下（下降または横ばい）だったかを示すフラグ。これも「買い1」の根拠となります。

5.  **`is_long_ma_turning_up_recently` (長期線が直近で上向きに転換した):**
    *   直近5日間の長期線傾きが上向き（`long_ma_slope_3d_pct > 0.01`）。これも「買い1」の根拠となります。

6.  **`is_long_ma_stable_rising` (長期線が安定した上昇トレンド):**
    *   長期線が10日、20日の両方で一定のパーセンテージ以上の上昇率を示しているかを示すフラグ。これは「買い2」の根拠となります。

7.  **`is_long_ma_very_strong_rising` (長期線が非常に強力な上昇トレンド):**
    *   長期線が15日、30日の両方でさらに高い一定のパーセンテージ以上の上昇率を示しているかを示すフラグ。これは「買い3」の根拠となります。

8.  **`is_short_ma_mostly_above_long_ma` (短期線がほぼ長期線の上):**
    *   過去15日間のうち10日以上、短期線が長期線の上にあったかを示すフラグ。これは「買い3」の根拠となります。

#### 各判定カテゴリの条件修正

*   **買い4：逆張り下方乖離 (BUY4)**
    *   **変更なし。** 乖離率の閾値と当日反発の条件を維持します。

*   **買い1：新規買い (BUY1)**
    *   **修正目的:** 長期線の下に長期間沈んでいた銘柄が、長期線の下降・横ばいトレンドから上向きへ転換する初動で長期線を上抜けるケースを確実に捉えます。
    *   **新たな条件:**
        *   `crossed_above_ma`: 株価または短期線が長期線を上抜けた。
        *   `is_long_period_below_ma`: 長らく長期線の下に沈んでいた（過去20日中12日以上）。
        *   `was_long_ma_flat_or_down_recent`: その期間の長期線が下降または横ばいだった。
        *   `is_long_ma_turning_up_recently`: 直近で長期線が上向きに転換した。
        *   `diff_rate <= 5.0`: 長期線から大きく上方に乖離していない。
    *   **効果:** ユーザー事例4743.T, 3064.T のような、下降トレンドからの転換初動を適切に「買い1」として判断できるようになります。

*   **買い2：再突き抜け (BUY2)**
    *   **修正目的:** 安定した上昇トレンド中の一時的な調整（短期的な長期線の下抜け）からの復帰を明確に区別します。
    *   **新たな条件:**
        *   `is_long_ma_stable_rising`: 長期線が安定した上昇トレンド（例: `long_ma_slope_10d_pct > 0.03%` かつ `long_ma_slope_20d_pct > 0.05%`）。
        *   `is_temp_dip`: 短期的に（過去10日中に1〜4日だけ）終値が長期線の下にあった。
        *   `recovered_above`: 本日、終値が長期線を上抜けた。
        *   `0.0 <= diff_rate <= 5.0`: 長期線から大きく上方に乖離していない。
        *   `not is_long_period_below_ma`: 「買い1」の条件とは排他的にする。
    *   **効果:** ユーザー事例4743.Tが、より厳密なトレンド判定により「買い2」から外れ、「買い1」または「NONE」に再分類されることを期待します。

*   **買い3：押し目反発 / 押し目待ち伏せ (BUY3 / BUY3_PRE)**
    *   **修正目的:** 非常に強力な上昇トレンド中での教科書通りの押し目反発のみを検出します。
    *   **新たな条件:**
        *   `is_long_ma_very_strong_rising`: 長期線が非常に強力な右肩上がりトレンド（例: `long_ma_slope_15d_pct > 0.08%` かつ `long_ma_slope_30d_pct > 0.1%`）。
        *   `is_short_ma_mostly_above_long_ma`: 短期線が長期線の上で継続的に推移している（過去15日中10日以上）。
        *   `has_pulled_back`: 過去に長期線から大きく上放れた実績がある。
        *   `is_close_to_ma`: `0.0 < diff_rate <= 3.5` で反発。
        *   `is_rebound`: 本日陽線かつ前日比プラス（BUY3の場合）。
        *   `is_resting_on_ma`: `-0.5 <= diff_rate <= 1.5` で待ち伏せ（BUY3_PREの場合）。
        *   `is_short_ma_rising`: 短期線も上向きで反発準備（BUY3_PREの場合）。
    *   **効果:** ユーザー事例155A.T, 2130.T, 3064.T のような、トレンドが弱い銘柄を「買い3」として誤判定するのを防ぎます。

#### 期待度スコアの微調整

各カテゴリの特性に合わせて、既存の加減点ロジックを一部調整します。
*   **BUY1:** トレンド転換初動の性質上、`is_slope_strong_relative` ではなく「陽線の実体の強さ」をより重視する。
*   **BUY2:** 安定トレンド中での復帰なので、`is_slope_strong_relative` と「陽線の実体の強さ」を評価。
*   **BUY3/BUY3_PRE:** 「支持線極近」と「陽線の実体の強さ」を評価。
*   **BUY4:** 「大陽線反発」と「陽線の実体の強さ」を評価。

---

### 3. 完成版のコード

以下に、上記の改善策を全て反映した「app.py」の完全版コードを提示します。

```python
import io
import os
import json
import time
import requests
import re
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta, timezone

# ==========================================
# ★ 設定パラメータ（Wフォーム設定＆クラウド対応）
# ==========================================
SYSTEM_TYPE = "mid"  # "short"(5/25) または "mid"(25/75)
html_output_path = "index.html" # ホームページとして公開するため index.html に固定

# 【Googleフォーム1：判定カテゴリ改善用】
FORM_CONFIG_CAT = {
    # 末尾を「QOw」に修正します
    "baseUrl": "https://docs.google.com/forms/d/e/1FAIpQLSeUMv4F3yxLUKXuAzU03riKKFRlZjoxORx5vGX69gXyxDiQOw/viewform",
    "entryCode": "entry.1616153480",
    "entryName": "entry.639288663",
    "entrySys":  "entry.1292630960",
    "entryCat":  "entry.432445345"
}

# 【Googleフォーム2：期待度改善用】
FORM_CONFIG_SCORE = {
    "baseUrl": "https://docs.google.com/forms/d/e/1FAIpQLSet_-Ab3-3HgXrRS5pG-5PT4K-qgip4lV4EUqqivaWNRBO_g/viewform",
    "entryCode": "entry.473391802",
    "entryName": "entry.1042173003",
    "entrySys":  "entry.1364518533",
    "entryScore": "entry.2008795821"
}
# ==========================================

# 日本時間(JST)の現在時刻をベースに動的な日付を計算
JST = timezone(timedelta(hours=+9))
now_jst = datetime.now(JST)
current_time_str = now_jst.strftime("%Y-%m-%d %H:%M:%S")

if SYSTEM_TYPE == "short":
    short_window = 5
    long_window = 25
    system_title = "短期（5日線/25日線）"
else:
    short_window = 25
    long_window = 75
    system_title = "中期（25日線/75日線）"

# NumPyの独自型やbytesを標準のPythonデータ型にクレンジングする関数
def clean_val(val):
    if isinstance(val, bytes):
        try:
            return val.decode('utf-8')
        except Exception:
            return str(val)
    elif hasattr(val, 'item'):  # numpy scalar (int64, float64等)
        return val.item()
    elif pd.isna(val):
        return None
    return val

# ★【件数前日比＆連続日数ハック】既存の index.html から前日のデータを自動解析
prev_counts = {
    "short": {"BUY1": 0, "BUY2": 0, "BUY3": 0, "BUY3_PRE": 0, "BUY4": 0, "TOTAL": 0},
    "mid": {"BUY1": 0, "BUY2": 0, "BUY3": 0, "BUY3_PRE": 0, "BUY4": 0, "TOTAL": 0}
}
prev_results_by_ticker = {}

if os.path.exists(html_output_path):
    print("既存の index.html から前日の集計データを自動解析中...")
    try:
        with open(html_output_path, "r", encoding="utf-8") as f:
            old_html = f.read()
        
        # results: [ ... ] の配列だけをカッコの深さを追って正確に抽出する安全な関数
        def extract_results_json(text):
            start_pos = text.find("results:")
            if start_pos == -1: return None
            b_start = text.find("[", start_pos)
            if b_start == -1: return None
            
            depth = 0
            in_string = False
            escape = False
            for i in range(b_start, len(text)):
                char = text[i]
                if escape:
                    escape = False
                    continue
                if char == '\\':
                    escape = True
                    continue
                if char == '"':
                    in_string = not in_string
                    continue
                if not in_string:
                    if char == '[':
                        depth += 1
                    elif char == ']':
                        depth -= 1
                        if depth == 0:
                            return text[b_start:i+1]
            return None

        prev_results_json = extract_results_json(old_html)
        
        if prev_results_json:
            prev_results = json.loads(prev_results_json)
            
            # 各システムの昨日点灯数を集計＆銘柄ルックアップを作成
            for item in prev_results:
                for sys_key in ["short", "mid"]:
                    cat = item.get(sys_key, {}).get("category", "NONE")
                    if cat in prev_counts[sys_key]:
                        prev_counts[sys_key][cat] += 1
                
                ticker_key = item.get("ticker")
                if ticker_key:
                    prev_results_by_ticker[ticker_key] = item
                        
            # アクティブな合計数を計算 (NONEを除外)
            for sys_key in ["short", "mid"]:
                prev_counts[sys_key]["TOTAL"] = len(prev_results)
                total_active = 0
                for cat in ["BUY1", "BUY2", "BUY3", "BUY3_PRE", "BUY4"]:
                    total_active += prev_counts[sys_key][cat]
                prev_counts[sys_key]["TOTAL_ACTIVE"] = total_active
            
            print(f" -> 前日データのパースに成功しました。（対象: {len(prev_results_by_ticker)} 銘柄）")
        else:
            print(" -> 前日データ(results)の抽出パターンが見つかりませんでした。")
    except Exception as e:
        print(f" -> 前日データの読み込みに失敗（初回実行として無視します）: {e}")

# 1. JPXから上場銘柄一覧をダウンロード
jpx_url = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"
print("JPXから銘柄一覧をダウンロード中...")
response = requests.get(jpx_url)
response.raise_for_status()

df_jpx = pd.read_excel(io.BytesIO(response.content))
df_tse = df_jpx[df_jpx["市場・商品区分"].str.contains("プライム|スタンダード|グロース", na=False)].copy()
df_tse["コード"] = df_tse["コード"].astype(str).str.zfill(4)
df_tse["ticker"] = df_tse["コード"] + ".T"

ticker_to_name = dict(zip(df_tse['ticker'], df_tse['銘柄名']))
ticker_to_market = dict(zip(df_tse['ticker'], df_tse['市場・商品区分']))
ticker_to_sector = dict(zip(df_tse['ticker'], df_tse['33業種区分']))

tickers = list(df_tse['ticker'])
print(f"東証3市場の個別株 合計 {len(tickers)} 銘柄のスキャンを開始します。")

# 2. 全銘柄のデータをブロック分けして一括ダウンロード
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
})

print("株価データ(2年分)を一括ダウンロード中...")
bulk_data = {}
chunk_size = 200
for i in range(0, len(tickers), chunk_size):
    chunk = tickers[i:i+chunk_size]
    print(f" -> ダウンロード実行中: {i + 1} 〜 {min(i + chunk_size, len(tickers))} 銘柄目...")
    try:
        # 以前のバージョンと同じ period="2y" 方式
        data = yf.download(chunk, period="2y", interval="1d", group_by="ticker", auto_adjust=False, progress=False, session=session)
        for ticker in chunk:
            if ticker in data.columns.levels[0]:
                df_single = data[ticker].dropna(subset=['Close']).copy()
                
                # タイムゾーン情報を剥離して平坦化
                if df_single.index.tz is not None:
                    df_single.index = df_single.index.tz_convert('Asia/Tokyo').tz_localize(None)
                else:
                    df_single.index = df_single.index.tz_localize(None)
                
                bulk_data[ticker] = df_single
    except Exception as e:
        print(f" -> ブロック取得でエラーが発生しました: {e}")
    
    time.sleep(4)

print(f"データのダウンロードが完了しました。正常取得銘柄数: {len(bulk_data)}")

# 1. 独自実装：正確なワイルダー平滑化方式のRSI（14日）を算出する関数
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    # ワイルダーの平滑化：alpha = 1 / period の指数移動平均(EMA)を使用
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    
    rs = avg_gain / avg_loss.replace(0, 1e-10) # ゼロ除算防止
    rsi = 100 - (100 / (1 + rs))
    return rsi

# 2. ヘルパー：先読みバイアスを排除したスイングロー（極小値）検出関数
def find_swing_lows(series, window=25):
    """
    直近の指定ウインドウ内における、前後2営業日で最小値となる極小値のインデックス(位置)を返します。
    本日(N-1)、昨日(N-2)は将来のデータがないため極小値の判定対象から除外し、先読みバイアスを防ぎます。
    """
    n = len(series)
    low_indices = []
    
    # 25営業日前から3営業日前までの範囲を探索 (今日がN-1)
    start_idx = max(2, n - window)
    end_idx = n - 2  # n-2は含まないため、探索は n-3 (3営業日前) まで
    
    for i in range(start_idx, end_idx):
        val = series.iloc[i]
        # 前後2営業日の計5日間で、自身が最小値であるかを判定
        if (val < series.iloc[i-1] and val < series.iloc[i-2] and 
            val < series.iloc[i+1] and val < series.iloc[i+2]):
            low_indices.append(i)
            
    return low_indices

# 3. 判定および採点ロジック関数（プロンプト要件・完全対応版）
def evaluate_logic(df_temp, short_window, long_window, market_type):
    df_temp = df_temp.copy()
    if isinstance(df_temp.columns, pd.MultiIndex):
        df_temp.columns = df_temp.columns.get_level_values(0)
        
    # 生データから正確なRSIを算出
    df_temp['rsi'] = calculate_rsi(df_temp['Close'], 14)
        
    df_temp['short_ma'] = df_temp['Close'].rolling(window=short_window).mean()
    df_temp['long_ma'] = df_temp['Close'].rolling(window=long_window).mean()
    
    # ロジックに必要な日数が確保されているか確認 (最長30日間の過去データ参照 + 長期線日数)
    min_required_data_for_logic = max(long_window + 1, 31 + 1) # long_window + 1 (MA計算), 30 + 1 (slope_30d)
    
    # 初回データ不足チェック (MA計算前)
    if len(df_temp) < min_required_data_for_logic:
        return {
            "category": "NONE", "categoryName": "データ不足",
            "badgeClass": "bg-slate-800 text-slate-500 border border-slate-700",
            "diffRate": 0.0, "reason": "分析に必要な生データ期間が不足しています。",
            "ma_short": 0.0, "ma_long": 0.0, "score": 1,
            "rsi": 50.0, "rsi_buy_reversal": False, "rsi_double_bottom": False, "rsi_divergence": False, "rsi_sell_warning": False,
            "score_reasons": []
        }

    df_temp = df_temp.dropna(subset=['short_ma', 'long_ma']) # NaN除去は移動平均線計算後
    
    # NaN除去後のデータ不足チェック
    if len(df_temp) < min_required_data_for_logic:
         return {
            "category": "NONE", "categoryName": "データ不足",
            "badgeClass": "bg-slate-800 text-slate-500 border border-slate-700",
            "diffRate": 0.0, "reason": "移動平均線計算後、分析に必要なデータ期間が不足しています。",
            "ma_short": 0.0, "ma_long": 0.0, "score": 1,
            "rsi": 50.0, "rsi_buy_reversal": False, "rsi_double_bottom": False, "rsi_divergence": False, "rsi_sell_warning": False,
            "score_reasons": []
        }
    
    # インデックスをリセットしてilocアクセスを安全に (末尾から-1, -2, ... のアクセスを保証)
    df_temp = df_temp.reset_index(drop=True)
        
    today = df_temp.iloc[-1]
    yesterday = df_temp.iloc[-2]
    
    price_today = float(today['Close'])
    price_yesterday = float(yesterday['Close'])
    open_today = float(today['Open'])
    high_today = float(today['High'])
    low_today = float(today['Low'])
    
    short_ma_today = float(today['short_ma'])
    short_ma_yesterday = float(yesterday['short_ma'])
    long_ma_today = float(today['long_ma'])
    long_ma_yesterday = float(yesterday['long_ma'])
    
    diff_rate = ((price_today - long_ma_today) / long_ma_today) * 100
    
    # ------------------------------------------
    # ★ 新規追加/修正：移動平均線の傾きと位置関係に関する詳細な判定変数
    # ------------------------------------------
    # 長期線の傾き (パーセンテージ変化率)
    # df_temp.iloc[-N-1]はN日前のデータにアクセスするためのもの (iloc[-1]が本日、iloc[-2]が昨日)
    long_ma_slope_3d_pct = ((long_ma_today - df_temp.iloc[-4]['long_ma']) / df_temp.iloc[-4]['long_ma']) * 100 if df_temp.iloc[-4]['long_ma'] != 0 else 0
    long_ma_slope_10d_pct = ((long_ma_today - df_temp.iloc[-11]['long_ma']) / df_temp.iloc[-11]['long_ma']) * 100 if df_temp.iloc[-11]['long_ma'] != 0 else 0
    long_ma_slope_15d_pct = ((long_ma_today - df_temp.iloc[-16]['long_ma']) / df_temp.iloc[-16]['long_ma']) * 100 if df_temp.iloc[-16]['long_ma'] != 0 else 0
    long_ma_slope_20d_pct = ((long_ma_today - df_temp.iloc[-21]['long_ma']) / df_temp.iloc[-21]['long_ma']) * 100 if df_temp.iloc[-21]['long_ma'] != 0 else 0
    long_ma_slope_30d_pct = ((long_ma_today - df_temp.iloc[-31]['long_ma']) / df_temp.iloc[-31]['long_ma']) * 100 if df_temp.iloc[-31]['long_ma'] != 0 else 0

    # 短期線の傾き (パーセンテージ変化率)
    short_ma_slope_3d_pct = ((short_ma_today - df_temp.iloc[-4]['short_ma']) / df_temp.iloc[-4]['short_ma']) * 100 if df_temp.iloc[-4]['short_ma'] != 0 else 0
    
    is_yang_candle = price_today > open_today
    is_price_up = price_today > price_yesterday
    
    # ------------------------------------------
    # ★ RSI シグナル検出セクション (変更なし)
    # ------------------------------------------
    rsi_series = df_temp['rsi']
    price_low_series = df_temp['Low']
    
    rsi_today = float(rsi_series.iloc[-1])
    rsi_yesterday = float(rsi_series.iloc[-2])
    
    # --- ① 過熱警戒 (減点 -1) ---
    is_rsi_sell_warning = False
    if rsi_today >= 70:
        is_rsi_sell_warning = True
    else:
        # 直近5営業日以内に70を超えた履歴があり、本日70を下抜け、かつ前日比RSI低下
        recent_rsi_5d = rsi_series.iloc[-6:-1]
        if (recent_rsi_5d > 70).any() and (rsi_yesterday >= 70) and (rsi_today < 70) and (rsi_today < rsi_yesterday):
            is_rsi_sell_warning = True

    # --- ② 通常反発 (加点 +1) ---
    is_rsi_buy_reversal = False
    recent_rsi_3d = rsi_series.iloc[-4:-1]  # 過去3営業日
    if (recent_rsi_3d <= 30).any():
        # 本日RSIが前日比+2.0%以上向上、または本日のローソク足が陽線
        if (rsi_today >= rsi_yesterday + 2.0) or is_yang_candle:
            is_rsi_buy_reversal = True

    # --- ③ 底値切り上がりダブルボトム (加点 +2) ---
    is_rsi_double_bottom = False
    rsi_lows = find_swing_lows(rsi_series, 25)
    # RSIが30%以下の領域に制限
    rsi_lows_30 = [i for i in rsi_lows if rsi_series.iloc[i] <= 30]
    
    if len(rsi_lows_30) >= 2:
        t1 = rsi_lows_30[-2]
        t2 = rsi_lows_30[-1]
        # 成立条件チェック
        if (5 <= (t2 - t1) <= 20) and (rsi_series.iloc[t2] > rsi_series.iloc[t1]):
            if (rsi_today > rsi_series.iloc[t2]) and (rsi_today > rsi_yesterday):
                is_rsi_double_bottom = True

    # --- ④ 強気のダイバージェンス (加点 +1) ---
    is_rsi_divergence = False
    price_lows = find_swing_lows(price_low_series, 25)
    
    if len(price_lows) >= 2:
        d1 = price_lows[-2]
        d2 = price_lows[-1]
        # 成立条件チェック
        if (5 <= (d2 - d1) <= 20) and (price_low_series.iloc[d2] < price_low_series.iloc[d1]):
            if rsi_series.iloc[d2] > rsi_series.iloc[d1]:
                # 本日が底打ち反発局面
                if (rsi_today <= 45) and (rsi_today > rsi_yesterday):
                    is_rsi_divergence = True

    # 急騰判定
    df_recent_40d = df_temp.tail(40)
    max_price_40d = df_recent_40d['Close'].max()
    min_price_40d = df_recent_40d['Close'].min()
    price_surge_ratio = max_price_40d / min_price_40d if min_price_40d > 0 else 1.0
    is_surged_stock = price_surge_ratio >= 1.50
    
    # 乖離率しきい値
    warning_suffix = ""
    if market_type == "東Ｐ":
        if is_surged_stock:
            oversold_threshold = -15.0 if long_window <= 25 else -20.0
            warning_suffix = " (⚠️直近急騰につきグロース警戒基準を適用)"
        else:
            oversold_threshold = -8.0 if long_window <= 25 else -12.0
    elif market_type == "東Ｓ":
        oversold_threshold = -12.0 if long_window <= 25 else -18.0
    elif market_type == "東Ｇ":
        oversold_threshold = -15.0 if long_window <= 25 else -20.0
    else:
        oversold_threshold = -10.0 if long_window <= 25 else -15.0
    
    # 出来高25日平均比
    recent_volumes = df_temp['Volume'].iloc[-26:-1]
    vol_ma25 = recent_volumes.mean() if len(recent_volumes) > 0 else 0
    vol_ratio = today['Volume'] / vol_ma25 if vol_ma25 > 0 else 1.0
    
    # 相対長期線変化率
    ma_change_series = df_temp['long_ma'].pct_change()
    ma_change_today = ma_change_series.iloc[-1]
    baseline_change_120d = ma_change_series.abs().tail(120).mean()
    is_slope_strong_relative = (ma_change_today > 0) and (ma_change_today > baseline_change_120d)
    
    # ローソク足形状
    candle_body_pct = ((price_today - open_today) / open_today) * 100 if open_today > 0 else 0.0
    max_body = max(price_today, open_today)
    upper_shadow = high_today - max_body
    total_range = high_today - low_today
    upper_shadow_pct = (upper_shadow / total_range) * 100 if total_range > 0 else 0.0

    category = "NONE"
    category_name = "条件外"
    badge_class = "bg-slate-800 text-slate-500 border border-slate-700"
    reason = f"シグナル(1〜4)条件からは外れています(長期線乖離: {diff_rate:.1f}%)。"
    
    # ------------------------------------------
    # ★ 改善された判定ロジック (ダマシ回避と人間的判断の再現)
    # ------------------------------------------

    # 買い4 (変更なし)
    if diff_rate <= oversold_threshold:
        if is_yang_candle or is_price_up:
            category = "BUY4"
            category_name = "買い4：逆張りリバ"
            badge_class = "bg-purple-500/15 text-purple-300 border border-purple-500/30"
            reason = f"{long_window}日移動平均線({long_ma_today:,.0f}円)から下方に大きく乖離({diff_rate:.1f}%)。本日反発しました。{warning_suffix}"

    # 買い1 (新規買い初動)
    # 長らく長期線の下に沈み、長期線も下降/横ばいだったものが、トレンド転換しつつ上抜ける初動
    
    # 条件1: 株価または短期線が長期線を上抜けた
    crossed_above_ma = (price_yesterday < long_ma_yesterday and price_today >= long_ma_today) or \
                       (short_ma_yesterday < long_ma_yesterday and short_ma_today >= long_ma_today)

    # 条件2: 長らく長期線の下に沈んでいた (過去20日中12日以上、終値が長期線の下)
    below_count_20d = (df_temp.iloc[-21:-1]['Close'] < df_temp.iloc[-21:-1]['long_ma']).sum()
    is_long_period_below_ma = below_count_20d >= 12

    # 条件3: 長期線が過去に下降または横ばいだった (過去20日の平均傾きがほぼ0以下)
    long_ma_history_slice_20d = df_temp.iloc[-21:-1]['long_ma']
    was_long_ma_flat_or_down_recent = long_ma_history_slice_20d.diff().mean() <= 0.01 if len(long_ma_history_slice_20d) > 1 else True # ほぼ横ばいか下降
    
    # 条件4: 直近で長期線が上向きに転換した (3日間の長期線変化率がプラス)
    is_long_ma_turning_up_recently = long_ma_slope_3d_pct > 0.01

    if category == "NONE" and crossed_above_ma and is_long_period_below_ma \
       and was_long_ma_flat_or_down_recent and is_long_ma_turning_up_recently \
       and (diff_rate <= 5.0): # 乖離率の制限は維持
        category = "BUY1"
        category_name = "買い1：新規買い"
        badge_class = "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
        reason = f"株価が長らく長期線の下で推移後、長期線が下落/横ばいから上向きに転換し、本日明確に上抜けました。"

    # 買い2 (再突き抜け) - 安定した上昇トレンド中の一時的な押し目からの復帰
    # 「買い1」とは異なり、既に上昇トレンドが確立されている銘柄が対象
    
    # 条件1: 長期線が安定した上昇トレンド (10日と20日の傾きが両方とも正で、かつ一定の閾値以上)
    is_long_ma_stable_rising = (long_ma_slope_10d_pct > 0.03) and \
                               (long_ma_slope_20d_pct > 0.05) # 例: 10日で0.03%, 20日で0.05%上昇

    # 条件2: 短期的に長期線を下抜けた後、本日復帰 (過去10日中に1-4日のみ下抜け)
    below_count_10d = (df_temp.iloc[-11:-1]['Close'] < df_temp.iloc[-11:-1]['long_ma']).sum()
    is_temp_dip = 1 <= below_count_10d <= 4 # 既存ロジックを再利用
    recovered_above = (price_yesterday < long_ma_yesterday) and (price_today >= long_ma_today) # 既存ロジックを再利用

    # 条件3: 「買い1」の条件とは排他的 (長期間下抜けしていた銘柄は「買い1」で処理されるべき)
    if category == "NONE" and is_long_ma_stable_rising and is_temp_dip and recovered_above \
       and (0.0 <= diff_rate <= 5.0) and not is_long_period_below_ma: # BUY1の条件と排他
        category = "BUY2"
        category_name = "買い2：再突き抜け"
        badge_class = "bg-sky-500/15 text-sky-300 border border-sky-500/30"
        reason = f"安定した上昇トレンド中、長期線を一時的に下抜け後、本日素早く上方に復帰しました。"

    # 買い3（通常：陽線＋プラス反発）& 買い3-Pre（下落日待ち伏せ用：支持線接触）
    # 非常に強力な上昇トレンド中での教科書通りの押し目反発のみを検出
    
    # 条件1: 長期線が非常に強力な右肩上がりトレンド (15日と30日の傾きが両方とも正で、かつより高い閾値以上)
    is_long_ma_very_strong_rising = (long_ma_slope_15d_pct > 0.08) and \
                                    (long_ma_slope_30d_pct > 0.1) # 例: 15日で0.08%, 30日で0.1%上昇

    # 条件2: 短期線が長期線の上で継続的に推移している (過去15日中10日以上で短期線が長期線の上)
    short_ma_above_long_ma_count_15d = (df_temp.iloc[-16:-1]['short_ma'] > df_temp.iloc[-16:-1]['long_ma']).sum()
    is_short_ma_mostly_above_long_ma = short_ma_above_long_ma_count_15d >= 10

    # 条件3: 過去に長期線から大きく上放れた実績がある (押し目の前提)
    max_diff_15d_close_ma = ((df_temp.iloc[-16:-1]['Close'] - df_temp.iloc[-16:-1]['long_ma']) / df_temp.iloc[-16:-1]['long_ma'] * 100).max()
    has_pulled_back = max_diff_15d_close_ma >= 4.0

    # BUY3 (通常：陽線＋プラス反発)
    is_close_to_ma = 0.0 < diff_rate <= 3.5
    is_rebound = is_yang_candle and is_price_up
    
    if category == "NONE" and is_long_ma_very_strong_rising and is_short_ma_mostly_above_long_ma \
       and has_pulled_back and is_close_to_ma and is_rebound:
        category = "BUY3"
        category_name = "買い3：押し目反発"
        badge_class = "bg-amber-500/15 text-amber-300 border border-amber-500/30"
        reason = f"強力な上昇トレンドの長期線を支持線とした、教科書通りの綺麗な陽線反発を観測しました。"

    # BUY3-Pre（下落日待ち伏せ用：支持線接触）
    is_resting_on_ma = -0.5 <= diff_rate <= 1.5
    # 短期線の上昇傾向も考慮 (短期線が下向きだと押し目買いにはリスクがあるため)
    is_short_ma_rising_for_pre = short_ma_slope_3d_pct > 0.01

    if category == "NONE" and is_long_ma_very_strong_rising and is_short_ma_mostly_above_long_ma \
       and has_pulled_back and is_resting_on_ma and is_short_ma_rising_for_pre:
        category = "BUY3_PRE"
        category_name = "買い3：押し目待ち伏せ"
        badge_class = "bg-amber-600/10 text-amber-400 border border-amber-500/20"
        reason = f"強力な長期上昇トレンド中、支持線接触まで十分に引き付けた仕込み待ち伏せ状態です。"

# 期待度スコア (RSI・クオンツ対応・内訳記録版)
    score = 3
    score_reasons = [] # ★ 新規追加：加減点の具体的な理由を記録するリスト
    
    if category != "NONE":
        # 1. 新しい4大RSIシグナルのスコアリング (変更なし)
        if is_rsi_sell_warning:
            score -= 1  # ① 過熱警戒 (-1)
            score_reasons.append("⚠️ RSI過熱警戒: -1")
        if is_rsi_buy_reversal:
            score += 1  # ② 通常反発 (+1)
            score_reasons.append("🔄 RSIゾーン反発: +1")
        if is_rsi_double_bottom:
            score += 2  # ③ Wボトム特別反発 (+2)
            score_reasons.append("📈 Wボトム特別反発: +2")
        if is_rsi_divergence:
            score += 1  # ④ 強気のダイバージェンス (+1)
            score_reasons.append("🛡️ 強気ダイバージェンス: +1")

        # 2. 既存のテクニカル加減点ロジック (一部調整)
        if vol_ratio >= 1.5:
            score += 1
            score_reasons.append("📊 出来高急増: +1")
        
        # 上髭超過の減点 (BUY4, BUY3_PRE以外に適用)
        if category not in ["BUY4", "BUY3_PRE"] and upper_shadow_pct >= 40.0:
            score -= 1
            score_reasons.append("🕯️ 上髭超過: -1")
            
        if category == "BUY1":
            # BUY1はトレンド転換初動のため、反発実体の強さを評価
            if candle_body_pct >= 1.0: # 陽線実体がしっかりある
                score += 1
                score_reasons.append("📈 反発実体堅調: +1")
            elif candle_body_pct < 0.5 and is_yang_candle: # 陽線だが実体が極小の場合
                score -= 1
                score_reasons.append("🕯️ 反発実体極小: -1")
            
        elif category == "BUY2":
            # 安定トレンド中の一時的下抜けからの復帰なので、トレンド加速と反発実体の強さを評価
            if is_slope_strong_relative: 
                score += 1
                score_reasons.append("📈 長期線トレンド加速: +1")
            if candle_body_pct >= 1.0: # 陽線実体がしっかりある
                score += 1
                score_reasons.append("📈 反発実体堅調: +1")
            
        elif category in ["BUY3", "BUY3_PRE"]:
            # 押し目なので、支持線への近さと反発実体の強さを評価
            if diff_rate <= 1.5: # 支持線に極めて近い場所での反発/待ち伏せ
                score += 1
                score_reasons.append("📏 支持線極近: +1")
            if category == "BUY3" and candle_body_pct >= 1.0: # BUY3は陽線反発が前提
                score += 1
                score_reasons.append("📈 反発実体堅調: +1")
            elif category == "BUY3" and candle_body_pct < 0.5 and is_yang_candle:
                score -= 1
                score_reasons.append("🕯️ 反発実体極小: -1")
            
        elif category == "BUY4":
            # 逆張りリバなので、強い反発（大陽線）を評価
            if candle_body_pct >= 3.0: # 大陽線での強い反発
                score += 1
                score_reasons.append("📈 大陽線反発: +1")
            elif candle_body_pct < 0.5 and is_yang_candle: # 陽線だが実体が極小の場合
                score -= 1
                score_reasons.append("🕯️ 反発実体極小: -1")
            
    score = max(1, min(5, score)) # スコアは1〜5にクランプ
    stars_str = "★" * score + "☆" * (5 - score)

    return {
        "category": clean_val(category),
        "categoryName": clean_val(category_name),
        "badgeClass": clean_val(badge_class),
        "diffRate": clean_val(diff_rate),
        "reason": clean_val(reason),
        "ma_short": clean_val(round(short_ma_today, 1)),
        "ma_long": clean_val(round(long_ma_today, 1)),
        "score": clean_val(int(score)),
        "stars": clean_val(stars_str),
        "rsi": clean_val(round(rsi_today, 1)),
        "rsi_sell_warning": is_rsi_sell_warning,
        "rsi_buy_reversal": is_rsi_buy_reversal,
        "rsi_double_bottom": is_rsi_double_bottom,
        "rsi_divergence": is_rsi_divergence,
        "score_reasons": score_reasons
    }

# ----------------------------------------------------------------------
# ★【Phase 1】東証33業種 HOTセクター自動算出関数 (時価総額/売買代金加重モデル)
# ----------------------------------------------------------------------
def calculate_hot_sectors(bulk_data, results_list, ticker_to_sector):
    """
    東証33業種ごとに資金流入度をスコア化(0〜100点)し、
    閾値を超えた「本日のHOT業種」を最大5業種まで抽出します。
    """
    sector_data = {}
    
    # 1. 業種ごとに全銘柄のパフォーマンスと売買代金をグループ集計
    for ticker, df in bulk_data.items():
        if df.empty or len(df) < 25:
            continue
            
        sector = ticker_to_sector.get(ticker)
        if not sector or sector == "不明":
            continue
            
        today = df.iloc[-1]
        yesterday = df.iloc[-2]
        price_today = float(today['Close'])
        price_yesterday = float(yesterday['Close'])
        
        if price_yesterday <= 0:
            continue
            
        change_rate = ((price_today - price_yesterday) / price_yesterday) * 100
        trading_value = price_today * float(today['Volume'])  # 本日の売買代金(ウェイト)
        
        # 5日移動平均線の傾き(短期モメンタム)
        ma5_today = df['Close'].tail(5).mean()
        ma5_5days_ago = df['Close'].iloc[-10:-5].mean() if len(df) >= 10 else ma5_today
        is_ma5_up = ma5_today > ma5_5days_ago

        if sector not in sector_data:
            sector_data[sector] = {
                "total_value": 0.0,
                "weighted_change_sum": 0.0,
                "signal_value": 0.0,
                "ma5_up_count": 0,
                "total_stocks": 0
            }
            
        sector_data[sector]["total_value"] += trading_value
        sector_data[sector]["weighted_change_sum"] += change_rate * trading_value
        sector_data[sector]["total_stocks"] += 1
        if is_ma5_up:
            sector_data[sector]["ma5_up_count"] += 1

    if not sector_data:
        return [], {}

    # 2. シグナル点灯銘柄の売買代金シェアを集計
    for item in results_list:
        ticker = item["ticker"] + ".T"
        sector = item["sector"]
        if sector in sector_data:
            today_price = item["price"]
            today_vol = item["volume"]
            sector_data[sector]["signal_value"] += (today_price * today_vol)

    # 3. 各業種の総合スコア(0〜100点)の算出
    scored_sectors = []
    
    for sector, s_info in sector_data.items():
        if s_info["total_value"] <= 0 or s_info["total_stocks"] < 3:
            continue
            
        # ① 加重平均騰落率 (%)
        weighted_change = s_info["weighted_change_sum"] / s_info["total_value"]
        
        # ② 加重シグナル密度 (%)：業種全体の売買代金に対するシグナル点灯銘柄のシェア
        signal_density = (s_info["signal_value"] / s_info["total_value"]) * 100
        
        # ③ 短期モメンタム比率 (%)：5日線が上向きの銘柄割合
        ma5_up_ratio = (s_info["ma5_up_count"] / s_info["total_stocks"]) * 100

        # --- 0〜100点への標準化スコアリング ---
        # パフォーマンス点 (最大40点) : 騰落率 +3%で満点
        score_perf = min(40.0, max(0.0, (weighted_change + 1.0) * 10.0))
        
        # シグナル密度点 (最大40点) : 点灯シェア 20%で満点
        score_density = min(40.0, max(0.0, signal_density * 2.0))
        
        # モメンタム点 (最大20点) : 5日線上向き率 70%で満点
        score_momentum = min(20.0, max(0.0, ma5_up_ratio * 0.285))
        
        total_score = round(score_perf + score_density + score_momentum, 1)

        scored_sectors.append({
            "sector": sector,
            "score": total_score,
            "changeRate": round(weighted_change, 2),
            "signalDensity": round(signal_density, 1)
        })

    # 4. スコア順にソートし、絶対閾値(55.0点以上)を満たす上位最大5業種を判定
    scored_sectors.sort(key=lambda x: x["score"], reverse=True)
    
    HOT_THRESHOLD = 55.0  # 絶対閾値
    hot_sectors = [s for s in scored_sectors if s["score"] >= HOT_THRESHOLD][:5]

    return hot_sectors, sector_data

# 4. 全データの判定実行 (足切り69日・最適化版)
results_list = []
print("各銘柄の判定ロジックを実行しています...")

# 短期・中期いずれのシステムでも確実にNONE（データ不足）になる若い銘柄を
# スキャンの初期段階で事前にスキップするための数学的最低日数（候補①：69日）
# evaluate_logic内で min_required_data を計算するようにしたので、ここでは一旦緩和
# ただし、yfinanceのダウンロードでデータが短い場合は処理しないため、最低限の期間は確保
MIN_REQUIRED_DAYS_FOR_DOWNLOAD = 69 

for ticker, df_stock in bulk_data.items():
    if df_stock.empty or len(df_stock) < MIN_REQUIRED_DAYS_FOR_DOWNLOAD: 
        continue
        
    today = df_stock.iloc[-1]
    yesterday = df_stock.iloc[-2]
    
    price_today = float(today['Close'])
    price_yesterday = float(yesterday['Close'])
    change = price_today - price_yesterday
    change_rate = (change / price_yesterday) * 100 if price_yesterday > 0 else 0.0
    
    volume_today = float(today['Volume'])
    is_low_volume = volume_today <= 10000
    
    market_raw = ticker_to_market.get(ticker, "")
    if "プライム" in market_raw:
        market_short = "東Ｐ"
    elif "スタンダード" in market_raw:
        market_short = "東Ｓ"
    elif "グロース" in market_raw:
        market_short = "東Ｇ"
    else:
        market_short = "他"
        
    # short_window, long_window は SYSTEM_TYPE に依存しない固定値で evaluate_logic に渡す
    short_res = evaluate_logic(df_stock, 5, 25, market_short)
    mid_res = evaluate_logic(df_stock, 25, 75, market_short)
    
    # ★【超軽量化ハック】短期・中期ともに「NONE(条件外)」の無駄データは結果リストに入れない
    if short_res["category"] == "NONE" and mid_res["category"] == "NONE":
        continue

# ★ 新規追加：前日データとの比較および連続日数の計算
    ticker_clean = ticker.replace(".T", "")
    yesterday_data = prev_results_by_ticker.get(ticker_clean)

    for sys_key, sys_res in [("short", short_res), ("mid", mid_res)]:
        if sys_res["category"] != "NONE":
            consecutive = 1
            prev_cat_name = None

            # 前日もこのシステムでデータが存在し、かつ条件外(NONE)ではない場合
            if yesterday_data and sys_key in yesterday_data:
                yes_sys = yesterday_data[sys_key]
                yes_cat = yes_sys.get("category", "NONE")

                if yes_cat != "NONE":
                    # 連続日数を1増やす
                    yes_consecutive = yes_sys.get("consecutiveDays", 1)
                    consecutive = yes_consecutive + 1

                    # 前日と今回の条件が異なる場合のみ、前日の条件名を記録
                    if yes_cat != sys_res["category"]:
                        prev_cat_name = yes_sys.get("categoryName", yes_cat).split('：')[0]

            sys_res["consecutiveDays"] = consecutive
            sys_res["prevCategory"] = prev_cat_name
        else:
            sys_res["consecutiveDays"] = 0
            sys_res["prevCategory"] = None
    # ★ ここまで追加    
    
    stock_info = {
        "ticker": clean_val(ticker.replace(".T", "")),
        "name": clean_val(ticker_to_name.get(ticker, "不明な銘柄")),
        "market": market_short,
        "sector": clean_val(ticker_to_sector.get(ticker, "不明")),
        "price": clean_val(price_today),
        "change": clean_val(change),
        "changeRate": clean_val(round(change_rate, 2)),
        "volume": clean_val(volume_today),
        "isLowVolume": clean_val(is_low_volume),
        "isStrongRelative": False,
        "short": short_res,
        "mid": mid_res
    }
    results_list.append(stock_info)

# 本日の東証全銘柄の騰落中央値を算出 (変更なし)
all_rates = [item["changeRate"] for item in results_list if item["changeRate"] is not None]
market_median_change = float(pd.Series(all_rates).median()) if all_rates else 0.0
print(f" -> 本日の東証全上場銘柄の騰落率中央値: {market_median_change:.2f}%")

# ★【Phase 1】東証33業種 HOTセクターの自動算出を実行
hot_sectors, all_sector_stats = calculate_hot_sectors(bulk_data, results_list, ticker_to_sector)
hot_sector_names = [s["sector"] for s in hot_sectors]
print(f" -> 本日のHOT業種 ({len(hot_sectors)}件検知): {', '.join(hot_sector_names) if hot_sectors else 'なし'}")

# ★【Phase 2】HOT業種に属する銘柄への期待度+1加点 ＆ 内訳理由の記録
for item in results_list:
    sector = item["sector"]
    is_hot = sector in hot_sector_names
    item["isHotSector"] = is_hot
    
    if is_hot:
        for sys_key in ["short", "mid"]:
            sys_data = item[sys_key]
            if sys_data["category"] != "NONE":
                # 期待度を+1（最大5点にクランプ）
                new_score = min(5, sys_data["score"] + 1)
                sys_data["score"] = new_score
                
                # score_reasonsがNoneの場合は空リストで初期化
                if sys_data["score_reasons"] is None:
                    sys_data["score_reasons"] = []
                sys_data["score_reasons"].append(f"🔥 追い風業種 ({sector}): +1")
                sys_data["stars"] = "★" * new_score + "☆" * (5 - new_score) # 星も更新

# 地合い強気銘柄の判定および加点 (スコア理由と星の更新を追加)
for item in results_list:
    is_strong_relative = False
    if market_median_change <= -1.0: # 市場が大きく下げている場合
        # この銘柄が市場平均より1.5%以上良い成績の場合に「地合い強気」と判断
        is_strong_relative = item["changeRate"] >= (market_median_change + 1.5)
        
    if is_strong_relative:
        item["isStrongRelative"] = True
        for sys_key in ["short", "mid"]:
            if item[sys_key]["category"] != "NONE":
                new_score = min(5, item[sys_key]["score"] + 1)
                item[sys_key]["score"] = new_score
                # score_reasonsがNoneの場合は空リストで初期化
                if item[sys_key]["score_reasons"] is None:
                    item[sys_key]["score_reasons"] = []
                item[sys_key]["score_reasons"].append("🛡️ 地合い強気: +1")
                item[sys_key]["stars"] = "★" * new_score + "☆" * (5 - new_score) # 星も更新

json_data_str = json.dumps(results_list, ensure_ascii=False, indent=2)
hot_sectors_json_str = json.dumps(hot_sectors, ensure_ascii=False)
form_cat_str = json.dumps(FORM_CONFIG_CAT, ensure_ascii=False)
form_score_str = json.dumps(FORM_CONFIG_SCORE, ensure_ascii=False)

# 昨日総計の集計をJSに渡す（NONEを除外した昨日各カテゴリ総計）
prev_counts_json_str = json.dumps(prev_counts, ensure_ascii=False)

# HTMLテンプレート (UI変更なし)
html_template = """<!doctype html>
<html lang="ja">
  <head>
    <meta charset="UTF-8" />
    <meta name="robots" content="noindex, nofollow, noarchive" />
    <title>グランビル法則スクリーナー 📈 東証全市場統合ダッシュボード</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Noto+Sans+JP:wght@400;500;700&display=swap" rel="stylesheet">
    <script>
      tailwind.config = {
        theme: {
          extend: {
            fontFamily: {
              sans: ['"Inter"', '"Noto Sans JP"', 'sans-serif'],
              mono: ['"JetBrains Mono"', 'monospace'],
            },
            colors: {
              brand: {
                50: '#f0f9ff',
                100: '#e0f2fe',
                500: '#0ea5e9',
                600: '#0284c7',
                700: '#0369a1',
                900: '#0c4a6e',
              }
            }
          }
        }
      }
    </script>
    <style>
      body { background-color: #0b0f19; color: #e2e8f0; }
      ::-webkit-scrollbar { width: 8px; height: 8px; }
      ::-webkit-scrollbar-track { background: #121824; }
      ::-webkit-scrollbar-thumb { background: #28354c; border-radius: 4px; }
      ::-webkit-scrollbar-thumb:hover { background: #3c4f74; }
    </style>
  </head>
  <body class="min-h-screen font-sans antialiased selection:bg-brand-500 selection:text-white pb-16">
    
    <!-- ヘッダー -->
    <header class="border-b border-slate-800/80 bg-slate-900/80 backdrop-blur sticky top-0 z-30">
      <div class="max-w-[1550px] mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div class="flex items-center space-x-3">
          <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-cyan-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-cyan-500/20 text-white font-bold text-xl">G</div>
          <div>
            <h1 class="text-base sm:text-lg font-bold text-white tracking-tight flex items-center gap-2">
              全自動グランビル・スクリーナー
              <span class="text-[10px] sm:text-xs px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-mono font-normal">PRO v3.8_ULTIMATE</span>
            </h1>
            <p class="text-xs text-slate-400 hidden sm:block">東証全市場自動解析・高精度ロジック（最終更新：__LAST_UPDATE__）</p>
          </div>
        </div>
        
        <!-- 短期・中期切り替え -->
        <div class="bg-slate-950 p-1 rounded-xl border border-slate-800 flex gap-1 text-xs">
          <button id="btnSystemShort" class="px-4 py-1.5 rounded-lg font-bold transition duration-200 text-slate-400 hover:text-slate-100 cursor-pointer">
            短期 (5日/25日線)
          </button>
          <button id="btnSystemMid" class="px-4 py-1.5 rounded-lg font-bold transition duration-200 bg-cyan-600 text-white shadow cursor-pointer">
            中期 (25日/75日線)
          </button>
        </div>
      </div>
    </header>

    <!-- メイン -->
    <main class="max-w-[1550px] mx-auto px-4 sm:px-6 lg:px-8 pt-6 space-y-6">

    <!-- ★ Phase 3: HOT業種ランキングバナー枠 -->
      <div id="hotSectorsBanner" class="hidden bg-slate-900/90 border border-amber-500/20 rounded-2xl p-3.5 shadow-xl flex flex-wrap items-center justify-between gap-3 text-xs">
        <!-- JavaScriptによってここにHOT業種バッジが挿入されます -->
      </div>
      
      <!-- サマリーカード -->
      <section class="grid grid-cols-2 md:grid-cols-5 gap-4">
        <div class="bg-slate-900/80 border border-slate-800 rounded-xl p-4 flex flex-col justify-between shadow-lg">
          <span class="text-[11px] font-bold text-slate-400 uppercase tracking-wider">東証判定シグナル数</span>
          <div class="flex items-baseline gap-2 mt-2">
            <span id="statTotal" class="text-2xl font-bold text-white">0</span>
            <span class="text-xs text-slate-500">銘柄</span>
            <span id="statTotalDiff" class="text-[10px] font-bold ml-1"></span>
          </div>
        </div>
        <div class="bg-slate-900/80 border border-emerald-500/20 rounded-xl p-4 flex flex-col justify-between shadow-lg">
          <span class="text-[11px] font-bold text-emerald-400 uppercase tracking-wider">買い1 (新規GC初動)</span>
          <div class="flex items-baseline justify-between mt-2" id="statBuy1">
            <span class="text-2xl font-bold text-emerald-400">0</span>
          </div>
        </div>
        <div class="bg-slate-900/80 border border-sky-500/20 rounded-xl p-4 flex flex-col justify-between shadow-lg">
          <span class="text-[11px] font-bold text-sky-400 uppercase tracking-wider">買い2 (下抜け復帰)</span>
          <div class="flex items-baseline justify-between mt-2" id="statBuy2">
            <span class="text-2xl font-bold text-sky-400">0</span>
          </div>
        </div>
        <div class="bg-slate-900/80 border border-amber-500/20 rounded-xl p-4 flex flex-col justify-between shadow-lg">
          <span class="text-[11px] font-bold text-amber-400 uppercase tracking-wider">買い3 (支持線反発/Pre)</span>
          <div class="flex items-baseline justify-between mt-2" id="statBuy3">
            <span class="text-2xl font-bold text-amber-400">0</span>
          </div>
        </div>
        <div class="bg-slate-900/80 border border-purple-500/20 rounded-xl p-4 flex flex-col justify-between shadow-lg">
          <span class="text-[11px] font-bold text-purple-400 uppercase tracking-wider">買い4 (下方乖離リバ)</span>
          <div class="flex items-baseline justify-between mt-2" id="statBuy4">
            <span class="text-2xl font-bold text-purple-400">0</span>
          </div>
        </div>
      </section>

      <!-- メインタスクエリア -->
      <section class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl flex flex-col">
        
        <!-- 複合コントロールバー -->
        <div class="flex flex-col xl:flex-row items-stretch xl:items-center justify-between gap-4 pb-4 border-b border-slate-800">
          
          <div class="flex flex-wrap items-center gap-3">
            <!-- 判定タブ -->
            <div class="flex bg-slate-950 p-1 rounded-xl border border-slate-800 text-xs w-full sm:w-auto" id="tabContainer">
              <button data-tab="BUY1" class="tab-btn px-4 py-1.5 rounded-lg font-medium bg-cyan-600 text-white shadow cursor-pointer">買い1</button>
              <button data-tab="BUY2" class="tab-btn px-4 py-1.5 rounded-lg text-slate-400 hover:text-white cursor-pointer">買い2</button>
              <button data-tab="BUY3" class="tab-btn px-4 py-1.5 rounded-lg text-slate-400 hover:text-white cursor-pointer">買い3</button>
              <button data-tab="BUY4" class="tab-btn px-4 py-1.5 rounded-lg text-slate-400 hover:text-white cursor-pointer">買い4</button>
              <button data-tab="ALL" class="tab-btn px-4 py-1.5 rounded-lg text-slate-500 hover:text-slate-300 cursor-pointer">すべて</button>
            </div>

            <!-- 市場フィルターボタン -->
            <div class="flex bg-slate-950 p-1 rounded-xl border border-slate-800 text-xs" id="marketFilterContainer">
              <span class="text-slate-500 self-center px-2.5 font-bold border-r border-slate-800 mr-1.5">市場</span>
              <button data-market="ALL" class="market-btn px-3 py-1.5 rounded-lg font-medium bg-slate-800 text-white cursor-pointer">すべて</button>
              <button data-market="東Ｐ" class="market-btn px-3 py-1.5 rounded-lg font-medium text-slate-400 hover:text-slate-100 cursor-pointer">東Ｐ</button>
              <button data-market="東Ｓ" class="market-btn px-3 py-1.5 rounded-lg font-medium text-slate-400 hover:text-slate-100 cursor-pointer">東Ｓ</button>
              <button data-market="東Ｇ" class="market-btn px-3 py-1.5 rounded-lg font-medium text-slate-400 hover:text-slate-100 cursor-pointer">東Ｇ</button>
            </div>
          </div>

          <!-- 検索 ＆ エクスポート -->
          <div class="flex items-center gap-3 w-full xl:w-auto">
            <div class="relative flex-1 xl:w-72">
              <input type="text" id="searchInput" placeholder="コード、銘柄名、業種で検索..." class="w-full bg-slate-950 border border-slate-800 rounded-xl pl-8 pr-3 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500 transition">
              <span class="absolute left-2.5 top-2 text-slate-500 text-xs">🔍</span>
            </div>
            <button id="btnExportCSV" class="bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 px-4 py-1.5 rounded-xl text-xs font-bold transition duration-200 cursor-pointer">📥 結果CSV出力</button>
          </div>
        </div>

        <!-- パフォーマンス警告バナー -->
        <div id="performanceWarning" class="mt-4 hidden bg-amber-500/10 border border-amber-500/20 text-amber-300 text-[11px] p-2.5 rounded-xl">
          ⚠️ 該当数が多いため最初の150件のみ表示しています。上の「市場別」「判定別」ボタンや検索窓を使って絞り込むとスムーズに閲覧できます。
        </div>

<!-- テーブル -->
        <div class="mt-6 overflow-x-auto">
          <table class="w-full text-left">
           <thead>
              <tr class="border-b border-slate-800 text-[11px] font-bold text-slate-400 uppercase bg-slate-950/60 select-none">
                <th class="p-3 w-20 whitespace-nowrap">判定</th>
                <!-- 幅を w-24 から w-16 に縮小 -->
                <th class="p-3 cursor-pointer select-none hover:text-cyan-400 text-center w-16 whitespace-nowrap transition duration-200" id="thScore" title="クリックで期待度順に並び替え">
                  <div class="flex items-center justify-center gap-1.5">
                    <span>期待度</span>
                    <span id="sortScoreIcon" class="text-cyan-400 font-mono text-[11px] w-3 text-center">↕</span>
                  </div>
                </th>
                <th class="p-3 w-28">コード</th>
                <th class="p-3 min-w-[200px]">銘柄名 / 業種</th>
                <th class="p-3 cursor-pointer select-none hover:text-cyan-400 text-right w-32 transition duration-200 whitespace-nowrap" id="thPrice" title="クリックで昇順/降順並び替え">
                  <div class="flex items-center justify-end gap-1.5">
                    <span>株価</span>
                    <span id="sortIcon" class="text-cyan-400 font-mono text-[11px] w-3 text-center">↕</span>
                  </div>
                </th>
                <th class="p-3 text-right w-36">前日比</th>
                <th class="p-3 text-right w-44" id="thma">5日線 / 25日線</th>
                <th class="p-3 text-right w-24">乖離率</th>
                <th class="p-3 text-center w-24">市場</th>
                <th class="p-3 text-center w-32">改善報告</th>
              </tr>
            </thead>
            <tbody id="resultTableBody" class="divide-y divide-slate-800/60 text-xs"></tbody>
          </table>
        </div>

        <!-- テーブルフッター -->
        <div class="mt-6 pt-4 border-t border-slate-800/80 flex flex-wrap items-center justify-between text-[11px] text-slate-400 gap-2">
          <span id="displayCountLabel" class="font-medium text-slate-300">表示中: 0 件</span>
          <div class="flex items-center gap-3 text-slate-500 font-mono text-[10px]">
            <span id="footerFormula">乖離率 = (株価 - 25日線) ÷ 25日線</span>
            <span>•</span>
            <span id="footerBase">基準線: 25日移動平均線</span>
          </div>
        </div>

      </section>

      <!-- 解説開閉ボタン -->
      <div class="flex justify-center mt-6">
        <button id="btnToggleExplanation" class="bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 px-6 py-2.5 rounded-xl text-xs font-bold transition duration-200 cursor-pointer shadow-md">
          📖 解説を表示
        </button>
      </div>

      <!-- 解説小窓 -->
      <section id="explanationSection" class="pt-6 border-t border-slate-800/60 hidden space-y-6">
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
          
          <!-- 左側：期待度マニュアル -->
          <div class="space-y-4">
            <h3 class="text-xs font-bold text-amber-400 uppercase tracking-wider flex items-center gap-2">
              <span>⭐</span> 期待度（1〜5）の評価要件マニュアル
            </h3>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
              <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-3.5">
                <span class="font-bold text-slate-200 block mb-1">基本採点（スタート値）</span>
                <p class="text-slate-400 text-[11px] leading-relaxed">
                  いずれかの買いシグナルが点灯した銘柄は、すべて初期値<strong>「3」</strong>として採点されます。
                </p>
              </div>
              <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-3.5">
                <span class="font-bold text-emerald-400 block mb-1">出来高急増ボーナス (+1)</span>
                <p class="text-slate-400 text-[11px] leading-relaxed">
                  本日の出来高が、過去25日間の移動平均出来高に対して <strong>1.5倍以上</strong> に急増している場合、大口の介入とみなし、星を加算。
                </p>
              </div>
              <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-3.5">
                <span class="font-bold text-cyan-400 block mb-1">相対的変化率ボーナス (+1)</span>
                <p class="text-slate-400 text-[11px] leading-relaxed">
                  本日の長期線の変化率が、過去半年間（120日）の平均変化スピードを上回っている（＝上昇トレンドが加速している）場合に星を加算。
                </p>
              </div>
              <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-3.5">
                <span class="font-bold text-purple-400 block mb-1">個別ローソク足補正 (+1 / -1)</span>
                <p class="text-slate-400 text-[11px] leading-relaxed">
                  ・(買い3) 線に極近(1.5%以下)で綺麗に反発 ➔ <strong>+1</strong><br>
                  ・(買い4) 3%以上の大陽線で反発 ➔ <strong>+1</strong><br>
                  ・(全共通) 上髭割合が40%以上 ➔ <strong>-1</strong><br>
                  ・(全共通) 反発時の実体が極小 ➔ <strong>-1</strong>
                </p>
              </div>
              <!-- 新規追加：トレンド方向性による減点 -->
              <div class="bg-slate-900/60 border border-rose-500/20 rounded-xl p-3.5">
                <span class="font-bold text-rose-400 block mb-1">トレンド下降減点 (-1〜-2)</span>
                <p class="text-slate-400 text-[11px] leading-relaxed">
                  ・長期線が直近で下降傾向にある場合 ➔ <strong>-1</strong><br>
                  ・さらに短期線が長期線の下で下降傾向の場合 ➔ <strong>追加で -1</strong>
                </p>
              </div>
            </div>
          </div>

          <!-- 右側：グランビル判定条件マニュアル -->
          <div class="space-y-4">
            <h3 class="text-xs font-bold text-cyan-400 uppercase tracking-wider flex items-center gap-2">
              <span>📖</span> グランビル買いシグナル（1〜4）詳細判定要件
            </h3>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
              <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-3.5 relative overflow-hidden">
                <span class="font-bold text-slate-300 block mb-1">買い1：新規買い初動</span>
                <p class="text-slate-400 text-[11px] leading-relaxed">
                  ・株価が長期線(<span class="exp-long"></span>)の下に<span class="font-mono">長期間沈み</span>、長期線自体も<span class="font-bold text-rose-300">下降/横ばい</span>だったが、<span class="font-bold text-emerald-300">本日上向きに転換しつつ</span>株価が上抜け。<br>
                  ・上抜け乖離率: 当日終値が長期線から <span class="font-mono">+5.0%</span> 以内
                </p>
              </div>
              <div class="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5">
                <span class="font-bold text-slate-200 block mb-1">買い2：一時下抜け復帰</span>
                <p class="text-slate-400 text-[11px] leading-relaxed">
                  ・長期線(<span class="exp-long"></span>)が<span class="font-bold text-emerald-300">安定した上昇トレンド</span>中、株価が一時的に下抜け後、本日素早く復帰。<br>
                  ・一時性: 過去10日で長期線の下に沈んだのが「1〜4日のみ」<br>
                  ・上抜け乖離率: 当日終値が長期線から <span class="font-mono">0.0%〜+5.0%</span> 以内
                </p>
              </div>
              <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-3.5">
                <span class="font-bold text-slate-200 block mb-1">買い3：押し目反発（待ち伏せ含む）</span>
                <p class="text-slate-400 text-[11px] leading-relaxed">
                  ・長期線(<span class="exp-long"></span>)が<span class="font-bold text-emerald-300">非常に強力な右肩上がりトレンド</span>中、短期線も長期線の上で推移。<br>
                  ・過去に株価が長期線から大きく上放れた実績あり。<br>
                  ・反発: 長期線のすぐ上(<span class="font-mono">0.0%〜+3.5%</span>)で本日反発。<br>
                  ・<strong>【下落日待ち伏せPre-Buy3】</strong>: 長期線の極近(JST -0.5%〜+1.5%)にあり、短期線も上向きなら特別点灯。
                </p>
              </div>
              <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-3.5">
                <span class="font-bold text-slate-200 block mb-1">買い4：逆張り下方乖離</span>
                <p class="text-slate-400 text-[11px] leading-relaxed">
                  下げ止まり(陽線または前日比プラス)を条件にリバウンド抽出。<br>
                  ・東Ｐ（通常）: <span id="expPNormal" class="font-mono"></span> 以下<br>
                  ・東Ｐ（急騰例外）: <span id="expPSurge" class="font-mono"></span> 以下<br>
                  ・東Ｓ: <span id="expS" class="font-mono"></span> 以下<br>
                  ・東Ｇ: <span id="expG" class="font-mono"></span> 以下
                </p>
              </div>
            </div>
          </div>

        </div>
      </section>

　　　 <!-- 詳細診断カルテ用ダイアログ (HTML5標準・ z-50で最前面) -->
      <dialog id="diagnosticDialog" class="bg-slate-900 border border-slate-800 text-slate-100 p-6 rounded-2xl shadow-2xl max-w-md w-full backdrop:bg-slate-950/80 focus:outline-none z-50">
        <div class="flex justify-between items-start border-b border-slate-800 pb-3 mb-4">
          <h3 id="dialogTitle" class="text-sm font-bold text-white tracking-tight flex items-center gap-2">📋 銘柄診断カルテ</h3>
          <button onclick="closeDiagnosticDialog()" class="text-slate-400 hover:text-white font-bold text-lg select-none cursor-pointer focus:outline-none">✕</button>
        </div>
        <div id="dialogContent" class="space-y-4 text-xs">
          <!-- JavaScriptによってここに情報が書き込まれます -->
        </div>
      </dialog>

    </main>

    <script>
      const state = {
        results: __PLACEHOLDER_RESULTS__,
        hotSectors: __PLACEHOLDER_HOT_SECTORS__, 
        prevCounts: __PLACEHOLDER_PREV_COUNTS__,
        marketMedian: __PLACEHOLDER_MARKET_MEDIAN__,
        currentSystem: 'mid',
        activeTab: 'BUY1',
        activeMarket: 'ALL',
        searchQuery: '',
        sortOrder: 'none',
        sortScoreOrder: 'none'
      };
      
      const FORM_CAT_CFG = /* PLACEHOLDER_FORM_CAT */ {};
      const FORM_SCORE_CFG = /* PLACEHOLDER_FORM_SCORE */ {};
      const MAX_RENDER_ROWS = 150;

      document.addEventListener('DOMContentLoaded', () => {
        document.getElementById('searchInput').addEventListener('input', (e) => {
          state.searchQuery = e.target.value.trim().toLowerCase();
          renderTable();
        });
        document.getElementById('btnSystemShort').addEventListener('click', () => switchSystem('short'));
        document.getElementById('btnSystemMid').addEventListener('click', () => switchSystem('mid'));
        document.getElementById('thPrice').addEventListener('click', togglePriceSort);
        document.getElementById('thScore').addEventListener('click', toggleScoreSort);
        document.getElementById('btnExportCSV').addEventListener('click', exportCSV);
        document.getElementById('btnToggleExplanation').addEventListener('click', toggleExplanation);

        document.querySelectorAll('.tab-btn').forEach(btn => {
          btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.className = 'tab-btn px-4 py-1.5 rounded-lg text-slate-400 hover:text-white cursor-pointer');
            btn.className = 'tab-btn px-4 py-1.5 rounded-lg bg-cyan-600 text-white shadow cursor-pointer';
            state.activeTab = btn.dataset.tab;
            renderTable();
          });
        });

        document.querySelectorAll('.market-btn').forEach(btn => {
          btn.addEventListener('click', () => {
            document.querySelectorAll('.market-btn').forEach(b => b.className = 'market-btn px-3 py-1.5 rounded-lg text-slate-400 hover:text-slate-100 cursor-pointer');
            btn.className = 'market-btn px-3 py-1.5 rounded-lg bg-slate-800 text-white cursor-pointer';
            state.activeMarket = btn.dataset.market;
            renderTable();
          });
        });

        renderHotSectorsBanner();
        switchSystem('mid');
      });
      function toggleExplanation() {
        const expSec = document.getElementById('explanationSection');
        const btn = document.getElementById('btnToggleExplanation');
        if (expSec.classList.contains('hidden')) {
          expSec.classList.remove('hidden');
          btn.textContent = '📖 解説を隠す';
        } else {
          expSec.classList.add('hidden');
          btn.textContent = '📖 解説を表示';
        }
      }

      function openCatFeedback(ticker, name, category) {
        const sysLabel = (state.currentSystem === 'short') ? "短期(5/25)" : "中期(25/75)";
        // 「?viewform&」を「?」に修正し、標準的なプリフィルURLにします
        const targetUrl = `${FORM_CAT_CFG.baseUrl}?${FORM_CAT_CFG.entryCode}=${encodeURIComponent(ticker)}&${FORM_CAT_CFG.entryName}=${encodeURIComponent(name)}&${FORM_CAT_CFG.entrySys}=${encodeURIComponent(sysLabel)}&${FORM_CAT_CFG.entryCat}=${encodeURIComponent(category)}`;
        window.open(targetUrl, '_blank', 'width=620,height=750');
      }

       function openScoreFeedback(ticker, name, score) {
        if (!FORM_SCORE_CFG.baseUrl || FORM_SCORE_CFG.baseUrl === "YOUR_SCORE_FORM_URL_HERE") {
          // ダブルクォーテーション " " を、改行に強いバッククォート ` ` に書き換えます
          alert(`【初期設定が必要です】\nコード冒頭の「FORM_CONFIG_SCORE」にご自身の2つ目のGoogleフォームのURLとIDを設定してください。`);
          return;
        }
        const sysLabel = (state.currentSystem === 'short') ? "短期(5/25)" : "中期(25/75)";
        const targetUrl = `${FORM_SCORE_CFG.baseUrl}?${FORM_SCORE_CFG.entryCode}=${encodeURIComponent(ticker)}&${FORM_SCORE_CFG.entryName}=${encodeURIComponent(name)}&${FORM_SCORE_CFG.entrySys}=${encodeURIComponent(sysLabel)}&${FORM_SCORE_CFG.entryScore}=${encodeURIComponent(score)}`;
        window.open(targetUrl, '_blank', 'width=620,height=750');
      }
      function togglePriceSort() {
        state.sortScoreOrder = 'none';
        document.getElementById('sortScoreIcon').textContent = '↕';
        if (state.sortOrder === 'none') {
          state.sortOrder = 'asc';
        } else if (state.sortOrder === 'asc') {
          state.sortOrder = 'desc';
        } else {
          state.sortOrder = 'none';
        }
        const sortIcon = document.getElementById('sortIcon');
        if (state.sortOrder === 'asc') sortIcon.textContent = '▲';
        else if (state.sortOrder === 'desc') sortIcon.textContent = '▼';
        else sortIcon.textContent = '↕';
        renderTable();
      }

      function toggleScoreSort() {
        state.sortOrder = 'none';
        document.getElementById('sortIcon').textContent = '↕';
        if (state.sortScoreOrder === 'none') {
          state.sortScoreOrder = 'desc';
        } else if (state.sortScoreOrder === 'desc') {
          state.sortScoreOrder = 'asc';
        } else {
          state.sortScoreOrder = 'none';
        }
        const sortScoreIcon = document.getElementById('sortScoreIcon');
        if (state.sortScoreOrder === 'asc') sortScoreIcon.textContent = '▲';
        else if (state.sortScoreOrder === 'desc') sortScoreIcon.textContent = '▼';
        else sortScoreIcon.textContent = '↕';
        renderTable();
      }

      function exportCSV() {
        const sys = state.currentSystem;
        let filtered = [...state.results];
        
        filtered = filtered.filter(r => r[sys].category !== "NONE");

        if (state.activeTab !== 'ALL') {
          if (state.activeTab === 'BUY3') {
            filtered = filtered.filter(r => r[sys].category === 'BUY3' || r[sys].category === 'BUY3_PRE');
          } else {
            filtered = filtered.filter(r => r[sys].category === state.activeTab);
          }
        }
        if (state.activeMarket !== 'ALL') filtered = filtered.filter(r => r.market === state.activeMarket);
        if (state.searchQuery) {
          filtered = filtered.filter(r => r.ticker.includes(state.searchQuery) || r.name.toLowerCase().includes(state.searchQuery) || r.sector.toLowerCase().includes(state.searchQuery));
        }
        if (filtered.length === 0) {
          alert("出力対象のデータがありません。");
          return;
        }
        let csvContent = "\\uFEFF";
        csvContent += "カテゴリ,期待度スコア,証券コード,銘柄名,株価,前日比,前日比率,本日出来高,市場,業種\\r\\n";
        filtered.forEach(item => {
          const sysData = item[sys];
          const isPlus = item.change >= 0;
          const sign = isPlus ? "+" : "";
          const row = [
            `"${sysData.categoryName.split('：')[0]}"`,
            `"${sysData.score}"`,
            `"${item.ticker}"`,
            `"${item.name}"`,
            `"${item.price}"`,
            `"${sign}${item.change}"`,
            `"${sign}${item.changeRate}%"`,
            `"${item.volume}"`,
            `"${item.market}"`,
            `"${item.sector}"`
          ].join(",");
          csvContent += row + "\\r\\n";
        });
        const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.setAttribute("href", url);
        const systemName = (sys === "short") ? "短期5-25" : "中期25-75";
        const tabName = (state.activeTab === "ALL") ? "すべて" : state.activeTab;
        link.setAttribute("download", `granville_export_${systemName}_${tabName}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      }

      function switchSystem(system) {
        state.currentSystem = system;
        const btnShort = document.getElementById('btnSystemShort');
        const btnMid = document.getElementById('btnSystemMid');
        const thma = document.getElementById('thma');
        const expsLong = document.querySelectorAll('.exp-long');
        const expPNormal = document.getElementById('expPNormal');
        const expPSurge = document.getElementById('expPSurge');
        const expS = document.getElementById('expS');
        const expG = document.getElementById('expG');

        if (system === 'short') {
          btnShort.className = 'px-4 py-1.5 rounded-lg font-bold bg-cyan-600 text-white shadow cursor-pointer';
          btnMid.className = 'px-4 py-1.5 rounded-lg font-bold text-slate-400 hover:text-slate-100 cursor-pointer';
          thma.textContent = '5日線 / 25日線';
          expsLong.forEach(el => el.textContent = '25日線');
          expPNormal.textContent = '-8.0%';
          expPSurge.textContent = '-15.0%';
          expS.textContent = '-12.0%';
          expG.textContent = '-15.0%';
        } else {
          btnMid.className = 'px-4 py-1.5 rounded-lg font-bold bg-cyan-600 text-white shadow cursor-pointer';
          btnShort.className = 'px-4 py-1.5 rounded-lg font-bold text-slate-400 hover:text-slate-100 cursor-pointer';
          thma.textContent = '25日線 / 75日線';
          expsLong.forEach(el => el.textContent = '75日線');
          expPNormal.textContent = '-12.0%';
          expPSurge.textContent = '-20.0%';
          expS.textContent = '-18.0%';
          expG.textContent = '-20.0%';
        }
        updateStats();
        renderTable();
      }

      function getDiffBadge(todayVal, yesterdayVal) {
        const diff = todayVal - yesterdayVal;
        if (diff > 0) {
          return `<span class="text-[11px] text-emerald-400 font-bold ml-1.5">(+${diff})</span>`;
        } else if (diff < 0) {
          return `<span class="text-[11px] text-rose-400 font-bold ml-1.5">(${diff})</span>`;
        } else {
          return `<span class="text-[10px] text-slate-500 font-normal ml-1.5">(±0)</span>`;
        }
      }

      function updateStats() {
        const counts = { BUY1: 0, BUY2: 0, BUY3: 0, BUY3_PRE: 0, BUY4: 0 };
        const sys = state.currentSystem;
        state.results.forEach(r => {
          const cat = r[sys].category;
          if (counts[cat] !== undefined) counts[cat]++;
        });
        
        const buy3Total = counts.BUY3 + counts.BUY3_PRE;
        const buy3Yesterday = (state.prevCounts[sys].BUY3 || 0) + (state.prevCounts[sys].BUY3_PRE || 0);

        const totalToday = state.results.filter(r => r[sys].category !== "NONE").length;
        const totalYesterday = state.prevCounts[sys].TOTAL_ACTIVE || 0; 
        const totalDiff = totalToday - totalYesterday;

        document.getElementById('statBuy1').innerHTML = `
          <span class="text-2xl font-bold text-emerald-400">${counts.BUY1}</span>
          ${getDiffBadge(counts.BUY1, state.prevCounts[sys].BUY1 || 0)}
        `;
        document.getElementById('statBuy2').innerHTML = `
          <span class="text-2xl font-bold text-sky-400">${counts.BUY2}</span>
          ${getDiffBadge(counts.BUY2, state.prevCounts[sys].BUY2 || 0)}
        `;
        document.getElementById('statBuy3').innerHTML = `
          <span class="text-2xl font-bold text-amber-400">${buy3Total}</span>
          ${getDiffBadge(buy3Total, buy3Yesterday)}
        `;
        document.getElementById('statBuy4').innerHTML = `
          <span class="text-2xl font-bold text-purple-400">${counts.BUY4}</span>
          ${getDiffBadge(counts.BUY4, state.prevCounts[sys].BUY4 || 0)}
        `;
        
        // statTotalの表示を修正: フィルター適用前の全銘柄数ではなく、シグナル点灯銘柄の合計数
        document.getElementById('statTotal').textContent = totalToday.toLocaleString();
        const totalDiffEl = document.getElementById('statTotalDiff');
        if (totalDiffEl) {
          totalDiffEl.innerHTML = totalDiff > 0 ? `+${totalDiff}` : totalDiff < 0 ? `${totalDiff}` : '±0';
          totalDiffEl.className = `text-[10px] font-bold ml-1.5 ${totalDiff > 0 ? 'text-emerald-400' : totalDiff < 0 ? 'text-rose-400' : 'text-slate-500'}`;
        }

        const labels = { ALL: 'すべて', BUY1: '買い1', BUY2: '買い2', BUY3: '買い3', BUY4: '買い4' };
        document.querySelectorAll('.tab-btn').forEach(btn => {
          const t = btn.dataset.tab;
          let count = 0;
          if (t === 'ALL') {
            count = totalToday; // 全アクティブシグナル数
          } else if (t === 'BUY3') {
            count = counts.BUY3 + counts.BUY3_PRE;
          } else {
            count = counts[t];
          }
          btn.textContent = `${labels[t]} (${count})`;
        });
      }

      function renderTable() {
        const tbody = document.getElementById('resultTableBody');
        tbody.innerHTML = '';
        const sys = state.currentSystem;
        let filtered = [...state.results];
        
        filtered = filtered.filter(r => r[sys].category !== "NONE");

        if (state.activeTab !== 'ALL') {
          if (state.activeTab === 'BUY3') {
            filtered = filtered.filter(r => r[sys].category === 'BUY3' || r[sys].category === 'BUY3_PRE');
          } else {
            filtered = filtered.filter(r => r[sys].category === state.activeTab);
          }
        }
        if (state.activeMarket !== 'ALL') filtered = filtered.filter(r => r.market === state.activeMarket);
        if (state.searchQuery) {
          filtered = filtered.filter(r => r.ticker.includes(state.searchQuery) || r.name.toLowerCase().includes(state.searchQuery) || r.sector.toLowerCase().includes(state.searchQuery));
        }
        if (state.sortOrder === 'asc') {
          filtered.sort((a, b) => a.price - b.price);
        } else if (state.sortOrder === 'desc') {
          filtered.sort((a, b) => b.price - a.price);
        } else if (state.sortScoreOrder === 'asc') {
          filtered.sort((a, b) => a[sys].score - b[sys].score);
        } else if (state.sortScoreOrder === 'desc') {
          filtered.sort((a, b) => b[sys].score - a[sys].score);
        }
        const totalFilteredCount = filtered.length;
        const warningBanner = document.getElementById('performanceWarning');
        if (totalFilteredCount > MAX_RENDER_ROWS) {
          warningBanner.classList.remove('hidden');
          document.getElementById('displayCountLabel').textContent = `表示中: ${MAX_RENDER_ROWS} 件 / 該当数: ${totalFilteredCount} 件中`;
          filtered = filtered.slice(0, MAX_RENDER_ROWS);
        } else {
          warningBanner.classList.add('hidden');
          document.getElementById('displayCountLabel').textContent = `表示中: ${totalFilteredCount} 件`;
        }
        if (filtered.length === 0) {
          const tr = document.createElement('tr');
          tr.innerHTML = `
            <td colspan="10" class="py-14 text-center text-slate-500">
              <p class="text-sm">該当する銘柄がありません</p>
            </td>
          `;
          tbody.appendChild(tr);
          return;
        }
        
filtered.forEach(item => {
          const sysData = item[sys];
          const isPlus = item.change >= 0;
          const tr = document.createElement('tr');
          tr.className = 'border-b border-slate-800/40 hover:bg-slate-800/40';
          let marketBadgeClass = "bg-slate-800 text-slate-300";
          if (item.market === "東Ｐ") marketBadgeClass = "bg-emerald-950/80 text-emerald-300 border border-emerald-800/40";
          if (item.market === "東Ｓ") marketBadgeClass = "bg-cyan-950/80 text-cyan-300 border border-cyan-800/40";
          if (item.market === "東Ｇ") marketBadgeClass = "bg-purple-950/80 text-purple-300 border border-purple-800/40";

          const categoryShortName = sysData.categoryName.split('：')[0];

          // 出来高警告の基準値を10,000株以下に適用
          const volumeWarning = item.isLowVolume 
            ? `<span class="ml-1 px-1 text-rose-400 font-bold select-none cursor-help" title="本日出来高: ${item.volume.toLocaleString()}株 (流動性リスク極めて高：10,000株以下)">⚠️</span>` 
            : ``;

          // 地合い強気バッジ
          const rsBadge = item.isStrongRelative 
            ? `<span class="ml-1 px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[9px] font-bold select-none cursor-help" title="本日市場中央値が ${state.marketMedian.toFixed(2)}% の大幅下落相場の中、この銘柄は ${item.changeRate}% で踏み止まり、大口の買い支えが確認されます。">🛡️ 地合い強気</span>` 
            : ``;

          // HOT業種バッジの作成
          const hotSectorBadge = item.isHotSector 
            ? `<span class="px-1.5 py-0.2 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20 text-[9px] font-bold select-none cursor-help" title="本日、大口資金が集中しているHOT業種（資金流入セクター）に属している銘柄です。">🔥 HOT業種</span>` 
            : ``;

          // 連続日数・初点灯バッジ
          const consecutiveBadge = sysData.consecutiveDays === 1 
            ? `<span class="text-[9px] px-1 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-bold block mt-1 w-max">🆕 初点灯</span>` 
            : sysData.consecutiveDays >= 2 
              ? `<span class="text-[9px] px-1 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20 font-bold block mt-1 w-max">🔥 ${sysData.consecutiveDays}日連続</span>` 
              : ``;

          // 前日カテゴリ名ラベル
          const prevCatLabel = sysData.prevCategory 
            ? `<span class="text-[9px] text-slate-400 font-medium block mt-1">前日: ${sysData.prevCategory}</span>` 
            : ``;

          // 4大RSI指標のステータスバッジ
          const rsiBadge = sysData.rsi_divergence
            ? `<span class="text-[9px] px-1 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-bold block mt-1" title="株価の底値が切り下がっているにもかかわらず、RSIの底値が切り上がっている強気の逆行現象です。強い上昇転換の予兆です。">🛡️ 強気ダイバージェンス</span>`
            : sysData.rsi_double_bottom
              ? `<span class="text-[9px] px-1 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20 font-bold block mt-1" title="RSIが30%以下の売られすぎ圏で底値切り上がりのダブルボトムを形成し、本日上向きに反発した強い買いサインです。">📈 Wボトム特別反発</span>`
              : sysData.rsi_buy_reversal
                ? `<span class="text-[9px] px-1 py-0.5 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-bold block mt-1" title="過去3日以内にRSIが30%以下に沈んだ後、本日陽線またはRSI大幅反発を伴って折り返しを開始したサインです。">🔄 RSIゾーン反発</span>`
                : sysData.rsi_sell_warning
                  ? `<span class="text-[9px] px-1 py-0.5 rounded bg-rose-500/10 text-rose-400 border border-rose-500/20 font-bold block mt-1" title="本日RSIが70%以上の買われすぎ圏に達しているか、または過去5日以内に70%を超えた後本日デッドクロスして下落に転じているため、過熱警戒です。">⚠️ RSI過熱警戒</span>`
                  : ``;

          // 期待度ホバー時の加減点内訳リスト（HTML）
          let reasonsListHtml = '';
          if (sysData.score_reasons && sysData.score_reasons.length > 0) {
            reasonsListHtml = sysData.score_reasons.map(r => `<li class="flex items-center gap-1.5 py-0.5 text-slate-300"><span>•</span><span>${r}</span></li>`).join('');
          } else {
            reasonsListHtml = `<li class="text-slate-500 py-0.5">※加減点なし (基本点 3)</li>`;
          }

          tr.innerHTML = `
            <td class="p-3">
              <div class="flex flex-col items-start">
                <span class="px-2 py-0.5 rounded text-[10px] font-bold ${sysData.badgeClass}">${categoryShortName}</span>
                ${consecutiveBadge}
                ${prevCatLabel}
              </div>
            </td>
            
            <td class="p-3 text-center text-amber-400 font-mono text-[14px] font-extrabold select-none cursor-help relative group">
              <span class="hover:text-amber-300">${sysData.score}</span>
              
              <div class="hidden group-hover:block absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 w-48 bg-slate-950/95 backdrop-blur border border-slate-800 text-left text-xs p-3 rounded-xl shadow-2xl z-30 select-none">
                <p class="font-bold text-[10px] text-slate-400 border-b border-slate-800 pb-1 mb-1.5">🌟 期待度スコア評価内訳</p>
                <ul class="space-y-0.5 text-[10px] font-normal leading-relaxed">
