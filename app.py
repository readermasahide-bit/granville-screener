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
    "baseUrl": "https://docs.google.com/forms/d/e/1FAIpQLSeUMv4F3yxLUKXuAzU03riKKFRlZjoxORx5vGX69gXyxDiQOw/viewform",
    "entryCode": "entry.1616153480",
    "entryName": "entry.639288663",
    "entrySys":  "entry.1292630960",
    "entryCat":  "entry.432445345"
}

# 【Googleフォーム2：期待度改善用】
FORM_CONFIG_SCORE = {
    "baseUrl": "https://docs.google.com/forms/d/e/1FAIpQLSet_-Ab3-3HgXrRS5pG-5PT4K-qgip4lV4EUqqivaWNRBOO_g/viewform",
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

# ★【件数前日比ハック】既存の index.html から昨日の件数をパースして自動計算
prev_counts = {
    "short": {"BUY1": 0, "BUY2": 0, "BUY3": 0, "BUY3_PRE": 0, "BUY4": 0, "TOTAL": 0},
    "mid": {"BUY1": 0, "BUY2": 0, "BUY3": 0, "BUY3_PRE": 0, "BUY4": 0, "TOTAL": 0}
}

if os.path.exists(html_output_path):
    print("既存の index.html から前日の集計データを自動解析中...")
    try:
        with open(html_output_path, "r", encoding="utf-8") as f:
            old_html = f.read()
        
        # 既存の results = [ ... ] の配列部分を正規表現で検出してパース
        match = re.search(r"results:\s*(\[.*?\]),", old_html, re.DOTALL)
        if match:
            prev_results_json = match.group(1)
            prev_results = json.loads(prev_results_json)
            
            # 各システムの昨日点灯数を集計
            for item in prev_results:
                for sys_key in ["short", "mid"]:
                    cat = item.get(sys_key, {}).get("category", "NONE")
                    if cat in prev_counts[sys_key]:
                        prev_counts[sys_key][cat] += 1
                        
            prev_counts["short"]["TOTAL"] = len(prev_results)
            prev_counts["mid"]["TOTAL"] = len(prev_results)
            print(f" -> 解析成功。前日の判定母数: {len(prev_results)} 銘柄")
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
    
    # API制限回避
    time.sleep(4)

print(f"データのダウンロードが完了しました。正常取得銘柄数: {len(bulk_data)}")

# 3. 判定および採点ロジック関数
def evaluate_logic(df_temp, short_window, long_window, market_type):
    df_temp = df_temp.copy()
    if isinstance(df_temp.columns, pd.MultiIndex):
        df_temp.columns = df_temp.columns.get_level_values(0)
        
    df_temp['short_ma'] = df_temp['Close'].rolling(window=short_window).mean()
    df_temp['long_ma'] = df_temp['Close'].rolling(window=long_window).mean()
    df_temp = df_temp.dropna(subset=['short_ma', 'long_ma']).reset_index(drop=True)
    
    min_len = 45 if long_window <= 25 else 130
    if len(df_temp) < min_len:
        return {
            "category": "NONE", "categoryName": "データ不足",
            "badgeClass": "bg-slate-800 text-slate-500 border border-slate-700",
            "diffRate": 0.0, "reason": "データが不足しています。",
            "ma_short": 0.0, "ma_long": 0.0, "score": 1
        }
        
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
    
    long_ma_slope_10d = long_ma_today - df_temp.iloc[-11]['long_ma']
    long_ma_slope_3d = long_ma_today - df_temp.iloc[-4]['long_ma']
    long_ma_slope_15d = long_ma_today - df_temp.iloc[-16]['long_ma']
    
    is_yang_candle = price_today > open_today
    is_price_up = price_today > price_yesterday
    
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
    
    # 買い4
    if diff_rate <= oversold_threshold:
        if is_yang_candle or is_price_up:
            category = "BUY4"
            category_name = "買い4：逆張りリバ"
            badge_class = "bg-purple-500/15 text-purple-300 border border-purple-500/30"
            reason = f"{long_window}日移動平均線({long_ma_today:,.0f}円)から下方に大きく乖離({diff_rate:.1f}%)。本日反発しました。{warning_suffix}"

    # 買い1
    crossed_above = (price_yesterday < long_ma_yesterday and price_today >= long_ma_today) or \
                    (short_ma_yesterday < long_ma_yesterday and short_ma_today >= long_ma_today)
    is_flat_or_rising = long_ma_slope_3d >= -0.01
    below_count_20d = (df_temp.iloc[-21:-1]['Close'] < df_temp.iloc[-21:-1]['long_ma']).sum()
    is_new_crossover = below_count_20d >= 12
    
    if category == "NONE" and crossed_above and is_flat_or_rising and is_new_crossover and (diff_rate <= 5.0):
        category = "BUY1"
        category_name = "買い1：新規買い"
        badge_class = "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
        reason = f"価格が横這い〜上昇トレンドの長期線({long_window}日線)を本日明確に上抜けました。"

    # 買い2
    is_long_ma_rising = long_ma_slope_10d > 0 and (long_ma_today > long_ma_yesterday)
    below_count_10d = (df_temp.iloc[-11:-1]['Close'] < df_temp.iloc[-11:-1]['long_ma']).sum()
    is_temp_dip = 1 <= below_count_10d <= 4
    recovered_above = (price_yesterday < long_ma_yesterday) and (price_today >= long_ma_today)
    
    if category == "NONE" and is_long_ma_rising and is_temp_dip and recovered_above and (0.0 <= diff_rate <= 5.0):
        category = "BUY2"
        category_name = "買い2：再突き抜け"
        badge_class = "bg-sky-500/15 text-sky-300 border border-sky-500/30"
        reason = f"良好な上昇トレンド中、長期線を一時的に下抜け後、本日素早く上方に復帰しました。"

    # 買い3（通常：陽線＋プラス反発）
    is_long_ma_rising_strong = long_ma_slope_15d > 0
    max_diff_15d = ((df_temp.iloc[-16:-1]['Close'] - df_temp.iloc[-16:-1]['long_ma']) / df_temp.iloc[-16:-1]['long_ma'] * 100).max()
    has_pulled_back = max_diff_15d >= 4.0
    is_close_to_ma = 0.0 < diff_rate <= 3.5
    is_rebound = is_yang_candle and is_price_up
    
    if category == "NONE" and is_long_ma_rising_strong and has_pulled_back and is_close_to_ma and is_rebound:
        category = "BUY3"
        category_name = "買い3：押し目反発"
        badge_class = "bg-amber-500/15 text-amber-300 border border-amber-500/30"
        reason = f"上向き長期線を支持線とした、教科書通りの綺麗な陽線反発を観測しました。"

    # ★【新設】買い3-Pre（下落日待ち伏せ用：陰線・マイナスを許容し、長期線の真上に接触した状態）
    is_resting_on_ma = -0.5 <= diff_rate <= 1.5  # 支持線まで極小乖離（わずかな下振れも許容）
    if category == "NONE" and is_long_ma_rising_strong and has_pulled_back and is_resting_on_ma:
        category = "BUY3_PRE"
        category_name = "買い3：押し目待ち伏せ"
        badge_class = "bg-amber-600/10 text-amber-400 border border-amber-500/20"
        reason = f"長期上昇トレンド中、地合い連れ安によって支持線接触まで十分に引き付けた絶好の『仕込み待ち伏せ』状態です。"

    # 期待度スコア
    score = 3
    if category != "NONE":
        if vol_ratio >= 1.5: score += 1
        if category not in ["BUY4", "BUY3_PRE"] and upper_shadow_pct >= 40.0: score -= 1
        if category == "BUY1":
            if is_slope_strong_relative: score += 1
            if candle_body_pct < 0.5: score -= 1
        elif category == "BUY2":
            if is_slope_strong_relative: score += 1
        elif category in ["BUY3", "BUY3_PRE"]:
            if diff_rate <= 1.5: score += 1
            if candle_body_pct < 1.0: score -= 1
        elif category == "BUY4":
            if candle_body_pct >= 3.0: score += 1
            if candle_body_pct < 0.5: score -= 1
            
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
        "stars": clean_val(stars_str)
    }

