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
            
            for item in prev_results:
                for sys_key in ["short", "mid"]:
                    cat = item.get(sys_key, {}).get("category", "NONE")
                    if cat in prev_counts[sys_key]:
                        prev_counts[sys_key][cat] += 1
                
                ticker_key = item.get("ticker")
                if ticker_key:
                    prev_results_by_ticker[ticker_key] = item
                        
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
        data = yf.download(chunk, period="2y", interval="1d", group_by="ticker", auto_adjust=False, progress=False, session=session)
for ticker in chunk:
            df_single = None
            if isinstance(data.columns, pd.MultiIndex):
                # 銘柄コードが Level 0 にある場合（従来仕様）
                if ticker in data.columns.get_level_values(0):
                    df_single = data[ticker].copy()
                # 銘柄コードが Level 1 にある場合（最新yfinance仕様）
                elif ticker in data.columns.get_level_values(1):
                    df_single = data.xs(ticker, axis=1, level=1).copy()
            else:
                if len(chunk) == 1:
                    df_single = data.copy()

            if df_single is not None and not df_single.empty:
                df_single = df_single.dropna(subset=['Close']).copy()
                if not df_single.empty:
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
    
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return rsi

# 2. ヘルパー：先読みバイアスを排除したスイングロー（極小値）検出関数
def find_swing_lows(series, window=25):
    n = len(series)
    low_indices = []
    
    start_idx = max(2, n - window)
    end_idx = n - 2
    
    for i in range(start_idx, end_idx):
        val = series.iloc[i]
        if (val < series.iloc[i-1] and val < series.iloc[i-2] and 
            val < series.iloc[i+1] and val < series.iloc[i+2]):
            low_indices.append(i)
            
    return low_indices

