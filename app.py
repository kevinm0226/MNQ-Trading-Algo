# ironbeam_client_demo.py
import json
import time
import threading
import queue
import requests
from websocket import WebSocketApp
import traceback
import numpy as np
from collections import deque
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()


# =======================
# CONFIGURATION (Plug In)
# =======================
USERNAME = os.getenv("USERNAME")
API_KEY = os.getenv("API_KEY")
BASE_URL = os.getenv("BASE_URL")
SYMBOL = os.getenv("SYMBOL")
TICK_SIZE = 0.25
TARGET_TICKS = 50
MAX_OPEN = 1
# =======================

tick_q = queue.Queue()
bar_q = queue.Queue()
stop_event = threading.Event()
open_trades = {}


# ---------- REST Client ---------------
class IronbeamREST:
    def __init__(self, base_url, account_id=None):
        self.base = base_url.rstrip("/")
        self.token = None
        self.account_id = account_id
        self.session = requests.Session()

    def auth(self, username, api_key):
        url = f"{self.base}/v2/auth"
        payload = {"Username": username, "ApiKey": api_key}
        r = self.session.post(url, json=payload, timeout=10)
        r.raise_for_status()
        self.token = r.json().get("token")
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        return self.token

    def create_stream(self):
        """Create a streamId (must do this before opening WSS)."""
        url = f"{self.base}/v2/stream/create"
        r = self.session.get(url, timeout=10)
        r.raise_for_status()
        return r.json()

    def place_order(
        self,
        symbol: str,
        side: str,
        qty: int = 1,
        stopLoss: float = None,
        takeProfit: float = None,
        order_type: str = "MARKET",
        close_price: float = None,
    ):

        if close_price is None:
            raise ValueError("close_price is required to set SL/TP levels")

        url = f"{self.base}/v1/order/{self.account_id}/place"
        body = {
            "exchSym": symbol,
            "side": side.upper(),
            "orderType": order_type,
            "quantity": qty,
            "takeProfit": takeProfit,
            "stopLoss": stopLoss,
        }

        r = self.session.post(url, json=body, timeout=10)
        try:
            return r.json()
        except Exception:
            return {"error": r.text}

    def get_open_orders(self, order_status="ANY"):
        url = f"{self.base}/v2/order/{self.account_id}/{order_status}"
        resp = self.session.get(url, headers={"Authorization": f"Bearer {self.token}"})
        resp.raise_for_status()
        return resp.json().get("orders", [])


# ---------- Bar Aggregator -------------
def bar_builder(trade_only: bool = True):

    current_sec = int(time.time())
    o = h = l = c = None
    vol = 0

    while not stop_event.is_set():
        sec_start = time.time()

        ticks_this_sec = []
        while True:
            try:
                tick = tick_q.get_nowait()
                ticks_this_sec.append(tick)
            except queue.Empty:
                break

        prices = []
        sizes = []

        for t in ticks_this_sec:
            if "price" in t:
                prices.append(t["price"])
                sizes.append(t.get("size", 0))
            elif not trade_only and "bid" in t and "ask" in t:
                mid = (t["bid"] + t["ask"]) / 2.0
                prices.append(mid)
                sizes.append((t.get("bid_size", 0) + t.get("ask_size", 0)) / 2.0)

        if prices:
            if o is None:
                o = prices[0]
            h = max(prices) if h is None else max(h, max(prices))
            l = min(prices) if l is None else min(l, min(prices))
            c = prices[-1]
            vol += sum(sizes)
        else:
            if c is not None:
                o = h = l = c
                vol = 0

        now_sec = int(time.time())
        if now_sec > current_sec and c is not None:
            bar = {
                "t": current_sec,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": vol,
            }
            bar_q.put(bar)
            print("BAR:", bar)

            current_sec = now_sec
            o = h = l = c
            vol = 0

        elapsed = time.time() - sec_start
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)


