from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import sqlite3
import pandas as pd
import os
import uvicorn

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, "sales.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

app = FastAPI()

templates = Jinja2Templates(directory=TEMPLATES_DIR)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

VAT_RATE = 0.15


# ---------- DATABASE ----------

def get_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        party TEXT,
        supplier TEXT,
        order_no TEXT,
        invoice_no TEXT,
        waybill TEXT,
        sale_date TEXT,
        supplier_cost REAL,
        client_charge REAL,
        vat REAL,
        total_invoice REAL,
        profit REAL,
        paid_status TEXT
    )
    """)

    conn.commit()
    conn.close()


init_db()


# ---------- MODEL ----------

class Sale(BaseModel):
    party: str
    supplier: str
    order_no: str
    invoice_no: str
    waybill: str
    sale_date: str
    supplier_cost: float
    client_charge: float
    paid_status: str


# ---------- HOME ----------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "parties": [], "suppliers": []}
    )


# ---------- RECORD ----------

@app.post("/record-sale")
def record_sale(sale: Sale, vat_enabled: bool = Query(True)):

    vat = sale.client_charge * VAT_RATE if vat_enabled else 0
    total = sale.client_charge + vat
    profit = sale.client_charge - sale.supplier_cost

    conn = get_conn()
    c = conn.cursor()

    c.execute("""
    INSERT INTO sales (
        party, supplier, order_no, invoice_no, waybill, sale_date,
        supplier_cost, client_charge, vat, total_invoice, profit, paid_status
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        sale.party,
        sale.supplier,
        sale.order_no,
        sale.invoice_no,
        sale.waybill,
        sale.sale_date,
        sale.supplier_cost,
        sale.client_charge,
        vat,
        total,
        profit,
        sale.paid_status
    ))

    conn.commit()
    conn.close()

    return {
        "vat": round(vat, 2),
        "total_invoice": round(total, 2),
        "profit": round(profit, 2)
    }


# ---------- LIST ----------

@app.get("/sales")
def get_sales():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM sales ORDER BY id DESC").fetchall()
    conn.close()

    return [dict(row) for row in rows]


# ---------- DELETE ----------

@app.delete("/delete-sale/{sale_id}")
def delete_sale(sale_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM sales WHERE id=?", (sale_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted"}


# ---------- DASHBOARD ----------

@app.get("/dashboard-monthly")
def dashboard():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM sales", conn)
    conn.close()

    if df.empty:
        return []

    df["sale_date"] = pd.to_datetime(df["sale_date"], errors="coerce")
    df["month"] = df["sale_date"].dt.strftime("%Y-%m")

    monthly = df.groupby("month")["profit"].sum().reset_index()
    return monthly.to_dict(orient="records")


# ---------- START ----------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
