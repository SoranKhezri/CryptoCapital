"""
Crypto Capital Rotation Radar - Python Edition (نسخه چندعکسی)
هماهنگ با اندیکاتور Pine Script | ارسال به تلگرام در قالب تصاویر جداگانه
"""

import os
import io
import json
import time
import requests
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFont

# ============================================================
# تنظیمات اصلی
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "")

TOP_N_UNIVERSE = 250     # تعداد کوینی که از CoinGecko دریافت میشه (بعد حذف استیبل‌کوین‌ها)
TOP_N_DISPLAY = 100      # تعداد نهایی که رتبه‌بندی و نمایش داده میشن
CHUNK_SIZE = 20          # هر عکس شامل چند کوین باشه (۵ عکس × ۲۰ = ۱۰۰)

# وزن‌های امتیازدهی
W_DOM = 30.0
W_MOMENTUM = 25.0
W_RELATIVE = 25.0
W_ACCELERATION = 20.0

# آستانه‌های وضعیت
STRONG_INFLOW = 80.0
INFLOW = 65.0
OUTFLOW = 35.0
STRONG_OUTFLOW = 20.0

# کوین‌هایی که باید حذف بشن (استیبل‌کوین، wrapped)
EXCLUDED_SYMBOLS = {
    "usdt", "usdc", "dai", "busd", "tusd", "usdd", "fdusd", "pyusd",
    "usde", "frax", "gusd", "usdp", "eurs", "eurt",
    "wbtc", "weth", "wsteth", "steth", "weeth", "cbbtc",
    "reth", "meth", "wbeth", "beth"
}

DATA_FILE = "data/previous_scores.json"

# ============================================================
# پالت رنگی (هماهنگ با تم اندیکاتور TradingView)
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

MEDALS = ["🥇", "🥈", "🥉"]  # فقط برای caption تلگرام استفاده می‌شه

# ============================================================
# تابع‌های کمکی برای API
# ============================================================

def cg_headers():
    h = {"User-Agent": "CapitalRotationRadar/1.0"}
    if COINGECKO_API_KEY:
        h["x-cg-demo-api-key"] = COINGECKO_API_KEY
    return h


def fetch_market_data():
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
            print(f"Try {attempt+1} failed: {e}")
            time.sleep(5)
    raise RuntimeError("CoinGecko fetch failed")


def fetch_usdt_history():
    url = "https://api.coingecko.com/api/v3/coins/tether/market_chart"
    params = {"vs_currency": "usd", "days": 8, "interval": "daily"}
    try:
        r = requests.get(url, params=params, headers=cg_headers(), timeout=20)
        r.raise_for_status()
        data = r.json()
        caps = data.get("market_caps", [])
        if len(caps) >= 2:
            return caps[0][1], caps[-2][1]
    except Exception as e:
        print(f"USDT history error: {e}")
    return None, None


# ============================================================
# توابع ریاضی
# ============================================================

def normalize(value, min_v, max_v):
    if value is None:
        return None
    v = max(min_v, min(max_v, value))
    return (v - min_v) / (max_v - min_v) * 100.0


def past_cap(current_cap, pct_change):
    if current_cap is None or pct_change is None:
        return None
    return current_cap / (1 + pct_change / 100.0)


def safe(v, default=0.0):
    return default if v is None else v


def pct_change(now, past):
    if now is None or past is None or past == 0:
        return None
    return (now / past - 1.0) * 100.0


# ============================================================
# مرحله اول: گرفتن داده
# ============================================================

print("Fetching data from CoinGecko...")
raw_coins = fetch_market_data()
usdt_main_past, usdt_short_past = fetch_usdt_history()

# ---- محاسبه شاخص‌های کلان ----

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
btc_dom_change = (btc_dom_now - btc_dom_main_past) if (btc_dom_now and btc_dom_main_past) else None

if usdt_main_past and usdt_short_past:
    usdt_dom_now = (usdt_cap_now / total_now * 100.0) if total_now else None
    usdt_dom_main_past = (usdt_main_past / total_main_past * 100.0) if total_main_past else None
    usdt_dom_change = (usdt_dom_now - usdt_dom_main_past) if (usdt_dom_now and usdt_dom_main_past) else None
else:
    usdt_dom_now = (usdt_cap_now / total_now * 100.0) if total_now else None
    usdt_dom_change = None


