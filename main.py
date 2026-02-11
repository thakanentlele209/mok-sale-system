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

# ---------------- PATH SAFETY ----------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, "sales.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

print("BASE_DIR:", BASE_DIR)
print("STATIC_DIR exists:", os.path.exists(STATIC_DIR))
print("TEMPLATES_DIR exists:", os.path.exists(TEMPLATES_DIR))

# ---------------- APP ----------------

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
        order_no TEXT,
        invoice_no TEXT,
        sale_date TEXT,
        supplier_cost REAL,
        client_charge REAL,
        vat REAL,
        total_invoice REAL,
        profit REAL
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
    "CUSTOMS","USAFETY","SILVER","MAXION"
]

SUPPLIERS = ["DHL", "JKJ", "MOK"]

# ---------------- MODEL ----------------

class Sale(BaseModel):
    party: str
    supplier: str
    order_no: str
    invoice_no: str
    sale_date: str
    supplier_cost: float
    client_charge: float

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
            party, supplier, order_no, invoice_no, sale_date,
            supplier_cost, client_charge, vat, total_invoice, profit
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        sale.party, sale.supplier, sale.order_no, sale.invoice_no,
        sale.sale_date, sale.supplier_cost, sale.client_charge,
        vat, total_invoice, profit
    ))

    conn.commit()
    conn.close()

    return JSONResponse({
        "vat": round(vat, 2),
        "total_invoice": round(total_invoice, 2),
        "profit": round(profit, 2)
    })

# ---------------- SALES LIST ----------------

@app.get("/sales")
def get_sales():
    conn = sqlite3.connect(DB)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, party, supplier, order_no, invoice_no,
               sale_date, client_charge, total_invoice, profit
        FROM sales
    """)

    rows = cursor.fetchall()
    conn.close()
    return [list(row) for row in rows]

@app.delete("/delete-sale/{sale_id}")
def delete_sale(sale_id: int):
    conn = sqlite3.connect(DB)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sales WHERE id=?", (sale_id,))
    conn.commit()
    conn.close()
    return {"message": "Sale deleted"}

# ---------------- EXPORT EXCEL ----------------

@app.get("/export-excel")
def export_excel():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT * FROM sales")
    rows = cur.fetchall()
    conn.close()

    wb = Workbook()
    ws = wb.active

    ws.merge_cells("A1:H1")
    ws["A1"] = "MOK TRANSPORT"
    ws["A1"].font = Font(size=18, bold=True)
    ws["A1"].alignment = Alignment(horizontal="center")

    ws.merge_cells("A2:H2")
    ws["A2"] = "12 JUPITER STELLER MALL, SHOP CO1 CROWN MINES, JOHANNESBURG, 2000"
    ws["A2"].alignment = Alignment(horizontal="center")

    logo_path = os.path.join(STATIC_DIR, "logo.png")
    if os.path.exists(logo_path):
        logo = XLImage(logo_path)
        logo.width = 120
        logo.height = 80
        ws.add_image(logo, "I1")

    headers = ["ID","Party","Supplier","Order","Invoice","Date",
               "Supplier Cost","Total Invoice","Profit"]

    ws.append([])
    ws.append(headers)

    for col in ws[4]:
        col.font = Font(bold=True)

    for row in rows:
        ws.append(row)

    file_path = os.path.join(BASE_DIR, "sales_export.xlsx")
    wb.save(file_path)

    return FileResponse(file_path, filename="mok_sales.xlsx")

# ---------------- PDF INVOICE ----------------

@app.get("/invoice/{sale_id}")
def invoice(sale_id: int):
    conn = sqlite3.connect(DB)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sales WHERE id=?", (sale_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {"error": "Sale not found"}

    file_name = os.path.join(BASE_DIR, f"invoice_{sale_id}.pdf")
    c = canvas.Canvas(file_name)

    c.setFont("Helvetica-Bold", 16)
    c.drawString(100, 780, "Mok Transport Invoice")

    c.setFont("Helvetica", 12)
    labels = [
        f"Party: {row[1]}",
        f"Supplier: {row[2]}",
        f"Order No: {row[3]}",
        f"Invoice No: {row[4]}",
        f"Date: {row[5]}",
        f"Supplier Cost: {row[6]}",
        f"Client Charge: {row[7]}",
        f"VAT: {round(row[8], 2)}",
        f"Total Invoice: {round(row[9], 2)}",
        f"Profit: {round(row[10], 2)}"
    ]

    y = 740
    for text in labels:
        c.drawString(100, y, text)
        y -= 20

    c.save()
    return FileResponse(file_name)

# ---------------- MONTHLY DASHBOARD ----------------

@app.get("/dashboard-monthly")
def dashboard_monthly():
    conn = sqlite3.connect(DB)
    df = pd.read_sql_query("SELECT * FROM sales", conn)
    conn.close()

    if df.empty:
        return []

    df["sale_date"] = pd.to_datetime(df["sale_date"], errors="coerce")
    df = df.dropna(subset=["sale_date"])
    df["month"] = df["sale_date"].dt.strftime("%Y-%m")

    monthly = df.groupby("month").agg({
        "client_charge": "sum",
        "vat": "sum",
        "profit": "sum"
    }).reset_index()

    return monthly.to_dict(orient="records")

# ---------------- STARTUP ----------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

