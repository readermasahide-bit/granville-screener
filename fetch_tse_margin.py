# ==========================================
# fetch_tse_margin.py (修正版)
# 東証日次PDF (銘柄別信用取引残高) 自動取得 & PyMuPDF爆速パーサー
# ==========================================

import os
import re
import json
import time
import requests
import fitz  # PyMuPDF

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

DATA_DIR = "data"
OUTPUT_JSON = os.path.join(DATA_DIR, "tse_margin.json")

def get_latest_pdf_url():
    """JPXのWebページから最新の信用取引残高PDF(mtall.pdf)のURLを検出"""
    # 個別銘柄の信用取引残高は 01.html
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
            
            # ページ内の全PDFリンクを抽出
            links = re.findall(r'href=["\']([^"\']+\.pdf)["\']', res.text, re.IGNORECASE)
            print(f"    検出されたPDFリンク総数: {len(links)}")
            
            # mtall を含むリンクを優先
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

def parse_num(s):
    """カンマ区切り文字列を数値に変換"""
    if not s or s == '-':
        return 0
    s_clean = s.replace(',', '').replace('△', '').replace('▲', '').replace('-', '').strip()
    try:
        return int(float(s_clean))
    except ValueError:
        return 0

def parse_tse_margin_pdf(pdf_bytes):
    """PyMuPDFを用いて全ページから銘柄別信用買残・売残を抽出"""
    margin_dict = {}
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(doc)
    
    # 5桁コード(末尾0) + JP番号 + 株数 Shs. の後続テキストを柔軟に抽出
    # 改行(\n)が含まれていても対応できるよう \s+ を使用
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
            
            # トークンに分解
            tokens = tail_text.split()
            # カンマ入りまたは純粋な数字のトークンを順番に抽出
            nums = []
            for tok in tokens:
                # 金額行や不要な記号の前の「株数列」を抽出
                if "金額" in tok or "Val." in tok:
                    break
                tok_clean = tok.replace(',', '').replace('△', '').replace('▲', '').replace('%', '').strip()
                if tok_clean.isdigit():
                    nums.append(tok)
            
            # 列並び: [売残高, 前日比, 買残高, 前日比, 一般売, 制度売, 一般買, 制度買]
            if len(nums) >= 3:
                sell_bal = parse_num(nums[0])
                # 前日比の「△」が独立トークンになる場合があるため調整
                buy_bal = parse_num(nums[2]) if len(nums) >= 3 else 0
                if len(nums) >= 4 and parse_num(nums[1]) == 0 and nums[1] in ['△', '▲']:
                    # 符号が分離していた場合のシフト
                    buy_bal = parse_num(nums[3])
                
                ratio = round(buy_bal / sell_bal, 2) if sell_bal > 0 else 999.0
                margin_dict[code_4digit] = {
                    "buy_balance": buy_bal,
                    "sell_balance": sell_bal,
                    "ratio": ratio
                }
                    
    doc.close()
    return margin_dict

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
    else:
        print(f"⚠️ 抽出銘柄数が少なすぎます ({len(margin_dict)}件)。保存をスキップします。")

    print(f"総所要時間: {time.time() - start_time:.2f}秒\n")

if __name__ == "__main__":
    main()
