import streamlit as st
import sqlite3
from datetime import datetime
import pandas as pd
from fpdf import FPDF
import hashlib

# -------------------------------------------------------------
# 1. إعداد قاعدة البيانات والترميز
# -------------------------------------------------------------
DATABASE_NAME = 'inventory_control.db'

def initialize_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    # جدول الأصناف
    cursor.execute('''CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        name TEXT UNIQUE, 
        sku TEXT UNIQUE, 
        quantity REAL, 
        min_stock REAL DEFAULT 5, 
        price REAL, 
        last_updated TEXT)''')
    # جدول الحركات (يشمل رقم السند DO أو PO)
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY, 
        ref_code TEXT,
        sku TEXT, 
        type TEXT, 
        quantity_change REAL, 
        user TEXT, 
        reason TEXT, 
        timestamp TEXT)''')
    # جدول المستخدمين
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
        st.error(f"فشلت العملية: {e}")
        return False
    finally:
        conn.close()

def fetch_query(query, params=()):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        return cursor.fetchall(), [d[0] for d in cursor.description]
    except: return [], []
    finally: conn.close()

# دالة لتوليد كود المنتج التالي
def generate_next_sku():
    res, _ = fetch_query("SELECT sku FROM items ORDER BY id DESC LIMIT 1")
    if not res: return "P-1001"
    try:
        last_sku = res[0][0]
        last_num = int(last_sku.split('-')[1])
        return f"P-{last_num + 1}"
    except: return "P-1001"

# -------------------------------------------------------------
# 2. التطبيق الرئيسي
# -------------------------------------------------------------
def main():
    initialize_db()
    if 'logged_in' not in st.session_state: st.session_state.logged_in = False

    if not st.session_state.logged_in:
        st.title("🏆 نظام اكسبو تايم - الدخول")
        t1, t2 = st.tabs(["تسجيل الدخول", "إنشاء حساب موظف"])
        with t1:
            with st.form("login"):
                u = st.text_input("اسم المستخدم")
                p = st.text_input("كلمة المرور", type="password")
                if st.form_submit_button("دخول"):
                    hp = hashlib.sha256(p.encode()).hexdigest()
                    res, _ = fetch_query("SELECT role FROM users WHERE username=? AND password=?", (u, hp))
                    if res:
                        st.session_state.logged_in = True
                        st.session_state.username = u
                        st.session_state.role = res[0][0]
                        st.rerun()
                    else: st.error("خطأ في البيانات")
        with t2:
            with st.form("signup"):
                nu = st.text_input("اسم المستخدم الجديد")
                np = st.text_input("كلمة المرور الجديدة", type="password")
                if st.form_submit_button("تسجيل"):
                    cnt, _ = fetch_query("SELECT COUNT(*) FROM users WHERE role='موظف'")
                    if cnt[0][0] >= 10: st.error("الحد الأقصى 10 موظفين")
                    elif nu and np:
                        hp = hashlib.sha256(np.encode()).hexdigest()
                        if execute_query("INSERT INTO users VALUES (?,?,'موظف')", (nu, hp)):
                            st.success("تم التسجيل")
        return

    st.sidebar.success(f"المستخدم: {st.session_state.username}")
    menu = ["📦 عرض المخزون", "➕ إضافة وتحديث", "📤 أمر صرف (DO)", "📄 طلب شراء (PO)", "📜 سجل العمليات"]
    choice = st.sidebar.selectbox("القائمة", menu)
    if st.sidebar.button("خروج"):
        st.session_state.logged_in = False
        st.rerun()

    # جلب البيانات المحدثة
    data_items, _ = fetch_query("SELECT sku, name, quantity FROM items")
    all_skus = [f"{x[0]} - {x[1]}" for x in data_items]

    # --- 1. إضافة وتحديث ---
    if choice == "➕ إضافة وتحديث":
        st.subheader("إدخال صنف جديد")
        mode = st.radio("العملية", ["جديد", "تحديث (مدير)"]) if st.session_state.role == "مدير" else "جديد"
        with st.form("add_form"):
            if mode == "جديد":
                new_sku = generate_next_sku()
                st.info(f"الكود التلقائي: {new_sku}")
                final_name = st.text_input("اسم المنتج")
                final_sku = new_sku
            else:
                final_sku = st.selectbox("اختر الكود", [x[0] for x in data_items])
                final_name = ""
            qty = st.number_input("الكمية", min_value=0.0)
            price = st.number_input("السعر", min_value=0.0)
            if st.form_submit_button("حفظ"):
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if mode == "جديد":
                    if execute_query("INSERT INTO items (name, sku, quantity, price, last_updated) VALUES (?,?,?,?,?)", (final_name, final_sku, qty, price, now)):
                        execute_query("INSERT INTO transactions VALUES (NULL, 'NEW', ?, 'IN', ?, ?, 'إضافة صنف', ?)", (final_sku, qty, st.session_state.username, now))
                        st.success(f"تم الحفظ بكود: {final_sku}"); st.rerun()
                else:
                    execute_query("UPDATE items SET quantity=quantity+?, price=?, last_updated=? WHERE sku=?", (qty, price, now, final_sku))
                    execute_query("INSERT INTO transactions VALUES (NULL, 'UPDATE', ?, 'IN', ?, ?, 'تحديث إداري', ?)", (final_sku, qty, st.session_state.username, now))
                    st.success("تم التحديث"); st.rerun()

    # --- 2. أمر صرف (DO) - جديد ---
    elif choice == "📤 أمر صرف (DO)":
        st.subheader("إنشاء أمر صرف مخزني (Delivery Order)")
        selected_item = st.selectbox("اختر المنتج للصرف", all_skus)
        dispatch_qty = st.number_input("الكمية المراد صرفها", min_value=1.0)
        reason = st.text_input("الجهة المستلمة / السبب")
        
        if st.button("تأكيد الصرف وتوليد السند"):
            now = datetime.now()
            do_ref = f"DO-{now.strftime('%Y%m%d-%H%M')}" # كود تلقائي لأمر الصرف
            sku_only = selected_item.split(' - ')[0]
            
            # التحقق من الكمية
            current_qty = [x[2] for x in data_items if x[0] == sku_only][0]
            if dispatch_qty > current_qty:
                st.error(f"الكمية غير كافية! المتوفر: {current_qty}")
            else:
                execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (dispatch_qty, sku_only))
                execute_query("INSERT INTO transactions VALUES (NULL, ?, ?, 'OUT', ?, ?, ?, ?)", 
                             (do_ref, sku_only, dispatch_qty, st.session_state.username, reason, now.strftime("%Y-%m-%d %H:%M")))
                st.success(f"تم الصرف بنجاح. رقم السند: {do_ref}")

    # --- 3. طلب شراء (PO) ---
    elif choice == "📄 طلب شراء (PO)":
        st.subheader("إنشاء طلب شراء (Purchase Order)")
        selected_item = st.selectbox("اختر المنتج المطلوب", all_skus)
        po_qty = st.number_input("الكمية المطلوبة", min_value=1.0)
        if st.button("توليد طلب PO"):
            now = datetime.now()
            po_ref = f"PO-{now.strftime('%Y%m%d-%H%M')}"
            st.success(f"تم توليد طلب شراء برقم: {po_ref}")
            # كود توليد الـ PDF يبقى كما في النسخ السابقة...

    # --- 4. عرض المخزون ---
    elif choice == "📦 عرض المخزون":
        d, _ = fetch_query("SELECT name, sku, quantity, price FROM items")
        st.table(pd.DataFrame(d, columns=['الاسم', 'SKU', 'الكمية', 'السعر']))

    # --- 5. سجل العمليات ---
    elif choice == "📜 سجل العمليات":
        st.subheader("سجل الحركات (تتبع PO و DO)")
        l, _ = fetch_query("SELECT timestamp, ref_code, sku, type, quantity_change, user, reason FROM transactions ORDER BY timestamp DESC")
        st.table(pd.DataFrame(l, columns=['الوقت', 'رقم السند', 'الكود', 'العملية', 'الكمية', 'المستخدم', 'البيان']))

if __name__ == "__main__":
    main()
