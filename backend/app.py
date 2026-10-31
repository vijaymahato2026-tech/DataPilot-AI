import os
import json
import uuid
import logging
import mimetypes
import tempfile
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
from flask import Flask, jsonify, request, render_template
from werkzeug.utils import secure_filename
from supabase import create_client
from dotenv import load_dotenv
from pypdf import PdfReader

# --------------------------------------------------
# Configuration
# --------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = BASE_DIR / "backend" / "templates"
STATIC_DIR = BASE_DIR / "backend" / "static"
TEMP_DIR = BASE_DIR / "uploads" / "temporary"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")

app = Flask(__name__, template_folder=str(TEMPLATE_DIR),
            static_folder=str(STATIC_DIR))
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
app.config["JSON_SORT_KEYS"] = False
app.secret_key = os.getenv("FLASK_SECRET_KEY") or os.urandom(32)

ALLOWED_EXTENSIONS = {"csv", "xlsx", "json", "pdf"}
BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "datapilot-files")
SUPABASE_URL = os.getenv("SUPABASE_URL")
# Server-side secret key only. Never expose this in frontend code.
SUPABASE_KEY = os.getenv("SUPABASE_SECRET_KEY")
supabase = None

logging.basicConfig(level=logging.INFO)
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        app.logger.info("Supabase server client initialized.")
    except Exception:
        app.logger.exception("Supabase initialization failed.")
else:
    app.logger.error("Missing SUPABASE_URL or SUPABASE_SECRET_KEY in .env")


def require_supabase():
    if supabase is None:
        raise RuntimeError("Supabase is not configured. Check .env.")


# --------------------------------------------------
# Data loading and profiling
# --------------------------------------------------
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def read_pdf(path):
    reader = PdfReader(str(path))
    rows = [{"page": n, "text": page.extract_text() or ""}
            for n, page in enumerate(reader.pages, start=1)]
    if not rows:
        raise ValueError("The PDF contains no pages.")
    df = pd.DataFrame(rows)
    if not any(str(v).strip() for v in df["text"]):
        raise ValueError("No selectable text found. Scanned PDFs need OCR.")
    return df


def load_dataset(path):
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".csv":
        try:
            return pd.read_csv(path, encoding="utf-8-sig")
        except UnicodeDecodeError:
            return pd.read_csv(path, encoding="cp1252")
    if ext == ".xlsx":
        return pd.read_excel(path, engine="openpyxl")
    if ext == ".json":
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                payload = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON file: {e}") from e
        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, dict):
            records = payload.get("data") if isinstance(payload.get("data"), list) else payload.get("records") if isinstance(payload.get("records"), list) else [payload]
        else:
            raise ValueError("JSON must contain an array of records or an object.")
        if not records:
            raise ValueError("The JSON dataset is empty.")
        return pd.json_normalize(records)
    if ext == ".pdf":
        return read_pdf(path)
    raise ValueError("Unsupported format. Use CSV, XLSX, JSON or PDF.")


def json_safe(value):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if value is None:
        return None
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value if isinstance(value, (str, int, float, bool)) else str(value)


def detect_field_type(series):
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


def create_dataset_profile(df):
    fields = []
    for column in df.columns:
        s = df[column]
        kind = detect_field_type(s)
        missing = int(s.isna().sum())
        unique = int(s.nunique(dropna=True))
        fields.append({
            "name": str(column), "data_type": kind, "field_type": kind,
            "pandas_type": str(s.dtype), "dtype": str(s.dtype),
            "nullable": bool(s.isna().any()), "missing": missing,
            "missing_values": missing, "unique": unique,
            "unique_values": unique,
            "sample_values": [json_safe(v) for v in s.dropna().head(5)]
        })
    return {
        "total_rows": int(len(df)), "total_columns": int(len(df.columns)),
        "duplicate_rows": int(df.duplicated().sum()), "columns": fields
    }


def validate_dataframe(df):
    if df.empty:
        raise ValueError("The uploaded dataset is empty.")
    if len(df.columns) == 0:
        raise ValueError("Dataset contains no columns.")
    if not df.columns.is_unique:
        raise ValueError("Duplicate column names are not supported.")
    if len(df.columns) > 200:
        raise ValueError("Maximum 200 columns are supported.")


