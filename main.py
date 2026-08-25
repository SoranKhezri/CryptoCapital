"""
Crypto Capital Rotation Radar - Python Edition
شبیه‌سازی اندیکاتور Pine Script با داده‌ی لایو از CoinGecko
و ارسال خروجی تصویری به تلگرام
"""

import os
import io
import json
import time
import requests
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFont

# ============================================================
# CONFIG
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "")  # اختیاری

TOP_N_UNIVERSE = 150   # تعداد کوین‌هایی که از CoinGecko می‌گیریم
TOP_N_DISPLAY = 30     # تعداد کوینی که در جدول نهایی نشون می‌دیم

# وزن‌های امتیازدهی (دقیقاً مثل نسخه‌ی Pine)
W_DOM = 30.0
W_MOMENTUM = 25.0
W_RELATIVE = 25.0
W_ACCELERATION = 20.0

STRONG_INFLOW = 80.0
INFLOW = 65.0
OUTFLOW = 35.0
STRONG_OUTFLOW = 20.0   # بهبود اضافه‌شده نسبت به نسخه‌ی اصلی Pine

# کوین‌هایی که از رتبه‌بندی آلت‌کوین حذف می‌شن (استیبل‌کوین‌ها و توکن‌های wrapped)
EXCLUDED_SYMBOLS = {
    "usdt", "usdc", "dai", "busd", "tusd", "usdd", "fdusd", "pyusd",
    "usde", "frax", "gusd", "usdp", "eurs", "eurt",
    "wbtc", "weth", "wsteth", "steth", "weeth", "cbbtc",
    "reth", "meth", "wbeth", "beth"
}

DATA_FILE = "data/previous_scores.json"

# ============================================================
# COLOR PALETTE (هماهنگ با تم تاریک اندیکاتور اصلی)
# ============================================================

COL_BG_MAIN = (5, 10, 20)
COL_HEADER = (9, 18, 36)
COL_PANEL = (10, 18, 32)
COL_PANEL_ALT = (13, 23, 40)
COL_GOLD = (235, 190, 75)
COL_BULL = (0, 220, 155)
COL_BEAR = (245, 75, 90)
COL_BLUE = (70, 155, 255)
COL_NEUTRAL = (155, 165, 185)
COL_WHITE = (232, 237, 245)
COL_BORDER = (28, 43, 69)

# ============================================================
# COINGECKO REQUESTS
# ============================================================

def cg_headers():
    headers = {"User-Agent": "CapitalRotationRadar/1.0"}
    if COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = COINGECKO_API_KEY
    return headers


def fetch_market_data():
    """گرفتن دیتای بازار برای TOP_N_UNIVERSE کوین در یک درخواست"""
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": TOP_N_UNIVERSE,
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "1h,24h,7d,14d,30d"
    }
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=cg_headers(), timeout=20)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"تلاش {attempt+1} ناموفق: {e}")
            time.sleep(5)
    raise RuntimeError("دریافت داده از CoinGecko ناموفق بود")


def fetch_usdt_history():
    """
    دریافت مارکت‌کپ واقعی USDT در گذشته (نه بر پایه‌ی قیمت، چون قیمت تتر تقریباً ثابته
    و تغییرات دامیننس تتر بیشتر ناشی از چاپ/سوزوندن است نه قیمت)
    """
    url = "https://api.coingecko.com/api/v3/coins/tether/market_chart"
    params = {"vs_currency": "usd", "days": 8, "interval": "daily"}
    try:
        r = requests.get(url, params=params, headers=cg_headers(), timeout=20)
        r.raise_for_status()
        data = r.json()
        caps = data.get("market_caps", [])
        if len(caps) >= 2:
            main_past = caps[0][1]        # ~۷-۸ روز قبل
            short_past = caps[-2][1]      # ~۱ روز قبل
            return main_past, short_past
    except Exception as e:
        print(f"خطا در دریافت تاریخچه‌ی USDT: {e}")
    return None, None


# ============================================================
# MATH HELPERS
# ============================================================

def normalize(value, min_v, max_v):
    if value is None:
        return None
    v = max(min_v, min(max_v, value))
    return (v - min_v) / (max_v - min_v) * 100.0


def past_cap(current_cap, pct_change):
    """تخمین مارکت‌کپ گذشته بر اساس درصد تغییر قیمت (فرض: عرضه‌ی گردشی تقریباً ثابت)"""
    if current_cap is None or pct_change is None:
        return None
    return current_cap / (1 + pct_change / 100.0)


