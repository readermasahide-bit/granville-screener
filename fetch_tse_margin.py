# ==========================================
# fetch_tse_margin.py (確定版)
# 東証日次PDF自動取得 & 前日比抽出 & 過去5営業日履歴蓄積
# ==========================================

import os
import re
import json
import time
import requests
import pymupdf as fitz  # 非推奨警告を解消

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

DATA_DIR = "data"
OUTPUT_JSON = os.path.join(DATA_DIR, "tse_margin.json")
HISTORY_JSON = os.path.join(DATA_DIR, "tse_margin_history.json")
MAX_HISTORY_DAYS = 5  # 保持する最大営業日数

def get_latest_pdf_url():
    """JPXのWebページから最新の信用取引残高PDF(mtall.pdf)のURLを検出"""
    candidate_pages = [
        "https://www.jpx.co.jp/markets/statistics-equities/margin/01.html",
        "https://www.jpx.co.jp/markets/statistics-equities/margin/index.html"
    ]
    
    for page_url in candidate_pages:
        try:
            print(f" -> 探索中: {page_url}")
            res = requests.get(page_url, headers=HEADERS, timeout=15)
            if res.status_code != 200:
                continue
            
            links = re.findall(r'href=["\']([^"\']+\.pdf)["\']', res.text, re.IGNORECASE)
            target_link = None
            for l in links:
                if 'mtall' in l.lower():
                    target_link = l
                    break
            if not target_link and links:
                target_link = links[0]
                
            if target_link:
                full_url = requests.compat.urljoin(page_url, target_link)
                date_match = re.search(r'(\d{8})', target_link)
                date_str = date_match.group(1) if date_match else "latest"
                return full_url, date_str
        except Exception as e:
            print(f"⚠️ {page_url} の取得中にエラー: {e}")
            
    return None, None

def parse_num_token(token):
    """カンマや記号をクレンジングして絶対値を返す"""
    if not token or token == '-':
        return 0
    clean = token.replace(',', '').replace('△', '').replace('▲', '').replace('-', '').replace('%', '').strip()
    try:
        return int(float(clean))
    except ValueError:
        return 0

def parse_signed_diff(tokens, val_idx):
    """
    数値トークンの前または自身に '△' / '▲' があればマイナス値として返す
    JPXの仕様: △ または ▲ は前日比マイナス（減少）
    """
    if val_idx >= len(tokens):
        return 0
    curr_tok = tokens[val_idx]
    raw_val = parse_num_token(curr_tok)
    
    # 自身に △/▲ が含まれている場合
    if '△' in curr_tok or '▲' in curr_tok:
        return -raw_val
        
    # 前のトークンが単独の △/▲ だった場合
    if val_idx > 0:
        prev_tok = tokens[val_idx - 1].strip()
        if prev_tok in ['△', '▲', '-']:
            return -raw_val
            
    return raw_val