def dataframe_preview(df, limit=100):
    preview = df.head(limit).astype(object)
    preview = preview.where(pd.notna(preview), None)
    return json.loads(preview.to_json(orient="records", date_format="iso", force_ascii=False))


# --------------------------------------------------
# Supabase helpers
# --------------------------------------------------
def get_dataset(dataset_id):
    require_supabase()
    try:
        result = supabase.table("datasets").select("*").eq("id", dataset_id).limit(1).execute()
        rows = result.data or []
        if not rows:
            return None, (jsonify({"success": False, "error": "Dataset not found."}), 404)
        return rows[0], None
    except Exception:
        app.logger.exception("Dataset metadata lookup failed.")
        return None, (jsonify({"success": False, "error": "Could not retrieve dataset from Supabase."}), 500)


def download_to_temp(dataset):
    require_supabase()
    suffix = Path(dataset["name"]).suffix.lower()
    handle = tempfile.NamedTemporaryFile(prefix="datapilot_", suffix=suffix,
                                         dir=TEMP_DIR, delete=False)
    path = Path(handle.name)
    handle.close()
    try:
        content = supabase.storage.from_(BUCKET).download(dataset["storage_path"])
        path.write_bytes(content)
        return path
    except Exception:
        path.unlink(missing_ok=True)
        raise


# --------------------------------------------------
# Pages
# --------------------------------------------------
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/dataset/<dataset_id>")
def dataset_page(dataset_id):
    return render_template("dataset.html")


@app.route("/dashboards")
def dashboards_page():
    return render_template("dashboards.html")


@app.route("/visual/<dataset_id>")
def visual_page(dataset_id):
    return render_template("visual.html")


# --------------------------------------------------
# Health
# --------------------------------------------------
@app.route("/health")
def health():
    initialized = supabase is not None
    return jsonify({
        "success": True, "project": "DataPilot AI", "status": "healthy",
        "version": "2.0.0", "supabase_client_initialized": initialized,
        "storage_bucket": BUCKET,
        "supabase_message": "Server client initialized." if initialized else "Check Supabase credentials in .env.",
        "analytics_engine": "Pandas",
        "supported_file_formats": ["csv", "xlsx", "json", "pdf"]
    })


# --------------------------------------------------
# Upload: validate locally, persist in Supabase Storage + DB
# --------------------------------------------------
@app.route("/api/datasets/upload", methods=["POST"])
def upload_dataset():
    if "file" not in request.files:
        return jsonify({"success": False, "error": "Please select a CSV, Excel, JSON or PDF file."}), 400
    incoming = request.files["file"]
    if not incoming.filename:
        return jsonify({"success": False, "error": "No file selected."}), 400
    if not allowed_file(incoming.filename):
        return jsonify({"success": False, "error": "Supported formats are CSV, XLSX, JSON and PDF."}), 400

    name = secure_filename(incoming.filename)
    if not name:
        return jsonify({"success": False, "error": "Invalid filename."}), 400

    require_supabase()
    dataset_id = str(uuid.uuid4())
    ext = Path(name).suffix.lower()
    storage_path = f"{dataset_id}/{name}"
    temp_path = TEMP_DIR / f"{dataset_id}{ext}"
    object_uploaded = False

    try:
        incoming.save(temp_path)
        size = temp_path.stat().st_size
        if size == 0:
            raise ValueError("The uploaded file is empty.")
        df = load_dataset(temp_path)
        validate_dataframe(df)
        profile = create_dataset_profile(df)

        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        supabase.storage.from_(BUCKET).upload(
            path=storage_path,
            file=temp_path.read_bytes(),
            file_options={"content-type": mime, "upsert": "false"}
        )
        object_uploaded = True

        metadata = {
            "id": dataset_id, "name": name,
            "file_type": ext.lstrip("."), "storage_path": storage_path,
            "file_size": size, "created_at": datetime.now(timezone.utc).isoformat(),
            "profile": profile
        }
        supabase.table("datasets").insert(metadata).execute()

        return jsonify({
            "success": True,
            "message": "Dataset uploaded to Supabase Storage successfully.",
            "dataset_id": dataset_id, "dataset_name": name,
            "file_type": ext.lstrip("."), "file_size": size,
            "profile": profile,
            "preview_url": f"/api/datasets/{dataset_id}/preview",
            "profile_url": f"/api/datasets/{dataset_id}/profile"
        }), 201
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception:
        app.logger.exception("Supabase upload failed.")
        if object_uploaded:
            try:
                supabase.storage.from_(BUCKET).remove([storage_path])
            except Exception:
                app.logger.exception("Could not roll back uploaded Storage object.")
        return jsonify({
            "success": False,
            "error": "Supabase upload failed. Check the Flask terminal for details and verify the bucket and database schema."
        }), 500
    finally:
        # Local file is only a short-lived processing copy.
        temp_path.unlink(missing_ok=True)


