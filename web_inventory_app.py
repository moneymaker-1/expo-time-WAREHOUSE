import streamlit as st
import sqlite3
from datetime import datetime
import pandas as pd
from fpdf import FPDF
import hashlib

# -------------------------------------------------------------
# إعداد قاعدة البيانات
# -------------------------------------------------------------
DATABASE_NAME = 'inventory_control.db'

def initialize_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS items 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, sku TEXT UNIQUE, quantity REAL, 
        min_stock REAL DEFAULT 5, price REAL, supplier_name TEXT DEFAULT 'غير محدد', last_updated TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, ref_code TEXT, sku TEXT, type TEXT, 
        quantity_change REAL, user TEXT, reason TEXT, timestamp TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS bom_recipes 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, parent_sku TEXT, component_sku TEXT, qty_needed REAL, 
        UNIQUE(parent_sku, component_sku))''')
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
        st.error(f"خطأ: {e}")
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

# -------------------------------------------------------------
# التطبيق الرئيسي
# -------------------------------------------------------------
def main():
    initialize_db()
    st.set_page_config(page_title="اكسبو تايم - نظام النواقص", layout="wide")

    if 'logged_in' not in st.session_state: st.session_state.logged_in = False

    if not st.session_state.logged_in:
        st.title("🏆 شركة اكسبو تايم - الدخول")
        u = st.text_input("المستخدم")
        p = st.text_input("كلمة المرور", type="password")
        if st.button("دخول"):
            hp = hashlib.sha256(p.encode()).hexdigest()
            res, _ = fetch_query("SELECT role FROM users WHERE username=? AND password=?", (u, hp))
            if res:
                st.session_state.logged_in, st.session_state.username, st.session_state.role = True, u, res[0][0]
                st.rerun()
        return

    # --- محرك التنبيهات الذكي ---
    low_stock_items, _ = fetch_query("SELECT name, quantity, min_stock FROM items WHERE quantity <= min_stock")
    if low_stock_items:
        st.sidebar.warning(f"🚨 تنبيه: يوجد {len(low_stock_items)} أصناف شارفت على النفاد!")

    st.sidebar.title(f"مرحباً {st.session_state.username}")
    menu = ["🔍 المخزون", "➕ إضافة وتحديث", "🚨 تنبيهات النواقص", "📤 صرف مدمج (DO)", "⚙️ تعريف BOM", "📜 السجل"]
    choice = st.sidebar.selectbox("القائمة", menu)

    # --- 1. تنبيهات النواقص (جديد) ---
    if choice == "🚨 تنبيهات النواقص":
        st.subheader("قائمة الأصناف المطلوبة (تحت الحد الأدنى)")
        if low_stock_items:
            df_low = pd.DataFrame(low_stock_items, columns=['اسم الصنف', 'الكمية الحالية', 'حد التنبيه'])
            st.error("الأصناف التالية تتطلب إعادة طلب شراء فوراً:")
            st.table(df_low)
            

[Image of an inventory reorder point graph showing safety stock and lead time]

        else:
            st.success("✅ جميع الأصناف متوفرة فوق الحد الأدنى.")

    # --- 2. إضافة وتحديث (مع تحديد حد التنبيه) ---
    elif choice == "➕ إضافة وتحديث":
        st.subheader("إدارة الأصناف")
        with st.form("add_item"):
            res, _ = fetch_query("SELECT MAX(id) FROM items")
            next_sku = f"P-{res[0][0]+1 if res[0][0] else 1001}"
            st.info(f"الكود التلقائي: {next_sku}")
            name = st.text_input("اسم المنتج")
            qty = st.number_input("الكمية الحالية", min_value=0.0)
            m_stock = st.number_input("حد التنبيه (أقل كمية مسموحة)", value=5.0) # حد النقصان
            price = st.number_input("السعر")
            if st.form_submit_button("حفظ"):
                now = datetime.now().strftime("%Y-%m-%d %H:%M")
                execute_query("INSERT INTO items (name, sku, quantity, min_stock, price, last_updated) VALUES (?,?,?,?,?,?)", 
                             (name, next_sku, qty, m_stock, price, now))
                st.success("تم الحفظ بنجاح")

    # --- 3. عرض المخزون ---
    elif choice == "🔍 المخزون":
        d, _ = fetch_query("SELECT name, sku, quantity, min_stock, price FROM items")
        df = pd.DataFrame(d, columns=['الاسم', 'SKU', 'الكمية', 'حد التنبيه', 'السعر'])
        
        # تلوين النواقص باللون الأحمر في الجدول
        def color_low_stock(val):
            color = 'red' if val <= 5 else 'black' # مثال بسيط للتلوين
            return f'color: {color}'
        
        st.dataframe(df.style.apply(lambda x: ['background-color: #ffcccc' if x['الكمية'] <= x['حد التنبيه'] else '' for i in x], axis=1), use_container_width=True)

    # --- الأقسام الأخرى (صرف، BOM، سجل) تبقى كما هي ---
    elif choice == "📤 صرف مدمج (DO)":
        st.subheader("أمر صرف مخزني")
        # (كود الصرف المدمج السابق...)
        pass

if __name__ == "__main__":
    main()
