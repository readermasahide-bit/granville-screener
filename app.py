import io
import os
import json
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta, timezone

# ==========================================
# ★ 設定パラメータ（取得いただいた2つのフォームURL・IDを完全適用済みです）
# ==========================================
SYSTEM_TYPE = "mid"  # "short"(5/25) または "mid"(25/75)
html_output_path = "index.html"

# 【Googleフォーム1：判定カテゴリ改善用】（適用済み）
FORM_CONFIG_CAT = {
    "baseUrl": "https://docs.google.com/forms/d/e/1FAIpQLSeUMv4F3yxLUKXuAzU03riKKFRlZjoxORx5vGX69gXyxDiQOw/viewform",
    "entryCode": "entry.1616153480",
    "entryName": "entry.639288663",
    "entrySys":  "entry.1292630960",
    "entryCat":  "entry.432445345"
}

# 【Googleフォーム2：期待度改善用】（適用済み）
FORM_CONFIG_SCORE = {
    "baseUrl": "https://docs.google.com/forms/d/e/1FAIpQLSet_-Ab3-3HgXrRS5pG-5PT4K-qgip4lV4EUqqivaWNRBOO_g/viewform",
    "entryCode": "entry.473391802",
    "entryName": "entry.1042173003",
    "entrySys":  "entry.1364518533",
    "entryScore": "entry.2008795821"
}
# ==========================================

JST = timezone(timedelta(hours=+9))
current_time_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")

if SYSTEM_TYPE == "short":
    short_window = 5
    long_window = 25
    system_title = "短期（5日線/25日線）"
else:
    short_window = 25
    long_window = 75
    system_title = "中期（25日線/75日線）"

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

# 2. User-Agent設定とバルクダウンロード
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
})

print("Yahoo! Financeから株価データをダウンロード中...")
bulk_data = {}
chunk_size = 200
for i in range(0, len(tickers), chunk_size):
    chunk = tickers[i:i+chunk_size]
    try:
        data = yf.download(chunk, period="2y", interval="1d", group_by="ticker", progress=False, session=session)
        if isinstance(data.columns, pd.MultiIndex):
            for ticker in chunk:
                if ticker in data.columns.levels[0]:
                    df_single = data[ticker].dropna(subset=['Close'])
                    if not df_single.empty:
                        bulk_data[ticker] = df_single
        else:
            for ticker in chunk:
                df_single = data.dropna(subset=['Close'])
                if not df_single.empty:
                    bulk_data[ticker] = df_single
    except Exception as e:
        print(f" -> ブロック取得エラー: {e}")

