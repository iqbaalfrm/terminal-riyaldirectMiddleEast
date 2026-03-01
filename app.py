import requests
import pytz
import os
from flask import Flask, render_template, jsonify
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)


def _f(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def _vol(v):
    """Format volume to compact string"""
    n = _f(v)
    if n >= 1000:
        return f"{n/1000:.1f}K"
    if n > 0:
        return f"{n:.0f}"
    return ""


# ── Binance P2P ─────────────────────────────────────────
def _binance(fiat, trade_type):
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    payload = {"asset": "USDT", "fiat": fiat, "merchantCheck": True,
               "page": 1, "rows": 20, "tradeType": trade_type}
    try:
        res = requests.post(url, json=payload,
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=12).json()
        out = []
        for x in (res.get("data") or []):
            adv = x.get("adv") or {}
            usr = x.get("advertiser") or {}
            p = _f(adv.get("price"))
            if p > 0:
                vol = _vol(adv.get("surplusAmount") or adv.get("tradableQuantity") or 0)
                out.append({"name": str(usr.get("nickName", "-"))[:12], "price": p, "vol": vol})
        return out
    except Exception:
        return []


# ── OKX C2C ─────────────────────────────────────────────
def _okx(fiat, side):
    url = "https://www.okx.com/v3/c2c/tradingOrders/books"
    params = {"quoteCurrency": fiat.lower(), "baseCurrency": "usdt",
              "side": side, "paymentMethod": "all", "userType": "all",
              "showTrade": "false", "showFollow": "false",
              "showAlreadyTraded": "false", "isAbleFilter": "false"}
    try:
        res = requests.get(url, params=params,
                           headers={"User-Agent": "Mozilla/5.0"}, timeout=12).json()
        raw = res.get("data", {})
        items = raw.get(side, []) if isinstance(raw, dict) else []
        out = []
        for x in items:
            p = _f(x.get("price"))
            if p > 0:
                vol = _vol(x.get("availableAmount") or x.get("quoteMaxAmountPerOrder") or 0)
                out.append({"name": str(x.get("nickName", "-"))[:12], "price": p, "vol": vol})
        return out
    except Exception:
        return []


# ── Bybit P2P ───────────────────────────────────────────
def _bybit(fiat, side):
    url = "https://api2.bybit.com/fiat/otc/item/online"
    payload = {"tokenId": "USDT", "currencyId": fiat,
               "payment": [], "side": str(side),
               "size": "20", "page": "1", "amount": ""}
    try:
        res = requests.post(url, json=payload,
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=12).json()
        items = res.get("result", {}).get("items", [])
        out = []
        for x in items:
            p = _f(x.get("price"))
            if p > 0:
                vol = _vol(x.get("quantity") or x.get("lastQuantity") or 0)
                out.append({"name": str(x.get("nickName", "-"))[:12], "price": p, "vol": vol})
        return out
    except Exception:
        return []


# ── KuCoin P2P ──────────────────────────────────────────
def _kucoin(fiat, side):
    url = "https://www.kucoin.com/_api/otc/ad/list"
    params = {"currency": "USDT", "fiatCurrency": fiat,
              "side": side, "status": "PUTUP",
              "page": 1, "pageSize": 20, "legal": fiat}
    try:
        res = requests.get(url, params=params,
                           headers={"User-Agent": "Mozilla/5.0"}, timeout=12).json()
        items = res.get("items") or []
        if not items and isinstance(res.get("data"), dict):
            items = res["data"].get("items", [])
        out = []
        for x in items:
            p = _f(x.get("premium") or x.get("floatPrice") or x.get("fixedPrice"))
            if p > 0:
                vol = _vol(x.get("currencyBalanceQuantity") or x.get("limitMaxQuote") or 0)
                out.append({"name": str(x.get("nickName", "-"))[:12], "price": p, "vol": vol})
        return out
    except Exception:
        return []


# ── Market Data ─────────────────────────────────────────
def get_market_data():
    limits = {"OKX": 10}

    def _safe(f, lim):
        try:
            return f.result(timeout=15)[:lim]
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=14) as exe:
        futs = {
            "Binance": {
                "sar_buy": exe.submit(_binance, "SAR", "BUY"),
                "sar_sell": exe.submit(_binance, "SAR", "SELL"),
                "aed_buy": exe.submit(_binance, "AED", "BUY"),
                "aed_sell": exe.submit(_binance, "AED", "SELL"),
            },
            "OKX": {
                "sar_buy": exe.submit(_okx, "SAR", "buy"),
                "sar_sell": exe.submit(_okx, "SAR", "sell"),
            },
            "Bybit": {
                "sar_buy": exe.submit(_bybit, "SAR", "1"),
                "sar_sell": exe.submit(_bybit, "SAR", "0"),
                "aed_buy": exe.submit(_bybit, "AED", "1"),
                "aed_sell": exe.submit(_bybit, "AED", "0"),
            },
            "KuCoin": {
                "sar_buy": exe.submit(_kucoin, "SAR", "BUY"),
                "sar_sell": exe.submit(_kucoin, "SAR", "SELL"),
                "aed_buy": exe.submit(_kucoin, "AED", "BUY"),
                "aed_sell": exe.submit(_kucoin, "AED", "SELL"),
            },
        }

    exchanges = {}
    for name, ex_futs in futs.items():
        lim = limits.get(name, 5)
        exchanges[name] = {k: _safe(v, lim) for k, v in ex_futs.items()}

    tz = pytz.timezone("Asia/Riyadh")
    now = datetime.now(tz)
    return {"time": now.strftime("%H:%M:%S"), "date": now.strftime("%d/%m/%Y"),
            "exchanges": exchanges}


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/data')
def api_data():
    return jsonify(get_market_data())


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port)
