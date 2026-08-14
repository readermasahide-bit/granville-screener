import io
import os
import json
import time
import requests
import re
import math
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta, timezone

# ==========================================
# ★ 設定パラメータ（クラウド対応）
# ==========================================
SYSTEM_TYPE = "mid"  # "short"(5/25) または "mid"(25/75)
html_output_path = "index.html" # ホームページとして公開するため index.html に固定
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
        
        # ★ここから下（def〜return Noneまで）のインデント（スペース8個）を揃えました
        def extract_results_json(text):
            start_tag = '<script id="data-results" type="application/json">'
            end_tag = '</script>'
            
            start_pos = text.find(start_tag)
            if start_pos != -1:
                b_start = start_pos + len(start_tag)
                end_pos = text.find(end_tag, b_start)
                if end_pos != -1:
                    return text[b_start:end_pos].strip()
                    
            # 古い形式(results:)との互換性バックアップ
            start_pos = text.find("results:")
            if start_pos != -1:
                b_start = text.find("[", start_pos)
                if b_start != -1:
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
                if ticker in data.columns.get_level_values(0):
                    df_single = data[ticker].copy()
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
            "stars": "★☆☆☆☆",
            "stop_loss_price": 0,
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

    lookback_period = 40
    price_below_count_recent = (df_temp.iloc[-lookback_period-1:-1]['Close'] < df_temp.iloc[-lookback_period-1:-1]['long_ma']).sum()
    short_ma_below_count_recent = (df_temp.iloc[-lookback_period-1:-1]['short_ma'] < df_temp.iloc[-lookback_period-1:-1]['long_ma']).sum()
    is_long_bottoming_recent = (price_below_count_recent >= lookback_period * 0.8) or (short_ma_below_count_recent >= lookback_period * 0.9)
    
    offset = 10
    if len(df_temp) >= lookback_period + offset + 1:
        price_below_count_past = (df_temp.iloc[-lookback_period-offset-1:-offset-1]['Close'] < df_temp.iloc[-lookback_period-offset-1:-offset-1]['long_ma']).sum()
        is_long_bottoming_past = (price_below_count_past >= lookback_period * 0.8)
    else:
        is_long_bottoming_past = False

    # 買い4：逆張りリバ
    if diff_rate <= oversold_threshold:
        if is_long_ma_falling:
            if is_yang_candle or is_price_up:
                category = "BUY4"
                category_name = "買い4：逆張りリバ"
                badge_class = "bg-purple-500/15 text-purple-300 border border-purple-500/30"
                reason = f"下落中の{long_window}日移動平均線({long_ma_today:,.0f}円)から下方に大きく乖離({diff_rate:.1f}%)。本日反発しました。{warning_suffix}"

    # ==========================================
    # 買い1：新規買い（トレンド転換・底練りからの上抜け）
    # ==========================================
    lookback_period = 40
    
    # 1. 底練り・位置関係（過去40日中28日以上沈んでいたこと）
    price_below_count = (df_temp.iloc[-lookback_period-1:-1]['Close'] < df_temp.iloc[-lookback_period-1:-1]['long_ma']).sum()
    is_long_bottoming = price_below_count >= (lookback_period * 0.7)

    # 2. レンジ相場排除フィルター（過去40日間に+5.0%以上上に飛び出した履歴がないこと）
    past_max_diff = ((df_temp.iloc[-lookback_period-1:-1]['Close'] - df_temp.iloc[-lookback_period-1:-1]['long_ma']) / df_temp.iloc[-lookback_period-1:-1]['long_ma'] * 100).max()
    is_not_range_bound = past_max_diff < 5.0

    # 3. 本日の突き抜け / GC判定
    price_crossed_above = (price_yesterday < long_ma_yesterday) and (price_today >= long_ma_today)
    gc_occurred = (short_ma_yesterday < long_ma_yesterday) and (short_ma_today >= long_ma_today)

    # 4. トレンド転換の裏付け（短期MAが長期MAのすぐ近くまで肉薄しているか）
    short_long_diff = ((short_ma_today - long_ma_today) / long_ma_today) * 100
    is_trend_reversing = short_long_diff >= -2.0 

    # 5. 長期MAの傾き判定（過去3日間の傾き、または単日での上向き転換）
    long_ma_3d_ago = df_temp.iloc[-4]['long_ma']
    long_ma_slope_3d = ((long_ma_today - long_ma_3d_ago) / long_ma_3d_ago) * 100
    
    is_long_ma_flat_or_rising = (long_ma_today > long_ma_yesterday) or (long_ma_slope_3d >= -0.2)

    # 6. 統合判定
    if category == "NONE" and (price_crossed_above or gc_occurred) and is_long_ma_flat_or_rising and is_long_bottoming and is_not_range_bound and is_trend_reversing and (diff_rate <= 5.0):
        category = "BUY1"
        category_name = "買い1：新規買い"
        badge_class = "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
        cross_type = "ゴールデンクロス" if gc_occurred else "価格の突き抜け"
        reason = f"底練りを経て、横這い〜上昇傾向の長期線({long_window}日線)に対して本日{cross_type}が発生。短期線も追従しておりトレンド転換の兆しです。"
        
    # 買い2：再突き抜け ＆ 初押し(下抜け復帰)
    below_count_15d = (df_temp.iloc[-16:-1]['Close'] < df_temp.iloc[-16:-1]['long_ma']).sum()
    is_temp_dip = 1 <= below_count_15d <= 3
    
    was_above_recently = (df_temp.iloc[-21:-1]['Close'] >= df_temp.iloc[-21:-1]['long_ma']).any()
    is_initial_dip_crossed = is_long_bottoming_past and was_above_recently and price_crossed_above

    if category == "NONE" and (diff_rate <= 5.0):
        if price_crossed_above and is_long_ma_rising and is_temp_dip:
            category = "BUY2"
            category_name = "買い2：再突き抜け"
            badge_class = "bg-sky-500/15 text-sky-300 border border-sky-500/30"
            reason = f"力強い上昇トレンド中、長期線をわずか数日下抜け後、本日素早く上方に復帰しました。"
        elif is_long_ma_flat_or_rising and is_initial_dip_crossed:
            category = "BUY2"
            category_name = "買い2：初押し(下抜け復帰)"
            badge_class = "bg-sky-500/15 text-sky-300 border border-sky-500/30"
            reason = f"長期の底練りから脱却後、最初の押し目で長期線を一度下抜け、本日再び上方に復帰しました。"

    # 買い3：押し目反発 ＆ 初押し(支持線反発)
    max_diff_15d = ((df_temp.iloc[-16:-1]['Close'] - df_temp.iloc[-16:-1]['long_ma']) / df_temp.iloc[-16:-1]['long_ma'] * 100).max()
    has_pulled_back = max_diff_15d >= 4.0
    
    is_close_to_ma = 0.0 < diff_rate <= 3.5
    is_rebound = is_yang_candle and is_price_up
    not_crossed_below_recent = (df_temp.iloc[-6:-1]['Close'] >= df_temp.iloc[-6:-1]['long_ma']).all()

    is_initial_dip_rebound = is_long_bottoming_past and was_above_recently and is_close_to_ma and is_rebound and not_crossed_below_recent

    if category == "NONE" and not_crossed_below_recent and is_long_ma_rising:
        if has_pulled_back and is_close_to_ma and is_rebound:
            category = "BUY3"
            category_name = "買い3：押し目反発"
            badge_class = "bg-amber-500/15 text-amber-300 border border-amber-500/30"
            reason = f"上向き長期線を支持線とした、教科書通りの綺麗な陽線反発を観測しました。"
        elif is_initial_dip_rebound:
            category = "BUY3"
            category_name = "買い3：初押し(支持線反発)"
            badge_class = "bg-amber-500/15 text-amber-300 border border-amber-500/30"
            reason = f"長期の底練りから脱却後、最初の押し目で長期線に接近し、下抜けることなく本日反発しました。"
        
    # 買い3-Pre：押し目待ち伏せ ＆ 初押し(待ち伏せ)
    is_resting_on_ma = -0.5 <= diff_rate <= 1.5
    is_initial_dip_resting = is_long_bottoming_past and was_above_recently and is_resting_on_ma and not_crossed_below_recent

    if category == "NONE" and not_crossed_below_recent and is_long_ma_rising:
        if has_pulled_back and is_resting_on_ma:
            category = "BUY3_PRE"
            category_name = "買い3：押し目待ち伏せ"
            badge_class = "bg-amber-600/10 text-amber-400 border border-amber-500/20"
            reason = f"長期上昇トレンド中、支持線接触まで十分に引き付けた仕込み待ち伏せ状態です。"
        elif is_initial_dip_resting:
            category = "BUY3_PRE"
            category_name = "買い3：初押し(待ち伏せ)"
            badge_class = "bg-amber-600/10 text-amber-400 border border-amber-500/20"
            reason = f"長期の底練りから脱却後の最初の押し目で、長期線の支持線付近まで十分に引き付けた状態です。"

    # ==========================================
    # ★【新規追加】カテゴリ別テクニカル損切り価格 (stop_loss_price) 自動算出
    # ==========================================
    stop_loss_price = 0
    if category == "BUY1":
        # 買い1: 直近20日間の最安値 × 0.995（0.5%下、切り捨て）
        low_20d = df_temp['Low'].tail(20).min()
        stop_loss_price = math.floor(low_20d * 0.995)
    elif category == "BUY2":
        # 買い2: 直近5日間の最安値 × 0.995（0.5%下、切り捨て）
        low_5d = df_temp['Low'].tail(5).min()
        stop_loss_price = math.floor(low_5d * 0.995)
    elif category in ["BUY3", "BUY3_PRE"]:
        # 買い3 / Pre: 長期移動平均線 × 0.985（1.5%下、切り捨て）
        stop_loss_price = math.floor(long_ma_today * 0.985)
    elif category == "BUY4":
        # 買い4: 当日安値 × 0.99（1.0%下、切り捨て）
        stop_loss_price = math.floor(low_today * 0.99)

    # ==========================================
    # 期待度スコア (10段階スケール解放版)
    # ==========================================
    score = 5 
    score_reasons = []
    
    if category != "NONE":
        if is_rsi_sell_warning:
            score -= 1
            score_reasons.append("⚠️ RSI過熱警戒: -1")
        else:
            if is_rsi_divergence:
                score += 1
                score_reasons.append("🛡️ 強気ダイバージェンス: +1")
            elif is_rsi_buy_reversal:
                score += 1
                score_reasons.append("🔄 RSIゾーン反発: +1")

        if volume_today <= 10000:
            score -= 1
            score_reasons.append("⚠️ 流動性極低(1万株以下): -1")
            
        if vol_ratio >= 1.5:
            if is_yang_candle:
                score += 1
                score_reasons.append("📊 陽線で出来高急増: +1")
            else:
                score -= 1
                score_reasons.append("⚠️ 陰線で出来高急増: -1")

        if category not in ["BUY4", "BUY3_PRE"] and upper_shadow_pct >= 40.0:
            score -= 1
            score_reasons.append("🕯️ 上髭超過: -1")
            
        short_diff_rate = ((price_today - short_ma_today) / short_ma_today) * 100
        if category in ["BUY1", "BUY2"] and short_diff_rate >= 5.0:
            score -= 1
            score_reasons.append("🚀 短期的な飛びすぎ警戒: -1")

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
            elif candle_body_pct < 0.5:
                score -= 1
                score_reasons.append("🕯️ 反発実体極小: -1")
                
    score = max(1, min(10, score))
    # 星表記（互換性確保）
    stars_str = "★" * min(5, score) + "☆" * max(0, 5 - min(5, score))

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
        "stop_loss_price": clean_val(int(stop_loss_price)),
        "rsi": clean_val(round(rsi_today, 1)),
        "rsi_sell_warning": is_rsi_sell_warning,
        "rsi_buy_reversal": is_rsi_buy_reversal,
        "rsi_double_bottom": is_rsi_double_bottom,
        "rsi_divergence": is_rsi_divergence,
        "score_reasons": score_reasons
    }