# ---- تشخیص رژیم بازار ----

risk_off = (
    usdt_dom_change is not None and total_momentum is not None
    and usdt_dom_change > 0.20 and total_momentum < 0
)

broad_alt_rotation = (
    not risk_off and None not in (total2_momentum, total3_momentum, total_momentum)
    and total2_momentum > total_momentum and total3_momentum > total2_momentum
)

alt_rotation = (
    not risk_off and None not in (btc_dom_change, total3_momentum, total_momentum)
    and btc_dom_change < 0 and total3_momentum > total_momentum
)

btc_rotation = (
    not risk_off and None not in (btc_dom_change, total3_momentum, total_momentum)
    and btc_dom_change > 0.15 and total3_momentum < total_momentum
)

risk_on = (
    not risk_off and usdt_dom_change is not None and total_momentum is not None
    and usdt_dom_change < -0.15 and total_momentum > 0
)

if risk_off:
    regime, regime_desc, regime_color = "RISK OFF", "USDT.D rising while total market weakens", COL_BEAR
elif broad_alt_rotation:
    regime, regime_desc, regime_color = "BROAD ALT ROTATION", "Altcoin market outperforming BTC", COL_BULL
elif alt_rotation:
    regime, regime_desc, regime_color = "ALTCOIN ROTATION", "Relative strength shifting to altcoins", COL_BULL
elif btc_rotation:
    regime, regime_desc, regime_color = "BTC ROTATION", "BTC gaining market share", COL_GOLD
elif risk_on:
    regime, regime_desc, regime_color = "RISK ON", "Liquidity improving", COL_BLUE
else:
    regime, regime_desc, regime_color = "NEUTRAL", "Market balanced", COL_NEUTRAL


# ============================================================
# مرحله دوم: محاسبه امتیاز هر کوین
# ============================================================

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
    if not total_now or not total_main_past or not total_short_past:
        continue

    cap_main_past = past_cap(cap_now, mom_7d)
    cap_short_past = past_cap(cap_now, mom_24h)

    dominance = cap_now / total_now * 100.0
    dominance_main_past = cap_main_past / total_main_past * 100.0
    dominance_short_past = cap_short_past / total_short_past * 100.0

    dom_change = dominance - dominance_main_past
    short_dom_change = dominance - dominance_short_past
    momentum = mom_7d
    relative_diff = (momentum - total3_momentum) if total3_momentum is not None else None

    # بازه‌های گسترده‌تر متناسب با نوسانات بازار کریپتو
    dom_score = normalize(dom_change, -2, 2)
    momentum_score = normalize(momentum, -50, 50)
    relative_score = normalize(relative_diff, -40, 40)
    acceleration_score = normalize(short_dom_change - dom_change, -3, 3)

    if None in (dom_score, momentum_score, relative_score, acceleration_score):
        continue

    weight_sum = max(W_DOM + W_MOMENTUM + W_RELATIVE + W_ACCELERATION, 0.0001)
    score = (
        dom_score * W_DOM +
        momentum_score * W_MOMENTUM +
        relative_score * W_RELATIVE +
        acceleration_score * W_ACCELERATION
    ) / weight_sum

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

# مقایسه با اجرای قبل برای ستون RANK
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

new_data = {r["symbol"]: {"rank": r["rank"], "score": r["score"]} for r in results}
os.makedirs("data", exist_ok=True)
with open(DATA_FILE, "w") as f:
    json.dump(new_data, f)

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
# مرحله سوم: تولید تصویر و ارسال به تلگرام
# ============================================================

FONT_DIR = "/usr/share/fonts/truetype/dejavu/"
font_bold = ImageFont.truetype(FONT_DIR + "DejaVuSans-Bold.ttf", 16)
font_regular = ImageFont.truetype(FONT_DIR + "DejaVuSans.ttf", 14)
font_small = ImageFont.truetype(FONT_DIR + "DejaVuSans.ttf", 11)
font_title = ImageFont.truetype(FONT_DIR + "DejaVuSans-Bold.ttf", 22)

WIDTH = 900
ROW_H = 32
TABLE_HEADER_H = 36
FOOTER_H = 30
COL_WIDTHS = [40, 90, 80, 90, 70, 70, 80, 140, 70, 170]


