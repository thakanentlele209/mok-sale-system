from fastapi import FastAPI, Request, Query, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
import pandas as pd
import os
import uvicorn
import secrets
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import FileResponse
import smtplib
from email.message import EmailMessage

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

app = FastAPI()

SECRET_KEY = os.getenv("SESSION_SECRET", secrets.token_hex(32))

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    max_age=60*60*8,
    same_site="lax"
)

templates = Jinja2Templates(directory=TEMPLATES_DIR)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

VAT_RATE = 0.15

# ---------------- USERS ----------------

USERS = {
    "ryan":{"password":"@Karabo2009@","role":"owner"},
    "lebo":{"password":"Karabo@2009","role":"accounts"},
    "admin":{"password":"Malebo2913$","role":"admin"}
}

# ---------------- PARTIES ----------------

PARTIES = [
"KONE","OTIS","ALICEWEAR","SPIRAX SARCO","TRACLO PTY LTD",
"TRACLO INTL","TRACLO INTER","MAXIONWHEEL","MINTEK",
"YMS TRADING DISTRIBUTORS","WALK-IN","WEG","SULZER",
"CUSTOMS","USAFETY","SILVER","MAXION",
"Mahniglory and Saama PTY LTD",
"UPPER LEVEL LIFTS PTY LTD",
"Power Elevators",
"Imperio Logistics Holdings (Pty) Ltd"
]

SUPPLIERS = ["DHL","JKJ","MOK"]

# ---------------- DATABASE ----------------

def get_conn():
    return psycopg2.connect(
        os.getenv("DATABASE_URL"),
        cursor_factory=RealDictCursor
    )