# ----------------------------------------------------------------------
# ★【Phase 1】東証33業種 HOTセクター自動算出関数
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
                new_score = min(10, sys_data["score"] + 1)
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
                new_score = min(10, item[sys_key]["score"] + 1)
                item[sys_key]["score"] = new_score

# ==========================================
# ★ AI相談用履歴データ分割出力 (100分割シャーディング)
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
    shard_key = ticker_num[-2:]
    
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
        
        diff = round(((c - m25) / m25) * 100, 1) if c and m25 else None
        records.append([dt_str, c, m5, m25, m75, diff, rsi])
        
    shards[shard_key][ticker.replace(".T", "")] = records

for shard_key, data_dict in shards.items():
    if data_dict:
        file_path = os.path.join(history_dir, f"data_{shard_key}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data_dict, f, separators=(',', ':'))
print(" -> AI履歴データの出力を完了しました")

# ==========================================
# ★【最終出力】template.html を読み込んで index.html を生成
# ==========================================

# 1. JSONデータの作成 (エスケープ事故を防ぐためコンパクトな1行文字列化)
json_data_str = json.dumps(results_list, ensure_ascii=False)
hot_sectors_json_str = json.dumps(hot_sectors, ensure_ascii=False)
prev_counts_json_str = json.dumps(prev_counts, ensure_ascii=False)

# 2. 外部テンプレートファイルの読み込み
template_path = "template.html"
if not os.path.exists(template_path):
    raise FileNotFoundError(f"テンプレートファイル '{template_path}' が見つかりません。")

with open(template_path, "r", encoding="utf-8") as f:
    html_template = f.read()

# 3. プレースホルダーの置き換え
html_content = html_template
html_content = html_content.replace("__LAST_UPDATE__", current_time_str)
html_content = html_content.replace("__PLACEHOLDER_MARKET_MEDIAN__", f"{market_median_change:.4f}")
html_content = html_content.replace("__PLACEHOLDER_HOT_SECTORS__", hot_sectors_json_str)
html_content = html_content.replace("__PLACEHOLDER_RESULTS__", json_data_str)
html_content = html_content.replace("__PLACEHOLDER_PREV_COUNTS__", prev_counts_json_str)

# 4. index.html として出力
with open(html_output_path, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"\n--- HTML生成が完了しました ---")
print(f"👉 生成されたファイル: {html_output_path} (自動更新時刻：{current_time_str})")