# 3. 判定および採点ロジック関数
def evaluate_logic(df_temp, short_window, long_window, market_type):
    df_temp = df_temp.copy()
    if isinstance(df_temp.columns, pd.MultiIndex):
        df_temp.columns = df_temp.columns.get_level_values(0)
        
    df_temp['short_ma'] = df_temp['Close'].rolling(window=short_window).mean()
    df_temp['long_ma'] = df_temp['Close'].rolling(window=long_window).mean()
    df_temp = df_temp.dropna(subset=['short_ma', 'long_ma']).reset_index(drop=True)
    
    if len(df_temp) < 45:
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
    
    # 買い4
    if diff_rate <= oversold_threshold:
        if is_yang_candle or is_price_up:
            category = "BUY4"
            category_name = "買い4：逆張りリバ"
            badge_class = "bg-purple-500/15 text-purple-300 border border-purple-500/30"
            reason = f"{long_window}日移動平均線({long_ma_today:,.0f}円)から下方に大きく乖離({diff_rate:.1f}%)。本日反発の兆候が確認されました。{warning_suffix}"

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
        reason = f"価格が、横這い〜上向きの長期線({long_window}日線: {long_ma_today:,.0f}円)を上抜けたゴールデンクロス初動です(乖離率 +{diff_rate:.1f}%)。"

    # 買い2
    is_long_ma_rising = long_ma_slope_10d > 0 and (long_ma_today > long_ma_yesterday)
    below_count_10d = (df_temp.iloc[-11:-1]['Close'] < df_temp.iloc[-11:-1]['long_ma']).sum()
    is_temp_dip = 1 <= below_count_10d <= 4
    recovered_above = (price_yesterday < long_ma_yesterday) and (price_today >= long_ma_today)
    
    if category == "NONE" and is_long_ma_rising and is_temp_dip and recovered_above and (0.0 <= diff_rate <= 5.0):
        category = "BUY2"
        category_name = "買い2：再突き抜け"
        badge_class = "bg-sky-500/15 text-sky-300 border border-sky-500/30"
        reason = f"上昇トレンドの中、長期線({long_window}日線)を一時下抜け後に回復した押し目ポイントです(乖離率 +{diff_rate:.1f}%)。"

    # 買い3（※記述エラーを完全に除去しました）
    is_long_ma_rising_strong = long_ma_slope_15d > 0
    max_diff_15d = ((df_temp.iloc[-16:-1]['Close'] - df_temp.iloc[-16:-1]['long_ma']) / df_temp.iloc[-16:-1]['long_ma'] * 100).max()
    has_pulled_back = max_diff_15d >= 4.0
    is_close_to_ma = 0.0 < diff_rate <= 3.5
    is_rebound = is_yang_candle and is_price_up
    
    if category == "NONE" and is_long_ma_rising_strong and has_pulled_back and is_close_to_ma and is_rebound:
        category = "BUY3"
        category_name = "買い3：押し目反発"
        badge_class = "bg-amber-500/15 text-amber-300 border border-amber-500/30"
        reason = f"上昇トレンドの中、一度大きく上昇した株価が長期線({long_window}日線: {long_ma_today:,.0f}円)の手前まで押し、本日反発しました(乖離率 +{diff_rate:.1f}%)。"

    # 期待度評価（星3からスタート）
    score = 3
    if category != "NONE":
        if vol_ratio >= 1.5: score += 1
        if category != "BUY4" and upper_shadow_pct >= 40.0: score -= 1
        if category == "BUY1":
            if is_slope_strong_relative: score += 1
            if candle_body_pct < 0.5: score -= 1
        elif category == "BUY2":
            if is_slope_strong_relative: score += 1
        elif category == "BUY3":
            if diff_rate <= 1.5: score += 1
            if candle_body_pct < 1.0: score -= 1
        elif category == "BUY4":
            if candle_body_pct >= 3.0: score += 1
            if candle_body_pct < 0.5: score -= 1
            
    score = max(1, min(5, score))
    stars_str = "★" * score + "☆" * (5 - score)

    return {
        "category": category,
        "categoryName": category_name,
        "badgeClass": badge_class,
        "diffRate": diff_rate,
        "reason": reason,
        "ma_short": round(short_ma_today, 1),
        "ma_long": round(long_ma_today, 1),
        "score": int(score),
        "stars": stars_str
    }

# 5. 全データの判定実行
results_list = []
print("判定ロジックを実行しています...")

for ticker, df_stock in bulk_data.items():
    if df_stock.empty or len(df_stock) < 130:
        continue
        
    today = df_stock.iloc[-1]
    yesterday = df_stock.iloc[-2]
    
    price_today = float(today['Close'])
    price_yesterday = float(yesterday['Close'])
    change = price_today - price_yesterday
    change_rate = (change / price_yesterday) * 100
    
    # 市場マッピング
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
        "ticker": ticker.replace(".T", ""),
        "name": ticker_to_name.get(ticker, "不明な銘柄"),
        "market": market_short,
        "sector": ticker_to_sector.get(ticker, "不明"),
        "price": price_today,
        "change": change,
        "changeRate": round(change_rate, 2),
        "short": short_res,
        "mid": mid_res
    }
    results_list.append(stock_info)

json_data_str = json.dumps(results_list, ensure_ascii=False, indent=2)

form_cat_str = json.dumps(FORM_CONFIG_CAT, ensure_ascii=False)
form_score_str = json.dumps(FORM_CONFIG_SCORE, ensure_ascii=False)

