from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import sqlite3
import pandas as pd
from reportlab.pdfgen import canvas
from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Font, Alignment
import os
import uvicorn

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, "sales.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

app = FastAPI(title="Mok Transport Internal Sales System")

templates = Jinja2Templates(directory=TEMPLATES_DIR)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

VAT_RATE = 0.15

# ---------------- DATABASE ----------------

def init_db():
    conn = sqlite3.connect(DB)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        party TEXT,
        supplier TEXT,
        waybill TEXT,
        invoice_no TEXT,
        sale_date TEXT,
        supplier_cost REAL,
        client_charge REAL,
        vat REAL,
        total_invoice REAL,
        profit REAL,
        status TEXT
    )
    """)

    conn.commit()
    conn.close()

init_db()

# ---------------- DATA ----------------

PARTIES = [
    "KONE","OTIS","ALICEWEAR","SPIRAX SARCO","TRACLO PTY LTD",
    "TRACLO INTL","TRACLO INTER","MAXIONWHEEL","MINTEK",
    "YMS TRADING DISTRIBUTORS","WALK-IN","WEG","SULZER",
    "CUSTOMS","USAFETY","SILVER","MAXION","Mahniglory and Saama PTY LTD"
]

SUPPLIERS = ["DHL", "JKJ", "MOK"]

# ---------------- MODEL ----------------

class Sale(BaseModel):
    party: str
    supplier: str
    waybill: str
    invoice_no: str
    sale_date: str
    supplier_cost: float
    client_charge: float
    status: str

# ---------------- HOME ----------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "parties": PARTIES, "suppliers": SUPPLIERS}
    )

# ---------------- RECORD SALE ----------------

@app.post("/record-sale")
def record_sale(sale: Sale, vat_enabled: bool = Query(True)):
    vat = sale.client_charge * VAT_RATE if vat_enabled else 0
    total_invoice = sale.client_charge + vat
    profit = sale.client_charge - sale.supplier_cost

    conn = sqlite3.connect(DB)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO sales (
            party, supplier, waybill, invoice_no, sale_date,
            supplier_cost, client_charge, vat, total_invoice, profit, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        sale.party, sale.supplier, sale.waybill, sale.invoice_no,
        sale.sale_date, sale.supplier_cost, sale.client_charge,
        vat, total_invoice, profit, sale.status
    ))

    conn.commit()
    conn.close()

    return JSONResponse({
        "vat": round(vat, 2),
        "total_invoice": round(total_invoice, 2),
        "profit": round(profit, 2)
    })

# ---------------- UPDATE SALE ----------------

@app.put("/update-sale/{sale_id}")
def update_sale(sale_id: int, sale: Sale):
    conn = sqlite3.connect(DB)
    cursor = conn.cursor()

    vat = sale.client_charge * VAT_RATE
    total_invoice = sale.client_charge + vat
    profit = sale.client_charge - sale.supplier_cost

    cursor.execute("""
        UPDATE sales SET
            party=?,
            supplier=?,
            waybill=?,
            invoice_no=?,
            sale_date=?,
            supplier_cost=?,
            client_charge=?,
            vat=?,
            total_invoice=?,
            profit=?,
            status=?
        WHERE id=?
    """, (
        sale.party, sale.supplier, sale.waybill, sale.invoice_no,
        sale.sale_date, sale.supplier_cost, sale.client_charge,
        vat, total_invoice, profit, sale.status, sale_id
    ))

    conn.commit()
    conn.close()

    return {"message": "Sale updated"}

# ---------------- SALES LIST ----------------

@app.get("/sales")
def get_sales():
    conn = sqlite3.connect(DB)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM sales")
    rows = cursor.fetchall()

    conn.close()
    return [list(row) for row in rows]

# ---------------- DELETE ----------------

@app.delete("/delete-sale/{sale_id}")
def delete_sale(sale_id: int):
    conn = sqlite3.connect(DB)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sales WHERE id=?", (sale_id,))
    conn.commit()
    conn.close()
    return {"message": "Deleted"}

# ---------------- DASHBOARD ----------------

@app.get("/dashboard-monthly")
def dashboard_monthly():
    conn = sqlite3.connect(DB)
    df = pd.read_sql_query("SELECT * FROM sales", conn)
    conn.close()

    if df.empty:
        return []

    df["sale_date"] = pd.to_datetime(df["sale_date"], errors="coerce")
    df["month"] = df["sale_date"].dt.strftime("%Y-%m")

    monthly = df.groupby("month").agg({
        "profit": "sum"
    }).reset_index()

    return monthly.to_dict(orient="records")

# ---------------- START ----------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)