# --------------------------------------------------
# Preview
# --------------------------------------------------
@app.route("/api/datasets/<dataset_id>/preview")
def preview_dataset(dataset_id):
    dataset, error = get_dataset(dataset_id)
    if error:
        return error
    temp = None
    try:
        temp = download_to_temp(dataset)
        df = load_dataset(temp)
        records = dataframe_preview(df, 100)
        columns = [str(c) for c in df.columns]
        return jsonify({
            "success": True, "dataset_id": dataset_id,
            "dataset_name": dataset["name"], "file_type": dataset.get("file_type"),
            "total_rows": int(len(df)), "preview_limit": 100,
            "columns": columns,
            "rows": [[record.get(c) for c in columns] for record in records],
            "data": records
        })
    except Exception:
        app.logger.exception("Dataset preview failed.")
        return jsonify({"success": False, "error": "Could not generate preview from Supabase Storage."}), 500
    finally:
        if temp:
            temp.unlink(missing_ok=True)


# --------------------------------------------------
# Profile
# --------------------------------------------------
@app.route("/api/datasets/<dataset_id>/profile")
def dataset_profile(dataset_id):
    dataset, error = get_dataset(dataset_id)
    if error:
        return error
    return jsonify({
        "success": True, "dataset_id": dataset_id,
        "dataset_name": dataset["name"], "profile": dataset.get("profile") or {}
    })


# --------------------------------------------------
# List
# --------------------------------------------------
@app.route("/api/datasets")
def list_datasets():
    try:
        require_supabase()
        result = supabase.table("datasets").select(
            "id,name,file_type,file_size,created_at,profile"
        ).order("created_at", desc=True).execute()
        items = []
        for row in result.data or []:
            profile = row.get("profile") or {}
            items.append({
                "id": row["id"], "name": row["name"],
                "file_type": row.get("file_type"),
                "file_size": row.get("file_size", 0),
                "created_at": row.get("created_at"),
                "total_rows": profile.get("total_rows", 0),
                "total_columns": profile.get("total_columns", 0)
            })
        return jsonify({"success": True, "total_datasets": len(items), "datasets": items})
    except Exception:
        app.logger.exception("Dataset listing failed.")
        return jsonify({"success": False, "error": "Could not list datasets from Supabase."}), 500