def init_db():

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sales(
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

    party:str
    supplier:str
    order_no:str
    invoice_no:str
    waybill:str
    sale_date:str
    supplier_cost:float
    client_charge:float
    paid_status:str

# ---------------- ROLE HELPER ----------------

def require_role(request:Request,roles):

    role=request.session.get("role")

    if role not in roles:
        return False

    return True

# ---------------- LOGIN ----------------

@app.get("/login",response_class=HTMLResponse)
def login_page(request:Request):

    return templates.TemplateResponse("login.html",{"request":request})

@app.post("/login")
def login(request:Request,username:str=Form(...),password:str=Form(...)):

    if username in USERS and USERS[username]["password"]==password:

        request.session["user"]=username
        request.session["role"]=USERS[username]["role"]

        if USERS[username]["role"]=="owner":
            return RedirectResponse("/owner-dashboard",302)

        return RedirectResponse("/",302)

    return templates.TemplateResponse(
        "login.html",
        {"request":request,"error":"Invalid login"}
    )

@app.get("/logout")
def logout(request:Request):

    request.session.clear()
    return RedirectResponse("/login")

# ---------------- HOME ----------------

@app.get("/",response_class=HTMLResponse)
def home(request:Request):

    if not request.session.get("user"):
        return RedirectResponse("/login")

    return templates.TemplateResponse(
        "index.html",
        {
            "request":request,
            "parties":PARTIES,
            "suppliers":SUPPLIERS,
            "role":request.session.get("role")
        }
    )

# ---------------- RECORD SALE ----------------

@app.post("/record-sale")
def record_sale(request:Request,sale:Sale,vat_enabled:bool=Query(True)):

    if not require_role(request,["accounts","admin"]):
        return {"error":"Permission denied"}

    vat=sale.client_charge*VAT_RATE if vat_enabled else 0
    total=sale.client_charge+vat
    profit=sale.client_charge-sale.supplier_cost

    sale_date=sale.sale_date if sale.sale_date else None

    conn=get_conn()
    cur=conn.cursor()

    cur.execute("""
    INSERT INTO sales(
    party,supplier,order_no,invoice_no,waybill,sale_date,
    supplier_cost,client_charge,vat,total_invoice,profit,paid_status
    )
    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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

# ---------------- UPDATE SALE ----------------

@app.put("/update-sale/{sale_id}")
def update_sale(request:Request,sale_id:int,sale:Sale,vat_enabled:bool=Query(True)):

    if not require_role(request,["accounts","admin"]):
        return {"error":"Permission denied"}

    vat=sale.client_charge*VAT_RATE if vat_enabled else 0
    total=sale.client_charge+vat
    profit=sale.client_charge-sale.supplier_cost

    sale_date=sale.sale_date if sale.sale_date else None

    conn=get_conn()
    cur=conn.cursor()

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

# ---------------- DELETE SALE ----------------

@app.delete("/delete-sale/{sale_id}")
def delete_sale(request:Request,sale_id:int):

    if not require_role(request,["accounts","admin"]):
        return {"error":"Permission denied"}

    conn=get_conn()
    cur=conn.cursor()

    cur.execute("DELETE FROM sales WHERE id=%s",(sale_id,))

    conn.commit()
    cur.close()
    conn.close()

    return {"status":"deleted"}

# ---------------- SALES TABLE ----------------

@app.get("/sales")
def get_sales():

    conn=get_conn()
    cur=conn.cursor()

    cur.execute("SELECT * FROM sales ORDER BY id DESC")

    rows=cur.fetchall()

    cur.close()
    conn.close()

    return rows

# ---------------- DASHBOARD KPIS ----------------

@app.get("/dashboard-kpis")
def dashboard_kpis():

    conn=get_conn()
    cur=conn.cursor()

    cur.execute("""
    SELECT
    COALESCE(SUM(client_charge),0) as total_sales,
    COALESCE(SUM(profit),0) as total_profit,
    COALESCE(SUM(CASE WHEN paid_status='Paid' THEN client_charge END),0) as paid_total,
    COALESCE(SUM(CASE WHEN paid_status!='Paid' THEN client_charge END),0) as outstanding_total
    FROM sales
    """)

    result=cur.fetchone()

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
    SELECT party, SUM(profit) as profit
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
    SELECT supplier, SUM(profit) as profit
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
    SELECT party, SUM(client_charge) as revenue
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
    COALESCE(SUM(CASE WHEN paid_status='Paid' THEN client_charge END),0) as paid_total,
    COALESCE(SUM(CASE WHEN paid_status!='Paid' THEN client_charge END),0) as outstanding_total
    FROM sales
    """)

    result = cur.fetchone()

    cur.close()
    conn.close()

    return result


# ---------------- Export Excel ----------------
@app.get("/export-excel")
def export_excel():

    conn = get_conn()

    df = pd.read_sql("SELECT * FROM sales ORDER BY id DESC", conn)

    conn.close()

    file_path = "sales_export.xlsx"

    df.to_excel(file_path, index=False)

    return FileResponse(
        file_path,
        filename="mok_transport_sales.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ---------------- Send Monthly Report ----------------

@app.post("/send-monthly-report")
def send_monthly_report(month: str, recipient: str):

    conn = get_conn()

    df = pd.read_sql(
        f"""
        SELECT *
        FROM sales
        WHERE TO_CHAR(sale_date,'YYYY-MM')='{month}'
        """,
        conn
    )

    conn.close()

    if df.empty:
        return {"error":"No data for this month"}

    file_path = f"report_{month}.xlsx"

    df.to_excel(file_path,index=False)

    EMAIL = os.getenv("EMAIL_USER")
    PASSWORD = os.getenv("EMAIL_PASS")

    msg = EmailMessage()
    msg["Subject"] = f"Mok Transport Sales Report {month}"
    msg["From"] = EMAIL
    msg["To"] = recipient

    msg.set_content("Attached is the monthly sales report.")

    with open(file_path,"rb") as f:
        msg.add_attachment(
            f.read(),
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=file_path
        )

    with smtplib.SMTP_SSL("smtp.gmail.com",465) as smtp:
        smtp.login(EMAIL,PASSWORD)
        smtp.send_message(msg)

    return {"message":"Report sent"}

# ---------------- OWNER DASHBOARD ----------------

@app.get("/owner-dashboard",response_class=HTMLResponse)
def owner_dashboard(request:Request):

    if not require_role(request,["owner"]):
        return RedirectResponse("/")

    conn=get_conn()
    cur=conn.cursor()

    cur.execute("""
    SELECT party,SUM(client_charge) revenue
    FROM sales
    GROUP BY party
    ORDER BY revenue DESC
    LIMIT 1
    """)

    top_client=cur.fetchone()

    cur.close()
    conn.close()

    return templates.TemplateResponse(
        "owner_dashboard.html",
        {"request":request,"top_client":top_client}
    )

# ---------------- OWNER ANALYTICS ----------------

@app.get("/owner-analytics")
def owner_analytics(request: Request):

    if not require_role(request, ["owner"]):
        return {"error": "owner only"}

    conn = get_conn()
    df = pd.read_sql("SELECT * FROM sales", conn)
    conn.close()

    if df.empty:
        return {
            "revenue": 0,
            "profit": 0,
            "vat": 0,
            "monthly_profit": {},
            "client_profit": {},
            "supplier_profit": {},
            "dependency_risk": {},
            "supplier_efficiency": {},
            "revenue_forecast": []
        }

    # ---------- CLEAN DATA ----------

    df["client_charge"] = pd.to_numeric(df["client_charge"], errors="coerce").fillna(0)
    df["profit"] = pd.to_numeric(df["profit"], errors="coerce").fillna(0)
    df["vat"] = pd.to_numeric(df["vat"], errors="coerce").fillna(0)

    df["sale_date"] = pd.to_datetime(df["sale_date"], errors="coerce")

    # ---------- CORE KPIs ----------

    revenue = float(df["client_charge"].sum())
    profit = float(df["profit"].sum())
    vat_total = float(df["vat"].sum())

    # ---------- MONTHLY PROFIT ----------

    monthly_df = df[df["sale_date"].notna()]

    monthly_profit = (
        monthly_df.groupby(monthly_df["sale_date"].dt.to_period("M"))["profit"]
        .sum()
        .fillna(0)
        .to_dict()
    )

    monthly_profit = {str(k): float(v) for k, v in monthly_profit.items()}

    # ---------- CLIENT PROFIT ----------

    client_profit = (
        df.groupby("party")["profit"]
        .sum()
        .fillna(0)
        .sort_values(ascending=False)
        .to_dict()
    )

    client_profit = {k: float(v) for k, v in client_profit.items()}

    # ---------- SUPPLIER PROFIT ----------

    supplier_profit = (
        df.groupby("supplier")["profit"]
        .sum()
        .fillna(0)
        .sort_values(ascending=False)
        .to_dict()
    )

    supplier_profit = {k: float(v) for k, v in supplier_profit.items()}

    # ---------- CLIENT DEPENDENCY ----------

    client_revenue = df.groupby("party")["client_charge"].sum()

    total_revenue = client_revenue.sum()

    if total_revenue == 0:
        dependency_risk = {}
    else:
        dependency_risk = (
            (client_revenue / total_revenue * 100)
            .fillna(0)
            .round(2)
            .sort_values(ascending=False)
            .to_dict()
        )

    dependency_risk = {k: float(v) for k, v in dependency_risk.items()}

    # ---------- SUPPLIER EFFICIENCY ----------

    supplier_efficiency = (
        df.groupby("supplier")["profit"]
        .mean()
        .fillna(0)
        .round(2)
        .sort_values(ascending=False)
        .to_dict()
    )

    supplier_efficiency = {k: float(v) for k, v in supplier_efficiency.items()}

    # ---------- REVENUE FORECAST ----------

    monthly_revenue = (
        monthly_df.groupby(monthly_df["sale_date"].dt.to_period("M"))["client_charge"]
        .sum()
        .fillna(0)
    )

    revenue_forecast = [float(v) for v in monthly_revenue.tail(6).tolist()]

    return {
        "revenue": revenue,
        "profit": profit,
        "vat": vat_total,
        "monthly_profit": monthly_profit,
        "client_profit": client_profit,
        "supplier_profit": supplier_profit,
        "dependency_risk": dependency_risk,
        "supplier_efficiency": supplier_efficiency,
        "revenue_forecast": revenue_forecast
    }


if __name__=="__main__":

    port=int(os.environ.get("PORT",8080))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port
    )





 