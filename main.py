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
import secrets
from email.message import EmailMessage
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

app = FastAPI()

# ---------------- SESSION SECURITY ----------------

SECRET_KEY = os.getenv("SESSION_SECRET", secrets.token_hex(32))

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    max_age=60 * 60 * 8,
    same_site="lax"
)

templates = Jinja2Templates(directory=TEMPLATES_DIR)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

VAT_RATE = 0.15

# ---------------- USERS ----------------

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

# ---------------- ROLE HELPER ----------------

def require_role(request: Request, allowed_roles):

    role = request.session.get("role")

    if role not in allowed_roles:
        return False

    return True

# ---------------- LOGIN ----------------

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login(request: Request, user: str = Form(...), password: str = Form(...)):

    if user in USERS and USERS[user]["password"] == password:

        request.session["user"] = user
        request.session["role"] = USERS[user]["role"]

        if USERS[user]["role"] == "owner":
            return RedirectResponse("/owner-dashboard", status_code=302)

        return RedirectResponse("/", status_code=302)

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Invalid login"}
    )

@app.get("/logout")
def logout(request: Request):

    request.session.clear()

    return RedirectResponse("/login")

# ---------------- HOME ----------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):

    user = request.session.get("user")
    role = request.session.get("role")

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

# ---------------- OWNER DASHBOARD ----------------

@app.get("/owner-dashboard", response_class=HTMLResponse)
def owner_dashboard(request: Request):

    if not require_role(request, ["owner"]):
        return RedirectResponse("/")

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT SUM(client_charge) as revenue FROM sales")
    revenue = cur.fetchone()["revenue"]

    cur.execute("SELECT SUM(profit) as profit FROM sales")
    profit = cur.fetchone()["profit"]

    cur.execute("""
    SELECT COUNT(*) as unpaid
    FROM sales
    WHERE paid_status!='Paid'
    """)
    unpaid = cur.fetchone()["unpaid"]

    cur.execute("""
    SELECT party, SUM(client_charge) as revenue
    FROM sales
    GROUP BY party
    ORDER BY revenue DESC
    LIMIT 1
    """)
    top_client = cur.fetchone()

    cur.execute("""
    SELECT supplier, SUM(profit) as profit
    FROM sales
    GROUP BY supplier
    ORDER BY profit DESC
    LIMIT 1
    """)
    top_supplier = cur.fetchone()

    cur.close()
    conn.close()

    return templates.TemplateResponse(
        "owner_dashboard.html",
        {
            "request": request,
            "revenue": revenue,
            "profit": profit,
            "unpaid": unpaid,
            "top_client": top_client,
            "top_supplier": top_supplier
        }
    )

# ---------------- RECORD SALE ----------------

@app.post("/record-sale")
def record_sale(request: Request, sale: Sale, vat_enabled: bool = Query(True)):

    if not require_role(request, ["accounts","admin"]):
        return {"error":"Permission denied"}

    vat = sale.client_charge * VAT_RATE if vat_enabled else 0
    total = sale.client_charge + vat
    profit = sale.client_charge - sale.supplier_cost

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

    return {"status":"recorded"}

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

