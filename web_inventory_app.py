import streamlit as st
import sqlite3
from datetime import datetime
import pandas as pd
from fpdf import FPDF
import hashlib

# -------------------------------------------------------------
# 1. إعداد قاعدة البيانات
# -------------------------------------------------------------
DATABASE_NAME = 'inventory_control.db'

def initialize_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    # إضافة عمود الوحدة (unit) وتعديل الكمية لتخزينها كقيم صحيحة
    cursor.execute('''CREATE TABLE IF NOT EXISTS items 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, sku TEXT UNIQUE, quantity INTEGER, 
        unit TEXT, min_stock INTEGER DEFAULT 5, price REAL, last_updated TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, ref_code TEXT, sku TEXT, type TEXT, 
        quantity_change INTEGER, user TEXT, reason TEXT, timestamp TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS bom_recipes 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, assembled_product_name TEXT, raw_material_sku TEXT, required_quantity INTEGER, 
        UNIQUE(assembled_product_name, raw_material_sku))''')
    cursor.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, role TEXT)')
    conn.commit()
    conn.close()
    
    admin_pass = hashlib.sha256("admin123".encode()).hexdigest()
    execute_query('INSERT OR IGNORE INTO users VALUES (?, ?, ?)', ('admin', admin_pass, 'مدير'))

def execute_query(query, params=()):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        conn.commit()
        return True
    except sqlite3.Error as e:
        st.error(f"خطأ في قاعدة البيانات: {e}")
        return False
    finally: conn.close()

def fetch_query(query, params=()):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        data = cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        return data, cols
    except: return [], []
    finally: conn.close()

def get_next_sku():
    res, _ = fetch_query("SELECT MAX(id) FROM items")
    next_id = (res[0][0] + 1) if res and res[0][0] else 1001
    return f"P-{next_id:05d}"

