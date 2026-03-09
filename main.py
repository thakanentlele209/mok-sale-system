from fastapi import FastAPI, Request, Query, Form
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

app = FastAPI()

templates = Jinja2Templates(directory=TEMPLATES_DIR)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

VAT_RATE = 0.15


# ---------------- USERS / ROLES ----------------

USERS = {
    "ryan": {"password": "@Karabo2009@", "role": "owner"},
    "lebo": {"password": "Karabo@2009", "role": "accounts"},
    "admin": {"password": "Malebo2913$", "role": "admin"}
}


# ---------------- DATABASE ----------------

def get_conn():
    database_url = os.getenv("DATABASE_URL")
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


# ---------------- MODEL ----------------

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


# ---------------- DATA ----------------

PARTIES = [
"KONE","OTIS","ALICEWEAR","SPIRAX SARCO","TRACLO PTY LTD",
"TRACLO INTL","TRACLO INTER","MAXIONWHEEL","MINTEK",
"YMS TRADING DISTRIBUTORS","WALK-IN","WEG","SULZER",
"CUSTOMS","USAFETY","SILVER","MAXION","Mahniglory and Saama PTY LTD",
"UPPER LEVEL LIFTS PTY LTD","Power Elevators","Imperio Logistics Holdings (Pty) Ltd"
]

SUPPLIERS = ["DHL","JKJ","MOK"]


# ---------------- LOGIN ----------------

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login(username: str = Form(...), password: str = Form(...)):

    if username in USERS and USERS[username]["password"] == password:

        response = RedirectResponse("/", status_code=302)

        response.set_cookie("user", username, httponly=True, samesite="lax")
        response.set_cookie("role", USERS[username]["role"], httponly=True, samesite="lax")

        return response

    return RedirectResponse("/login", status_code=302)


@app.get("/logout")
def logout():

    response = RedirectResponse("/login")

    response.delete_cookie("user")
    response.delete_cookie("role")

    return response


# ---------------- HOME ----------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):

    user = request.cookies.get("user")
    role = request.cookies.get("role")

    if not user:
        return RedirectResponse("/login")

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "parties": PARTIES,
            "suppliers": SUPPLIERS,
            "role": role
        }
    )


# ---------------- RECORD SALE ----------------

@app.post("/record-sale")
def record_sale(request: Request, sale: Sale, vat_enabled: bool = Query(True)):

    role = request.cookies.get("role")

    if role not in ["accounts", "admin"]:
        return {"error": "Permission denied"}

    vat = sale.client_charge * VAT_RATE if vat_enabled else 0
    total = sale.client_charge + vat
    profit = sale.client_charge - sale.supplier_cost

    # fix empty date
    sale_date = sale.sale_date if sale.sale_date else None

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO sales (
        party,supplier,order_no,invoice_no,waybill,sale_date,
        supplier_cost,client_charge,vat,total_invoice,profit,paid_status
    )
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """,(
        sale.party,
        sale.supplier,
        sale.order_no,
        sale.invoice_no,
        sale.waybill,
        sale_date,
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
        "status":"recorded",
        "vat":vat,
        "total_invoice":total,
        "profit":profit
    }


# ---------------- SALES TABLE ----------------

@app.get("/sales")
def get_sales():

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM sales ORDER BY id DESC")
    rows = cur.fetchall()

    cur.close()
    conn.close()

    return rows


# ---------------- DELETE SALE ----------------

@app.delete("/delete-sale/{sale_id}")
def delete_sale(request: Request, sale_id: int):

    role = request.cookies.get("role")

    if role not in ["accounts","admin"]:
        return {"error":"Permission denied"}

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("DELETE FROM sales WHERE id=%s",(sale_id,))

    conn.commit()
    cur.close()
    conn.close()

    return {"status":"deleted"}


# ---------------- UPDATE SALE ----------------

@app.put("/update-sale/{sale_id}")
def update_sale(request: Request, sale_id:int, sale:Sale, vat_enabled: bool = Query(True)):

    role = request.cookies.get("role")

    if role not in ["accounts","admin"]:
        return {"error":"Permission denied"}

    vat = sale.client_charge * VAT_RATE if vat_enabled else 0
    total = sale.client_charge + vat
    profit = sale.client_charge - sale.supplier_cost

    sale_date = sale.sale_date if sale.sale_date else None

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
        sale_date,
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

    return {"status":"updated"}


# ---------------- DASHBOARDS ----------------

@app.get("/dashboard-kpis")
def dashboard_kpis():

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    SELECT
    SUM(client_charge) as total_sales,
    SUM(profit) as total_profit,
    SUM(CASE WHEN paid_status='Paid' THEN client_charge ELSE 0 END) as paid_total,
    SUM(CASE WHEN paid_status!='Paid' THEN client_charge ELSE 0 END) as outstanding_total
    FROM sales
    """)

    result = cur.fetchone()

    cur.close()
    conn.close()

    return result


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


@app.get("/dashboard-supplier-performance")
def dashboard_supplier():

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
def dashboard_clients():

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


# ---------------- EXPORT EXCEL ----------------

@app.get("/export-excel")
def export_excel():

    conn = get_conn()
    df = pd.read_sql("SELECT * FROM sales", conn)
    conn.close()

    path = os.path.join(BASE_DIR,"sales_export.xlsx")
    df.to_excel(path,index=False)

    return FileResponse(path, filename="sales_export.xlsx")


# ---------------- EMAIL REPORT ----------------

@app.post("/send-monthly-report")
def send_monthly_report(month:str, recipient:str):

    conn = get_conn()

    df = pd.read_sql(
        "SELECT * FROM sales WHERE TO_CHAR(sale_date,'YYYY-MM')=%s",
        conn,
        params=[month]
    )

    conn.close()

    if df.empty:
        return {"error":"No data"}

    body=f"""
Mok Transport Monthly Report {month}

Total Sales: {df.client_charge.sum()}
Total Cost: {df.supplier_cost.sum()}
Total Profit: {df.profit.sum()}

Paid: {df[df.paid_status=='Paid'].client_charge.sum()}
Outstanding: {df[df.paid_status!='Paid'].client_charge.sum()}
"""

    msg=EmailMessage()

    msg["Subject"]=f"Mok Transport Monthly Report {month}"
    msg["From"]=os.getenv("EMAIL_USER")
    msg["To"]=recipient

    msg.set_content(body)

    with smtplib.SMTP("smtp.office365.com",587) as server:

        server.starttls()

        server.login(
            os.getenv("EMAIL_USER"),
            os.getenv("EMAIL_PASS")
        )

        server.send_message(msg)

    return {"message":"Email sent successfully"}


# ---------------- START SERVER ----------------

if __name__ == "__main__":

    port = int(os.environ.get("PORT",8080))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port
    )

