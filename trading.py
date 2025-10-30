# ironbeam_client_demo.py
import json
import time as timemod
import threading
import queue
import requests
from websocket import WebSocketApp
import traceback
from datetime import datetime, time, date
from collections import deque
import csv
import os
import numpy as np
from zoneinfo import ZoneInfo

# CSV_FILE = "tests/live_1.csv"
DATA_GATHER_FILE = "data/MNQ_1s_10.29.2025.csv"

# if not os.path.exists(CSV_FILE):
#     with open(CSV_FILE, mode="w", newline="") as f:
#         writer = csv.DictWriter(
#             f,
#             fieldnames=[
#                 "side",
#                 "entry",
#                 "exit",
#                 "ticks",
#                 "result",
#                 "duration_sec",
#                 "start_time",
#                 "end_time",
#             ],
#         )
#         writer.writeheader()

# if not os.path.exists(DATA_GATHER_FILE):
#     with open(CSV_FILE, mode="w", newline="") as f:
#         writer = csv.DictWriter(
#             f, fieldnames=["t", "open", "high", "low", "close", "volume"]
#         )
#         writer.writeheader()


# =======================
# CONFIGURATION (Plug In)
# =======================
API_KEY = "fcf40e424c514511a47113896dd99329"
ACCOUNT_ID = "23210937"
BASE_URL = "https://live.ironbeamapi.com"
SYMBOL = "XCME:MNQ.Z25"
TICK_SIZE = 0.25
TICK_VALUE = 0.50
TICKS = 50
open_trades = {}
MAX_OPEN = 1
DAILY_DRAWDOWN_LIMIT = 100
current_equity = 0
peak_equity = 0
trading_paused = False
num_contracts = 1


tick_q = queue.Queue()
bar_q = queue.Queue()
stop_event = threading.Event()


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
        url = f"{self.base}/v2/stream/create"
        r = self.session.get(url, timeout=10)
        r.raise_for_status()
        return r.json()

    def get_balance(self):
        url = f"{self.base}/v2/account/{self.account_id}/balance"
        try:
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            balance = data["balances"][0]["totalEquity"]
            print(f"💰 Current balance: {balance}")
            return float(balance) if balance else None

        except requests.exceptions.RequestException as e:
            print(f"❌ Error fetching open orders: {e}")
            return []

    def place_order(
        self,
        symbol: str,
        side: str,
        qty: int = 1,
        order_type: str = "MARKET",
    ):

        url = f"{self.base}/v2/order/{self.account_id}/place"
        body = {
            "exchSym": symbol,
            "side": side.upper(),
            "orderType": order_type,
            "quantity": qty,
        }

        r = self.session.post(url, json=body, timeout=10)
        try:
            return r.json()
        except Exception:
            return {"error": r.text}

    def get_open_orders(self):

        url = f"{self.base}/v2/account/{self.account_id}/positions"
        headers = {"Authorization": f"Bearer {self.token}"}

        try:
            resp = self.session.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            positions = data.get("positions") or []

            pos_list = []
            for pos in positions:
                pos_list.append(
                    {
                        "symbol": pos.get("exchSym"),
                        "side": pos.get("side"),
                        "quantity": pos.get("quantity"),
                        "entry_price": pos.get("price"),
                        "unrealizedPL": float(pos.get("unrealizedPL", 0)),
                        "positionId": pos.get("positionId"),
                    }
                )

            return pos_list

        except requests.exceptions.RequestException as e:
            print(f"❌ Error fetching open orders: {e}")
            return []


# ---------- Bar Aggregator -------------
def bar_builder(trade_only: bool = True):

    current_sec = int(timemod.time())
    o = h = l = c = None
    vol = 0

    while not stop_event.is_set():
        sec_start = timemod.time()

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
            if "price" in t:  # trade tick
                prices.append(t["price"])
                sizes.append(t.get("size", 0))
            elif not trade_only and "bid" in t and "ask" in t:  # quote tick
                mid = (t["bid"] + t["ask"]) / 2.0
                prices.append(mid)
                sizes.append((t.get("bid_size", 0) + t.get("ask_size", 0)) / 2.0)

        # Update OHLCV
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

        now_sec = int(timemod.time())
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

            with open(DATA_GATHER_FILE, mode="a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=bar.keys())
                writer.writerow(bar)

            current_sec = now_sec
            o = h = l = c
            vol = 0

        elapsed = timemod.time() - sec_start
        if elapsed < 1.0:
            timemod.sleep(1.0 - elapsed)


from collections import deque


def strategy(rest, bar):

    if not hasattr(strategy, "closes"):
        strategy.closes = deque(maxlen=120)

    balance = rest.get_balance()

    if balance <= 650:
        print("no soup for you.......")
        return None

    strategy.closes.append(bar["close"])

    if len(strategy.closes) < 120:
        print("wait for it....")
        return None

    closes = np.array(strategy.closes)
    mean_close = closes.mean()
    current_close = closes[-1]

    threshold = 0.00075 * mean_close

    open_orders = rest.get_open_orders()

    if len(open_orders) > 0:
        pos = open_orders[0]
        pl = pos["unrealizedPL"]

        if pl >= 25:
            rest.place_order(
                SYMBOL,
                "SELL",
                num_contracts,
                "MARKET",
            )
        elif pl <= -25:
            rest.place_order(
                SYMBOL,
                "SELL",
                num_contracts,
                "MARKET",
            )
        return None

    now = datetime.now(ZoneInfo("America/New_York"))
    stop_dt = datetime(2025, 10, 30, 16, 0, tzinfo=ZoneInfo("America/New_York"))

    if now >= stop_dt:
        print(
            "🛑 Market closed for the day — stopping trading after Oct 30, 2025 4:00 PM ET."
        )
        return None

    if current_close < mean_close - threshold:
        rest.place_order(
            SYMBOL,
            "BUY",
            num_contracts,
            "MARKET",
        )

    return None


strategy.ranges = deque(maxlen=20)


def trade_loop(rest):
    while not stop_event.is_set():
        try:
            bar = bar_q.get(timeout=1)
        except queue.Empty:
            continue

        strategy(rest, bar)


# ========== WEBSOCKET STREAMING (correct usage of websocket-client) ==========
def start_streaming(rest):
    while not stop_event.is_set():
        try:
            sr = rest.create_stream()
            stream_id = sr.get("streamId")
            if not stream_id:
                print("No streamId returned:", sr)
                timemod.sleep(5)
                continue

            ws_url = (
                f"wss://live.ironbeamapi.com/v2/stream/{stream_id}?token={rest.token}"
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
            timemod.sleep(1)

        except Exception as e:
            print("Exception in start_streaming:", e)
            traceback.print_exc()
            timemod.sleep(2)


# ---------- Main Runner -------------
def main():
    rest = IronbeamREST(BASE_URL, ACCOUNT_ID)
    token = rest.auth(ACCOUNT_ID, API_KEY)
    print("Authentication successful, token acquired.")

    # Threads
    threading.Thread(target=bar_builder, daemon=True).start()
    threading.Thread(target=trade_loop, args=(rest,), daemon=True).start()

    # Start data stream
    start_streaming(rest)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        stop_event.set()
        print("Shutdown initiated.")
