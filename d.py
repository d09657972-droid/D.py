import logging
import io
import requests
import pandas as pd
import numpy as np
import mplfinance as mpf

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

# ================== CONFIG ==================
TOKEN = "8280130026:AAHbVDd0g_NdWiuiNNPXHKEsCkxmkHsQzPI"
BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/24hr?symbol={}"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

# Allowlist: only these Telegram IDs can use the bot
ALLOWED_USERS = [6691628498]  # replace with your Telegram ID(s)

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================== ACCESS CONTROL ==================
def require_access(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        if uid not in ALLOWED_USERS:
            if update.message:
                await update.message.reply_text("❌ You are not authorized to use this bot.")
            elif update.callback_query:
                await update.callback_query.answer("❌ Access denied", show_alert=True)
            return
        return await func(update, context)
    return wrapper

# ================== HELPERS ==================
def get_price(symbol: str) -> str:
    try:
        resp = requests.get(BINANCE_TICKER_URL.format(symbol), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return f"{symbol} price: {data['lastPrice']} USDT"
    except Exception as e:
        logger.exception(e)
        return f"Error: {e}"

def get_analysis_simple(symbol: str) -> str:
    try:
        resp = requests.get(BINANCE_TICKER_URL.format(symbol), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        pct = float(data["priceChangePercent"])
        if pct > 0:
            return f"{symbol} recommendation: Long ✅ (last 24h {pct:.2f}%)"
        else:
            return f"{symbol} recommendation: Short ⚠️ (last 24h {pct:.2f}%)"
    except Exception as e:
        logger.exception(e)
        return f"Error: {e}"

def fetch_klines(symbol: str, interval: str = "1h", limit: int = 200) -> pd.DataFrame | None:
    try:
        r = requests.get(
            BINANCE_KLINES_URL,
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=12,
        )
        r.raise_for_status()
        raw = r.json()
        if not isinstance(raw, list) or not raw:
            return None
        cols = ["open_time", "open", "high", "low", "close", "volume",
                "close_time", "q1", "q2", "q3", "q4", "q5"]
        df = pd.DataFrame(raw, columns=cols)
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = df[c].astype(float)
        df["date"] = pd.to_datetime(df["close_time"], unit="ms")
        return df[["date", "open", "high", "low", "close", "volume"]]
    except Exception as e:
        logger.exception(e)
        return None

def render_chart_png(symbol: str, interval: str = "1h") -> bytes | None:
    df = fetch_klines(symbol, interval=interval, limit=200)
    if df is None or df.empty:
        return None
    dfp = df.copy()
    dfp.set_index("date", inplace=True)
    dfp.index.name = "Date"
    fig, _ = mpf.plot(
        dfp, type="candle", volume=True, style="charles",
        returnfig=True, figsize=(9, 5),
    )
    bio = io.BytesIO()
    fig.savefig(bio, format="png", bbox_inches="tight")
    bio.seek(0)
    return bio.read()

# ================== UI: CRYPTOS ==================
COIN_BUTTONS = [
    ("BTC", "BTCUSDT"),
    ("ETH", "ETHUSDT"),
    ("XRP", "XRPUSDT"),
    ("SOL", "SOLUSDT"),
    ("BNB", "BNBUSDT"),
    ("ADA", "ADAUSDT"),
]

def cryptos_keyboard(interval: str = "1h") -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(COIN_BUTTONS), 3):
        chunk = COIN_BUTTONS[i:i+3]
        rows.append([InlineKeyboardButton(lbl, callback_data=f"coin:{sym}:{interval}") for (lbl, sym) in chunk])
    rows.append([
        InlineKeyboardButton("15m", callback_data="iv:15m"),
        InlineKeyboardButton("1h ✓", callback_data="iv:1h"),
        InlineKeyboardButton("4h", callback_data="iv:4h"),
        InlineKeyboardButton("1d", callback_data="iv:1d"),
    ])
    return InlineKeyboardMarkup(rows)

# ================== COMMANDS ==================
@require_access
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to the Crypto Analysis Bot!\n"
        "/price BTC → current price\n"
        "/analysis BTC → simple analysis\n"
        "/cryptos → chart menu for popular coins"
    )

@require_access
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/price <coin> → e.g. /price BTC\n"
        "/analysis <coin> → e.g. /analysis ETH\n"
        "/cryptos → quick access to 6 popular coins with charts"
    )

@require_access
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        base = context.args[0].upper()
        symbol = base + "USDT" if not base.endswith("USDT") else base
        result = get_price(symbol)
        await update.message.reply_text(result)
    else:
        await update.message.reply_text("Usage: /price BTC")

@require_access
async def analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        base = context.args[0].upper()
        symbol = base + "USDT" if not base.endswith("USDT") else base
        result = get_analysis_simple(symbol)
        await update.message.reply_text(result)
    else:
        await update.message.reply_text("Usage: /analysis BTC")

@require_access
async def cryptos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cryptos:", reply_markup=cryptos_keyboard())

# ================== CALLBACKS ==================
USER_INTERVAL: dict[int, str] = {}

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id not in ALLOWED_USERS:
        await q.answer("❌ Access denied", show_alert=True)
        return

    await q.answer()
    data = q.data
    try:
        if data.startswith("iv:"):
            _, iv = data.split(":")
            uid = q.from_user.id
            USER_INTERVAL[uid] = iv
            # Update interval selection UI
            rows = []
            for i in range(0, len(COIN_BUTTONS), 3):
                chunk = COIN_BUTTONS[i:i+3]
                rows.append([InlineKeyboardButton(lbl, callback_data=f"coin:{sym}:{iv}") for (lbl, sym) in chunk])
            rows.append([
                InlineKeyboardButton(("15m ✓" if iv=="15m" else "15m"), callback_data="iv:15m"),
                InlineKeyboardButton(("1h ✓" if iv=="1h" else "1h"), callback_data="iv:1h"),
                InlineKeyboardButton(("4h ✓" if iv=="4h" else "4h"), callback_data="iv:4h"),
                InlineKeyboardButton(("1d ✓" if iv=="1d" else "1d"), callback_data="iv:1d"),
            ])
            await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(rows))
            return

        if data.startswith("coin:"):
            _, symbol, interval = data.split(":")
            uid = q.from_user.id
            if uid in USER_INTERVAL:
                interval = USER_INTERVAL[uid]

            try:
                await q.edit_message_text(f"{symbol} {interval} chart is being prepared...")
            except Exception:
                pass

            png = render_chart_png(symbol, interval)
            if png:
                await context.bot.send_photo(
                    chat_id=q.message.chat.id,
                    photo=png,
                    caption=f"{symbol} {interval} chart",
                    reply_markup=cryptos_keyboard(interval),
                )
            else:
                await context.bot.send_message(
                    chat_id=q.message.chat.id,
                    text=f"Failed to fetch {symbol} {interval} chart.",
                    reply_markup=cryptos_keyboard(interval),
                )
            return

    except Exception as e:
        logger.exception(e)
        try:
            await q.edit_message_text("An error occurred. Please try /cryptos again.")
        except Exception:
            await context.bot.send_message(chat_id=q.message.chat.id, text="An error occurred. Please try /cryptos again.")

# ================== RUN ==================
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("analysis", analysis))
    app.add_handler(CommandHandler("cryptos", cryptos))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.run_polling()

if __name__ == "__main__":
    main()