# 報告ボタン順序(期待度 ➔ 判定カテゴリ)修正済みテンプレート
html_template = """<!doctype html>
<html lang="ja">
  <head>
    <meta charset="UTF-8" />
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
              グランビル法則スクリーナー
              <span class="text-[10px] sm:text-xs px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-mono font-normal">PRO v3.7_FULL_FEEDBACK</span>
            </h1>
            <p class="text-xs text-slate-400 hidden sm:block">東証3市場（プライム・スタンダード・グロース）自動解析・高精度ロジック（最終更新：__LAST_UPDATE__）</p>
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
      
      <!-- サマリーカード -->
      <section class="grid grid-cols-2 md:grid-cols-5 gap-4">
        <div class="bg-slate-900/80 border border-slate-800 rounded-xl p-4 flex flex-col justify-between shadow-lg">
          <span class="text-[11px] font-bold text-slate-400 uppercase tracking-wider">東証判定対象数</span>
          <div class="flex items-baseline gap-2 mt-2">
            <span id="statTotal" class="text-2xl font-bold text-white">0</span>
            <span class="text-xs text-slate-500">銘柄 (P•S•G)</span>
          </div>
        </div>
        <div class="bg-slate-900/80 border border-emerald-500/20 rounded-xl p-4 flex flex-col justify-between shadow-lg">
          <span class="text-[11px] font-bold text-emerald-400 uppercase tracking-wider">買い1 (新規ゴールデン)</span>
          <span id="statBuy1" class="text-2xl font-bold text-emerald-400 mt-2">0</span>
        </div>
        <div class="bg-slate-900/80 border border-sky-500/20 rounded-xl p-4 flex flex-col justify-between shadow-lg">
          <span class="text-[11px] font-bold text-sky-400 uppercase tracking-wider">買い2 (一時下抜け復帰)</span>
          <span id="statBuy2" class="text-2xl font-bold text-sky-400 mt-2">0</span>
        </div>
        <div class="bg-slate-900/80 border border-amber-500/20 rounded-xl p-4 flex flex-col justify-between shadow-lg">
          <span class="text-[11px] font-bold text-amber-400 uppercase tracking-wider">買い3 (サポート反発)</span>
          <span id="statBuy3" class="text-2xl font-bold text-amber-400 mt-2">0</span>
        </div>
        <div class="bg-slate-900/80 border border-purple-500/20 rounded-xl p-4 flex flex-col justify-between shadow-lg">
          <span class="text-[11px] font-bold text-purple-400 uppercase tracking-wider">買い4 (下方乖離リバ)</span>
          <span id="statBuy4" class="text-2xl font-bold text-purple-400 mt-2">0</span>
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
              <button data-market="東Ｐ" class="market-btn px-3 py-1.5 rounded-lg font-medium text-slate-400 hover:text-slate-100 cursor-pointer">東Ｐ (プライム)</button>
              <button data-market="東Ｓ" class="market-btn px-3 py-1.5 rounded-lg font-medium text-slate-400 hover:text-slate-100 cursor-pointer">東Ｓ (スタンダード)</button>
              <button data-market="東Ｇ" class="market-btn px-3 py-1.5 rounded-lg font-medium text-slate-400 hover:text-slate-100 cursor-pointer">東Ｇ (グロース)</button>
            </div>
          </div>

          <!-- 検索 ＆ エクスポート ＆ 解説トグルスイッチ -->
          <div class="flex items-center gap-3 w-full xl:w-auto">
            <div class="relative flex-1 xl:w-72">
              <input type="text" id="searchInput" placeholder="コード、銘柄名、業種で検索..." class="w-full bg-slate-950 border border-slate-800 rounded-xl pl-8 pr-3 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500 transition">
              <span class="absolute left-2.5 top-2 text-slate-500 text-xs">🔍</span>
            </div>
            
            <button id="btnToggleExplanation" class="bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 px-4 py-1.5 rounded-xl text-xs font-bold transition duration-200 cursor-pointer">
              📖 解説を表示
            </button>
            
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
                <th class="p-3 w-32">判定カテゴリ</th>
                <th class="p-3 cursor-pointer select-none hover:text-cyan-400 text-center w-28 whitespace-nowrap transition duration-200" id="thScore" title="クリックで期待度順に並び替え">
                  <div class="flex items-center justify-center gap-1.5">
                    <span>期待度</span>
                    <span id="sortScoreIcon" class="text-cyan-400 font-mono text-[11px] w-3 text-center">↕</span>
                  </div>
                </th>
                <th class="p-3 w-28">コード</th>
                <th class="p-3 min-w-[200px]">銘柄名 / 業種</th>
                <th class="p-3 cursor-pointer select-none hover:text-cyan-400 transition duration-200 whitespace-nowrap" id="thPrice" title="クリックで昇順/降順並び替え">
                  <div class="flex items-center justify-end gap-1.5">
                    <span>株価</span>
                    <span id="sortIcon" class="text-cyan-400 font-mono text-[11px] w-3 text-center">↕</span>
                  </div>
                </th>
                <th class="p-3 text-right">前日比</th>
                <th class="p-3 text-right w-44" id="thma">5日線 / 25日線</th>
                <th class="p-3 text-right w-20">乖離率</th>
                <th class="p-3 text-center w-20">市場</th>
                <th class="p-3 text-center w-32">改善報告</th>
                <th class="p-3">判定理由</th>
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
                <span class="font-bold text-slate-200 block mb-1">買い1：新規買い初動</span>
                <p class="text-slate-300 text-[11px] leading-relaxed">
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
                <span class="font-bold text-slate-200 block mb-1">買い3：押し目反発</span>
                <p class="text-slate-400 text-[11px] leading-relaxed">
                  ・長期線(<span class="exp-long"></span>)が右肩上がり<br>
                  ・調整: 過去15日以内に長期線から <span class="font-mono">+4.0%</span> 以上上に離れた山を作っていること<br>
                  ・反発: 長期線のすぐ上(<span class="font-mono">0.0%〜+3.5%</span>)で本日「前日比プラス」かつ「陽線」反発
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
        if (state.activeTab !== 'ALL') filtered = filtered.filter(r => r[sys].category === state.activeTab);
        if (state.activeMarket !== 'ALL') filtered = filtered.filter(r => r.market === state.activeMarket);
        if (state.searchQuery) {
          filtered = filtered.filter(r => r.ticker.includes(state.searchQuery) || r.name.toLowerCase().includes(state.searchQuery) || r.sector.toLowerCase().includes(state.searchQuery));
        }
        if (filtered.length === 0) {
          alert("出力対象のデータがありません。");
          return;
        }
        let csvContent = "\\uFEFF";
        csvContent += "カテゴリ,期待度スコア,証券コード,銘柄名,株価,前日比,前日比率,市場,業種,判定理由\\r\\n";
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
            `"${item.market}"`,
            `"${item.sector}"`,
            `"${sysData.reason.replace(/"/g, '""')}"`
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

      function updateStats() {
        const counts = { BUY1: 0, BUY2: 0, BUY3: 0, BUY4: 0 };
        const sys = state.currentSystem;
        state.results.forEach(r => {
          const cat = r[sys].category;
          if (counts[cat] !== undefined) counts[cat]++;
        });
        document.getElementById('statBuy1').textContent = counts.BUY1;
        document.getElementById('statBuy2').textContent = counts.BUY2;
        document.getElementById('statBuy3').textContent = counts.BUY3;
        document.getElementById('statBuy4').textContent = counts.BUY4;
        document.getElementById('statTotal').textContent = state.results.length;
        const labels = { ALL: 'すべて', BUY1: '買い1', BUY2: '買い2', BUY3: '買い3', BUY4: '買い4', NONE: '条件外' };
        document.querySelectorAll('.tab-btn').forEach(btn => {
          const t = btn.dataset.tab;
          const count = (t === 'ALL') ? state.results.length : state.results.filter(r => r[sys].category === t).length;
          btn.textContent = `${labels[t]} (${count})`;
        });
      }

      function renderTable() {
        const tbody = document.getElementById('resultTableBody');
        tbody.innerHTML = '';
        const sys = state.currentSystem;
        let filtered = [...state.results];
        if (state.activeTab !== 'ALL') filtered = filtered.filter(r => r[sys].category === state.activeTab);
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
            <td colspan="11" class="py-14 text-center text-slate-500">
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

          // ★【並び替え対応】左に「期待度」、右に「判定」の報告ボタンを並び替え
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
              <div class="font-bold text-slate-100 text-sm">${item.name}</div>
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
            
            <!-- ★【並び替え対応】左に「期待度」、右に「判定」の報告ボタンを並び替え -->
            <td class="p-3 text-center space-x-1 whitespace-nowrap">
              <button onclick="openScoreFeedback('${item.ticker}', '${item.name}', '${sysData.score}')" class="px-2 py-1 bg-slate-800 hover:bg-amber-600 text-slate-300 hover:text-white rounded border border-slate-700 text-[10px] font-bold transition duration-200 cursor-pointer" title="期待度スコアの妥当性に対して報告">
                ⭐ 期待度
              </button>
              <button onclick="openCatFeedback('${item.ticker}', '${item.name}', '${categoryShortName}')" class="px-2 py-1 bg-slate-800 hover:bg-emerald-600 text-slate-300 hover:text-white rounded border border-slate-700 text-[10px] font-bold transition duration-200 cursor-pointer" title="シグナルの判定カテゴリに対して報告">
                ✍️ 判定
              </button>
            </td>
            
            <td class="p-3 text-slate-300">${sysData.reason}</td>
          `;
          tbody.appendChild(tr);
        });
      }
    </script>
  </body>
</html>"""

# HTML置換と書き込み
html_content = html_template.replace("/* PLACEHOLDER_RESULTS */ []", json_data_str)
html_content = html_content.replace("/* PLACEHOLDER_FORM_CAT */ {}", form_cat_str)
html_content = html_content.replace("/* PLACEHOLDER_FORM_SCORE */ {}", form_score_str)

with open(html_output_path, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"自動更新刻印「{current_time_str}」入りHTMLを index.html として上書き書き出し完了しました！")