def safe(v, default=0.0):
    return default if v is None else v


# ============================================================
# FETCH & PROCESS
# ============================================================

print("در حال دریافت داده از CoinGecko ...")
raw_coins = fetch_market_data()
usdt_main_past, usdt_short_past = fetch_usdt_history()

# ------ ساخت TOTAL و مشتقاتش ------

total_now = sum(safe(c.get("market_cap")) for c in raw_coins)
total_main_past = sum(
    safe(past_cap(c.get("market_cap"), c.get("price_change_percentage_7d_in_currency")))
    for c in raw_coins
)
total_short_past = sum(
    safe(past_cap(c.get("market_cap"), c.get("price_change_percentage_24h_in_currency")))
    for c in raw_coins
)

btc = next((c for c in raw_coins if c["id"] == "bitcoin"), None)
eth = next((c for c in raw_coins if c["id"] == "ethereum"), None)
usdt = next((c for c in raw_coins if c["id"] == "tether"), None)

btc_cap_now = safe(btc.get("market_cap")) if btc else 0
btc_cap_main_past = safe(past_cap(btc_cap_now, btc.get("price_change_percentage_7d_in_currency"))) if btc else 0

eth_cap_now = safe(eth.get("market_cap")) if eth else 0
eth_cap_main_past = safe(past_cap(eth_cap_now, eth.get("price_change_percentage_7d_in_currency"))) if eth else 0

usdt_cap_now = safe(usdt.get("market_cap")) if usdt else 0

top10_sum_now = sum(safe(c.get("market_cap")) for c in raw_coins[:10])
top10_sum_main_past = sum(
    safe(past_cap(c.get("market_cap"), c.get("price_change_percentage_7d_in_currency")))
    for c in raw_coins[:10]
)

def pct_change(now, past):
    if now is None or past is None or past == 0:
        return None
    return (now / past - 1.0) * 100.0

total_momentum = pct_change(total_now, total_main_past)
total2_now = total_now - btc_cap_now
total2_main_past = total_main_past - btc_cap_main_past
total2_momentum = pct_change(total2_now, total2_main_past)

total3_now = total2_now - eth_cap_now
total3_main_past = total2_main_past - eth_cap_main_past
total3_momentum = pct_change(total3_now, total3_main_past)

others_now = total_now - top10_sum_now
others_main_past = total_main_past - top10_sum_main_past
others_momentum = pct_change(others_now, others_main_past)

btc_dom_now = (btc_cap_now / total_now * 100.0) if total_now else None
btc_dom_main_past = (btc_cap_main_past / total_main_past * 100.0) if total_main_past else None
btc_dom_change = (btc_dom_now - btc_dom_main_past) if (btc_dom_now is not None and btc_dom_main_past is not None) else None

if usdt_main_past and usdt_short_past:
    usdt_dom_now = (usdt_cap_now / total_now * 100.0) if total_now else None
    usdt_dom_main_past = (usdt_main_past / total_main_past * 100.0) if total_main_past else None
    usdt_dom_change = (usdt_dom_now - usdt_dom_main_past) if (usdt_dom_now is not None and usdt_dom_main_past is not None) else None
else:
    usdt_dom_now = (usdt_cap_now / total_now * 100.0) if total_now else None
    usdt_dom_change = None

# ------ رژیم بازار ------

risk_off = (usdt_dom_change is not None and total_momentum is not None
            and usdt_dom_change > 0.20 and total_momentum < 0)

broad_alt_rotation = (not risk_off and None not in (total2_momentum, total3_momentum, total_momentum)
                       and total2_momentum > total_momentum and total3_momentum > total2_momentum)

alt_rotation = (not risk_off and None not in (btc_dom_change, total3_momentum, total_momentum)
                and btc_dom_change < 0 and total3_momentum > total_momentum)

btc_rotation = (not risk_off and None not in (btc_dom_change, total3_momentum, total_momentum)
                and btc_dom_change > 0.15 and total3_momentum < total_momentum)

risk_on = (not risk_off and usdt_dom_change is not None and total_momentum is not None
           and usdt_dom_change < -0.15 and total_momentum > 0)

if risk_off:
    regime, regime_desc, regime_color = "RISK OFF", "USDT.D rising while total market weakens", COL_BEAR
