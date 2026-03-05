from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
import pandas as pd
import os
import uvicorn
import smtplib
from email.message import EmailMessage
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

app = FastAPI()

templates = Jinja2Templates(directory=TEMPLATES_DIR)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

VAT_RATE = 0.15


# ---------- DATABASE ----------

def get_conn():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise Exception("DATABASE_URL not set in environment variables")
    return psycopg2.connect(database_url, cursor_factory=RealDictCursor)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id SERIAL PRIMARY KEY,
            party TEXT,
            supplier TEXT,
            order_no TEXT,
            invoice_no TEXT,
            waybill TEXT,
            sale_date DATE,
            supplier_cost NUMERIC,
            client_charge NUMERIC,
            vat NUMERIC,
            total_invoice NUMERIC,
            profit NUMERIC,
            paid_status TEXT
        )
    """)

    conn.commit()
    cur.close()
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


# ---------- DATA ----------

PARTIES = [
    "KONE","OTIS","ALICEWEAR","SPIRAX SARCO","TRACLO PTY LTD",
    "TRACLO INTL","TRACLO INTER","MAXIONWHEEL","MINTEK",
    "YMS TRADING DISTRIBUTORS","WALK-IN","WEG","SULZER",
    "CUSTOMS","USAFETY","SILVER","MAXION","Mahniglory and Saama PTY LTD",
    "UPPER LEVEL LIFTS PTY LTD","Power Elevators","Imperio Logistics Holdings (Pty) Ltd"
]

SUPPLIERS = ["DHL", "JKJ", "MOK"]


# ---------- HOME ----------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "parties": PARTIES, "suppliers": SUPPLIERS}
    )


# ---------- RECORD ----------

@app.post("/record-sale")
def record_sale(sale: Sale, vat_enabled: bool = Query(True)):

    vat = sale.client_charge * VAT_RATE if vat_enabled else 0
    total = sale.client_charge + vat
    profit = sale.client_charge - sale.supplier_cost

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO sales (
            party, supplier, order_no, invoice_no, waybill, sale_date,
            supplier_cost, client_charge, vat, total_invoice, profit, paid_status
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """,(
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
    cur.close()
    conn.close()

    return {
        "vat": round(vat,2),
        "total_invoice": round(total,2),
        "profit": round(profit,2)
    }


# ---------- LIST SALES ----------

@app.get("/sales")
def get_sales():

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM sales ORDER BY id DESC")
    rows = cur.fetchall()

    cur.close()
    conn.close()

    return rows


# ---------- DELETE ----------

@app.delete("/delete-sale/{sale_id}")
def delete_sale(sale_id:int):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("DELETE FROM sales WHERE id=%s",(sale_id,))

    conn.commit()
    cur.close()
    conn.close()

    return {"status":"deleted"}


# ---------- UPDATE ----------

@app.put("/update-sale/{sale_id}")
def update_sale(sale_id:int, sale:Sale, vat_enabled: bool = Query(True)):

    vat = sale.client_charge * VAT_RATE if vat_enabled else 0
    total = sale.client_charge + vat
    profit = sale.client_charge - sale.supplier_cost

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE sales SET
            party=%s,
            supplier=%s,
            order_no=%s,
            invoice_no=%s,
            waybill=%s,
            sale_date=%s,
            supplier_cost=%s,
            client_charge=%s,
            vat=%s,
            total_invoice=%s,
            profit=%s,
            paid_status=%s
        WHERE id=%s
    """,(
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
        sale.paid_status,
        sale_id
    ))

    conn.commit()
    cur.close()
    conn.close()

    return {
        "vat": round(vat,2),
        "total_invoice": round(total,2),
        "profit": round(profit,2)
    }


# ---------- LOCK SALE FOR EDIT ----------

@app.post("/lock-sale/{sale_id}")
def lock_sale(sale_id: int):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE sales
        SET waybill = waybill
        WHERE id = %s
        RETURNING id
    """, (sale_id,))

    row = cur.fetchone()

    cur.close()
    conn.close()

    if not row:
        return {"error": "Sale not found"}

    return {"status": "locked"}
# ---------- EXPORT EXCEL ----------

