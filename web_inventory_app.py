import streamlit as st
import sqlite3
from datetime import datetime, timedelta
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
    cursor.execute('CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT UNIQUE, sku TEXT UNIQUE, quantity REAL, min_stock REAL DEFAULT 5, price REAL, last_updated TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY, sku TEXT, type TEXT, quantity_change REAL, user TEXT, reason TEXT, timestamp TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, role TEXT)')
    conn.commit()
    conn.close()
    
    # حساب المدير الافتراضي (admin / admin123)
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
    finally:
        conn.close()

def fetch_query(query, params=()):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        data = cursor.fetchall()
        return data, [d[0] for d in cursor.description]
    except: return [], []
    finally: conn.close()

# -------------------------------------------------------------
# 2. واجهة الدخول والتسجيل
# -------------------------------------------------------------
def auth_page():
    st.title("🏆 نظام اكسبو تايم للمخزون")
    
    tabs = st.tabs(["تسجيل الدخول", "إنشاء حساب جديد"])
    
    # --- قسم تسجيل الدخول ---
    with tabs[0]:
        with st.form("login_form"):
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
                else: st.error("بيانات الدخول غير صحيحة")

    # --- قسم إنشاء حساب جديد ---
    with tabs[1]:
        st.info("ملاحظة: الحد الأقصى للموظفين هو 10 فقط.")
        with st.form("signup_form"):
            new_u = st.text_input("اختر اسم مستخدم")
            new_p = st.text_input("اختر كلمة مرور", type="password")
            confirm_p = st.text_input("تأكيد كلمة المرور", type="password")
            if st.form_submit_button("تسجيل"):
                # فحص عدد الموظفين الحاليين
                users_count, _ = fetch_query("SELECT COUNT(*) FROM users WHERE role='موظف'")
                if users_count[0][0] >= 10:
                    st.error("عذراً، تم الوصول للحد الأقصى للموظفين (10).")
                elif new_p != confirm_p:
                    st.error("كلمات المرور غير متطابقة.")
                elif new_u and new_p:
                    hp = hashlib.sha256(new_p.encode()).hexdigest()
                    if execute_query("INSERT INTO users VALUES (?, ?, 'موظف')", (new_u, hp)):
                        st.success("تم إنشاء الحساب بنجاح! يمكنك الآن تسجيل الدخول.")
                else: st.warning("يرجى ملء كافة الخانات.")

# -------------------------------------------------------------
# 3. الوظائف الإضافية (PDF وغيرها)
# -------------------------------------------------------------
def create_pdf_content(order_ref, items_list, creation_date, created_by):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="EXPO TIME - PURCHASE ORDER", ln=True, align='C')
    pdf.ln(10)
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Order: {order_ref} | Created By: {created_by}", ln=True)
    pdf.ln(5)
    for item in items_list:
        pdf.cell(0, 10, txt=f"SKU: {item[0]} | Qty: {item[1]} | Date: {item[2]}", ln=True)
    return pdf.output(dest='S').encode('latin-1')