# 3. 判定および採点ロジック関数
def evaluate_logic(df_temp, short_window, long_window, market_type):
    df_temp = df_temp.copy()
    if isinstance(df_temp.columns, pd.MultiIndex):
        df_temp.columns = df_temp.columns.get_level_values(0)
        
    df_temp['rsi'] = calculate_rsi(df_temp['Close'], 14)
        
    df_temp['short_ma'] = df_temp['Close'].rolling(window=short_window).mean()
    df_temp['long_ma'] = df_temp['Close'].rolling(window=long_window).mean()
    df_temp = df_temp.dropna(subset=['short_ma', 'long_ma']).reset_index(drop=True)
    
    min_len = 45 if long_window <= 25 else 130
    if len(df_temp) < min_len:
        return {
            "category": "NONE", "categoryName": "データ不足",
            "badgeClass": "bg-slate-800 text-slate-500 border border-slate-700",
            "diffRate": 0.0, "reason": "データが不足しています。",
            "ma_short": 0.0, "ma_long": 0.0, "score": 1,
            "rsi": 50.0, "rsi_buy_reversal": False, "rsi_double_bottom": False, "rsi_divergence": False, "rsi_sell_warning": False
        }
        
    today = df_temp.iloc[-1]
    yesterday = df_temp.iloc[-2]
    
    price_today = float(today['Close'])
    price_yesterday = float(yesterday['Close'])
    open_today = float(today['Open'])
    high_today = float(today['High'])
    low_today = float(today['Low'])
    volume_today = float(today['Volume'])
    
    short_ma_today = float(today['short_ma'])
    short_ma_yesterday = float(yesterday['short_ma'])
    long_ma_today = float(today['long_ma'])
    long_ma_yesterday = float(yesterday['long_ma'])
    
    diff_rate = ((price_today - long_ma_today) / long_ma_today) * 100

    long_ma_slope_5d = long_ma_today - df_temp.iloc[-6]['long_ma']
    long_ma_slope_10d = long_ma_today - df_temp.iloc[-11]['long_ma']
    long_ma_slope_3d = long_ma_today - df_temp.iloc[-4]['long_ma']
    long_ma_slope_15d = long_ma_today - df_temp.iloc[-16]['long_ma']
    
    is_yang_candle = price_today > open_today
    is_price_up = price_today > price_yesterday
    
    # ------------------------------------------
    # ★ RSI シグナル検出セクション
    # ------------------------------------------
    rsi_series = df_temp['rsi']
    price_low_series = df_temp['Low']
    
    rsi_today = float(rsi_series.iloc[-1])
    rsi_yesterday = float(rsi_series.iloc[-2])
    
    is_rsi_sell_warning = False
    if rsi_today >= 70:
        is_rsi_sell_warning = True
    else:
        recent_rsi_5d = rsi_series.iloc[-6:-1]
        if (recent_rsi_5d > 70).any() and (rsi_yesterday >= 70) and (rsi_today < 70) and (rsi_today < rsi_yesterday):
            is_rsi_sell_warning = True

    is_rsi_buy_reversal = False
    recent_rsi_3d = rsi_series.iloc[-4:-1]
    if (recent_rsi_3d <= 30).any():
        if (rsi_today >= rsi_yesterday + 2.0) or is_yang_candle:
            is_rsi_buy_reversal = True

    is_rsi_double_bottom = False
    rsi_lows = find_swing_lows(rsi_series, 25)
    rsi_lows_30 = [i for i in rsi_lows if rsi_series.iloc[i] <= 30]
    
    if len(rsi_lows_30) >= 2:
        t1 = rsi_lows_30[-2]
        t2 = rsi_lows_30[-1]
        if (5 <= (t2 - t1) <= 20) and (rsi_series.iloc[t2] > rsi_series.iloc[t1]):
            if (rsi_today > rsi_series.iloc[t2]) and (rsi_today > rsi_yesterday):
                is_rsi_double_bottom = True

    is_rsi_divergence = False
    price_lows = find_swing_lows(price_low_series, 25)
    
    if len(price_lows) >= 2:
        d1 = price_lows[-2]
        d2 = price_lows[-1]
        if (5 <= (d2 - d1) <= 20) and (price_low_series.iloc[d2] < price_low_series.iloc[d1]):
            if rsi_series.iloc[d2] > rsi_series.iloc[d1]:
                if (rsi_today <= 45) and (rsi_today > rsi_yesterday):
                    is_rsi_divergence = True

    df_recent_40d = df_temp.tail(40)
    max_price_40d = df_recent_40d['Close'].max()
    min_price_40d = df_recent_40d['Close'].min()
    price_surge_ratio = max_price_40d / min_price_40d if min_price_40d > 0 else 1.0
    is_surged_stock = price_surge_ratio >= 1.50
    
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
    
    recent_volumes = df_temp['Volume'].iloc[-26:-1]
    vol_ma25 = recent_volumes.mean() if len(recent_volumes) > 0 else 0
    vol_ratio = today['Volume'] / vol_ma25 if vol_ma25 > 0 else 1.0
    
    ma_change_series = df_temp['long_ma'].pct_change()
    ma_change_today = ma_change_series.iloc[-1]
    baseline_change_120d = ma_change_series.abs().tail(120).mean()
    is_slope_strong_relative = (ma_change_today > 0) and (ma_change_today > baseline_change_120d)
    
    candle_body_pct = ((price_today - open_today) / open_today) * 100 if open_today > 0 else 0.0
    max_body = max(price_today, open_today)
    upper_shadow = high_today - max_body
    total_range = high_today - low_today
    upper_shadow_pct = (upper_shadow / total_range) * 100 if total_range > 0 else 0.0

    category = "NONE"
    category_name = "条件外"
    badge_class = "bg-slate-800 text-slate-500 border border-slate-700"
    reason = f"シグナル(1〜4)条件からは外れています(長期線乖離: {diff_rate:.1f}%)。"
    
    is_long_ma_falling = long_ma_slope_5d < -0.05
    is_long_ma_flat_or_rising = long_ma_slope_5d >= -0.01
    is_long_ma_rising = long_ma_slope_5d > 0.05

    price_crossed_above = (price_yesterday < long_ma_yesterday) and (price_today >= long_ma_today)
    gc_occurred = (short_ma_yesterday < long_ma_yesterday) and (short_ma_today >= long_ma_today)

    # ==========================================
    # ★ ベースのフラグ計算（底練り・初動実績）
    # ==========================================
    lookback_period = 40
    # ① 直近40日での底練り判定（完全な新規初動用）
    price_below_count_recent = (df_temp.iloc[-lookback_period-1:-1]['Close'] < df_temp.iloc[-lookback_period-1:-1]['long_ma']).sum()
    short_ma_below_count_recent = (df_temp.iloc[-lookback_period-1:-1]['short_ma'] < df_temp.iloc[-lookback_period-1:-1]['long_ma']).sum()
    is_long_bottoming_recent = (price_below_count_recent >= lookback_period * 0.8) or (short_ma_below_count_recent >= lookback_period * 0.9)
    
    # ② 少し前（10日前〜50日前）での底練り判定（上抜けで滞在割合が薄まる「初押し」救済用）
    offset = 10
    if len(df_temp) >= lookback_period + offset + 1:
        price_below_count_past = (df_temp.iloc[-lookback_period-offset-1:-offset-1]['Close'] < df_temp.iloc[-lookback_period-offset-1:-offset-1]['long_ma']).sum()
        is_long_bottoming_past = (price_below_count_past >= lookback_period * 0.8)
    else:
        is_long_bottoming_past = False

    # ==========================================
    # 買い4：逆張りリバ
    # ==========================================
    if diff_rate <= oversold_threshold:
        if is_long_ma_falling:
            if is_yang_candle or is_price_up:
                category = "BUY4"
                category_name = "買い4：逆張りリバ"
                badge_class = "bg-purple-500/15 text-purple-300 border border-purple-500/30"
                reason = f"下落中の{long_window}日移動平均線({long_ma_today:,.0f}円)から下方に大きく乖離({diff_rate:.1f}%)。本日反発しました。{warning_suffix}"

     # ==========================================
    # 買い1：新規買い（正真正銘の初動クロス）
    # ==========================================
    if category == "NONE" and (price_crossed_above or gc_occurred) and is_long_ma_flat_or_rising and is_long_bottoming_recent and (diff_rate <= 5.0):
        category = "BUY1"
        category_name = "買い1：新規買い"
        badge_class = "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
        cross_type = "ゴールデンクロス" if gc_occurred else "価格の突き抜け"
        reason = f"長期間の下落・底練りを経て、横這い〜上昇傾向の長期線({long_window}日線)に対して本日{cross_type}が発生しました。"

    # ==========================================
    # 買い2：再突き抜け ＆ 初押し(下抜け復帰)
    # ==========================================
    below_count_15d = (df_temp.iloc[-16:-1]['Close'] < df_temp.iloc[-16:-1]['long_ma']).sum()
    is_temp_dip = 1 <= below_count_15d <= 3  # 通常の一時下抜け
    
    # 初押しの下抜け（過去に底練りがあり、直近で一度上にいて、今回下抜けて復帰した）
    was_above_recently = (df_temp.iloc[-21:-1]['Close'] >= df_temp.iloc[-21:-1]['long_ma']).any()
    is_initial_dip_crossed = is_long_bottoming_past and was_above_recently and price_crossed_above

    if category == "NONE" and (diff_rate <= 5.0):
        # パターンA：力強い上昇トレンド中の一時下抜け再クロス
        if price_crossed_above and is_long_ma_rising and is_temp_dip:
            category = "BUY2"
            category_name = "買い2：再突き抜け"
            badge_class = "bg-sky-500/15 text-sky-300 border border-sky-500/30"
            reason = f"力強い上昇トレンド中、長期線をわずか数日下抜け後、本日素早く上方に復帰しました。"
        # パターンB：底練り脱却後の「初押し」で下抜けて再クロス
        elif is_long_ma_flat_or_rising and is_initial_dip_crossed:
            category = "BUY2"
            category_name = "買い2：初押し(下抜け復帰)"
            badge_class = "bg-sky-500/15 text-sky-300 border border-sky-500/30"
            reason = f"長期の底練りから脱却後、最初の押し目で長期線を一度下抜け、本日再び上方に復帰しました。"

    # ==========================================
    # 買い3：押し目反発 ＆ 初押し(支持線反発)
    # ==========================================
    max_diff_15d = ((df_temp.iloc[-16:-1]['Close'] - df_temp.iloc[-16:-1]['long_ma']) / df_temp.iloc[-16:-1]['long_ma'] * 100).max()
    has_pulled_back = max_diff_15d >= 4.0  # 通常の買い3で要求される上放れ実績
    
    is_close_to_ma = 0.0 < diff_rate <= 3.5
    is_rebound = is_yang_candle and is_price_up
    not_crossed_below_recent = (df_temp.iloc[-6:-1]['Close'] >= df_temp.iloc[-6:-1]['long_ma']).all()

    # 初押しの反発（過去に底練りがあり、下抜けずにMA付近で反発。4%の乖離実績や強い上昇トレンドを要求しない）
    is_initial_dip_rebound = is_long_bottoming_past and was_above_recently and is_close_to_ma and is_rebound and not_crossed_below_recent

    if category == "NONE" and not_crossed_below_recent:
        # パターンA：明確な上昇トレンド中のオーソドックスな押し目反発
        if is_long_ma_rising and has_pulled_back and is_close_to_ma and is_rebound:
            category = "BUY3"
            category_name = "買い3：押し目反発"
            badge_class = "bg-amber-500/15 text-amber-300 border border-amber-500/30"
            reason = f"上向き長期線を支持線とした、教科書通りの綺麗な陽線反発を観測しました。"
        # パターンB：底練り脱却後の「初押し」で下抜けずに反発
        elif is_long_ma_flat_or_rising and is_initial_dip_rebound:
            category = "BUY3"
            category_name = "買い3：初押し(支持線反発)"
            badge_class = "bg-amber-500/15 text-amber-300 border border-amber-500/30"
            reason = f"長期の底練りから脱却後、最初の押し目で長期線に接近し、下抜けることなく本日反発しました。"
        