# --------------------------------------------------
# Chart generation
# --------------------------------------------------
@app.route("/api/datasets/<dataset_id>/chart", methods=["POST"])
def generate_chart(dataset_id):
    dataset, error = get_dataset(dataset_id)
    if error:
        return error
    temp = None
    try:
        cfg = request.get_json(silent=True) or {}
        chart_type = cfg.get("chart_type", "bar")
        x_axis = cfg.get("x_axis")
        y_axis = cfg.get("y_axis")
        aggregation = cfg.get("aggregation", "sum")
        legend = cfg.get("legend_field")

        charts = {"bar", "line", "pie", "donut", "area", "scatter", "histogram", "box", "table"}
        aggregations = {"sum", "avg", "count", "min", "max"}
        if chart_type not in charts:
            return jsonify({"success": False, "error": "Unsupported chart type."}), 400
        if aggregation not in aggregations:
            return jsonify({"success": False, "error": "Unsupported aggregation."}), 400

        temp = download_to_temp(dataset)
        df = load_dataset(temp)
        if x_axis not in df.columns:
            return jsonify({"success": False, "error": "Please select a valid X-axis field."}), 400
        if chart_type not in {"histogram", "table"} and y_axis not in df.columns:
            return jsonify({"success": False, "error": "Please select a valid Y-axis field."}), 400
        if legend and legend not in df.columns:
            return jsonify({"success": False, "error": "Invalid legend field."}), 400

        if chart_type == "table":
            return jsonify({"success": True, "chart_type": "table",
                            "columns": [str(c) for c in df.columns],
                            "records": dataframe_preview(df, 500)})

        if chart_type == "histogram":
            values = pd.to_numeric(df[x_axis], errors="coerce").dropna()
            if values.empty:
                return jsonify({"success": False, "error": "Histogram requires a numeric field."}), 400
            bins = pd.cut(values, bins=min(20, max(1, values.nunique())))
            grouped_hist = bins.value_counts(sort=False)
            labels = [str(v) for v in grouped_hist.index]
            counts = [int(v) for v in grouped_hist.values]
            plotly_data = [{"type": "bar", "x": labels, "y": counts, "marker": {"color": "#6C63FF"}}]
            plotly_layout = {"xaxis": {"title": x_axis}, "yaxis": {"title": "Count"},
                             "plot_bgcolor": "#fff", "paper_bgcolor": "#fff", "margin": {"t": 30, "b": 80}}
            return jsonify({"success": True, "chart_type": "histogram",
                            "data": plotly_data, "layout": plotly_layout})

        if chart_type in {"scatter", "box"}:
            sample = df[[x_axis, y_axis]].copy()
            sample[y_axis] = pd.to_numeric(sample[y_axis], errors="coerce")
            sample = sample.dropna().head(2000)
            x_vals = sample[x_axis].astype(str).tolist()
            y_vals = sample[y_axis].tolist()
            if chart_type == "scatter":
                plotly_data = [{"type": "scatter", "mode": "markers", "x": x_vals, "y": y_vals,
                                "marker": {"color": "#6C63FF", "opacity": 0.7}}]
            else:
                plotly_data = [{"type": "box", "y": y_vals, "name": y_axis, "marker": {"color": "#6C63FF"}}]
            plotly_layout = {"xaxis": {"title": x_axis}, "yaxis": {"title": y_axis},
                             "plot_bgcolor": "#fff", "paper_bgcolor": "#fff", "margin": {"t": 30, "b": 80}}
            return jsonify({"success": True, "chart_type": chart_type,
                            "data": plotly_data, "layout": plotly_layout})

        work = df.copy()
        if aggregation != "count":
            work[y_axis] = pd.to_numeric(work[y_axis], errors="coerce")
        group_cols = [x_axis]
        if legend and legend != x_axis:
            group_cols.append(legend)

        if aggregation == "count":
            grouped = work.groupby(group_cols, dropna=False)[y_axis].count().reset_index(name="chart_value")
        else:
            op = {"sum": "sum", "avg": "mean", "min": "min", "max": "max"}[aggregation]
            grouped = work.groupby(group_cols, dropna=False)[y_axis].agg(op).reset_index(name="chart_value")

        grouped = grouped.dropna(subset=["chart_value"]).head(500)
        labels = grouped[x_axis].fillna("Unknown").astype(str).tolist()
        values_list = grouped["chart_value"].tolist()

        PLOTLY_COLORS = ["#6C63FF", "#19C6D1", "#FF6B6B", "#FFD166", "#06D6A0", "#8338EC", "#FB5607", "#3A86FF"]
        common_layout = {
            "plot_bgcolor": "#fff", "paper_bgcolor": "#fff",
            "xaxis": {"title": x_axis, "tickangle": -30},
            "yaxis": {"title": f"{aggregation.upper()} of {y_axis}"},
            "legend": {"orientation": "h", "y": -0.25},
            "margin": {"t": 30, "b": 100},
        }

        if chart_type in {"bar", "area", "line"}:
            if legend and legend != x_axis:
                group_vals = grouped[legend].fillna("Unknown").astype(str).tolist()
                unique_groups = list(dict.fromkeys(group_vals))
                traces = []
                for i, grp in enumerate(unique_groups):
                    mask = [g == grp for g in group_vals]
                    t = {
                        "name": grp,
                        "x": [labels[j] for j, m in enumerate(mask) if m],
                        "y": [values_list[j] for j, m in enumerate(mask) if m],
                        "marker": {"color": PLOTLY_COLORS[i % len(PLOTLY_COLORS)]},
                    }
                    if chart_type == "bar":
                        t["type"] = "bar"
                    elif chart_type == "line":
                        t["type"] = "scatter"; t["mode"] = "lines+markers"
                    else:
                        t["type"] = "scatter"; t["mode"] = "lines"; t["fill"] = "tozeroy"
                    traces.append(t)
                if chart_type == "bar":
                    common_layout["barmode"] = "group"
            else:
                t = {"x": labels, "y": values_list, "marker": {"color": PLOTLY_COLORS[0]}}
                if chart_type == "bar":
                    t["type"] = "bar"
                elif chart_type == "line":
                    t["type"] = "scatter"; t["mode"] = "lines+markers"; t["line"] = {"color": PLOTLY_COLORS[0]}
                else:
                    t["type"] = "scatter"; t["mode"] = "lines"; t["fill"] = "tozeroy"; t["line"] = {"color": PLOTLY_COLORS[0]}
                traces = [t]
            return jsonify(json_safe({"success": True, "chart_type": chart_type,
                                      "data": traces, "layout": common_layout}))

        if chart_type in {"pie", "donut"}:
            trace = {
                "type": "pie", "labels": labels, "values": values_list,
                "hole": 0.45 if chart_type == "donut" else 0,
                "marker": {"colors": PLOTLY_COLORS}, "textinfo": "label+percent",
            }
            pie_layout = {"plot_bgcolor": "#fff", "paper_bgcolor": "#fff",
                          "margin": {"t": 30, "b": 30}, "showlegend": True}
            return jsonify(json_safe({"success": True, "chart_type": chart_type,
                                      "data": [trace], "layout": pie_layout}))

        return jsonify(json_safe({"success": True, "chart_type": chart_type,
                                  "data": [{"type": "bar", "x": labels, "y": values_list}],
                                  "layout": common_layout}))
    except Exception:
        app.logger.exception("Chart generation failed.")
        return jsonify({"success": False, "error": "Unable to generate chart. Check your selected fields."}), 500
    finally:
        if temp:
            temp.unlink(missing_ok=True)


