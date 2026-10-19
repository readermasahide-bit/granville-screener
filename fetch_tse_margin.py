# ==========================================
# fetch_tse_margin.py
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
JPX_MARGIN_PAGE = "https://www.jpx.co.jp/markets/statistics-equities/margin/04.html"

def get_latest_pdf_url():
    """JPXのWebページから最新の信用取引残高PDF(mtall.pdf)のURLを検出"""
    try:
        res = requests.get(JPX_MARGIN_PAGE, headers=HEADERS, timeout=15)
        if res.status_code != 200:
            # トップページ側もフォールバック探索
            res = requests.get("https://www.jpx.co.jp/markets/statistics-equities/margin/index.html", headers=HEADERS, timeout=15)
            
        if res.status_code == 200:
            # 例: /markets/statistics-equities/margin/tvdivq0000001rnl-att/20261016_mtall.pdf
            match = re.search(r'href=["\']([^"\']*?(\d{8})_mtall\.pdf)["\']', res.text, re.IGNORECASE)
            if match:
                link = match.group(1)
                full_url = link if link.startswith('http') else requests.compat.urljoin(JPX_MARGIN_PAGE, link)
                date_str = match.group(2)
                return full_url, date_str
    except Exception as e:
        print(f"⚠️ PDFリンク探索中にエラー: {e}")
    return None, None

def parse_num(s):
    """カンマ区切り文字列を数値に変換（△や▲はマイナス）"""
    if not s or s == '-':
        return 0
    s_clean = s.replace(',', '').replace('△', '-').replace('▲', '-').strip()
    try:
        return int(float(s_clean))
    except ValueError:
        return 0

def parse_tse_margin_pdf(pdf_bytes):
    """PyMuPDFを用いて全ページから銘柄別信用買残・売残を抽出"""
    margin_dict = {}
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(doc)
    
    # 銘柄行の正規表現パターン:
    # 5桁コード(末尾0) + JP番号 + "株数" または "Shs." が含まれる行を検出
    # 例: B. 極洋 普通株式 プライム 貸 13010 JP3257200000 株数 Shs. 9,400 △ 100 0.1% 158,800 △ 3,800 ...
    line_pattern = re.compile(r'(\d{4})0\s+JP[A-Z0-9]{10}\s+株数\s+Shs\.(.+)', re.DOTALL)
    
    for page_idx in range(total_pages):
        page = doc[page_idx]
        text = page.get_text("text")
        lines = text.split('\n')
        
        # 1行ずつ走査
        for line in lines:
            line = line.strip()
            if "株数" not in line or "Shs." not in line:
                continue
                
            m = line_pattern.search(line)
            if not m:
                # 複数スペースやタブ等で分かれている場合のフォールバック抽出
                parts = line.split()
                try:
                    # 5桁コードを探す
                    code_idx = -1
                    for idx, part in enumerate(parts):
                        if len(part) == 5 and part.isdigit() and part.endswith('0'):
                            code_idx = idx
                            break
                    if code_idx != -1:
                        code_4digit = parts[code_idx][:4]
                        # "Shs." の後ろにある数値を順番に取得
                        shs_idx = parts.index("Shs.") if "Shs." in parts else -1
                        if shs_idx != -1:
                            val_tokens = parts[shs_idx + 1:]
                            # 数字と思われるトークン（カンマ区切り等）を抽出
                            nums = []
                            for tok in val_tokens:
                                tok_clean = tok.replace(',', '').replace('△', '').replace('▲', '').replace('%', '').strip()
                                if tok_clean.replace('.', '', 1).isdigit():
                                    nums.append(tok)
                            # numsの並び: [売残高, 前日比, 上場比(%), 買残高, 前日比, ...]
                            if len(nums) >= 4:
                                sell_bal = parse_num(nums[0])
                                buy_bal = parse_num(nums[3])
                                ratio = round(buy_bal / sell_bal, 2) if sell_bal > 0 else 999.0
                                margin_dict[code_4digit] = {
                                    "buy_balance": buy_bal,
                                    "sell_balance": sell_bal,
                                    "ratio": ratio
                                }
                except Exception:
                    continue
            else:
                # 正規表現マッチ時の抽出
                code_4digit = m.group(1)
                tail_str = m.group(2).strip()
                tokens = tail_str.split()
                nums = []
                for tok in tokens:
                    tok_clean = tok.replace(',', '').replace('△', '').replace('▲', '').replace('%', '').strip()
                    if tok_clean.replace('.', '', 1).isdigit():
                        nums.append(tok)
                if len(nums) >= 4:
                    sell_bal = parse_num(nums[0])
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
        # 1,000銘柄以上抽出できていれば正常と判定して保存
        output_payload = {
            "date": date_str,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "data": margin_dict
        }
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(output_payload, f, ensure_ascii=False, indent=2)
        print(f"✅ {OUTPUT_JSON} に最新信用残高データを正常保存しました。")
    else:
        print(f"⚠️ 抽出銘柄数が少なすぎます ({len(margin_dict)}件)。フォーマット検証のため保存をスキップします。")

    print(f"総所要時間: {time.time() - start_time:.2f}秒\n")

if __name__ == "__main__":
    main()
