import pandas as pd

FILE = "cardata.csv"
DATE_COLUMN = "date"

def parse_mixed_date(x):
    x = str(x)
    if len(x) == 7:  # e.g., 5022018
        return pd.to_datetime(x, format="%m%d%Y", errors="coerce")
    elif len(x) == 8:  # e.g., 12052018
        return pd.to_datetime(x, format="%m%d%Y", errors="coerce")
    else:
        return pd.NaT  # Not a valid date

def main():
    df = pd.read_csv(FILE)

    # Apply custom parser
    df[DATE_COLUMN] = df[DATE_COLUMN].apply(parse_mixed_date)

    # Save back as U.S. format
    df[DATE_COLUMN] = df[DATE_COLUMN].dt.strftime("%m/%d/%Y")

    # Overwrite the file
    df.to_csv(FILE, index=False)
    print(f"✅ Dates fixed (both 7- and 8-digit) and saved back to {FILE}")

if __name__ == "__main__":
    main()