elif broad_alt_rotation:
    regime, regime_desc, regime_color = "BROAD ALT ROTATION", "Altcoin market is outperforming BTC", COL_BULL
elif alt_rotation:
    regime, regime_desc, regime_color = "ALTCOIN ROTATION", "Relative strength shifting toward altcoins", COL_BULL
elif btc_rotation:
    regime, regime_desc, regime_color = "BTC ROTATION", "BTC is gaining market share", COL_GOLD
elif risk_on:
    regime, regime_desc, regime_color = "RISK ON", "Liquidity conditions improving", COL_BLUE
else:
    regime, regime_desc, regime_color = "NEUTRAL", "Market structure is balanced", COL_NEUTRAL

# ------ محاسبه‌ی امتیاز برای هر کوین ------

universe = [
    c for c in raw_coins
    if c["id"] not in ("bitcoin", "ethereum")
    and c.get("symbol", "").lower() not in EXCLUDED_SYMBOLS
    and c.get("market_cap") is not None
]

results = []

for c in universe:
    cap_now = c.get("market_cap")
    mom_7d = c.get("price_change_percentage_7d_in_currency")
    mom_24h = c.get("price_change_percentage_24h_in_currency")

    if mom_7d is None or mom_24h is None or cap_now is None:
        continue

    cap_main_past = past_cap(cap_now, mom_7d)
    cap_short_past = past_cap(cap_now, mom_24h)

    if not total_now or not total_main_past or not total_short_past:
        continue

    dominance = cap_now / total_now * 100.0
    dominance_main_past = cap_main_past / total_main_past * 100.0
    dominance_short_past = cap_short_past / total_short_past * 100.0

    dom_change = dominance - dominance_main_past
    short_dom_change = dominance - dominance_short_past

    momentum = mom_7d

    relative_diff = (momentum - total3_momentum) if total3_momentum is not None else None
    relative_score = normalize(relative_diff, -10, 10)

    dom_score = normalize(dom_change, -1, 1)
    momentum_score = normalize(momentum, -10, 10)
    acceleration_score = normalize(short_dom_change - dom_change, -1, 1)

    if None in (dom_score, momentum_score, relative_score, acceleration_score):
        continue

    weight_sum = max(W_DOM + W_MOMENTUM + W_RELATIVE + W_ACCELERATION, 0.0001)
    score = (dom_score * W_DOM + momentum_score * W_MOMENTUM +
             relative_score * W_RELATIVE + acceleration_score * W_ACCELERATION) / weight_sum

    results.append({
        "symbol": c["symbol"].upper(),
        "dominance": dominance,
        "dom_change": dom_change,
        "momentum": momentum,
        "relative": relative_score,
        "acceleration": acceleration_score,
        "score": score,
    })

results.sort(key=lambda x: x["score"], reverse=True)
results = results[:TOP_N_DISPLAY]

for i, r in enumerate(results):
    r["rank"] = i + 1

# ------ مقایسه با اجرای قبلی برای ستون RANK ------

previous_scores = {}
if os.path.exists(DATA_FILE):
    try:
        with open(DATA_FILE, "r") as f:
            previous_scores = json.load(f)
    except Exception:
        previous_scores = {}

for r in results:
    prev_rank = previous_scores.get(r["symbol"], {}).get("rank")
    if prev_rank is None:
        r["rank_change_text"] = "—"
        r["rank_change_dir"] = 0
    elif prev_rank == r["rank"]:
        r["rank_change_text"] = "→"
        r["rank_change_dir"] = 0
    elif prev_rank > r["rank"]:
        r["rank_change_text"] = f"↑{prev_rank - r['rank']}"
        r["rank_change_dir"] = 1
    else:
        r["rank_change_text"] = f"↓{r['rank'] - prev_rank}"
        r["rank_change_dir"] = -1

new_scores_data = {r["symbol"]: {"rank": r["rank"], "score": r["score"]} for r in results}
os.makedirs("data", exist_ok=True)
with open(DATA_FILE, "w") as f:
    json.dump(new_scores_data, f)

# ------ Status هر کوین ------

def get_status(score, dom_change):
    if score >= STRONG_INFLOW and dom_change > 0:
        return "STRONG INFLOW", COL_BULL
    if score >= INFLOW and dom_change >= 0:
        return "INFLOW", (90, 205, 160)
    if score <= STRONG_OUTFLOW:
        return "STRONG OUTFLOW", COL_BEAR
    if score <= OUTFLOW:
        return "OUTFLOW", COL_BEAR
    return "NEUTRAL", COL_NEUTRAL