def parse_tse_margin_pdf(pdf_bytes):
    """PyMuPDFを用いて全ページから銘柄別信用残高および前日比を抽出"""
    margin_dict = {}
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(doc)
    
    pattern = re.compile(
        r'(\d{4})0\s+JP[A-Z0-9]{10}\s+株数\s+Shs\.\s+(.+?)(?=(?:\d{4}0\s+JP|\Z))',
        re.DOTALL
    )
    
    for page_idx in range(total_pages):
        page = doc[page_idx]
        text = page.get_text("text")
        
        for m in pattern.finditer(text):
            code_4digit = m.group(1)
            tail_text = m.group(2)
            
            tokens = tail_text.split()
            # 金額行(Val.)の手前までを株数列として抽出
            stock_tokens = []
            for tok in tokens:
                if "金額" in tok or "Val." in tok:
                    break
                stock_tokens.append(tok)
            
            # 数値または符号トークンのインデックスを特定
            num_indices = []
            for idx, tok in enumerate(stock_tokens):
                tok_c = tok.replace(',', '').replace('△', '').replace('▲', '').replace('%', '').strip()
                if tok_c.isdigit():
                    num_indices.append(idx)
            
            # 列並び: [0:売残高, 1:売前日比, 2:買残高, 3:買前日比, ...]
            if len(num_indices) >= 4:
                sell_idx = num_indices[0]
                diff_sell_idx = num_indices[1]
                buy_idx = num_indices[2]
                diff_buy_idx = num_indices[3]
                
                sell_bal = parse_num_token(stock_tokens[sell_idx])
                diff_sell = parse_signed_diff(stock_tokens, diff_sell_idx)
                
                buy_bal = parse_num_token(stock_tokens[buy_idx])
                diff_buy = parse_signed_diff(stock_tokens, diff_buy_idx)
                
                ratio = round(buy_bal / sell_bal, 2) if sell_bal > 0 else 999.0
                
                margin_dict[code_4digit] = {
                    "buy_balance": buy_bal,
                    "sell_balance": sell_bal,
                    "diff_buy": diff_buy,      # プラス=増加, マイナス=減少
                    "diff_sell": diff_sell,    # プラス=増加, マイナス=減少
                    "ratio": ratio
                }
                    
    doc.close()
    return margin_dict

def update_history_json(date_str, current_data):
    """過去5営業日分のスナップショットを蓄積保存"""
    history = {}
    if os.path.exists(HISTORY_JSON):
        try:
            with open(HISTORY_JSON, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = {}
            
    history[date_str] = current_data
    
    # 日付降順でソートし、最新5営業日のみ保持
    sorted_dates = sorted(history.keys(), reverse=True)[:MAX_HISTORY_DAYS]
    trimmed_history = {d: history[d] for d in sorted_dates}
    
    with open(HISTORY_JSON, "w", encoding="utf-8") as f:
        json.dump(trimmed_history, f, ensure_ascii=False)
    print(f"✅ {HISTORY_JSON} に履歴を更新保存しました (保持日数: {len(trimmed_history)}日分: {', '.join(sorted_dates)})")

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    print("JPXから東証日次信用取引残高PDFを探索中...")
    start_time = time.time()
    
    pdf_url, date_str = get_latest_pdf_url()
    if not pdf_url:
        print("⚠️ 東証信用残高PDFのURLが特定できませんでした。既存キャッシュを保持します。")
        return

    print(f" -> 最新PDF検出: 日付={date_str}, URL={pdf_url}")
    print(" -> PDFダウンロード中...")
    try:
        res = requests.get(pdf_url, headers=HEADERS, timeout=30)
        res.raise_for_status()
        pdf_bytes = res.content
        print(f" -> ダウンロード完了 ({len(pdf_bytes) / 1024 / 1024:.2f} MB)")
    except Exception as e:
        print(f"⚠️ PDFダウンロード失敗: {e}。既存キャッシュを保持します。")
        return

    print(" -> PyMuPDFで解析中...")
    parse_start = time.time()
    margin_dict = parse_tse_margin_pdf(pdf_bytes)
    parse_elapsed = time.time() - parse_start
    print(f" -> 解析完了: {len(margin_dict)} 銘柄を抽出 (解析所要時間: {parse_elapsed:.2f}秒)")

    if len(margin_dict) > 1000:
        output_payload = {
            "date": date_str,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "data": margin_dict
        }
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(output_payload, f, ensure_ascii=False, indent=2)
        print(f"✅ {OUTPUT_JSON} に最新信用残高データを正常保存しました。")
        
        # 履歴データの蓄積保存を実行
        update_history_json(date_str, margin_dict)
    else:
        print(f"⚠️ 抽出銘柄数が少なすぎます ({len(margin_dict)}件)。保存をスキップします。")

    print(f"総所要時間: {time.time() - start_time:.2f}秒\n")

if __name__ == "__main__":
    main()