# -------------------------------------------------------------
# 2. التطبيق الرئيسي
# -------------------------------------------------------------
def main():
    initialize_db()
    st.set_page_config(page_title="نظام اكسبو تايم - الإصدار المطور", layout="wide")

    if 'logged_in' not in st.session_state: st.session_state.logged_in = False

    if not st.session_state.logged_in:
        st.title("قفل الأمان - شركة اكسبو تايم")
        u = st.text_input("اسم المستخدم")
        p = st.text_input("كلمة المرور", type="password")
        if st.button("دخول"):
            hp = hashlib.sha256(p.encode()).hexdigest()
            res, _ = fetch_query("SELECT role FROM users WHERE username=? AND password=?", (u, hp))
            if res:
                st.session_state.logged_in, st.session_state.username, st.session_state.role = True, u, res[0][0]
                st.rerun()
        return

    # تنبيه النواقص
    low_stock_data, _ = fetch_query("SELECT name FROM items WHERE quantity <= min_stock")
    if low_stock_data:
        st.sidebar.warning(f"🚨 تنبيه: يوجد {len(low_stock_data)} أصناف تحت الحد الأدنى!")

    st.sidebar.title(f"مرحباً {st.session_state.username}")
    menu = ["🔍 عرض الأصناف", "➕ إضافة صنف جديد", "📤 صرف أصناف مجمع (DO)", "⚙️ تعريف BOM", "📜 سجل العمليات"]
    choice = st.sidebar.selectbox("القائمة الرئيسية", menu)
    
    skus_raw, _ = fetch_query("SELECT sku, name, quantity, unit FROM items")
    all_units = ["قطعة", "بكت", "جرام", "درزن"]

    # --- 1. عرض الأصناف (أرقام صحيحة + وحدة المنتج) ---
    if choice == "🔍 عرض الأصناف":
        st.subheader("إدارة المخزون")
        search = st.text_input("بحث بالاسم أو الكود")
        data, _ = fetch_query("SELECT name, sku, quantity, unit, price, min_stock FROM items WHERE name LIKE ? OR sku LIKE ?", (f'%{search}%', f'%{search}%'))
        if data:
            df = pd.DataFrame(data, columns=['الاسم', 'الكود SKU', 'الكمية', 'الوحدة', 'السعر', 'الحد الأدنى'])
            
            def highlight_low(row):
                if row.الكمية <= row['الحد الأدنى']:
                    return ['background-color: #fff0f0; color: #b30000; font-weight: bold'] * len(row)
                return [''] * len(row)
            
            st.dataframe(df.style.apply(highlight_low, axis=1), use_container_width=True)

    # --- 2. إضافة صنف جديد (وحدات مخصصة + كود تلقائي) ---
    elif choice == "➕ إضافة صنف جديد":
        st.subheader("إدخال صنف جديد")
        auto_sku = get_next_sku()
        st.info(f"كود المنتج القادم: {auto_sku}")
        with st.form("add_form"):
            name = st.text_input("اسم المنتج")
            col1, col2 = st.columns(2)
            qty = col1.number_input("الكمية الافتتاحية", min_value=0, step=1, format="%d")
            unit = col2.selectbox("وحدة القياس", all_units)
            price = st.number_input("سعر التكلفة", min_value=0.0)
            m_stock = st.number_input("حد تنبيه النواقص", value=5, step=1, format="%d")
            
            if st.form_submit_button("حفظ في المخزن"):
                if name:
                    now = datetime.now().strftime("%Y-%m-%d %H:%M")
                    if execute_query("INSERT INTO items (name, sku, quantity, unit, min_stock, price, last_updated) VALUES (?,?,?,?,?,?,?)", 
                                     (name, auto_sku, int(qty), unit, int(m_stock), price, now)):
                        execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES ('NEW', ?, 'IN', ?, ?, 'إضافة صنف', ?)", 
                                     (auto_sku, int(qty), st.session_state.username, now))
                        st.success(f"تم الحفظ بنجاح بالكود: {auto_sku}"); st.rerun()

    # --- 3. صرف أصناف مجمع (DO) ---
    elif choice == "📤 صرف أصناف مجمع (DO)":
        st.subheader("سلة صرف الأصناف (متعدد)")
        if 'basket' not in st.session_state: st.session_state.basket = []

        col1, col2, col3 = st.columns([3, 1, 1])
        item_sel = col1.selectbox("اختر الصنف", [""] + [f"{x[0]} | {x[1]} ({x[3]})" for x in skus_raw])
        amount = col2.number_input("الكمية", min_value=1, step=1, format="%d")
        
        if col3.button("➕ أضف للسند"):
            if item_sel:
                sku = item_sel.split(" | ")[0]
                name = item_sel.split(" | ")[1].split(" (")[0]
                st.session_state.basket.append({"الكود": sku, "الاسم": name, "الكمية": int(amount)})
                st.toast("تمت الإضافة للسلة")

        if st.session_state.basket:
            st.table(pd.DataFrame(st.session_state.basket))
            c1, c2 = st.columns(2)
            if c1.button("🚀 تأكيد صرف السند"):
                now = datetime.now()
                do_ref = f"DO-{now.strftime('%y%m%d%H%M')}"
                for item in st.session_state.basket:
                    execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (item['الكمية'], item['الكود']))
                    execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES (?,?,'OUT',?,?,?,?)", 
                                 (do_ref, item['الكود'], item['الكمية'], st.session_state.username, "صرف مجمع", now.strftime("%Y-%m-%d %H:%M")))
                st.success(f"تم الصرف بالسند: {do_ref}"); st.session_state.basket = []; st.rerun()
            if c2.button("🗑️ إفراغ السلة"):
                st.session_state.basket = []; st.rerun()

    # --- 4. سجل العمليات (أرقام صحيحة) ---
    elif choice == "📜 سجل العمليات":
        st.subheader("سجل الحركات")
        logs, _ = fetch_query("SELECT timestamp, ref_code, sku, type, quantity_change, user, reason FROM transactions ORDER BY id DESC")
        if logs:
            df_logs = pd.DataFrame(logs, columns=['الوقت', 'السند', 'الكود', 'العملية', 'الكمية', 'المستخدم', 'السبب'])
            # تحويل الكمية في السجل لرقم صحيح عند العرض
            df_logs['الكمية'] = df_logs['الكمية'].astype(int)
            st.table(df_logs)

if __name__ == "__main__":
    main()
