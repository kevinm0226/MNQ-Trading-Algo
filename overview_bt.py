import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

CSV_FILE = "tests/test_9.csv"

# Constants for MNQ
TICK_VALUE = 0.50  # $ per tick per contract


def analyze_trades():
    df = pd.read_csv(CSV_FILE)

    if df.empty:
        print("No trades found in CSV.")
        return

    # Add PnL in $
    df["pnl"] = df["ticks"] * TICK_VALUE
    df["cum_pnl"] = df["pnl"].cumsum()

    # Basic stats
    total_trades = len(df)
    wins = (df["result"] == "WIN").sum()
    losses = (df["result"] == "LOSS").sum()
    win_rate = wins / total_trades * 100

    avg_ticks = df["ticks"].mean()
    avg_win = df[df["result"] == "WIN"]["ticks"].mean()
    avg_loss = df[df["result"] == "LOSS"]["ticks"].mean()

    avg_pnl = df["pnl"].mean()
    avg_win_pnl = df[df["result"] == "WIN"]["pnl"].mean()
    avg_loss_pnl = df[df["result"] == "LOSS"]["pnl"].mean()

    # Equity curve (cumulative ticks)
    df["cum_ticks"] = df["ticks"].cumsum()

    # Max drawdown in ticks and $
    roll_max_ticks = df["cum_ticks"].cummax()
    drawdown_ticks = df["cum_ticks"] - roll_max_ticks
    max_dd_ticks = drawdown_ticks.min()

    roll_max_pnl = df["cum_pnl"].cummax()
    drawdown_pnl = df["cum_pnl"] - roll_max_pnl
    max_dd_pnl = drawdown_pnl.min()

    # Profit Factor
    gross_profit = df[df["pnl"] > 0]["pnl"].sum()
    gross_loss = df[df["pnl"] < 0]["pnl"].sum()
    profit_factor = gross_profit / abs(gross_loss) if gross_loss != 0 else np.inf

    # Sharpe Ratio (per trade basis)
    returns = df["pnl"]
    sharpe_ratio = (
        (returns.mean() / returns.std()) * np.sqrt(len(returns))
        if returns.std() != 0
        else np.nan
    )

    # Average trade duration
    if "duration_sec" in df.columns:
        avg_duration_sec = df["duration_sec"].mean()
        minutes = int(avg_duration_sec // 60)
        seconds = int(avg_duration_sec % 60)
        avg_duration_str = f"{minutes}m {seconds}s"
    else:
        avg_duration_str = "N/A"

    # Print results
    print("===== Trade Analysis =====")
    print(f"Total trades: {total_trades}")
    print(f"Wins: {wins}, Losses: {losses}, Win rate: {win_rate:.2f}%")
    print(f"Avg ticks per trade: {avg_ticks:.2f} → ${avg_pnl:.2f}")
    print(f"Avg win: {avg_win:.2f} ticks → ${avg_win_pnl:.2f}")
    print(f"Avg loss: {avg_loss:.2f} ticks → ${avg_loss_pnl:.2f}")
    print(f"Max drawdown: {max_dd_ticks} ticks → ${max_dd_pnl:.2f}")
    print(f"Net result: {df['ticks'].sum()} ticks → ${df['pnl'].sum():.2f}")
    print(f"Profit Factor: {profit_factor:.2f}")
    print(f"Sharpe Ratio: {sharpe_ratio:.2f}")
    print(f"Avg time in trade: {avg_duration_str}")

    plt.figure(figsize=(12, 5))
    plt.plot(df["cum_pnl"], label="Equity Curve ($)", color="green")
    plt.xlabel("Trade #")
    plt.ylabel("Cumulative PnL ($)")
    plt.title("Equity Curve ($)")
    plt.grid(True)
    plt.legend()

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    analyze_trades()
