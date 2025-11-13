import os
from dotenv import load_dotenv
import psycopg2
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort
import string, random, json
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "fallback_secret")

DB_CONFIG = {
    'dbname': os.getenv("DB_NAME"),
    'user': os.getenv("DB_USER"),
    'password': os.getenv("DB_PASSWORD"),
    'host': os.getenv("DB_HOST", "localhost"),
    'port': int(os.getenv("DB_PORT", 5432))
}

def get_db():
    return psycopg2.connect(**DB_CONFIG)

def generate_code(n=6):
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(n))

@app.route('static/favicon.ico')
def favicon():
    return send_from_directory('static', 'favicon.ico', mimetype='image/vnd.microsoft.icon')

# ----------------- AUTH -----------------
@app.route('/register', methods=['GET','POST'])
def register():
    if request.method=='POST':
        u,p=request.form['username'],request.form['password']
        if not u or not p: return render_template('register.html',error="Required fields missing")
        conn=get_db();cur=conn.cursor()
        try:
            cur.execute("INSERT INTO users(username,password) VALUES(%s,%s)",(u,generate_password_hash(p)))
            conn.commit();cur.close();conn.close()
            return redirect(url_for('login'))
        except:
            cur.close();conn.close()
            return render_template('register.html',error="Username already exists")
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        u,p=request.form['username'],request.form['password']
        conn=get_db();cur=conn.cursor()
        cur.execute("SELECT id,password FROM users WHERE username=%s",(u,))
        r=cur.fetchone();cur.close();conn.close()
        if r and check_password_hash(r[1],p):
            session['user_id'],session['username']=r[0],u
            return redirect(url_for('dashboard'))
        return render_template('login.html',error="Invalid credentials")
    return render_template('login.html')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

# ----------------- DASHBOARD -----------------
@app.route('/')
def home(): return redirect(url_for('dashboard')) if 'user_id' in session else redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    uid=session['user_id']
    conn=get_db();cur=conn.cursor()
    cur.execute("SELECT * FROM expenses WHERE user_id=%s ORDER BY id DESC",(uid,))
    expenses=cur.fetchall()
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM expenses WHERE user_id=%s",(uid,));total=cur.fetchone()[0]
    cur.execute("SELECT * FROM urls WHERE user_id=%s ORDER BY id DESC",(uid,));urls=cur.fetchall()
    cur.execute("SELECT id,description,category,amount,date FROM expenses WHERE user_id=%s ORDER BY amount DESC LIMIT 5",(uid,))
    top5=cur.fetchall();cur.close();conn.close()
    return render_template('index.html',username=session['username'],expenses=expenses,total=total,urls=urls,top5=top5)

# ----------------- QUICK EXPENSE -----------------
@app.route('/add_expense',methods=['POST'])
def add_expense():
    if 'user_id' not in session: return redirect(url_for('login'))
    d=request.form['description']; c=request.form.get('category','Other')
    try:a=float(request.form['amount'])
    except:return redirect(url_for('dashboard'))
    conn=get_db();cur=conn.cursor()
    cur.execute("INSERT INTO expenses(user_id,description,category,amount,date)VALUES(%s,%s,%s,%s,%s)",
                (session['user_id'],d,c,a,datetime.now()))
    conn.commit();cur.close();conn.close()
    return redirect(url_for('dashboard'))

@app.route('/delete_expense/<int:id>')
def delete_expense(id):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn=get_db();cur=conn.cursor()
    cur.execute("DELETE FROM expenses WHERE id=%s AND user_id=%s",(id,session['user_id']))
    conn.commit();cur.close();conn.close()
    return redirect(url_for('dashboard'))

# ----------------- URL SHORTENER -----------------
BITLY_DOMAIN = "https://website"  # Display domain for short URLs

