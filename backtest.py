import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from collections import deque
import time
from datetime import datetime
import pytz

# === Config ===
TICK_SIZE = 0.25
TICK_VALUE = 0.50
OHLC_PATH = "OHLC"


def strategy(bar, state, lookback, threshold_factor):
    if "closes" not in state:
        state["closes"] = deque(maxlen=lookback)

    state["closes"].append(bar["close"])

    if len(state["closes"]) < lookback:
        return None

    closes = np.array(state["closes"])
    mean_close = closes.mean()
    current_close = closes[-1]
    threshold = threshold_factor * mean_close

    if current_close < mean_close - threshold:
        return {"side": "BUY", "entry": current_close}

    return None


COMMISSION_PER_TRADE = 0.78


def run_backtest(df, strategy):
    trades = []
    state = {"active_trade": None}

    for idx, bar in df.iterrows():
        if state["active_trade"]:
            trade = state["active_trade"]
            entry = trade["entry"]
            stop = trade["stop"]
            target = trade["target"]

            stopped = exited = False
            exit_price = None

            # Check stop first
            if bar["open"] <= stop:
                stopped, exit_price = True, stop
            elif bar["open"] >= target:
                exited, exit_price = True, target
            else:
                if bar["high"] >= target:
                    exited, exit_price = True, target
                elif bar["low"] <= stop:
                    stopped, exit_price = True, stop

            if stopped or exited:
                ticks = int((exit_price - entry) / TICK_SIZE)
                pnl = ticks * TICK_VALUE - COMMISSION_PER_TRADE
                duration_bars = idx - trade["entry_idx"]

                # ✅ Get entry + exit timestamp from CSV and convert to EST
                entry_ts = df.loc[trade["entry_idx"], "time"]
                exit_ts = df.loc[idx, "time"]

                entry_time_est = datetime.fromtimestamp(entry_ts, pytz.utc).astimezone(
                    pytz.timezone("US/Eastern")
                )
                exit_time_est = datetime.fromtimestamp(exit_ts, pytz.utc).astimezone(
                    pytz.timezone("US/Eastern")
                )

                trades.append(
                    {
                        "side": "BUY",
                        "entry": entry,
                        "exit": exit_price,
                        "ticks": ticks,
                        "pnl": pnl,
                        "duration_sec": duration_bars,
                        "entry_time_est": entry_time_est,
                        "exit_time_est": exit_time_est,
                    }
                )

                state["active_trade"] = None

        if not state["active_trade"]:
            signal = strategy(bar, state)
            if signal and signal["side"] == "BUY":
                entry = signal["entry"]
                stop = entry - STOP_TICKS * TICK_SIZE
                target = entry + STOP_TICKS * TICK_SIZE

                state["active_trade"] = {
                    "side": "BUY",
                    "entry": entry,
                    "stop": stop,
                    "target": target,
                    "entry_idx": idx,
                }

    return pd.DataFrame(trades)


if __name__ == "__main__":
    data_files = [
        # "data/MNQ_1s_10.07.2025.csv",
        # "data/MNQ_1s_10.08.2025.csv",
        # "data/MNQ_1s_10.20.2025.csv",
        # "data/MNQ_1s_10.21.2025.csv",
        # "data/MNQ_1s_10.22.2025.csv",
        # "data/MNQ_1s_10.23.2025.csv",
        # "data/MNQ_1s_10.24.2025.csv",
        # "data/MNQ_1s_10.28.2025.csv",
        "data/MNQ_1s_10.29.2025.csv",
    ]

    lookback_values = [120]
    threshold_values = [0.00075]
    stop_tick_values = [50]

    df_list = [pd.read_csv(f) for f in data_files]
    df = pd.concat(df_list, ignore_index=True)

    total_tests = len(lookback_values) * len(threshold_values) * len(stop_tick_values)
    test_counter = 0
    start_time = time.time()
    results = []
    start_time = time.time()

    for lookback in lookback_values:
        for threshold in threshold_values:
            for stop_ticks in stop_tick_values:
                test_counter += 1
                elapsed = time.time() - start_time
                pct = (test_counter / total_tests) * 100
                print(
                    f"Progress: {test_counter}/{total_tests} ({pct:.2f}%) | Elapsed: {elapsed:.1f}s",
                    end="\r",
                )

                STOP_TICKS = stop_ticks

                def strategy_wrapper(bar, state):
                    return strategy(
                        bar, state, lookback=lookback, threshold_factor=threshold
                    )

                trades = run_backtest(df, strategy_wrapper)

                if not trades.empty:
                    total_pnl = trades["pnl"].sum()
                    win_rate = (trades["ticks"] > 0).mean() * 100
                    trades["equity"] = trades["pnl"].cumsum()
                    trades["running_max"] = trades["equity"].cummax()
                    trades["drawdown"] = trades["running_max"] - trades["equity"]
                    max_drawdown = trades["drawdown"].max()
                    avg_duration_sec = trades["duration_sec"].mean()
                    minutes, seconds = divmod(int(avg_duration_sec), 60)
                    avg_duration = f"{minutes}m {seconds}s"
                    # print("\n=== Trades with Entry/Exit Times (EST) ===")
                    # print(trades[["entry_time_est", "exit_time_est", "pnl", "ticks"]])
                else:
                    total_pnl = 0
                    win_rate = 0
                    avg_duration = "0m 0s"
                    max_drawdown = 0

                results.append(
                    {
                        "lookback": lookback,
                        "threshold": threshold,
                        "stop_ticks": stop_ticks,
                        "total_pnl": total_pnl,
                        "win_rate": win_rate,
                        "num_trades": len(trades),
                        "avg_time_in_trade": avg_duration,
                        "max_drawdown": max_drawdown,
                    }
                )

    equity = trades["pnl"].cumsum().values
    equity = np.insert(equity, 0, 0)
    print("\n===== Optimization Complete =====")
    results_df = pd.DataFrame(results)
    best = results_df.sort_values(by="total_pnl", ascending=False).head(10)
    print(best)
    plt.figure(figsize=(12, 6))
    plt.plot(equity)
    plt.title(
        f"Equity Curve (Lookback={lookback}, Threshold={threshold}, Stop={stop_ticks})"
    )
    plt.xlabel("Trade Number")
    plt.ylabel("Cumulative PnL")
    plt.grid(True)
    plt.show()