# --------------------------------------------------
# Delete from Storage and database
# --------------------------------------------------
@app.route("/api/datasets/<dataset_id>", methods=["DELETE"])
def delete_dataset(dataset_id):
    dataset, error = get_dataset(dataset_id)
    if error:
        return error
    try:
        supabase.storage.from_(BUCKET).remove([dataset["storage_path"]])
        supabase.table("datasets").delete().eq("id", dataset_id).execute()
        return jsonify({"success": True, "message": "Dataset deleted from Supabase.", "dataset_id": dataset_id})
    except Exception:
        app.logger.exception("Dataset deletion failed.")
        return jsonify({"success": False, "error": "Could not delete dataset from Supabase."}), 500


# --------------------------------------------------
# Dashboard APIs: create, list, load, update, duplicate, delete
# --------------------------------------------------
def _dashboard_payload(data, partial=False):
    """Validate and prepare dashboard fields for Supabase."""
    if not isinstance(data, dict):
        raise ValueError("Request body must be a JSON object.")

    result = {}
    if not partial or "name" in data:
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValueError("Dashboard name is required.")
        if len(name) > 120:
            raise ValueError("Dashboard name must be 120 characters or fewer.")
        result["name"] = name

    if "description" in data:
        result["description"] = str(data.get("description") or "")
    elif not partial:
        result["description"] = ""

    if "layout" in data:
        if not isinstance(data["layout"], (list, dict)):
            raise ValueError("Layout must be a JSON list or object.")
        result["layout"] = data["layout"]
    elif not partial:
        result["layout"] = []

    if "charts" in data:
        if not isinstance(data["charts"], list):
            raise ValueError("Charts must be a JSON list.")
        result["charts"] = data["charts"]
    elif not partial:
        result["charts"] = []

    return result


@app.route("/api/dashboards", methods=["GET"])
def list_dashboards():
    try:
        require_supabase()
        response = (supabase.table("dashboards").select("*")
                    .order("updated_at", desc=True).execute())
        return jsonify({"success": True, "dashboards": response.data or []}), 200
    except Exception:
        app.logger.exception("Dashboard listing failed.")
        return jsonify({"success": False, "error": "Could not load dashboards from Supabase."}), 500