@app.route('/shorten', methods=['POST'])
def shorten():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    original_url = request.form['original_url']
    code = generate_code(6)  # 6-character short code

    conn = get_db()
    cur = conn.cursor()
    
    # Ensure code uniqueness
    cur.execute("SELECT id FROM urls WHERE short_code=%s", (code,))
    while cur.fetchone():
        code = generate_code(6)

    cur.execute(
        "INSERT INTO urls(user_id, original_url, short_code, created_at) VALUES (%s,%s,%s,%s)",
        (session['user_id'], original_url, code, datetime.now())
    )
    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for('dashboard'))

@app.route('/<code>')
def go(code):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT original_url FROM urls WHERE short_code=%s", (code,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row:
        return redirect(row[0])
    else:
        abort(404)

@app.route('/delete_url/<int:id>')
def delete_url(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM urls WHERE id=%s AND user_id=%s", (id, session['user_id']))
    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for('dashboard'))


# ----------------- CHART API -----------------
@app.route('/api/monthly_data')
def monthly_data():
    if 'user_id' not in session: return jsonify({})
    conn=get_db();cur=conn.cursor()
    cur.execute("SELECT TO_CHAR(date,'YYYY-MM'),SUM(amount) FROM expenses WHERE user_id=%s GROUP BY 1",(session['user_id'],))
    rows=cur.fetchall();cur.close();conn.close()
    return jsonify(labels=[r[0] for r in rows],values=[float(r[1]) for r in rows])

@app.route('/api/category_data')
def category_data():
    if 'user_id' not in session: return jsonify({})
    conn=get_db();cur=conn.cursor()
    cur.execute("SELECT category,SUM(amount) FROM expenses WHERE user_id=%s GROUP BY category",(session['user_id'],))
    rows=cur.fetchall();cur.close();conn.close()
    return jsonify(labels=[r[0] for r in rows],values=[float(r[1]) for r in rows])


# ----------------- DAILY EXPENSE -----------------
@app.route('/daily')
def daily():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('daily.html')

@app.route('/save_daily',methods=['POST'])
def save_daily():
    if 'user_id' not in session: return redirect(url_for('login'))
    items=json.loads(request.form['items'])
    total=float(request.form['total'])
    conn=get_db();cur=conn.cursor()
    cur.execute("INSERT INTO daily_expenses(user_id,date,items_json,total_amount)VALUES(%s,%s,%s,%s)",
                (session['user_id'],datetime.now(),json.dumps(items),total))
    conn.commit();cur.close();conn.close()
    return redirect(url_for('daily_records'))

@app.route('/daily_records',methods=['GET'])
def daily_records():
    if 'user_id' not in session: return redirect(url_for('login'))
    uid=session['user_id'];start=request.args.get('start_date','');end=request.args.get('end_date','')
    conn=get_db();cur=conn.cursor()
    if start and end:
        cur.execute("SELECT id,date,total_amount FROM daily_expenses WHERE user_id=%s AND date BETWEEN %s AND %s ORDER BY date DESC",
                    (uid,start+" 00:00:00",end+" 23:59:59"))
    else:
        cur.execute("SELECT id,date,total_amount FROM daily_expenses WHERE user_id=%s ORDER BY date DESC",(uid,))
    rec=cur.fetchall();cur.close();conn.close()
    return render_template('daily_records.html',records=rec,start_date=start,end_date=end)

@app.route('/view_daily/<int:id>')
def view_daily(id):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn=get_db();cur=conn.cursor()
    cur.execute("SELECT date,items_json,total_amount FROM daily_expenses WHERE id=%s AND user_id=%s",(id,session['user_id']))
    r=cur.fetchone();cur.close();conn.close()
    items=json.loads(r[1]) if r else []
    return render_template('daily.html',readonly=True,items=items,total=r[2],date=r[0])

@app.route('/delete_daily/<int:id>')
def delete_daily(id):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn=get_db();cur=conn.cursor()
    cur.execute("DELETE FROM daily_expenses WHERE id=%s AND user_id=%s",(id,session['user_id']))
    conn.commit();cur.close();conn.close()
    return redirect(url_for('daily_records'))

if __name__=="__main__":
    app.run(debug=True)
