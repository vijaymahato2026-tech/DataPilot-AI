"""
universal_reader.py — lightweight helper that wraps app.py's load/profile logic
so it can be used or tested independently.
"""
from pathlib import Path
import pandas as pd
from pypdf import PdfReader


def _read_pdf(path):
    reader = PdfReader(str(path))
    rows = [{"page": n, "text": page.extract_text() or ""}
            for n, page in enumerate(reader.pages, start=1)]
    if not rows:
        raise ValueError("The PDF contains no pages.")
    df = pd.DataFrame(rows)
    if not any(str(v).strip() for v in df["text"]):
        raise ValueError("No selectable text found. Scanned PDFs need OCR.")
    return df


def _detect_field_type(series):
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    if pd.api.types.is_numeric_dtype(series):
        return "number"
    values = series.dropna()
    if not values.empty:
        parsed = pd.to_datetime(values, errors="coerce")
        if parsed.notna().mean() >= 0.9:
            return "datetime"
    return "text"


def load_dataframe(file_path):
    """Load a CSV / XLSX / JSON / PDF file and return a DataFrame."""
    path = Path(file_path)
    ext = path.suffix.lower()
    if ext == ".csv":
        try:
            return pd.read_csv(path, encoding="utf-8-sig")
        except UnicodeDecodeError:
            return pd.read_csv(path, encoding="cp1252")
    if ext == ".xlsx":
        return pd.read_excel(path, engine="openpyxl")
    if ext == ".json":
        import json
        with open(path, "r", encoding="utf-8-sig") as f:
            payload = json.load(f)
        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, dict):
            records = (payload.get("data") if isinstance(payload.get("data"), list)
                       else payload.get("records") if isinstance(payload.get("records"), list)
                       else [payload])
        else:
            raise ValueError("JSON must contain an array of records or an object.")
        if not records:
            raise ValueError("The JSON dataset is empty.")
        return pd.json_normalize(records)
    if ext == ".pdf":
        return _read_pdf(path)
    raise ValueError("Unsupported format. Use CSV, XLSX, JSON or PDF.")


def analyze_dataset(file_path):
    """Return a profile dict for every sheet/tab in the file."""
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext == ".xlsx":
        xl = pd.ExcelFile(path, engine="openpyxl")
        sheets = xl.sheet_names
    else:
        sheets = ["Sheet1"]

    result = {}
    for sheet in sheets:
        if ext == ".xlsx":
            df = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
        else:
            df = load_dataframe(path)

        fields = []
        for col in df.columns:
            s = df[col]
            fields.append({
                "name": str(col),
                "data_type": _detect_field_type(s),
                "missing": int(s.isna().sum()),
                "unique": int(s.nunique(dropna=True)),
            })

        result[sheet] = {
            "total_rows": int(len(df)),
            "total_columns": int(len(df.columns)),
            "duplicate_rows": int(df.duplicated().sum()),
            "fields": fields,
        }

    return result


if __name__ == "__main__":
    file_path = input("Enter your CSV, XLSX, JSON or PDF file path: ")
    try:
        data = analyze_dataset(file_path)
        for sheet_name, details in data.items():
            print(f"\nSheet: {sheet_name}")
            print(f"Rows: {details['total_rows']}")
            print(f"Columns: {details['total_columns']}")
            print(f"Duplicates: {details['duplicate_rows']}")
            print("\nDetected fields:")
            for field in details["fields"]:
                print(f"  {field['name']} | {field['data_type']}")
        print("\nUNIVERSAL DATA READER WORKING SUCCESSFULLY!")
    except Exception as error:
        print(f"\nERROR: {error}")
