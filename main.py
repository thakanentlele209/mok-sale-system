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
import smtplib
from email.message import EmailMessage

# ---------------- PATH SAFETY ----------------

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
        fuel_charge REAL,
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
    fuel_charge: float

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

    subtotal = sale.client_charge + sale.fuel_charge
    vat = subtotal * VAT_RATE if vat_enabled else 0
    total_invoice = subtotal + vat
    profit = subtotal - sale.supplier_cost

    conn = sqlite3.connect(DB)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO sales (
            party, supplier, waybill, invoice_no, sale_date,
            supplier_cost, client_charge, fuel_charge,
            vat, total_invoice, profit
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        sale.party, sale.supplier, sale.waybill, sale.invoice_no,
        sale.sale_date, sale.supplier_cost, sale.client_charge,
        sale.fuel_charge, vat, total_invoice, profit
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
        SELECT id, party, supplier, waybill, invoice_no,
               sale_date, client_charge, fuel_charge,
               total_invoice, profit
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

    ws.merge_cells("A1:J1")
    ws["A1"] = "MOK TRANSPORT"
    ws["A1"].font = Font(size=18, bold=True)
    ws["A1"].alignment = Alignment(horizontal="center")

    headers = [
        "ID","Party","Supplier","Waybill","Invoice",
        "Date","Supplier Cost","Client Charge",
        "Fuel Charge","Total Invoice","Profit"
    ]

    ws.append([])
    ws.append(headers)

    for col in ws[4]:
        col.font = Font(bold=True)

    for row in rows:
        ws.append(row)

    logo_path = os.path.join(STATIC_DIR, "logo.png")
    if os.path.exists(logo_path):
        logo = XLImage(logo_path)
        ws.add_image(logo, "L1")

    file_path = os.path.join(BASE_DIR, "sales_export.xlsx")
    wb.save(file_path)

    return FileResponse(file_path, filename="mok_sales.xlsx")

# ---------------- EMAIL REPORT ----------------

@app.get("/email-report")
def email_report():

    file_path = export_excel().path

    msg = EmailMessage()
    msg["Subject"] = "Mok Sales Report"
    msg["From"] = "your-email@gmail.com"
    msg["To"] = "recipient@email.com"
    msg.set_content("Attached is the latest sales report.")

    with open(file_path, "rb") as f:
        msg.add_attachment(
            f.read(),
            maintype="application",
            subtype="xlsx",
            filename="mok_sales.xlsx"
        )

    # configure your SMTP
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login("your-email@gmail.com", "APP_PASSWORD")
        smtp.send_message(msg)

    return {"message": "Email sent successfully"}

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

    labels = [
        f"Party: {row[1]}",
        f"Supplier: {row[2]}",
        f"Waybill: {row[3]}",
        f"Invoice No: {row[4]}",
        f"Date: {row[5]}",
        f"Supplier Cost: {row[6]}",
        f"Client Charge: {row[7]}",
        f"Fuel Charge: {row[8]}",
        f"VAT: {round(row[9], 2)}",
        f"Total Invoice: {round(row[10], 2)}",
        f"Profit: {round(row[11], 2)}"
    ]

    y = 750
    for text in labels:
        c.drawString(100, y, text)
        y -= 20

    c.save()
    return FileResponse(file_name)

# ---------------- STARTUP ----------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
