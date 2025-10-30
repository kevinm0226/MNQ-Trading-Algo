import pandas as pd
import os


def label_csv(file_path):
    df = pd.read_csv(file_path, header=None)
    df.columns = ["time", "open", "high", "low", "close", "volume"]
    df.to_csv(file_path, index=False)


if __name__ == "__main__":
    folder = "data"
    for filename in os.listdir(folder):
        if filename.endswith(".csv"):
            file_path = os.path.join(folder, filename)
            label_csv(file_path)
            print(f"Labeled {filename}")
