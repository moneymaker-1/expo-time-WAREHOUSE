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
    # تحديث الجداول لدعم الوحدات والترقيم التلقائي
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
        st.error(f"خطأ برمجيا: {e}")
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

# دالة توليد كود SKU تلقائياً لضمان التسلسل
def get_next_sku():
    res, _ = fetch_query("SELECT MAX(id) FROM items")
    next_id = (res[0][0] + 1) if res and res[0][0] else 1001
    return f"P-{next_id:05d}"

# -------------------------------------------------------------
# 2. التطبيق الرئيسي
# -------------------------------------------------------------
def main():
    initialize_db()
    st.set_page_config(page_title="اكسبو تايم - المتكامل", layout="wide")

    if 'logged_in' not in st.session_state: st.session_state.logged_in = False

    if not st.session_state.logged_in:
        st.title("قفل الأمان - شركة اكسبو تايم")
        u = st.text_input("المستخدم")
        p = st.text_input("كلمة المرور", type="password")
        if st.button("دخول"):
            hp = hashlib.sha256(p.encode()).hexdigest()
            res, _ = fetch_query("SELECT role FROM users WHERE username=? AND password=?", (u, hp))
            if res:
                st.session_state.logged_in, st.session_state.username, st.session_state.role = True, u, res[0][0]
                st.rerun()
        return

    # الشريط الجانبي وتنبيهات النواقص
    low_stock_data, _ = fetch_query("SELECT name FROM items WHERE quantity <= min_stock")
    if low_stock_data:
        st.sidebar.warning(f"🚨 يوجد {len(low_stock_data)} أصناف تحت الحد الأدنى!")

    st.sidebar.title(f"مرحباً {st.session_state.username}")
    menu = ["🔍 عرض المخزون", "➕ إضافة صنف جديد", "⚙️ تعريف BOM", "📤 صرف أصناف (DO)", "📜 سجل العمليات"]
    choice = st.sidebar.selectbox("القائمة", menu)
    
    skus_raw, _ = fetch_query("SELECT sku, name, quantity, unit FROM items")
    all_units = ["قطعة", "بكت", "جرام", "درزن"]

    # --- 1. إضافة صنف جديد (وحدات مخصصة + كود تلقائي) ---
    if choice == "➕ إضافة صنف جديد":
        st.subheader("إدخال صنف جديد")
        auto_sku = get_next_sku()
        st.info(f"كود المنتج القادم: {auto_sku}")
        with st.form("add_form"):
            name = st.text_input("اسم المنتج")
            col1, col2 = st.columns(2)
            # حل مشكلة Float/Integer عبر ضبط القيمة الافتراضية كـ Int
            qty = col1.number_input("الكمية الافتتاحية", min_value=0, step=1, value=0, format="%d")
            unit = col2.selectbox("وحدة القياس", all_units)
            price = st.number_input("سعر التكلفة", min_value=0.0)
            m_stock = st.number_input("حد تنبيه النواقص", min_value=0, step=1, value=5, format="%d")
            
            if st.form_submit_button("حفظ"):
                if name:
                    now = datetime.now().strftime("%Y-%m-%d %H:%M")
                    if execute_query("INSERT INTO items (name, sku, quantity, unit, min_stock, price, last_updated) VALUES (?,?,?,?,?,?,?)", 
                                     (name, auto_sku, int(qty), unit, int(m_stock), price, now)):
                        execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES ('NEW', ?, 'IN', ?, ?, 'إضافة صنف', ?)", 
                                     (auto_sku, int(qty), st.session_state.username, now))
                        st.success(f"تم الحفظ بنجاح بالكود: {auto_sku}"); st.rerun()

    # --- 2. تعريف BOM (دمج الوحدات) ---
    elif choice == "⚙️ تعريف BOM":
        st.subheader("تعريف مكونات المنتج")
        with st.form("bom_reg"):
            p_name = st.selectbox("المنتج المجمع", [x[1] for x in skus_raw])
            c_sku = st.selectbox("المكون المادي (المادة الخام)", [f"{x[0]} | {x[1]} ({x[3]})" for x in skus_raw])
            req_qty = st.number_input("الكمية المطلوبة لكل وحدة", min_value=1, step=1, value=1, format="%d")
            if st.form_submit_button("حفظ الربط"):
                sku_only = c_sku.split(" | ")[0]
                execute_query("INSERT OR REPLACE INTO bom_recipes (assembled_product_name, raw_material_sku, required_quantity) VALUES (?,?,?)", 
                             (p_name, sku_only, int(req_qty)))
                st.success("تم الربط بنجاح")

    # --- 3. صرف أصناف مجمع (DO) (حل مشكلة Integer) ---
    elif choice == "📤 صرف أصناف (DO)":
        st.subheader("سلة صرف الأصناف")
        if 'basket' not in st.session_state: st.session_state.basket = []
        
        col1, col2, col3 = st.columns([3, 1, 1])
        item_sel = col1.selectbox("اختر الصنف", [""] + [f"{x[0]} | {x[1]} ({x[3]})" for x in skus_raw])
        amount = col2.number_input("الكمية", min_value=1, step=1, value=1, format="%d")
        
        if col3.button("➕ أضف للسند"):
            if item_sel:
                sku = item_sel.split(" | ")[0]
                st.session_state.basket.append({"الكود": sku, "الكمية": int(amount)})
                st.toast("تمت الإضافة")

        if st.session_state.basket:
            st.table(pd.DataFrame(st.session_state.basket))
            if st.button("🚀 تأكيد صرف السند"):
                now = datetime.now()
                do_ref = f"DO-{now.strftime('%y%m%d%H%M')}"
                for item in st.session_state.basket:
                    execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (item['الكمية'], item['الكود']))
                    execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES (?,?,'OUT',?,?,?,?)", 
                                 (do_ref, item['الكود'], item['الكمية'], st.session_state.username, "صرف مجمع", now.strftime("%Y-%m-%d %H:%M")))
                st.success(f"تم الصرف بالسند: {do_ref}"); st.session_state.basket = []; st.rerun()

    # --- 4. عرض المخزون (أرقام صحيحة وتنسيق احترافي) ---
    elif choice == "🔍 عرض المخزون":
        data, _ = fetch_query("SELECT name, sku, quantity, unit, price, min_stock FROM items")
        if data:
            df = pd.DataFrame(data, columns=['الاسم', 'SKU', 'الكمية', 'الوحدة', 'السعر', 'الحد الأدنى'])
            def highlight_low(row):
                if row.الكمية <= row['الحد الأدنى']:
                    return ['background-color: #fff0f0; color: #b30000; font-weight: bold'] * len(row)
                return [''] * len(row)
            st.dataframe(df.style.apply(highlight_low, axis=1), use_container_width=True)

    elif choice == "📜 سجل العمليات":
        logs, _ = fetch_query("SELECT timestamp, ref_code, sku, type, quantity_change, user FROM transactions ORDER BY id DESC")
        if logs:
            df_logs = pd.DataFrame(logs, columns=['الوقت', 'السند', 'الكود', 'النوع', 'الكمية', 'المستخدم'])
            df_logs['الكمية'] = df_logs['الكمية'].astype(int)
            st.table(df_logs)

if __name__ == "__main__":
    main()