# 4. 全データの判定実行（市場中央値とレラティブストレングスの算出）
results_list = []
print("各銘柄の判定ロジックを実行しています...")

for ticker, df_stock in bulk_data.items():
    if df_stock.empty or len(df_stock) < 130:
        continue
        
    today = df_stock.iloc[-1]
    yesterday = df_stock.iloc[-2]
    
    price_today = float(today['Close'])
    price_yesterday = float(yesterday['Close'])
    change = price_today - price_yesterday
    change_rate = (change / price_yesterday) * 100 if price_yesterday > 0 else 0.0
    
    # 出来高の抽出
    volume_today = float(today['Volume'])
    is_low_volume = volume_today <= 1000  # 出来高1000株以下判定フラグ
    
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
    
    stock_info = {
        "ticker": clean_val(ticker.replace(".T", "")),
        "name": clean_val(ticker_to_name.get(ticker, "不明な銘柄")),
        "market": clean_val(market_short),
        "sector": clean_val(ticker_to_sector.get(ticker, "不明")),
        "price": clean_val(price_today),
        "change": clean_val(change),
        "changeRate": clean_val(round(change_rate, 2)),
        "volume": clean_val(volume_today),
        "isLowVolume": clean_val(is_low_volume),
        "isStrongRelative": False, # 後から一括計算
        "short": short_res,
        "mid": mid_res
    }
    results_list.append(stock_info)

