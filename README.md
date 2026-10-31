# DataPilot AI 🚀

DataPilot AI is a modern web-based data analytics and dashboard platform built with Python, Flask, Supabase, and Plotly.

## ✨ Features

- **Multi-Format Dataset Upload**: Support for CSV, Excel (`.xlsx`), JSON, and PDF files.
- **Automated Profiling & Preview**: Instant summary of rows, columns, duplicate rows, missing values, and data types.
- **Interactive Visual Builder**: Build custom charts (Bar, Line, Area, Pie, Donut, Scatter, Box, Histogram, Data Table) powered by Plotly.js.
- **Dashboard Management**: Create, view, duplicate, and delete dashboards with saved chart arrangements.
- **Cloud-Backed Storage**: Datasets are stored in Supabase Storage with metadata in Supabase PostgreSQL.

## 🛠️ Tech Stack

- **Backend**: Python 3, Flask, Pandas, Werkzeug
- **Database & Storage**: Supabase (PostgreSQL & Storage Bucket)
- **Frontend**: HTML5, CSS3, Vanilla JavaScript, Plotly.js

## 🚀 Getting Started

### 1. Prerequisites

- Python 3.10+
- A Supabase project with:
  - `datasets` and `dashboards` tables configured
  - A storage bucket named `datapilot-files`

### 2. Setup & Installation

Clone the repository and install dependencies:

```bash
git clone <your-repo-url>
cd DataPilot-AI
python -m venv venv
# Windows:
.\venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Environment Variables

Copy `.env.example` to `.env` and fill in your Supabase credentials:

```bash
cp .env.example .env
```

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_PUBLISHABLE_KEY=your-publishable-key
SUPABASE_SECRET_KEY=your-supabase-secret-key
SUPABASE_STORAGE_BUCKET=datapilot-files
FLASK_SECRET_KEY=your-flask-secret-key
```

> **Warning**: Never commit your `.env` file to version control.

### 4. Run the Application

```bash
python backend/app.py
```

Visit [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.