# ========== WEBSOCKET STREAMING (correct usage of websocket-client) ==========
def start_streaming(rest):
    """Create streamId, open WebSocketApp, subscribe to trades, and put incoming messages to tick_q."""
    while not stop_event.is_set():
        try:
            # 1) Create streamId
            sr = rest.create_stream()
            stream_id = sr.get("streamId")
            if not stream_id:
                print("No streamId returned:", sr)
                time.sleep(5)
                continue

            ws_url = (
                f"wss://demo.ironbeamapi.com/v2/stream/{stream_id}?token={rest.token}"
            )
            print("Connecting to", ws_url)

            def on_open(ws):
                print("WebSocket opened.")

                headers = {"Authorization": f"Bearer {rest.token}"}

                quotes_url = f"{BASE_URL}/v1/market/quotes/subscribe/{stream_id}?symbols={SYMBOL}"
                try:
                    r_q = requests.get(quotes_url, headers=headers, timeout=5)
                    print("Quotes subscribe:", r_q.status_code, r_q.text[:500])
                except Exception as e:
                    print("Failed to subscribe quotes:", e)

                trades_url = f"{BASE_URL}/v1/market/trades/subscribe/{stream_id}?symbols={SYMBOL}"
                try:
                    r_t = requests.get(trades_url, headers=headers, timeout=5)
                    print("Trades subscribe:", r_t.status_code, r_t.text[:500])
                except Exception as e:
                    print("Failed to subscribe trades:", e)

            def on_message(ws, message):
                try:
                    data = json.loads(message)

                except Exception as e:
                    print("Bad WS message:", message, e)
                    return

                # Ping
                if "p" in data and "ping" in data["p"]:
                    return

                # Balance updates
                if "b" in data:
                    return

                if "q" in data:
                    print(data)

                    for q in data["q"]:
                        tick_q.put(
                            {
                                "bid": q.get("b"),
                                "ask": q.get("a"),
                                "bid_size": q.get("bs"),
                                "ask_size": q.get("as"),
                                "last": q.get("la"),
                                "ts": q.get("at"),
                            }
                        )
                    return

                # Trades come under "tr"
                if "tr" in data:
                    for trade in data["tr"]:
                        tick_q.put(
                            {
                                "price": trade.get("p"),
                                "size": trade.get("sz"),
                                "ts": trade.get("st"),
                            }
                        )
                    return

            def on_error(ws, err):
                print("WebSocket error:", err)

            def on_close(ws, close_status_code, close_msg):
                print("WebSocket closed:", close_status_code, close_msg)

            ws_app = WebSocketApp(
                ws_url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )

            ws_app.run_forever()
            print("WebSocket run_forever ended, reconnecting in 1s...")
            time.sleep(1)

        except Exception as e:
            print("Exception in start_streaming:", e)
            traceback.print_exc()
            time.sleep(2)


def fetch_open_orders(rest):
    try:
        resp = rest.session.get(
            f"{rest.base}/v2/order/{rest.account_id}/ANY",
            headers={"Authorization": f"Bearer {rest.token}"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("orders", [])
    except Exception as e:
        print("Error fetching open orders:", e)
        return []


def exit_trade(rest, trade, current_price):
    """Exit trade by placing opposite market order."""
    side = "SELL" if trade["side"] == "BUY" else "BUY"
    resp = rest.place_order(SYMBOL, side, qty=trade["qty"], close_price=current_price)
    print(f"EXIT {trade['side']} order {trade['orderId']} → response: {resp}")
    open_trades.pop(trade["orderId"], None)


def strategy(rest, bar):
    print("ok")
    if not hasattr(strategy, "closes"):
        strategy.closes = deque(maxlen=120)

    strategy.closes.append(bar["close"])

    if len(strategy.closes) < 120:
        return None

    closes = np.array(strategy.closes)
    mean_close = closes.mean()
    current_close = closes[-1]

    threshold = 0.00075 * mean_close

    if current_close < mean_close - threshold:
        rest.place_order(
            SYMBOL,
            "BUY",
            1,
            current_close - (TARGET_TICKS / 4),
            current_close + (TARGET_TICKS / 4),
            "MARKET",
            current_close,
        )


# ---------- Main Runner -------------
def main():
    rest = IronbeamREST(BASE_URL, USERNAME)
    token = rest.auth(USERNAME, API_KEY)
    print("Authentication successful, token acquired.")

    bar_thread = threading.Thread(
        target=bar_builder, args=(lambda bar: strategy(rest, bar),), daemon=True
    )
    bar_thread.start()
    start_streaming(rest)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        stop_event.set()
        print("Shutdown initiated.")