# ★【クオンツ地合い算出】本日の東証全銘柄の騰落中央値を動的算出
all_rates = [item["changeRate"] for item in results_list if item["changeRate"] is not None]
market_median_change = float(pd.Series(all_rates).median()) if all_rates else 0.0
print(f" -> 本日の東証全上場銘柄の騰落率中央値: {market_median_change:.2f}%")

# 地合い連れ安日に逆行・抵抗している「🛡️ 地合い強気」銘柄を算出し、期待度スコアを加算
for item in results_list:
    is_strong_relative = False
    # 全体相場が軟調（中央値が -1.0% 以下）の時、市場平均より +1.5% 以上踏ん張っているか？
    if market_median_change <= -1.0:
        is_strong_relative = item["changeRate"] >= (market_median_change + 1.5)
        
    if is_strong_relative:
        item["isStrongRelative"] = True
        # シグナル点灯銘柄であれば、期待度をボーナス+1点（上限5）
        for sys_key in ["short", "mid"]:
            if item[sys_key]["category"] != "NONE":
                new_score = min(5, item[sys_key]["score"] + 1)
                item[sys_key]["score"] = new_score
                item[sys_key]["stars"] = "★" * new_score + "☆" * (5 - new_score)

json_data_str = json.dumps(results_list, ensure_ascii=False, indent=2)

form_cat_str = json.dumps(FORM_CONFIG_CAT, ensure_ascii=False)
form_score_str = json.dumps(FORM_CONFIG_SCORE, ensure_ascii=False)
prev_counts_str = json.dumps(prev_counts, ensure_ascii=False)