# ==========================================
    # 買い3-Pre：押し目待ち伏せ ＆ 初押し(待ち伏せ)
    # ==========================================
    is_resting_on_ma = -0.5 <= diff_rate <= 1.5
    
    # 初押しの待ち伏せ（反発はまだしていないが、MA極近まで押してきている状態）
    is_initial_dip_resting = is_long_bottoming_past and was_above_recently and is_resting_on_ma and not_crossed_below_recent

    if category == "NONE" and not_crossed_below_recent:
        # パターンA：明確な上昇トレンド中のオーソドックスな待ち伏せ
        if is_long_ma_rising and has_pulled_back and is_resting_on_ma:
            category = "BUY3_PRE"
            category_name = "買い3：押し目待ち伏せ"
            badge_class = "bg-amber-600/10 text-amber-400 border border-amber-500/20"
            reason = f"長期上昇トレンド中、支持線接触まで十分に引き付けた仕込み待ち伏せ状態です。"
        # パターンB：底練り脱却後の「初押し」で長期線付近で待機中
        elif is_long_ma_flat_or_rising and is_initial_dip_resting:
            category = "BUY3_PRE"
            category_name = "買い3：初押し(待ち伏せ)"
            badge_class = "bg-amber-600/10 text-amber-400 border border-amber-500/20"
            reason = f"長期の底練りから脱却後の最初の押し目で、長期線の支持線付近まで十分に引き付けた状態です。"

    # 期待度スコア (RSI・クオンツ対応・内訳記録版)
    score = 3
    score_reasons = []
    
    if category != "NONE":
        if is_rsi_sell_warning:
            score -= 1
            score_reasons.append("⚠️ RSI過熱警戒: -1")
        if is_rsi_buy_reversal:
            score += 1
            score_reasons.append("🔄 RSIゾーン反発: +1")
        if is_rsi_double_bottom:
            score += 2
            score_reasons.append("📈 Wボトム特別反発: +2")
        if is_rsi_divergence:
            score += 1
            score_reasons.append("🛡️ 強気ダイバージェンス: +1")

        if volume_today <= 10000:
            score -= 1
            score_reasons.append("⚠️ 流動性極低(1万株以下): -1")
        if vol_ratio >= 1.5:
            score += 1
            score_reasons.append("📊 出来高急増: +1")
        if category not in ["BUY4", "BUY3_PRE"] and upper_shadow_pct >= 40.0:
            score -= 1
            score_reasons.append("🕯️ 上髭超過: -1")
            
        if category == "BUY1":
            if is_slope_strong_relative:
                score += 1
                score_reasons.append("📈 長期線トレンド加速: +1")
            if candle_body_pct < 0.5:
                score -= 1
                score_reasons.append("🕯️ 反発実体極小: -1")
        elif category == "BUY2":
            if is_slope_strong_relative:
                score += 1
                score_reasons.append("📈 長期線トレンド加速: +1")
        elif category in ["BUY3", "BUY3_PRE"]:
            if diff_rate <= 1.5:
                score += 1
                score_reasons.append("📏 支持線極近: +1")
            if candle_body_pct < 1.0:
                score -= 1
                score_reasons.append("🕯️ 反発実体小: -1")
        elif category == "BUY4":
            if candle_body_pct >= 3.0:
                score += 1
                score_reasons.append("📈 大陽線反発: +1")
            if candle_body_pct < 0.5:
                score -= 1
                score_reasons.append("🕯️ 反発実体極小: -1")
            
    score = max(1, min(5, score))
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
    sector_data = {}
    
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
        trading_value = price_today * float(today['Volume'])
        
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

    for item in results_list:
        ticker = item["ticker"] + ".T"
        sector = item["sector"]
        if sector in sector_data:
            today_price = item["price"]
            today_vol = item["volume"]
            sector_data[sector]["signal_value"] += (today_price * today_vol)

    scored_sectors = []
    
    for sector, s_info in sector_data.items():
        if s_info["total_value"] <= 0 or s_info["total_stocks"] < 3:
            continue
            
        weighted_change = s_info["weighted_change_sum"] / s_info["total_value"]
        signal_density = (s_info["signal_value"] / s_info["total_value"]) * 100
        ma5_up_ratio = (s_info["ma5_up_count"] / s_info["total_stocks"]) * 100

        score_perf = min(40.0, max(0.0, (weighted_change + 1.0) * 10.0))
        score_density = min(40.0, max(0.0, signal_density * 2.0))
        score_momentum = min(20.0, max(0.0, ma5_up_ratio * 0.285))
        
        total_score = round(score_perf + score_density + score_momentum, 1)

        scored_sectors.append({
            "sector": sector,
            "score": total_score,
            "changeRate": round(weighted_change, 2),
            "signalDensity": round(signal_density, 1)
        })

    scored_sectors.sort(key=lambda x: x["score"], reverse=True)
    
    HOT_THRESHOLD = 55.0
    hot_sectors = [s for s in scored_sectors if s["score"] >= HOT_THRESHOLD][:5]

    return hot_sectors, sector_data

# 4. 全データの判定実行
results_list = []
print("各銘柄の判定ロジックを実行しています...", flush=True)

MIN_REQUIRED_DAYS = 69