def draw_medal(draw, cx, cy, rank, radius=11):
    """رسم دستی مدال به صورت دایره‌ی رنگی به‌جای ایموجی (که در فونت پشتیبانی نمی‌شه)"""
    colors = {1: (255, 215, 0), 2: (200, 205, 215), 3: (205, 140, 80)}
    color = colors.get(rank, COL_WHITE)
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                 fill=color, outline=(20, 20, 20), width=1)
    draw.text((cx, cy + 1), str(rank), fill=(15, 15, 15),
              font=font_small, anchor="mm")


def draw_top3_summary(draw, cy, top3_list):
    """رسم خلاصه Top3 با مدال‌های دستی به‌جای ایموجی"""
    medal_r = 10
    gap_after_medal = 6
    gap_between_items = 35

    segments = []
    for r in top3_list:
        text = f"{r['symbol']} {r['score']:.1f}"
        text_w = draw.textlength(text, font=font_regular)
        seg_w = medal_r * 2 + gap_after_medal + text_w
        segments.append((text, seg_w))

    total_w = sum(s[1] for s in segments) + gap_between_items * (len(segments) - 1)
    x = (WIDTH - total_w) // 2

    for i, (text, seg_w) in enumerate(segments):
        cx = x + medal_r
        draw_medal(draw, cx, cy, i + 1, medal_r)
        draw.text((x + medal_r * 2 + gap_after_medal, cy), text,
                  fill=COL_GOLD, font=font_regular, anchor="lm")
        x += seg_w + gap_between_items