# HTMLテンプレート
# ・判定カテゴリ列の幅を w-20 (最狭化) にし、他の列に大きなゆとりを持たせました。
# ・出来高極小バッジを文字なしのアイコン「⚠️」のみに極小化しました。
# ・運用上読まれていなかった「判定理由」列を完全廃止し、表示ゆとりを最大化しました。
# ・前営業日の index.html から昨日件数をパースして自動比較表示する前日比機能を搭載。
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
            <p class="text-xs text-slate-400 hidden sm:block">東証全3,800銘柄 自動解析・下落相場特化・待ち伏せ判定機能（最終更新：__LAST_UPDATE__）</p>
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
      
      <!-- サマリーカード (前日比のカウント増減差に対応) -->
      <section class="grid grid-cols-2 md:grid-cols-5 gap-4">
        <div class="bg-slate-900/80 border border-slate-800 rounded-xl p-4 flex flex-col justify-between shadow-lg">
          <span class="text-[11px] font-bold text-slate-400 uppercase tracking-wider">東証判定対象数</span>
          <div class="flex items-baseline gap-2 mt-2">
            <span id="statTotal" class="text-2xl font-bold text-white">0</span>
            <span class="text-xs text-slate-500">銘柄</span>
            <span id="statTotalDiff" class="text-[10px] font-bold"></span>
          </div>
        </div>
        <div class="bg-slate-900/80 border border-emerald-500/20 rounded-xl p-4 flex flex-col justify-between shadow-lg">
          <span class="text-[11px] font-bold text-emerald-400 uppercase tracking-wider">買い1 (GC初動)</span>
          <div class="flex items-baseline justify-between mt-2">
            <span id="statBuy1" class="text-2xl font-bold text-emerald-400">0</span>
          </div>
        </div>
        <div class="bg-slate-900/80 border border-sky-500/20 rounded-xl p-4 flex flex-col justify-between shadow-lg">
          <span class="text-[11px] font-bold text-sky-400 uppercase tracking-wider">買い2 (下抜け復帰)</span>
          <div class="flex items-baseline justify-between mt-2">
            <span id="statBuy2" class="text-2xl font-bold text-sky-400">0</span>
          </div>
        </div>
        <div class="bg-slate-900/80 border border-amber-500/20 rounded-xl p-4 flex flex-col justify-between shadow-lg">
          <span class="text-[11px] font-bold text-amber-400 uppercase tracking-wider">買い3 (支持線反発/Pre)</span>
          <div class="flex items-baseline justify-between mt-2">
            <span id="statBuy3" class="text-2xl font-bold text-amber-400">0</span>
          </div>
        </div>
        <div class="bg-slate-900/80 border border-purple-500/20 rounded-xl p-4 flex flex-col justify-between shadow-lg">
          <span class="text-[11px] font-bold text-purple-400 uppercase tracking-wider">買い4 (下方乖離リバ)</span>
          <div class="flex items-baseline justify-between mt-2">
            <span id="statBuy4" class="text-2xl font-bold text-purple-400">0</span>
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

        <!-- テーブル (判定理由列を廃止、その他の列の横幅に絶妙なゆとりを確保) -->
        <div class="mt-6 overflow-x-auto">
          <table class="w-full text-left table-fixed">
            <thead>
              <tr class="border-b border-slate-800 text-[11px] font-bold text-slate-400 uppercase bg-slate-950/60 select-none">
                <th class="p-3 w-28 whitespace-nowrap">判定</th>
                <th class="p-3 cursor-pointer select-none hover:text-cyan-400 text-center w-24 whitespace-nowrap transition duration-200" id="thScore" title="クリックで期待度順に並び替え">
                  <div class="flex items-center justify-center gap-1">
                    <span>期待度</span>
                    <span id="sortScoreIcon" class="text-cyan-400 font-mono">↕</span>
                  </div>
                </th>
                <th class="p-3 w-32">コード</th>
                <th class="p-3 min-w-[200px]">銘柄名 / 業種</th>
                <th class="p-3 cursor-pointer select-none hover:text-cyan-400 text-right w-28 transition duration-200 whitespace-nowrap" id="thPrice" title="クリックで昇順/降順並び替え">
                  <div class="flex items-center justify-end gap-1">
                    <span>株価</span>
                    <span id="sortIcon" class="text-cyan-400 font-mono">↕</span>
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
                  ・長期線(<span class="exp-long"></span>)の傾き: 直近3日で横這い〜上向き(<span class="font-mono">&gt;=-0.01</span>)<br>
                  ・底確認: 過去20日のうち12日以上は線の下に沈んでいたこと<br>
                  ・上抜け乖離率: 当日終値が長期線から <span class="font-mono">+5.0%</span> 以内
                </p>
              </div>
              <div class="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5">
                <span class="font-bold text-slate-200 block mb-1">買い2：一時下抜け復帰</span>
                <p class="text-slate-400 text-[11px] leading-relaxed">
                  ・長期線(<span class="exp-long"></span>)が右肩上がり<br>
                  ・一時性: 過去10日で長期線の下に沈んだのが「1〜4日のみ」<br>
                  ・本日、再度長期線の上に復帰し、乖離率が <span class="font-mono">0.0%〜+5.0%</span> 以内
                </p>
              </div>
              <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-3.5">
                <span class="font-bold text-slate-200 block mb-1">買い3：押し目反発（待ち伏せ含む）</span>
                <p class="text-slate-400 text-[11px] leading-relaxed">
                  ・長期線(<span class="exp-long"></span>)が右肩上がり<br>
                  ・調整: 過去15日以内に長期線から <span class="font-mono">+4.0%</span> 離れた山を作っていること<br>
                  ・反発: 長期線のすぐ上(<span class="font-mono">0.0%〜+3.5%</span>)で本日反発。<br>
                  ・<strong>【下落相場用Pre-Buy3】</strong>: 長期線の極近(JST -0.5%〜+1.5%)に位置する場合、陰線やマイナス引けでも「待ち伏せシグナル」として特別に点灯。
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

    </main>

    <script>
      const state = {
        results: /* PLACEHOLDER_RESULTS */ [],
        prevCounts: /* PLACEHOLDER_PREV_COUNTS */ {"short":{"BUY1":0,"BUY2":0,"BUY3":0,"BUY3_PRE":0,"BUY4":0,"TOTAL":0},"mid":{"BUY1":0,"BUY2":0,"BUY3":0,"BUY3_PRE":0,"BUY4":0,"TOTAL":0}},
        marketMedian: __MARKET_MEDIAN__,  # 本日の東証騰落中央値
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
        const targetUrl = `${FORM_CAT_CFG.baseUrl}?viewform&${FORM_CAT_CFG.entryCode}=${encodeURIComponent(ticker)}&${FORM_CAT_CFG.entryName}=${encodeURIComponent(name)}&${FORM_CAT_CFG.entrySys}=${encodeURIComponent(sysLabel)}&${FORM_CAT_CFG.entryCat}=${encodeURIComponent(category)}`;
        window.open(targetUrl, '_blank', 'width=620,height=750');
      }

      function openScoreFeedback(ticker, name, score) {
        if (!FORM_SCORE_CFG.baseUrl || FORM_SCORE_CFG.baseUrl === "YOUR_SCORE_FORM_URL_HERE") {
          alert("【初期設定が必要です】\\nコード冒頭の「FORM_CONFIG_SCORE」にご自身の2つ目のGoogleフォームのURLとIDを設定してください。");
          return;
        }
        const sysLabel = (state.currentSystem === 'short') ? "短期(5/25)" : "中期(25/75)";
        const targetUrl = `${FORM_SCORE_CFG.baseUrl}?viewform&${FORM_SCORE_CFG.entryCode}=${encodeURIComponent(ticker)}&${FORM_SCORE_CFG.entryName}=${encodeURIComponent(name)}&${FORM_SCORE_CFG.entrySys}=${encodeURIComponent(sysLabel)}&${FORM_SCORE_CFG.entryScore}=${encodeURIComponent(score)}`;
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

      // ★ 前日比の差分バッジを生成するヘルパー関数
      function getDiffBadge(todayVal, yesterdayVal) {
        const diff = todayVal - yesterdayVal;
        if (diff > 0) {
          return `<span class="text-xs text-emerald-400 font-bold ml-1.5">(+${diff})</span>`;
        } else if (diff < 0) {
          return `<span class="text-xs text-rose-400 font-bold ml-1.5">(${diff})</span>`;
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
        
        // 買い3カードは「通常買い3」と「待ち伏せPre-Buy3」を合算
        const buy3Total = counts.BUY3 + counts.BUY3_PRE;
        const buy3Yesterday = (state.prevCounts[sys].BUY3 || 0) + (state.prevCounts[sys].BUY3_PRE || 0);

        const totalToday = state.results.filter(r => r[sys].category !== "NONE").length;
        const totalYesterday = state.prevCounts[sys].TOTAL_ACTIVE || 0; // NONE以外の昨日総計
        const totalDiff = totalToday - totalYesterday;

        document.getElementById('statBuy1').innerHTML = `${counts.BUY1} ${getDiffBadge(counts.BUY1, state.prevCounts[sys].BUY1 || 0)}`;
        document.getElementById('statBuy2').innerHTML = `${counts.BUY2} ${getDiffBadge(counts.BUY2, state.prevCounts[sys].BUY2 || 0)}`;
        document.getElementById('statBuy3').innerHTML = `${buy3Total} ${getDiffBadge(buy3Total, buy3Yesterday)}`;
        document.getElementById('statBuy4').innerHTML = `${counts.BUY4} ${getDiffBadge(counts.BUY4, state.prevCounts[sys].BUY4 || 0)}`;
        
        document.getElementById('statTotal').textContent = state.results.length;
        const totalDiffEl = document.getElementById('statTotalDiff');
        if (totalDiffEl) {
          const tDiff = state.results.length - (state.prevCounts[sys].TOTAL || 0);
          totalDiffEl.innerHTML = tDiff > 0 ? `+${tDiff}` : tDiff < 0 ? `${tDiff}` : '±0';
          totalDiffEl.className = `text-[10px] font-bold ml-1.5 ${tDiff > 0 ? 'text-emerald-400' : tDiff < 0 ? 'text-rose-400' : 'text-slate-500'}`;
        }

        const labels = { ALL: 'すべて', BUY1: '買い1', BUY2: '買い2', BUY3: '買い3', BUY4: '買い4' };
        document.querySelectorAll('.tab-btn').forEach(btn => {
          const t = btn.dataset.tab;
          let count = 0;
          if (t === 'ALL') {
            count = state.results.filter(r => r[sys].category !== 'NONE').length;
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
        
        // NONE(条件外)は初期状態やタブ切り替え時にリストに混ざらないよう排除
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

          // 出来高極小サインを文字なしの極小バッジアイコン「⚠️」へ集約
          const volumeWarning = item.isLowVolume 
            ? `<span class="ml-1 px-1 text-rose-400 font-bold select-none cursor-help" title="本日出来高: ${item.volume.toLocaleString()}株 (流動性リスク極めて高：1,000株以下)">⚠️</span>` 
            : '';

          // 「🛡️地合い強気」バッジの生成
          const rsBadge = item.isStrongRelative 
            ? `<span class="ml-1 px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[9px] font-bold select-none cursor-help" title="本日市場中央値が ${state.marketMedian.toFixed(2)}% の大幅下落相場の中、この銘柄は ${item.changeRate}% で踏み止まり、大口の買い支えが確認されます。">🛡️ 地合い強気</span>` 
            : '';

          tr.innerHTML = `
            <td class="p-3"><span class="px-2 py-0.5 rounded text-[10px] font-bold ${sysData.badgeClass}">${categoryShortName}</span></td>
            <td class="p-3 text-center text-amber-400 font-mono text-[14px] font-extrabold select-none">${sysData.score}</td>
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
                ${volumeWarning}
                ${rsBadge}
              </div>
              <div class="text-[10px] text-slate-400 mt-0.5">${item.sector}</div>
            </td>
            <td class="p-3 text-right font-mono font-bold">${item.price.toLocaleString()}</td>
            <td class="p-3 text-right font-mono ${isPlus ? 'text-emerald-400' : 'text-rose-400'}">${isPlus ? '+' : ''}${item.change.toLocaleString()} (${isPlus ? '+' : ''}${item.changeRate}%)</td>
            <td class="p-3 text-right font-mono text-slate-300">
              <div>${sys==='short'?'5日':'25日'}: ${sysData.ma_short.toLocaleString()}</div>
              <div class="text-[10px] text-slate-400">${sys==='short'?'25日':'75日'}: ${sysData.ma_long.toLocaleString()}</div>
            </td>
            <td class="p-3 text-right font-mono ${sysData.diffRate >= 0 ? 'text-cyan-400' : 'text-purple-400'}">${sysData.diffRate >= 0 ? '+' : ''}${sysData.diffRate.toFixed(1)}%</td>
            <td class="p-3 text-center"><span class="${marketBadgeClass} px-2 py-0.5 rounded text-[10px] font-bold">${item.market}</span></td>
            
            <td class="p-3 text-center space-x-1 whitespace-nowrap">
              <button onclick="openScoreFeedback('${item.ticker}', '${item.name}', '${sysData.score}')" class="px-2 py-1 bg-slate-800 hover:bg-amber-600 text-slate-300 hover:text-white rounded border border-slate-700 text-[10px] font-bold transition duration-200 cursor-pointer" title="期待度スコアの妥当性に対して報告">
                ⭐ 期待度
              </button>
              <button onclick="openCatFeedback('${item.ticker}', '${item.name}', '${categoryShortName}')" class="px-2 py-1 bg-slate-800 hover:bg-emerald-600 text-slate-300 hover:text-white rounded border border-slate-700 text-[10px] font-bold transition duration-200 cursor-pointer" title="シグナルの判定カテゴリに対して報告">
                ✍️ 判定
              </button>
            </td>
          `;
          tbody.appendChild(tr);
        });
      }
    </script>
  </body>
</html>"""

# HTMLテンプレートの動的更新
html_content = html_template.replace("__LAST_UPDATE__", current_time_str)
html_content = html_content.replace("__MARKET_MEDIAN__", f"{market_median_change:.4f}")
html_content = html_content.replace("/* PLACEHOLDER_RESULTS */ []", json_data_str)
html_content = html_content.replace("/* PLACEHOLDER_FORM_CAT */ {}", form_cat_str)
html_content = html_content.replace("/* PLACEHOLDER_FORM_SCORE */ {}", form_score_str)

# 昨日総計の集計をJSに渡す（NONEを除外したTOTAL_ACTIVEも渡す）
for sys_key in ["short", "mid"]:
    total_active = 0
    for cat in ["BUY1", "BUY2", "BUY3", "BUY3_PRE", "BUY4"]:
        total_active += prev_counts[sys_key][cat]
    prev_counts[sys_key]["TOTAL_ACTIVE"] = total_active

prev_counts_json_str = json.dumps(prev_counts, ensure_ascii=False)
html_content = html_content.replace("/* PLACEHOLDER_PREV_COUNTS */ {\"short\":{\"BUY1\":0,\"BUY2\":0,\"BUY3\":0,\"BUY3_PRE\":0,\"BUY4\":0,\"TOTAL\":0},\"mid\":{\"BUY1\":0,\"BUY2\":0,\"BUY3\":0,\"BUY3_PRE\":0,\"BUY4\":0,\"TOTAL\":0}}", prev_counts_json_str)

with open(html_output_path, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"\n--- HTML生成が完了しました ---")
print(f"👉 生成されたファイル: {html_output_path} (自動更新時刻：{current_time_str})")