# ---------- ACCOUNTS RECEIVABLE DASHBOARD ----------

@app.get("/accounts-receivable")
def accounts_receivable():

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            SUM(CASE WHEN paid_status='Paid' THEN client_charge ELSE 0 END) as paid_total,
            SUM(CASE WHEN paid_status!='Paid' THEN client_charge ELSE 0 END) as outstanding_total
        FROM sales
    """)

    result = cur.fetchone()

    cur.close()
    conn.close()

    return result



@app.get("/export-excel")
def export_excel():

    conn = get_conn()
    df = pd.read_sql("SELECT * FROM sales", conn)
    conn.close()

    if df.empty:
        return {"error":"No data"}

    path = os.path.join(BASE_DIR,"sales_export.xlsx")
    df.to_excel(path,index=False)

    return FileResponse(path,filename="sales_export.xlsx")


# ---------- MONTHLY DASHBOARD ----------

@app.get("/dashboard-monthly")
def dashboard_monthly():

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            TO_CHAR(sale_date,'YYYY-MM') as month,
            SUM(profit) as profit
        FROM sales
        GROUP BY month
        ORDER BY month
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return rows


# ---------- PROFIT BY PARTY ----------

@app.get("/dashboard-by-party")
def dashboard_by_party():

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            party,
            SUM(profit) as profit
        FROM sales
        GROUP BY party
        ORDER BY profit DESC
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return rows


# ---------- MONTHLY REPORT ----------

@app.get("/monthly-report")
def monthly_report(month:str):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM sales
        WHERE TO_CHAR(sale_date,'YYYY-MM') = %s
    """,(month,))

    rows = cur.fetchall()

    cur.close()
    conn.close()

    if not rows:
        return {}

    df = pd.DataFrame(rows)

    return {
        "month":month,
        "total_sales":float(df["client_charge"].sum()),
        "total_cost":float(df["supplier_cost"].sum()),
        "total_profit":float(df["profit"].sum()),
        "paid_total":float(df[df["paid_status"]=="Paid"]["client_charge"].sum()),
        "outstanding_total":float(df[df["paid_status"]!="Paid"]["client_charge"].sum()),
        "profit_by_party": df.groupby("party")["profit"].sum().reset_index().to_dict(orient="records")
    }

@app.get("/dashboard-profit-trend")
def profit_trend():

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            TO_CHAR(sale_date,'YYYY-MM') as month,
            SUM(profit) as profit
        FROM sales
        GROUP BY month
        ORDER BY month
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return rows


@app.get("/dashboard-supplier-performance")
def supplier_performance():

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            supplier,
            SUM(profit) as profit
        FROM sales
        GROUP BY supplier
        ORDER BY profit DESC
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return rows


@app.get("/dashboard-top-clients")
def top_clients():

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            party,
            SUM(client_charge) as revenue
        FROM sales
        GROUP BY party
        ORDER BY revenue DESC
        LIMIT 10
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return rows


# ---------- EMAIL REPORT ----------

@app.post("/send-monthly-report")
def send_monthly_report(month:str, recipient:str):

    report = monthly_report(month)

    if not report:
        return {"error":"No data for selected month"}

    body = f"""
Mok Transport Monthly Report - {month}

Total Sales: {report['total_sales']}
Total Cost: {report['total_cost']}
Total Profit: {report['total_profit']}

Paid Total: {report['paid_total']}
Outstanding Total: {report['outstanding_total']}
"""

    msg = EmailMessage()
    msg["Subject"] = f"Mok Transport Monthly Report - {month}"
    msg["From"] = os.getenv("EMAIL_USER")
    msg["To"] = recipient
    msg.set_content(body)

    try:

        with smtplib.SMTP("smtp.office365.com",587) as server:

            server.starttls()

            server.login(
                os.getenv("EMAIL_USER"),
                os.getenv("EMAIL_PASS")
            )

            server.send_message(msg)

        return {"message":"Report sent successfully"}

    except Exception as e:

        return {"error":str(e)}


# ---------- START ----------

if __name__ == "__main__":

    port = int(os.environ.get("PORT",8080))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port
    )





    