def build_image(results_slice, part_number, total_parts):
    """ساخت یک عکس برای یک بخش از لیست"""

    is_first = (part_number == 1)

    # محاسبه ارتفاع با توجه به اینکه هدر کامل یا خلاصه باشه
    header_h = 150 if is_first else 50
    height = header_h + TABLE_HEADER_H + ROW_H * len(results_slice) + FOOTER_H

    img = Image.new("RGB", (WIDTH, height), COL_BG_MAIN)
    draw = ImageDraw.Draw(img)
    y = 0

    # ---------- عنوان و اطلاعات رژیم (فقط در عکس اول) ----------
    title_text = f"◈  CRYPTO CAPITAL ROTATION RADAR  ◈   ({part_number}/{total_parts})"
    draw.rectangle([0, y, WIDTH, y + 50], fill=COL_HEADER)
    draw.text((WIDTH // 2, y + 25), title_text,
              fill=COL_GOLD, font=font_title, anchor="mm")
    y += 50

    if is_first:
        # رژیم
        rg_bg = tuple(min(255, c + 15) for c in COL_BG_MAIN)
        draw.rectangle([0, y, WIDTH, y + 34], fill=rg_bg)
        draw.text((WIDTH // 2, y + 17),
                  f"◉  {regime}   |   {regime_desc}",
                  fill=regime_color, font=font_regular, anchor="mm")
        y += 34

        # سطر ماکرو ۱
        draw.rectangle([0, y, WIDTH, y + 32], fill=COL_PANEL)
        macro_items = [
            ("BTC.D", f"{btc_dom_now:.2f}%" if btc_dom_now else "—", COL_WHITE),
            ("\u0394", f"{btc_dom_change:+.2f}%" if btc_dom_change is not None else "—",
             COL_GOLD if (btc_dom_change or 0) >= 0 else COL_BULL),
            ("USDT.D", f"{usdt_dom_now:.2f}%" if usdt_dom_now else "—", COL_WHITE),
            ("\u0394", f"{usdt_dom_change:+.2f}%" if usdt_dom_change is not None else "—",
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

        # سطر ماکرو ۲
        draw.rectangle([0, y, WIDTH, y + 32], fill=COL_PANEL_ALT)
        macro_items2 = [("TOTAL2", total2_momentum), ("TOTAL3", total3_momentum),
                        ("OTHERS", others_momentum)]
        col_w2 = WIDTH // len(macro_items2)
        for i, (label, value) in enumerate(macro_items2):
            cx = i * col_w2 + col_w2 // 2
            clr = COL_BULL if (value or 0) >= 0 else COL_BEAR
            draw.text((cx, y + 10), label, fill=COL_WHITE, font=font_small, anchor="mm")
            draw.text((cx, y + 24), f"{value:+.2f}%" if value is not None else "—",
                      fill=clr, font=font_small, anchor="mm")
        y += 32

        # Top 3
        draw.rectangle([0, y, WIDTH, y + 34], fill=(30, 24, 8))
        draw_top3_summary(draw, y + 17, top3)
        y += 34

    # ---------- هدر جدول ----------
    headers = ["#", "COIN", "DOM", "MOM", "REL", "ACC", "SCORE", "POWER", "RANK", "STATUS"]
    draw.rectangle([0, y, WIDTH, y + TABLE_HEADER_H], fill=COL_HEADER)
    x = 0
    for h, w in zip(headers, COL_WIDTHS):
        draw.text((x + w // 2, y + TABLE_HEADER_H // 2), h,
                  fill=COL_GOLD, font=font_small, anchor="mm")
        x += w
    y += TABLE_HEADER_H

    # ---------- ردیف‌ها ----------
    global_start_rank = results_slice[0]["rank"]
    global_end_rank = results_slice[-1]["rank"]

    for idx_local, r in enumerate(results_slice):
        row_bg = COL_PANEL if idx_local % 2 == 0 else COL_PANEL_ALT
        if r["rank"] <= 3:
            row_bg = (40, 32, 12)
        draw.rectangle([0, y, WIDTH, y + ROW_H], fill=row_bg)

        x = 0
        if r["rank"] <= 3:
            draw_medal(draw, x + COL_WIDTHS[0] // 2, y + ROW_H // 2, r["rank"])
        else:
            draw.text((x + COL_WIDTHS[0] // 2, y + ROW_H // 2), str(r["rank"]),
                      fill=COL_WHITE, font=font_small, anchor="mm")
        x += COL_WIDTHS[0]

        draw.text((x + 10, y + ROW_H // 2), r["symbol"],
                  fill=COL_WHITE, font=font_regular, anchor="lm")
        x += COL_WIDTHS[1]

        draw.text((x + COL_WIDTHS[2] // 2, y + ROW_H // 2),
                  f"{r['dominance']:.2f}%", fill=(190, 200, 215),
                  font=font_small, anchor="mm")
        x += COL_WIDTHS[2]

        mom_clr = COL_BULL if r["momentum"] >= 0 else COL_BEAR
        draw.text((x + COL_WIDTHS[3] // 2, y + ROW_H // 2),
                  f"{r['momentum']:+.2f}%", fill=mom_clr,
                  font=font_small, anchor="mm")
        x += COL_WIDTHS[3]

        rel_clr = COL_BULL if r["relative"] >= 50 else COL_BEAR
        draw.text((x + COL_WIDTHS[4] // 2, y + ROW_H // 2),
                  f"{r['relative']:.1f}", fill=rel_clr,
                  font=font_small, anchor="mm")
        x += COL_WIDTHS[4]

        acc_clr = COL_BULL if r["acceleration"] >= 50 else COL_BEAR
        draw.text((x + COL_WIDTHS[5] // 2, y + ROW_H // 2),
                  f"{r['acceleration']:.1f}", fill=acc_clr,
                  font=font_small, anchor="mm")
        x += COL_WIDTHS[5]

        draw.text((x + COL_WIDTHS[6] // 2, y + ROW_H // 2),
                  f"{r['score']:.1f}", fill=r["status_color"],
                  font=font_bold, anchor="mm")
        x += COL_WIDTHS[6]

        bars = max(0, min(10, round(r["score"] / 10)))
        power_str = "\u2588" * bars + "\u2591" * (10 - bars)
        draw.text((x + COL_WIDTHS[7] // 2, y + ROW_H // 2), power_str,
                  fill=r["status_color"], font=font_small, anchor="mm")
        x += COL_WIDTHS[7]

        rk_clr = COL_BULL if r["rank_change_dir"] > 0 \
            else COL_BEAR if r["rank_change_dir"] < 0 else COL_NEUTRAL
        draw.text((x + COL_WIDTHS[8] // 2, y + ROW_H // 2),
                  r["rank_change_text"], fill=rk_clr,
                  font=font_small, anchor="mm")
        x += COL_WIDTHS[8]

        draw.text((x + COL_WIDTHS[9] // 2, y + ROW_H // 2),
                  r["status"], fill=r["status_color"],
                  font=font_small, anchor="mm")

        y += ROW_H

    # ---------- فوتر ----------
    draw.rectangle([0, y, WIDTH, y + FOOTER_H], fill=COL_HEADER)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # عنوان فارسی بخش جاری
    persian_part_names = {
        1: "لیست ۲۰ تای اول",
        2: "لیست ۲۰ تای دوم",
        3: "لیست ۲۰ تای سوم",
        4: "لیست ۲۰ تای چهارم",
        5: "لیست ۲۰ تای پنجم",
        6: "لیست ۲۰ تای ششم",
        7: "لیست ۲۰ تای هفتم",
        8: "لیست ۲۰ تای هشتم",
        9: "لیست ۲۰ تای نهم",
        10: "لیست ۲۰ تای دهم"
    }

    part_name_farsi = persian_part_names.get(part_number, f"{part_number}")

    footer_text = (
        f"Updated: {now_str}  |  "
        f"{part_number}/{total_parts} - {part_name_farsi}  "
        f"(رتبه\u200cها {global_start_rank}-{global_end_rank})"
    )

    draw.text((WIDTH // 2, y + FOOTER_H // 2), footer_text,
              fill=(150, 165, 185), font=font_small, anchor="mm")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


# ---------- تقسیم نتایج به بخش‌های ۲۰تایی ----------

def chunk_list(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


chunks = list(chunk_list(results, CHUNK_SIZE))
total_parts = len(chunks)

print(f"Total coins: {len(results)}, Chunks: {total_parts}")


# ---------- ارسال هر بخش به تلگرام ----------

for part_num, chunk_data in enumerate(chunks, start=1):

    image_buffer = build_image(chunk_data, part_num, total_parts)

    if part_num == 1:
        caption = (
            f"<b>\ud83c\udfaf Top 3:</b> "
            + " | ".join(f"{MEDALS[i]} {r['symbol']} ({r['score']:.1f})" 
                        for i, r in enumerate(top3))
            + f"\n<b>Regime:</b> {regime}"
            + f"\n<b>{part_num}/{total_parts}</b> - "
        )
        if total_parts <= 5:
            names = {
                1: "\u0644\u06cc\u0633\u062a \u06f2\u06f0 \u062a\u0627 \u0627\u0648\u0644",
                2: "\u0644\u06cc\u0633\u062a \u06f2\u06f0 \u062a\u0627 \u062f\u0648\u0645",
                3: "\u0644\u06cc\u0633\u062a \u06f2\u06f0 \u062a\u0627 \u0633\u0648\u0645",
                4: "\u0644\u06cc\u0633\u062a \u06f2\u06f0 \u062a\u0627 \u0686\u0647\u0627\u0631\u0645",
                5: "\u0644\u06cc\u0633\u062a \u06f2\u06f0 \u062a\u0627 \u067e\u0646\u062c\u0645"
            }
            caption += names.get(part_num, str(part_num))
        else:
            caption += f"Part {part_num}"
    else:
        caption = f"<b>{part_num}/{total_parts}</b> - "
        if total_parts <= 5:
            names = {
                1: "\u0644\u06cc\u0633\u062a \u06f2\u06f0 \u062a\u0627 \u0627\u0648\u0644",
                2: "\u0644\u06cc\u0633\u062a \u06f2\u06f0 \u062a\u0627 \u062f\u0648\u0645",
                3: "\u0644\u06cc\u0633\u062a \u06f2\u06f0 \u062a\u0627 \u0633\u0648\u0645",
                4: "\u0644\u06cc\u0633\u062a \u06f2\u06f0 \u062a\u0627 \u0686\u0647\u0627\u0631\u0645",
                5: "\u0644\u06cc\u0633\u062a \u06f2\u06f0 \u062a\u0627 \u067e\u0646\u062c\u0645"
            }
            caption += names.get(part_num, str(part_num))
        else:
            caption += f"Part {part_num}"

    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": caption,
            "parse_mode": "HTML"
        },
        files={"photo": (f"radar_{part_num}.png", image_buffer, "image/png")}
    )

    print(f"Part {part_num}/{total_parts} -> {resp.status_code}: {resp.text[:120]}")

    time.sleep(1.5)  # جلوگیری از Rate Limit تلگرام


print("All done!")
