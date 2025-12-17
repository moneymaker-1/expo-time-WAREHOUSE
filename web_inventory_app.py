import streamlit as st
import sqlite3
from datetime import datetime
import pandas as pd
import hashlib

# -------------------------------------------------------------
# 1. إعداد قاعدة البيانات
# -------------------------------------------------------------
DATABASE_NAME = 'inventory_control.db'

def initialize_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        name TEXT UNIQUE, 
        sku TEXT UNIQUE, 
        quantity REAL, 
        price REAL, 
        supplier_name TEXT DEFAULT 'غير محدد', 
        last_updated TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS bom (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_sku TEXT,
        component_sku TEXT,
        quantity_needed REAL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        ref_code TEXT, sku TEXT, type TEXT, quantity_change REAL, 
        user TEXT, reason TEXT, timestamp TEXT)''')
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
        if "UNIQUE constraint failed" in str(e):
            st.error("❌ المنتج أو الكود موجود مسبقاً!")
        else:
            st.error(f"⚠️ خطأ: {e}")
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

# --- دالة توليد الكود المصححة لضمان التطابق ---
def get_next_sku():
    # جلب أكبر رقم ID موجود لضمان تسلسل الأرقام
    res, _ = fetch_query("SELECT MAX(id) FROM items")
    if res and res[0][0]:
        next_val = res[0][0] + 1
    else:
        next_val = 1001  # البداية الافتراضية إذا كان الجدول فارغاً
    return f"P-{next_val}"

# -------------------------------------------------------------
# 2. التطبيق الرئيسي
# -------------------------------------------------------------
def main():
    initialize_db()
    
    if 'logged_in' not in st.session_state: st.session_state.logged_in = False

    if not st.session_state.logged_in:
        st.title("🏆 نظام شركة اكسبو تايم")
        tab1, tab2 = st.tabs(["تسجيل الدخول", "إنشاء حساب"])
        with tab1:
            u = st.text_input("المستخدم")
            p = st.text_input("كلمة المرور", type="password")
            if st.button("دخول"):
                hp = hashlib.sha256(p.encode()).hexdigest()
                res, _ = fetch_query("SELECT role FROM users WHERE username=? AND password=?", (u, hp))
                if res:
                    st.session_state.logged_in, st.session_state.username, st.session_state.role = True, u, res[0][0]
                    st.rerun()
        return

    st.sidebar.title(f"مرحباً {st.session_state.username}")
    menu = ["📦 المخزون", "➕ إضافة منتج", "📤 أمر صرف (DO)", "🛠️ قائمة BOM", "📜 السجل"]
    choice = st.sidebar.selectbox("القائمة", menu)
    if st.sidebar.button("خروج"):
        st.session_state.logged_in = False
        st.rerun()

    # --- 1. إضافة منتج (مع الكود المصحح) ---
    if choice == "➕ إضافة منتج":
        st.subheader("إضافة صنف جديد")
        # استدعاء الدالة الجديدة لضمان الكود P-1xxx
        next_sku = get_next_sku()
        with st.form("add_form"):
            st.info(f"الكود التلقائي للمنتج: {next_sku}")
            name = st.text_input("اسم المنتج")
            qty = st.number_input("الكمية", min_value=0.0)
            price = st.number_input("السعر", min_value=0.0)
            supplier = st.text_input("المورد", value="اكسبو تايم")
            if st.form_submit_button("حفظ"):
                if name:
                    now = datetime.now().strftime("%Y-%m-%d %H:%M")
                    if execute_query("INSERT INTO items (name, sku, quantity, price, supplier_name, last_updated) VALUES (?,?,?,?,?,?)", 
                                     (name, next_sku, qty, price, supplier, now)):
                        st.success(f"✅ تم الحفظ بنجاح بالكود: {next_sku}")
                        st.rerun()
                else: st.warning("يرجى كتابة اسم المنتج")

    # --- 2. المخزون (تعديل وحذف) ---
    elif choice == "📦 المخزون":
        st.subheader("إدارة المخزون")
        data, _ = fetch_query("SELECT id, name, sku, quantity, price FROM items")
        if data:
            df = pd.DataFrame(data, columns=['ID', 'الاسم', 'SKU', 'الكمية', 'السعر'])
            st.table(df)
            
            if st.session_state.role == "مدير":
                st.markdown("---")
                c1, c2 = st.columns(2)
                with c1:
                    target_sku = st.selectbox("اختر SKU للتعديل", [x[2] for x in data])
                    new_q = st.number_input("تحديث الكمية")
                    if st.button("تحديث"):
                        execute_query("UPDATE items SET quantity=? WHERE sku=?", (new_q, target_sku))
                        st.rerun()
                with c2:
                    del_sku = st.selectbox("اختر SKU للحذف", [x[2] for x in data])
                    if st.button("حذف نهائي"):
                        execute_query("DELETE FROM items WHERE sku=?", (del_sku,))
                        st.rerun()

    # --- 3. أمر صرف (DO) - إصلاح محرك الصرف ---
    elif choice == "📤 أمر صرف (DO)":
        st.subheader("صرف مخزني")
        items_raw, _ = fetch_query("SELECT sku, name, quantity FROM items")
        selection = st.selectbox("المنتج", [f"{x[0]} | {x[1]}" for x in items_raw])
        q_out = st.number_input("الكمية", min_value=1.0)
        if st.button("تأكيد الصرف"):
            sku_only = selection.split(" | ")[0]
            curr_qty = [x[2] for x in items_raw if x[0] == sku_only][0]
            if q_out > curr_qty: st.error("المخزون غير كافٍ")
            else:
                now = datetime.now()
                do_ref = f"DO-{now.strftime('%y%m%d%H%M')}"
                execute_query("UPDATE items SET quantity = quantity - ? WHERE sku = ?", (q_out, sku_only))
                execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES (?,?,'OUT',?,?,?,?)",
                             (do_ref, sku_only, q_out, st.session_state.username, "صرف عادي", now.strftime("%Y-%m-%d %H:%M")))
                st.success(f"✅ تم الصرف برقم: {do_ref}")
                st.rerun()

    # --- 4. قائمة BOM ---
    elif choice == "🛠️ قائمة BOM":
        st.subheader("تعريف المكونات (BOM)")
        items_raw, _ = fetch_query("SELECT sku, name FROM items")
        options = [f"{x[0]} | {x[1]}" for x in items_raw]
        with st.form("bom"):
            p_sku = st.selectbox("المنتج النهائي", options).split(" | ")[0]
            c_sku = st.selectbox("المكون المادي", options).split(" | ")[0]
            qty_n = st.number_input("الكمية المطلوبة", min_value=0.1)
            if st.form_submit_button("إضافة"):
                execute_query("INSERT INTO bom (parent_sku, component_sku, quantity_needed) VALUES (?,?,?)", (p_sku, c_sku, qty_n))
                st.success("تم الربط")

    elif choice == "📜 سجل العمليات":
        l, _ = fetch_query("SELECT timestamp, ref_code, sku, type, quantity_change, user FROM transactions ORDER BY id DESC")
        st.table(pd.DataFrame(l, columns=['الوقت', 'السند', 'الكود', 'النوع', 'الكمية', 'المستخدم']))

if __name__ == "__main__":
    main()