for ticker, df_stock in bulk_data.items():
    try:
        if df_stock.empty or len(df_stock) < MIN_REQUIRED_DAYS:
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
            
        short_res = evaluate_logic(df_stock, 5, 25, market_short)
        mid_res = evaluate_logic(df_stock, 25, 75, market_short)
        
        if short_res["category"] == "NONE" and mid_res["category"] == "NONE":
            continue

        ticker_clean = ticker.replace(".T", "")
        yesterday_data = prev_results_by_ticker.get(ticker_clean)

        for sys_key, sys_res in [("short", short_res), ("mid", mid_res)]:
            if sys_res["category"] != "NONE":
                consecutive = 1
                prev_cat_name = None

                if yesterday_data and sys_key in yesterday_data:
                    yes_sys = yesterday_data[sys_key]
                    yes_cat = yes_sys.get("category", "NONE")

                    if yes_cat != "NONE":
                        yes_consecutive = yes_sys.get("consecutiveDays", 1)
                        consecutive = yes_consecutive + 1

                        if yes_cat != sys_res["category"]:
                            prev_cat_name = yes_sys.get("categoryName", yes_cat).split('：')[0]

                sys_res["consecutiveDays"] = consecutive
                sys_res["prevCategory"] = prev_cat_name
            else:
                sys_res["consecutiveDays"] = 0
                sys_res["prevCategory"] = None
        
        stock_info = {
            "ticker": clean_val(ticker_clean),
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

    except Exception as e:
        print(f"⚠️ {ticker} の判定中にエラーが発生しスキップしました: {e}", flush=True)

all_rates = [item["changeRate"] for item in results_list if item["changeRate"] is not None]
market_median_change = float(pd.Series(all_rates).median()) if all_rates else 0.0
print(f" -> 本日の東証全上場銘柄の騰落率中央値: {market_median_change:.2f}%")

hot_sectors, all_sector_stats = calculate_hot_sectors(bulk_data, results_list, ticker_to_sector)
hot_sector_names = [s["sector"] for s in hot_sectors]
print(f" -> 本日のHOT業種 ({len(hot_sectors)}件検知): {', '.join(hot_sector_names) if hot_sectors else 'なし'}")

for item in results_list:
    sector = item["sector"]
    is_hot = sector in hot_sector_names
    item["isHotSector"] = is_hot
    
    if is_hot:
        for sys_key in ["short", "mid"]:
            sys_data = item[sys_key]
            if sys_data["category"] != "NONE":
                new_score = min(5, sys_data["score"] + 1)
                sys_data["score"] = new_score
                
                if "score_reasons" not in sys_data or sys_data["score_reasons"] is None:
                    sys_data["score_reasons"] = []
                sys_data["score_reasons"].append(f"🔥 追い風業種 ({sector}): +1")

for item in results_list:
    is_strong_relative = False
    if market_median_change <= -1.0:
        is_strong_relative = item["changeRate"] >= (market_median_change + 1.5)
        
    if is_strong_relative:
        item["isStrongRelative"] = True
        for sys_key in ["short", "mid"]:
            if item[sys_key]["category"] != "NONE":
                new_score = min(5, item[sys_key]["score"] + 1)
                item[sys_key]["score"] = new_score
                item[sys_key]["stars"] = "★" * new_score + "☆" * (5 - new_score)

# ==========================================
# ★【Phase 3】全銘柄のAI相談用履歴データ分割出力 (100分割シャーディング)
# ==========================================
print("AI相談用の履歴データを分割出力しています...")
history_dir = "history_data"
os.makedirs(history_dir, exist_ok=True)
shards = {f"{i:02d}": {} for i in range(100)}

for ticker, df in bulk_data.items():
    if df.empty:
        continue
    
    ticker_num = ''.join(filter(str.isdigit, ticker))
    if len(ticker_num) < 2:
        continue
    shard_key = ticker_num[-2:] # 下2桁で100個のバケツに振り分け
    
    # 全データで計算してから直近120日分を切り出す（MAやRSIの欠損を防ぐため）
    df_calc = df.copy()
    df_calc['ma_short'] = df_calc['Close'].rolling(window=5).mean().round(1)
    df_calc['ma_mid'] = df_calc['Close'].rolling(window=25).mean().round(1)
    df_calc['ma_long'] = df_calc['Close'].rolling(window=75).mean().round(1)
    df_calc['rsi'] = calculate_rsi(df_calc['Close'], 14).round(1)
    
    df_recent = df_calc.tail(120)
    
    records = []
    for date, row in df_recent.iterrows():
        dt_str = date.strftime("%m/%d")
        c = round(float(row['Close']), 1) if pd.notna(row['Close']) else None
        m5 = float(row['ma_short']) if pd.notna(row['ma_short']) else None
        m25 = float(row['ma_mid']) if pd.notna(row['ma_mid']) else None
        m75 = float(row['ma_long']) if pd.notna(row['ma_long']) else None
        rsi = float(row['rsi']) if pd.notna(row['rsi']) else None
        
        # AI用に25日線を基準とした乖離率を算出
        diff = round(((c - m25) / m25) * 100, 1) if c and m25 else None
        
        # キーを省いた軽量配列
        records.append([dt_str, c, m5, m25, m75, diff, rsi])
        
    shards[shard_key][ticker.replace(".T", "")] = records

# JSONファイルとして一括保存（容量削減のため改行なし設定）
for shard_key, data_dict in shards.items():
    if data_dict:
        file_path = os.path.join(history_dir, f"data_{shard_key}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data_dict, f, separators=(',', ':'))
print(" -> AI履歴データの出力を完了しました")
# ==========================================

json_data_str = json.dumps(results_list, ensure_ascii=False, indent=2)
hot_sectors_json_str = json.dumps(hot_sectors, ensure_ascii=False)
form_cat_str = json.dumps(FORM_CONFIG_CAT, ensure_ascii=False)
form_score_str = json.dumps(FORM_CONFIG_SCORE, ensure_ascii=False)
prev_counts_json_str = json.dumps(prev_counts, ensure_ascii=False)

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
    
    <header class="border-b border-slate-800/80 bg-slate-900/80 backdrop-blur sticky top-0 z-30">
      <div class="max-w-[1550px] mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div class="flex items-center space-x-3">
          <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-cyan-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-cyan-500/20 text-white font-bold text-xl">G</div>
          <div>
            <h1 class="text-base sm:text-lg font-bold text-white tracking-tight flex items-center gap-2">
              全自動グランビル・スクリーナー
              <span class="text-[10px] sm:text-xs px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-mono font-normal">PRO v3.9_ULTIMATE</span>
            </h1>
            <p class="text-xs text-slate-400 hidden sm:block">東証全市場自動解析・高精度ロジック（最終更新：__LAST_UPDATE__）</p>
          </div>
        </div>
        
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

    <main class="max-w-[1550px] mx-auto px-4 sm:px-6 lg:px-8 pt-6 space-y-6">

      <div id="hotSectorsBanner" class="hidden bg-slate-900/90 border border-amber-500/20 rounded-2xl p-3.5 shadow-xl flex flex-wrap items-center justify-between gap-3 text-xs">
      </div>
      
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
          <span class="text-[11px] font-bold text-sky-400 uppercase tracking-wider">買い2 (初押し/再復帰)</span>
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

      <section class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl flex flex-col">
        
        <div class="flex flex-col xl:flex-row items-stretch xl:items-center justify-between gap-4 pb-4 border-b border-slate-800">
          
          <div class="flex flex-wrap items-center gap-3">
            <div class="flex bg-slate-950 p-1 rounded-xl border border-slate-800 text-xs w-full sm:w-auto" id="tabContainer">
              <button data-tab="BUY1" class="tab-btn px-4 py-1.5 rounded-lg font-medium bg-cyan-600 text-white shadow cursor-pointer">買い1</button>
              <button data-tab="BUY2" class="tab-btn px-4 py-1.5 rounded-lg text-slate-400 hover:text-white cursor-pointer">買い2</button>
              <button data-tab="BUY3" class="tab-btn px-4 py-1.5 rounded-lg text-slate-400 hover:text-white cursor-pointer">買い3</button>
              <button data-tab="BUY4" class="tab-btn px-4 py-1.5 rounded-lg text-slate-400 hover:text-white cursor-pointer">買い4</button>
              <button data-tab="ALL" class="tab-btn px-4 py-1.5 rounded-lg text-slate-500 hover:text-slate-300 cursor-pointer">すべて</button>
            </div>

            <div class="flex bg-slate-950 p-1 rounded-xl border border-slate-800 text-xs" id="marketFilterContainer">
              <span class="text-slate-500 self-center px-2.5 font-bold border-r border-slate-800 mr-1.5">市場</span>
              <button data-market="ALL" class="market-btn px-3 py-1.5 rounded-lg font-medium bg-slate-800 text-white cursor-pointer">すべて</button>
              <button data-market="東Ｐ" class="market-btn px-3 py-1.5 rounded-lg font-medium text-slate-400 hover:text-slate-100 cursor-pointer">東Ｐ</button>
              <button data-market="東Ｓ" class="market-btn px-3 py-1.5 rounded-lg font-medium text-slate-400 hover:text-slate-100 cursor-pointer">東Ｓ</button>
              <button data-market="東Ｇ" class="market-btn px-3 py-1.5 rounded-lg font-medium text-slate-400 hover:text-slate-100 cursor-pointer">東Ｇ</button>
            </div>
          </div>

          <!-- AI個別抽出 ＆ エクスポート -->
          <div class="flex items-center gap-3 w-full xl:w-auto">
            <div class="flex items-center gap-1.5 flex-1 xl:w-auto">
              <input type="text" id="aiExtractInput" placeholder="個別抽出 (例: 7974)" class="w-full xl:w-40 bg-slate-950 border border-slate-800 rounded-xl px-3 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 transition font-mono tracking-widest">
              <button id="btnAiExtract" class="bg-indigo-900/50 hover:bg-indigo-600 text-indigo-300 hover:text-white border border-indigo-700/50 hover:border-indigo-500 px-3 py-1.5 rounded-xl text-xs font-bold transition duration-200 cursor-pointer flex items-center gap-1.5 shrink-0">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
                AI抽出
              </button>
            </div>
            <button id="btnExportCSV" class="bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 px-4 py-1.5 rounded-xl text-xs font-bold transition duration-200 cursor-pointer shrink-0">📥 CSV出力</button>
          </div>
        </div>

        <div id="performanceWarning" class="mt-4 hidden bg-amber-500/10 border border-amber-500/20 text-amber-300 text-[11px] p-2.5 rounded-xl">
          ⚠️ 該当数が多いため最初の150件のみ表示しています。上の「市場別」「判定別」ボタンや検索窓を使って絞り込むとスムーズに閲覧できます。
        </div>

        <div class="mt-6 overflow-x-auto">
          <table class="w-full text-left">
           <thead>
              <tr class="border-b border-slate-800 text-[11px] font-bold text-slate-400 uppercase bg-slate-950/60 select-none">
                <th class="p-3 w-20 whitespace-nowrap">判定</th>
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

        <div class="mt-6 pt-4 border-t border-slate-800/80 flex flex-wrap items-center justify-between text-[11px] text-slate-400 gap-2">
          <span id="displayCountLabel" class="font-medium text-slate-300">表示中: 0 件</span>
          <div class="flex items-center gap-3 text-slate-500 font-mono text-[10px]">
            <span id="footerFormula">乖離率 = (株価 - 25日線) ÷ 25日線</span>
            <span>•</span>
            <span id="footerBase">基準線: 25日移動平均線</span>
          </div>
        </div>

      </section>

      <div class="flex justify-center mt-6">
        <button id="btnToggleExplanation" class="bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 px-6 py-2.5 rounded-xl text-xs font-bold transition duration-200 cursor-pointer shadow-md">
          📖 解説を表示
        </button>
      </div>

      <section id="explanationSection" class="pt-6 border-t border-slate-800/60 hidden space-y-6">
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
          
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

              <div class="bg-slate-900/60 border border-sky-500/20 rounded-xl p-3.5">
                <span class="font-bold text-sky-400 block mb-1">出来高・流動性評価 (+1 / -1)</span>
                <p class="text-slate-400 text-[11px] leading-relaxed">
                  ・過去25日平均に対し出来高が1.5倍以上に急増 ➔ <strong class="text-emerald-400">+1</strong><br>
                  ・出来高1万株以下の過疎銘柄（流動性リスク高） ➔ <strong class="text-rose-400">-1</strong>
                </p>
              </div>

              <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-3.5">
                <span class="font-bold text-cyan-400 block mb-1">相対的変化率ボーナス (+1)</span>
                <p class="text-slate-400 text-[11px] leading-relaxed">
                  本日の長期線の変化率が、過去半年間（120日）の平均変化スピードを上回っている（＝上昇トレンドが加速している）場合に星を加算。
                </p>
              </div>

              <div class="bg-slate-900/60 border border-rose-500/20 rounded-xl p-3.5">
                <span class="font-bold text-rose-400 block mb-1">トレンド下降減点 (-1〜-2)</span>
                <p class="text-slate-400 text-[11px] leading-relaxed">
                  ・長期線が直近で下降傾向にある場合 ➔ <strong class="text-rose-400">-1</strong><br>
                  ・さらに短期線が長期線の下で下降傾向の場合 ➔ <strong class="text-rose-400">追加で -1</strong>
                </p>
              </div>

              <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-3.5">
                <span class="font-bold text-purple-400 block mb-1">個別ローソク足補正 (+1 / -1)</span>
                <p class="text-slate-400 text-[11px] leading-relaxed">
                  ・(買い3) 支持線極近 / (買い4) 大陽線反発 ➔ <strong class="text-emerald-400">+1</strong><br>
                  ・上髭割合が40%以上 / 反発時の実体が極小 ➔ <strong class="text-rose-400">-1</strong>
                </p>
              </div>

              <div class="bg-slate-900/60 border border-teal-500/20 rounded-xl p-3.5">
                <span class="font-bold text-teal-400 block mb-1">RSIテクニカル評価 (+1〜+2 / -1)</span>
                <p class="text-slate-400 text-[11px] leading-relaxed">
                  ・ゾーン反発 / 強気のダイバージェンス ➔ <strong class="text-emerald-400">+1</strong><br>
                  ・Wボトム形成からの強力な特別反発 ➔ <strong class="text-emerald-400">+2</strong><br>
                  ・過熱警戒ゾーンでの危険な買いシグナル ➔ <strong class="text-rose-400">-1</strong>
                </p>
              </div>

            </div>
          </div>

          <div class="space-y-4">
            <h3 class="text-xs font-bold text-cyan-400 uppercase tracking-wider flex items-center gap-2">
              <span>📖</span> グランビル買いシグナル（1〜4）詳細判定要件
            </h3>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
              <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-3.5 relative overflow-hidden">
                <span class="font-bold text-slate-300 block mb-1">買い1：新規買い初動</span>
                <p class="text-slate-400 text-[11px] leading-relaxed">
                  ・長期線(<span class="exp-long"></span>)の傾き: 横ばい〜上向き<br>
                  ・底確認: 過去40日のうち<span class="font-mono">80%以上</span>は線の下に沈んでいたこと<br>
                  ・本日、完全なる初上抜け(ゴールデンクロス含む)<br>
                  ・上抜け乖離率: 当日終値が長期線から <span class="font-mono">+5.0%</span> 以内
                </p>
              </div>
              <div class="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5">
                <span class="font-bold text-slate-200 block mb-1">買い2：初押し・再突き抜け</span>
                <p class="text-slate-400 text-[11px] leading-relaxed">
                  ・通常: 安定した右肩上がりの長期線(<span class="exp-long"></span>)を過去10日で1〜3日のみ下抜けし、本日復帰。<br>
                  ・初押し: 長期底練りからの脱却直後に、初めて長期線付近まで押して再上抜け、または反発したもの。<br>
                  ・乖離率 <span class="font-mono">0.0%〜+5.0%</span> 以内
                </p>
              </div>
              <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-3.5">
                <span class="font-bold text-slate-200 block mb-1">買い3：押し目反発（待ち伏せ含む）</span>
                <p class="text-slate-400 text-[11px] leading-relaxed">
                  ・長期線(<span class="exp-long"></span>)が<span class="font-bold text-emerald-300">明確な右肩上がりトレンド</span>中<br>
                  ・過去に株価が長期線から<span class="font-mono">+4.0%以上</span>上放れた実績あり<br>
                  ・反発: 長期線のすぐ上(<span class="font-mono">0.0%〜+3.5%</span>)で本日反発。<br>
                  ・<strong>【待ち伏せPre-Buy3】</strong>: 長期線の極近(-0.5%〜+1.5%)にあり、短期線も上昇傾向なら特別点灯。
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

      <dialog id="diagnosticDialog" class="bg-slate-900 border border-slate-800 text-slate-100 p-6 rounded-2xl shadow-2xl max-w-md w-full backdrop:bg-slate-950/80 focus:outline-none z-50">
        <div class="flex justify-between items-start border-b border-slate-800 pb-3 mb-4">
          <h3 id="dialogTitle" class="text-sm font-bold text-white tracking-tight flex items-center gap-2">📋 銘柄診断カルテ</h3>
          <button onclick="closeDiagnosticDialog()" class="text-slate-400 hover:text-white font-bold text-lg select-none cursor-pointer focus:outline-none">✕</button>
        </div>
        <div id="dialogContent" class="space-y-4 text-xs">
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
        activeTab: 'ALL', // ← 'BUY1' から 'ALL' (すべて) に変更して初期表示時の0件化を防ぐ
        activeMarket: 'ALL',
        searchQuery: '',
        sortOrder: 'none',
        sortScoreOrder: 'none'
      };
      
      const FORM_CAT_CFG = /* PLACEHOLDER_FORM_CAT */ {};
      const FORM_SCORE_CFG = /* PLACEHOLDER_FORM_SCORE */ {};
      const MAX_RENDER_ROWS = 150;

      document.addEventListener('DOMContentLoaded', () => {
        // AI個別抽出ボタンの処理（従来の検索窓は廃止）
        document.getElementById('btnAiExtract').addEventListener('click', () => {
          const input = document.getElementById('aiExtractInput').value.trim();
          if (!input) return;
          
          // 名前が分かる場合は取得（NONE銘柄の場合は名前なしで処理）
          const item = state.results.find(r => r.ticker === input);
          const name = item ? item.name : "";
          copyAiData(input, name);
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
        async function copyAiData(ticker, name) {
        if (!ticker) return;
        
        const tickerNum = ticker.replace(/[^0-9]/g, '');
        if (tickerNum.length < 2) {
          alert("無効な銘柄コードです。");
          return;
        }
        const shardKey = tickerNum.slice(-2);
        const url = `history_data/data_${shardKey}.json`;

        try {
          const response = await fetch(url);
          if (!response.ok) throw new Error("データの取得に失敗しました。まだファイルが生成されていない可能性があります。");
          const data = await response.json();
          
          const history = data[ticker];
          if (!history || history.length === 0) {
            alert(`銘柄コード [${ticker}] の履歴データが見つかりません。`);
            return;
          }

          let md = `【対象銘柄: ${ticker} ${name || ""}】\n`;
          md += `【システム設定: 短期(5/25) & 中期(25/75)】\n\n`;
          md += "| 日付 | 終値 | 5日線 | 25日線 | 75日線 | 25日線乖離率 | RSI(14) |\n";
          md += "|---|---|---|---|---|---|---|\n";
          
          history.forEach(row => {
             const [dt, close, ma5, ma25, ma75, diff, rsi] = row;
             const diffStr = diff > 0 ? `+${diff}%` : (diff !== null ? `${diff}%` : '-');
             md += `| ${dt} | ${close || '-'} | ${ma5 || '-'} | ${ma25 || '-'} | ${ma75 || '-'} | ${diffStr} | ${rsi || '-'} |\n`;
          });

          await navigator.clipboard.writeText(md);
          alert(`✅ [${ticker}] のAI相談用データをコピーしました！\n\nChatGPTやClaudeの入力欄にそのまま「貼り付け（ペースト）」して分析させてください。`);
          
        } catch (err) {
          console.error(err);
          alert(`エラーが発生しました:\n${err.message}`);
        }
      }
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
        const targetUrl = `${FORM_CAT_CFG.baseUrl}?${FORM_CAT_CFG.entryCode}=${encodeURIComponent(ticker)}&${FORM_CAT_CFG.entryName}=${encodeURIComponent(name)}&${FORM_CAT_CFG.entrySys}=${encodeURIComponent(sysLabel)}&${FORM_CAT_CFG.entryCat}=${encodeURIComponent(category)}`;
        window.open(targetUrl, '_blank', 'width=620,height=750');
      }

       function openScoreFeedback(ticker, name, score) {
        if (!FORM_SCORE_CFG.baseUrl || FORM_SCORE_CFG.baseUrl === "YOUR_SCORE_FORM_URL_HERE") {
          alert(`【初期設定が必要です】\\nコード冒頭の「FORM_CONFIG_SCORE」にご自身の2つ目のGoogleフォームのURLとIDを設定してください。`);
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
            count = totalToday;
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

          const volumeWarning = item.isLowVolume 
            ? `<span class="ml-1 px-1 text-rose-400 font-bold select-none cursor-help" title="本日出来高: ${item.volume.toLocaleString()}株 (流動性リスク極めて高：10,000株以下)">⚠️</span>` 
            : ``;

          const rsBadge = item.isStrongRelative 
            ? `<span class="ml-1 px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[9px] font-bold select-none cursor-help" title="本日市場中央値が ${state.marketMedian.toFixed(2)}% の大幅下落相場の中、この銘柄は ${item.changeRate}% で踏み止まり、大口の買い支えが確認されます。">🛡️ 地合い強気</span>` 
            : ``;

          const hotSectorBadge = item.isHotSector 
            ? `<span class="px-1.5 py-0.2 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20 text-[9px] font-bold select-none cursor-help" title="本日、大口資金が集中しているHOT業種（資金流入セクター）に属している銘柄です。">🔥 HOT業種</span>` 
            : ``;

          const consecutiveBadge = sysData.consecutiveDays === 1 
            ? `<span class="text-[9px] px-1 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-bold block mt-1 w-max">🆕 初点灯</span>` 
            : sysData.consecutiveDays >= 2 
              ? `<span class="text-[9px] px-1 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20 font-bold block mt-1 w-max">🔥 ${sysData.consecutiveDays}日連続</span>` 
              : ``;

          const prevCatLabel = sysData.prevCategory 
            ? `<span class="text-[9px] text-slate-400 font-medium block mt-1">前日: ${sysData.prevCategory}</span>` 
            : ``;

          const rsiBadge = sysData.rsi_divergence
            ? `<span class="text-[9px] px-1 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-bold block mt-1" title="株価の底値が切り下がっているにもかかわらず、RSIの底値が切り上がっている強気の逆行現象です。強い上昇転換の予兆です。">🛡️ 強気ダイバージェンス</span>`
            : sysData.rsi_double_bottom
              ? `<span class="text-[9px] px-1 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20 font-bold block mt-1" title="RSIが30%以下の売られすぎ圏で底値切り上がりのダブルボトムを形成し、本日上向きに反発した強い買いサインです。">📈 Wボトム特別反発</span>`
              : sysData.rsi_buy_reversal
                ? `<span class="text-[9px] px-1 py-0.5 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-bold block mt-1" title="過去3日以内にRSIが30%以下に沈んだ後、本日陽線またはRSI大幅反発を伴って折り返しを開始したサインです。">🔄 RSIゾーン反発</span>`
                : sysData.rsi_sell_warning
                  ? `<span class="text-[9px] px-1 py-0.5 rounded bg-rose-500/10 text-rose-400 border border-rose-500/20 font-bold block mt-1" title="本日RSIが70%以上の買われすぎ圏に達しているか、または過去5日以内に70%を超えた後本日デッドクロスして下落に転じているため、過熱警戒です。">⚠️ RSI過熱警戒</span>`
                  : ``;

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
                  ${reasonsListHtml}
                </ul>
              </div>
            </td>
            
            <td class="p-3 font-mono font-bold text-white">
              <div class="flex items-center gap-1.5">
                <span>${item.ticker}</span>
                <a href="https://kabutan.jp/stock/?code=${item.ticker}" target="_blank" class="px-1 py-0.5 rounded bg-slate-800 hover:bg-cyan-600 text-[10px]">探</a>
                <a href="https://finance.yahoo.co.jp/quote/${item.ticker}.T" target="_blank" class="px-1 py-0.5 rounded bg-slate-800 hover:bg-rose-600 text-[10px]">Y!</a>
                <a href="https://jp.tradingview.com/chart/?symbol=TSE%3A${item.ticker}" target="_blank" class="px-1 py-0.5 rounded bg-slate-800 hover:bg-indigo-600 text-[10px]" title="TradingView">C</a>
              </div>
            </td>
            <td class="p-3">
              <div class="font-bold text-slate-100 text-sm flex items-center flex-wrap gap-1">
                <span>${item.name}</span>
                <button onclick="openDiagnosticDialog('${item.ticker}', '${sys}')" class="text-xs hover:text-cyan-400 ml-1.5 cursor-pointer select-none focus:outline-none" title="詳細診断カルテを表示">📋</button>
                ${volumeWarning}
                ${rsBadge}
              </div>
              <div class="text-[10px] text-slate-400 mt-0.5 flex items-center gap-1.5 flex-wrap">
                <span>${item.sector}</span>
                ${hotSectorBadge}
              </div>
            </td>
            <td class="p-3 text-right font-mono font-bold">${item.price.toLocaleString()}</td>
            <td class="p-3 text-right font-mono ${isPlus ? 'text-emerald-400' : 'text-rose-400'}">${isPlus ? '+' : ''}${item.change.toLocaleString()} (${isPlus ? '+' : ''}${item.changeRate}%)</td>
            <td class="p-3 text-right font-mono text-slate-300">
              <div>${sys==='short'?'5日':'25日'}: ${sysData.ma_short.toLocaleString()}</div>
              <div class="text-[10px] text-slate-400">${sys==='short'?'25日':'75日'}: ${sysData.ma_long.toLocaleString()}</div>
            </td>
            <td class="p-3 text-right font-mono">
              <div class="flex flex-col items-end">
                <span class="${sysData.diffRate >= 0 ? 'text-cyan-400' : 'text-purple-400'} font-bold">${sysData.diffRate >= 0 ? '+' : ''}${sysData.diffRate.toFixed(1)}%</span>
                <span class="text-[10px] text-slate-400">RSI: ${sysData.rsi}%</span>
                ${rsiBadge}
              </div>
            </td>
            <td class="p-3 text-center"><span class="${marketBadgeClass} px-2 py-0.5 rounded text-[10px] font-bold">${item.market}</span></td>
            
            <td class="p-3 text-center space-x-1 whitespace-nowrap">
              <button onclick="openScoreFeedback('${item.ticker}', '${item.name}', '${sysData.score}')" class="px-2 py-1 bg-slate-800 hover:bg-amber-600 text-slate-300 hover:text-white rounded border border-slate-700 text-[10px] font-bold transition duration-200 cursor-pointer" title="期待度スコアの妥当性に対して報告">
                ⭐ 期待度
              </button>
              <button onclick="copyAiData('${item.ticker}', '${item.name}')" class="flex items-center gap-1 px-2 py-1 bg-indigo-950/80 hover:bg-indigo-600 text-indigo-300 hover:text-white rounded border border-indigo-800/50 hover:border-indigo-500 text-[10px] font-bold transition duration-200 cursor-pointer shadow-sm" title="AIに相談するための時系列データをコピー">
                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
                AI抽出
              </button>
            </td>
          `;
          tbody.appendChild(tr);
        });        
      }

      function openDiagnosticDialog(ticker, sys) {
        const item = state.results.find(r => r.ticker === ticker);
        if (!item) return;
        const sysData = item[sys];
        
        const dialog = document.getElementById('diagnosticDialog');
        const title = document.getElementById('dialogTitle');
        const content = document.getElementById('dialogContent');
        
        title.innerHTML = `📋 診断カルテ: <span class="font-mono text-cyan-400 font-bold ml-1.5">[${item.ticker}] ${item.name}</span>`;
        
        let reasonsHtml = '';
        if (sysData.score_reasons && sysData.score_reasons.length > 0) {
          reasonsHtml = sysData.score_reasons.map(r => `<li class="flex items-center gap-1.5 py-0.5"><span>•</span><span>${r}</span></li>`).join('');
        } else {
          reasonsHtml = '<li class="text-slate-500 py-0.5">※加減点なし (基本点 3)</li>';
        }

        content.innerHTML = `
          <div class="grid grid-cols-2 gap-4 border-b border-slate-800 pb-3">
            <div>
              <span class="text-slate-400 text-[10px] uppercase block">本日終値</span>
              <strong class="text-white text-base font-mono">${item.price.toLocaleString()} 円</strong>
            </div>
            <div>
              <span class="text-slate-400 text-[10px] uppercase block">長期線乖離率</span>
              <strong class="${sysData.diffRate >= 0 ? 'text-cyan-400' : 'text-purple-400'} text-base font-mono">${sysData.diffRate >= 0 ? '+' : ''}${sysData.diffRate.toFixed(1)}%</strong>
            </div>
          </div>
          
          <div class="grid grid-cols-2 gap-4 border-b border-slate-800 pb-3">
            <div>
              <span class="text-slate-400 text-[10px] uppercase block">判定カテゴリ</span>
              <span class="px-2 py-0.5 rounded font-bold text-[10px] inline-block mt-1 ${sysData.badgeClass}">${sysData.categoryName}</span>
            </div>
            <div>
              <span class="text-slate-400 text-[10px] uppercase block">RSI (14日)</span>
              <strong class="text-white text-base font-mono">${sysData.rsi}%</strong>
            </div>
          </div>
          
          <div class="space-y-2 border-b border-slate-800 pb-3">
            <span class="text-slate-400 font-bold block text-[10px] uppercase tracking-wider">🌟 期待度スコア評価内訳 (スコア: ${sysData.score})</span>
            <ul class="space-y-0.5 text-slate-300 text-[11px] leading-relaxed pl-1">
              ${reasonsHtml}
            </ul>
          </div>
          
          <div class="p-3 bg-slate-950 border border-slate-800/80 rounded-xl">
            <span class="text-[10px] text-slate-400 block mb-1">💡 判定詳細 / 推奨戦略</span>
            <p class="text-slate-300 text-[11px] leading-relaxed">${sysData.reason}</p>
          </div>
          
          <div class="text-[10px] text-slate-500 pt-1 text-right">
            システム: ${(sys === 'short') ? '短期(5/25)' : '中期(25/75)'} | 市場: ${item.market} | 業種: ${item.sector}
          </div>
        `;
        
        dialog.showModal();
      }

      function closeDiagnosticDialog() {
        const dialog = document.getElementById('diagnosticDialog');
        dialog.close();
      }
      
      function renderHotSectorsBanner() {
        const container = document.getElementById('hotSectorsBanner');
        if (!container) return;
        
        const sectors = state.hotSectors || [];
        container.classList.remove('hidden');

        if (sectors.length === 0) {
          container.innerHTML = `
            <div class="flex items-center gap-2 text-slate-400 font-medium text-xs">
              <span class="text-amber-400 font-bold">🔥 本日のHOT業種:</span>
              <span>該当なし（売買資金が分散中、または市場全体が警戒相場です）</span>
            </div>
          `;
          return;
        }

        const badgesHtml = sectors.map((s, idx) => {
          const rank = idx + 1;
          const isPlus = s.changeRate >= 0;
          const sign = isPlus ? '+' : '';
          return `
            <div class="flex items-center gap-1.5 px-2.5 py-1 bg-slate-950/80 border border-amber-500/30 rounded-xl font-mono text-xs">
              <span class="text-[10px] font-extrabold px-1.5 py-0.2 rounded bg-amber-500/20 text-amber-300">#${rank}</span>
              <span class="font-bold text-slate-200 font-sans">${s.sector}</span>
              <span class="${isPlus ? 'text-emerald-400' : 'text-rose-400'} font-bold">${sign}${s.changeRate}%</span>
            </div>
          `;
        }).join('');

        container.innerHTML = `
          <div class="flex items-center gap-2">
            <span class="font-bold text-amber-400 text-xs flex items-center gap-1 shrink-0">
              <span>🔥</span> 本日のHOT業種 (資金集中セクター):
            </span>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            ${badgesHtml}
          </div>
        `;
      }          
    </script>
  </body>
</html>"""

# 実際の置換処理
html_content = html_template
html_content = html_content.replace("__LAST_UPDATE__", current_time_str)
html_content = html_content.replace("__PLACEHOLDER_MARKET_MEDIAN__", f"{market_median_change:.4f}")
html_content = html_content.replace("__PLACEHOLDER_HOT_SECTORS__", hot_sectors_json_str)
html_content = html_content.replace("__PLACEHOLDER_RESULTS__", json_data_str)
html_content = html_content.replace("__PLACEHOLDER_PREV_COUNTS__", prev_counts_json_str)
html_content = html_content.replace("/* PLACEHOLDER_FORM_CAT */ {}", form_cat_str)
html_content = html_content.replace("/* PLACEHOLDER_FORM_SCORE */ {}", form_score_str)

with open(html_output_path, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"\n--- HTML生成が完了しました ---")
print(f"👉 生成されたファイル: {html_output_path} (自動更新時刻：{current_time_str})")