for r in results:
    r["status"], r["status_color"] = get_status(r["score"], r["dom_change"])

top3 = results[:3]

# ============================================================
# IMAGE GENERATION
# ============================================================

FONT_DIR = "/usr/share/fonts/truetype/dejavu/"
font_bold = ImageFont.truetype(FONT_DIR + "DejaVuSans-Bold.ttf", 16)
font_regular = ImageFont.truetype(FONT_DIR + "DejaVuSans.ttf", 14)
font_small = ImageFont.truetype(FONT_DIR + "DejaVuSans.ttf", 11)
font_title = ImageFont.truetype(FONT_DIR + "DejaVuSans-Bold.ttf", 22)

WIDTH = 900
ROW_H = 32
HEADER_H = 200
TABLE_HEADER_H = 36
FOOTER_H = 30
HEIGHT = HEADER_H + TABLE_HEADER_H + ROW_H * len(results) + FOOTER_H

img = Image.new("RGB", (WIDTH, HEIGHT), COL_BG_MAIN)
draw = ImageDraw.Draw(img)

y = 0

# Title
draw.rectangle([0, y, WIDTH, y + 50], fill=COL_HEADER)
draw.text((WIDTH // 2, y + 25), "◈  CRYPTO CAPITAL ROTATION RADAR  ◈",
          fill=COL_GOLD, font=font_title, anchor="mm")
y += 50

# Regime bar
regime_bg = tuple(min(255, c + 15) for c in COL_BG_MAIN)
draw.rectangle([0, y, WIDTH, y + 34], fill=regime_bg)
draw.text((WIDTH // 2, y + 17), f"◉  {regime}   |   {regime_desc}",
          fill=regime_color, font=font_regular, anchor="mm")
y += 34

# Macro row 1
draw.rectangle([0, y, WIDTH, y + 32], fill=COL_PANEL)
macro_items = [
    ("BTC.D", f"{btc_dom_now:.2f}%" if btc_dom_now else "—", COL_WHITE),
    ("Δ", f"{btc_dom_change:+.2f}%" if btc_dom_change is not None else "—",
     COL_GOLD if (btc_dom_change or 0) >= 0 else COL_BULL),
    ("USDT.D", f"{usdt_dom_now:.2f}%" if usdt_dom_now else "—", COL_WHITE),
    ("Δ", f"{usdt_dom_change:+.2f}%" if usdt_dom_change is not None else "—",
     COL_BEAR if (usdt_dom_change or 0) > 0 else COL_BULL),
    ("TOTAL", f"{total_momentum:+.2f}%" if total_momentum is not None else "—",
     COL_BULL if (total_momentum or 0) >= 0 else COL_BEAR),
]
col_w = WIDTH // len(macro_items)
for i, (label, value, color) in enumerate(macro_items):
    cx = i * col_w + col_w // 2
    draw.text((cx, y + 10), label, fill=COL_GOLD, font=font_small, anchor="mm")
    draw.text((cx, y + 24), value, fill=color, font=font_small, anchor="mm")
y += 32

# Macro row 2
draw.rectangle([0, y, WIDTH, y + 32], fill=COL_PANEL_ALT)
macro_items2 = [
    ("TOTAL2", total2_momentum), ("TOTAL3", total3_momentum), ("OTHERS", others_momentum),
]
col_w2 = WIDTH // len(macro_items2)
for i, (label, value) in enumerate(macro_items2):
    cx = i * col_w2 + col_w2 // 2
    color = COL_BULL if (value or 0) >= 0 else COL_BEAR
    draw.text((cx, y + 10), label, fill=COL_WHITE, font=font_small, anchor="mm")
    draw.text((cx, y + 24), f"{value:+.2f}%" if value is not None else "—", fill=color, font=font_small, anchor="mm")
y += 32

# Top 3
draw.rectangle([0, y, WIDTH, y + 34], fill=(30, 24, 8))
medals = ["🥇", "🥈", "🥉"]
top3_text = "   •   ".join(
    f"{medals[i]} {r['symbol']} {r['score']:.1f}" for i, r in enumerate(top3)
)
draw.text((WIDTH // 2, y + 17), top3_text, fill=COL_GOLD, font=font_regular, anchor="mm")
y += 34

# Table headers
headers = ["#", "COIN", "DOM", "MOM", "REL", "ACC", "SCORE", "POWER", "RANK", "STATUS"]
col_widths = [40, 90, 80, 90, 70, 70, 80, 140, 70, 170]
draw.rectangle([0, y, WIDTH, y + TABLE_HEADER_H], fill=COL_HEADER)
x = 0
for h, w in zip(headers, col_widths):
    draw.text((x + w // 2, y + TABLE_HEADER_H // 2), h, fill=COL_GOLD, font=font_small, anchor="mm")
    x += w
y += TABLE_HEADER_H

# Table rows
for idx, r in enumerate(results):
    row_bg = COL_PANEL if idx % 2 == 0 else COL_PANEL_ALT
    if idx < 3:
        row_bg = (40, 32, 12)
    draw.rectangle([0, y, WIDTH, y + ROW_H], fill=row_bg)

    x = 0
    rank_text = f"{medals[idx]}" if idx < 3 else str(r["rank"])
    draw.text((x + col_widths[0] // 2, y + ROW_H // 2), rank_text, fill=COL_GOLD if idx < 3 else COL_WHITE, font=font_small, anchor="mm")
    x += col_widths[0]

    draw.text((x + 10, y + ROW_H // 2), r["symbol"], fill=COL_WHITE, font=font_regular, anchor="lm")
    x += col_widths[1]

    draw.text((x + col_widths[2] // 2, y + ROW_H // 2), f"{r['dominance']:.2f}%", fill=(190, 200, 215), font=font_small, anchor="mm")
    x += col_widths[2]

    mom_color = COL_BULL if r["momentum"] >= 0 else COL_BEAR
    draw.text((x + col_widths[3] // 2, y + ROW_H // 2), f"{r['momentum']:+.2f}%", fill=mom_color, font=font_small, anchor="mm")
    x += col_widths[3]

    rel_color = COL_BULL if r["relative"] >= 50 else COL_BEAR
    draw.text((x + col_widths[4] // 2, y + ROW_H // 2), f"{r['relative']:.1f}", fill=rel_color, font=font_small, anchor="mm")
    x += col_widths[4]

    acc_color = COL_BULL if r["acceleration"] >= 50 else COL_BEAR
    draw.text((x + col_widths[5] // 2, y + ROW_H // 2), f"{r['acceleration']:.1f}", fill=acc_color, font=font_small, anchor="mm")
    x += col_widths[5]

    draw.text((x + col_widths[6] // 2, y + ROW_H // 2), f"{r['score']:.1f}", fill=r["status_color"], font=font_bold, anchor="mm")
    x += col_widths[6]

    bars = max(0, min(10, round(r["score"] / 10)))
    power_str = "█" * bars + "░" * (10 - bars)
    draw.text((x + col_widths[7] // 2, y + ROW_H // 2), power_str, fill=r["status_color"], font=font_small, anchor="mm")
    x += col_widths[7]

    rank_color = COL_BULL if r["rank_change_dir"] > 0 else COL_BEAR if r["rank_change_dir"] < 0 else COL_NEUTRAL
    draw.text((x + col_widths[8] // 2, y + ROW_H // 2), r["rank_change_text"], fill=rank_color, font=font_small, anchor="mm")
    x += col_widths[8]

    draw.text((x + col_widths[9] // 2, y + ROW_H // 2), r["status"], fill=r["status_color"], font=font_small, anchor="mm")

    y += ROW_H

# Footer
draw.rectangle([0, y, WIDTH, y + FOOTER_H], fill=COL_HEADER)
now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
draw.text((WIDTH // 2, y + FOOTER_H // 2), f"Updated: {now_str}", fill=(150, 165, 185), font=font_small, anchor="mm")

# ============================================================
# SEND TO TELEGRAM
# ============================================================

buffer = io.BytesIO()
img.save(buffer, format="PNG")
buffer.seek(0)

caption = (
    f"<b>🎯 Top 3:</b> "
    + " | ".join(f"{medals[i]} {r['symbol']} ({r['score']:.1f})" for i, r in enumerate(top3))
    + f"\n<b>Regime:</b> {regime}"
)

resp = requests.post(
    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
    data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"},
    files={"photo": ("rotation_radar.png", buffer, "image/png")}
)

print("Telegram response:", resp.status_code, resp.text[:200])