# -------------------------------------------------------------
# 4. التطبيق الرئيسي
# -------------------------------------------------------------
def main():
    initialize_db()
    if 'logged_in' not in st.session_state: st.session_state.logged_in = False

    if not st.session_state.logged_in:
        auth_page()
        return

    # شريط التحكم الجانبي
    st.sidebar.success(f"مرحباً {st.session_state.username} ({st.session_state.role})")
    if st.sidebar.button("تسجيل الخروج"):
        st.session_state.logged_in = False
        st.rerun()

    menu = ["📦 عرض المخزون", "➕ إضافة وتحديث", "📤 صرف أصناف", "📄 طلب شراء PDF", "📜 سجل العمليات", "👥 إدارة المستخدمين"]
    if st.session_state.role != "مدير": menu.remove("👥 إدارة المستخدمين")
    choice = st.sidebar.selectbox("القائمة", menu)

    # جلب البيانات للبحث
    skus_raw, _ = fetch_query("SELECT sku, name FROM items")
    all_skus = [s[0] for s in skus_raw]
    all_names = [s[1] for s in skus_raw]

    # --- إدارة المستخدمين (للمدير فقط) ---
    if choice == "👥 إدارة المستخدمين":
        st.subheader("التحكم في الموظفين")
        u_list, _ = fetch_query("SELECT username FROM users WHERE role='موظف'")
        to_del = st.selectbox("حذف موظف", [""] + [u[0] for u in u_list])
        if st.button("حذف نهائي") and to_del:
            execute_query("DELETE FROM users WHERE username=?", (to_del,))
            st.success("تم الحذف"); st.rerun()

    # --- إضافة وتحديث (مع ميزة P- الثابتة) ---
    elif choice == "➕ إضافة وتحديث":
        st.subheader("إدخال المخزون")
        if st.session_state.role == "مدير":
            mode = st.radio("العملية", ["جديد", "تحديث"])
        else:
            st.info("صلاحيتك: إضافة صنف جديد فقط.")
            mode = "جديد"
        
        with st.form("item_form"):
            if mode == "تحديث":
                target_sku = st.selectbox("اختر الصنف", [""] + all_skus)
                target_name = ""
            else:
                c1, c2 = st.columns([1, 10])
                c1.markdown("### **P-**")
                sku_in = c2.text_input("تكملة الكود")
                target_sku = f"P-{sku_in}"
                target_name = st.text_input("اسم المنتج الجديد")
            
            qty = st.number_input("الكمية")
            price = st.number_input("السعر")
            
            if st.form_submit_button("اعتماد"):
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if mode == "جديد":
                    if target_name in all_names or target_sku in all_skus:
                        st.error("الاسم أو الكود موجود مسبقاً.")
                    else:
                        execute_query("INSERT INTO items VALUES (NULL,?,?,?,5,?,?)", (target_name, target_sku, qty, price, now))
                        execute_query("INSERT INTO transactions VALUES (NULL, ?, 'IN', ?, ?, 'إضافة صنف', ?)", (target_sku, qty, st.session_state.username, now))
                        st.success("تم الحفظ"); st.rerun()
                else:
                    execute_query("UPDATE items SET quantity=quantity+?, price=?, last_updated=? WHERE sku=?", (qty, price, now, target_sku))
                    execute_query("INSERT INTO transactions VALUES (NULL, ?, 'IN', ?, ?, 'تحديث مدير', ?)", (target_sku, qty, st.session_state.username, now))
                    st.success("تم التحديث"); st.rerun()

    # --- بقية الخيارات (مختصرة) ---
    elif choice == "📦 عرض المخزون":
        d, _ = fetch_query("SELECT name, sku, quantity, price FROM items")
        st.table(pd.DataFrame(d, columns=['الاسم', 'SKU', 'الكمية', 'السعر']))
        if st.session_state.role == "مدير":
            sku_del = st.selectbox("حذف صنف", [""] + all_skus)
            if st.button("حذف المنتج") and sku_del:
                execute_query("DELETE FROM items WHERE sku=?", (sku_del,))
                st.rerun()

    elif choice == "📤 صرف أصناف":
        s = st.selectbox("الصنف", [""] + all_skus)
        q = st.number_input("الكمية")
        if st.button("صرف"):
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (q, s))
            execute_query("INSERT INTO transactions VALUES (NULL, ?, 'OUT', ?, ?, 'صرف مخزني', ?)", (s, q, st.session_state.username, now))
            st.success("تم"); st.rerun()

    elif choice == "📄 طلب شراء PDF":
        po_s = st.selectbox("الصنف", [""] + all_skus)
        po_q = st.number_input("الكمية")
        if st.button("تجهيز PDF"):
            now = datetime.now()
            pdf_b = create_pdf_content("PO-X", [(po_s, po_q, now.date())], now.date(), st.session_state.username)
            st.download_button("تنزيل", pdf_b, "PO.pdf", "application/pdf")

    elif choice == "📜 سجل العمليات":
        logs, _ = fetch_query("SELECT * FROM transactions ORDER BY timestamp DESC")
        st.table(logs)

if __name__ == "__main__":
    main()