@app.route("/api/dashboards", methods=["POST"])
def create_dashboard():
    try:
        require_supabase()
        payload = _dashboard_payload(request.get_json(silent=True) or {})
        response = supabase.table("dashboards").insert(payload).execute()
        if not response.data:
            raise RuntimeError("Supabase did not return the created dashboard.")
        return jsonify({"success": True, "message": "Dashboard created.",
                        "dashboard": response.data[0]}), 201
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception:
        app.logger.exception("Dashboard creation failed.")
        return jsonify({"success": False, "error": "Could not create dashboard."}), 500


@app.route("/api/dashboards/<dashboard_id>", methods=["GET"])
def get_dashboard(dashboard_id):
    try:
        require_supabase()
        response = (supabase.table("dashboards").select("*")
                    .eq("id", dashboard_id).limit(1).execute())
        if not response.data:
            return jsonify({"success": False, "error": "Dashboard not found."}), 404
        return jsonify({"success": True, "dashboard": response.data[0]}), 200
    except Exception:
        app.logger.exception("Dashboard retrieval failed.")
        return jsonify({"success": False, "error": "Could not retrieve dashboard."}), 500


@app.route("/api/dashboards/<dashboard_id>", methods=["PUT"])
def update_dashboard(dashboard_id):
    try:
        require_supabase()
        payload = _dashboard_payload(request.get_json(silent=True) or {}, partial=True)
        if not payload:
            return jsonify({"success": False, "error": "No dashboard changes were provided."}), 400
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        response = (supabase.table("dashboards").update(payload)
                    .eq("id", dashboard_id).select("*").execute())
        if not response.data:
            return jsonify({"success": False, "error": "Dashboard not found."}), 404
        return jsonify({"success": True, "message": "Dashboard updated.",
                        "dashboard": response.data[0]}), 200
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception:
        app.logger.exception("Dashboard update failed.")
        return jsonify({"success": False, "error": "Could not update dashboard."}), 500


@app.route("/api/dashboards/<dashboard_id>/duplicate", methods=["POST"])
def duplicate_dashboard(dashboard_id):
    try:
        require_supabase()
        original = (supabase.table("dashboards").select("*")
                    .eq("id", dashboard_id).limit(1).execute())
        if not original.data:
            return jsonify({"success": False, "error": "Dashboard not found."}), 404
        source = original.data[0]
        copy_data = {
            "name": f"{source.get('name', 'Dashboard')} (Copy)",
            "description": source.get("description") or "",
            "layout": source.get("layout") or [],
            "charts": source.get("charts") or []
        }
        copied = supabase.table("dashboards").insert(copy_data).execute()
        if not copied.data:
            raise RuntimeError("Supabase did not return the duplicated dashboard.")
        return jsonify({"success": True, "message": "Dashboard duplicated.",
                        "dashboard": copied.data[0]}), 201
    except Exception:
        app.logger.exception("Dashboard duplication failed.")
        return jsonify({"success": False, "error": "Could not duplicate dashboard."}), 500


@app.route("/api/dashboards/<dashboard_id>", methods=["DELETE"])
def delete_dashboard(dashboard_id):
    try:
        require_supabase()
        response = (supabase.table("dashboards").delete()
                    .eq("id", dashboard_id).select("id").execute())
        if not response.data:
            return jsonify({"success": False, "error": "Dashboard not found."}), 404
        return jsonify({"success": True, "message": "Dashboard deleted."}), 200
    except Exception:
        app.logger.exception("Dashboard deletion failed.")
        return jsonify({"success": False, "error": "Could not delete dashboard."}), 500


# --------------------------------------------------
# Error handling and start
# --------------------------------------------------
@app.errorhandler(413)
def file_too_large(error):
    return jsonify({"success": False, "error": "Maximum upload size is 25 MB."}), 413


@app.errorhandler(404)
def not_found(error):
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "error": "API endpoint not found."}), 404
    return render_template("index.html"), 404


@app.errorhandler(500)
def internal_error(error):
    app.logger.exception("Internal server error.")
    return jsonify({"success": False, "error": "An internal server error occurred."}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
