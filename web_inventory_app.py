import streamlit as st
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
from fpdf import FPDF
import hashlib
import os

# -------------------------------------------------------------
# 1. إعداد قاعدة البيانات وتأمين الدخول الافتراضي
# -------------------------------------------------------------
DATABASE_NAME = 'inventory_control.db'

def initialize_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY, 
        name TEXT UNIQUE, 
        sku TEXT UNIQUE, 
        quantity REAL, 
        min_stock REAL DEFAULT 5, 
        price REAL, 
        last_updated TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY, 
        sku TEXT, 
        type TEXT, 
        quantity_change REAL, 
        user TEXT, 
        reason TEXT, 
        timestamp TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS bom_recipes (
        id INTEGER PRIMARY KEY, 
        assembled_product_name TEXT, 
        raw_material_sku TEXT, 
        required_quantity REAL, 
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
    finally:
        conn.close()

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
# 2. وظيفة إنشاء ملف PDF لطلبات المشتريات
# -------------------------------------------------------------
def create_pdf_content(order_ref, items_list, creation_date, created_by):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="EXPO TIME - PURCHASE ORDER", ln=True, align='C')
    pdf.ln(10)
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Order Reference: {order_ref}", ln=True)
    pdf.cell(200, 10, txt=f"Date: {creation_date}", ln=True)
    pdf.cell(200, 10, txt=f"Created By: {created_by}", ln=True)
    pdf.ln(5)
    pdf.set_fill_color(220, 220, 220)
    pdf.cell(60, 10, "SKU", 1, 0, 'C', True)
    pdf.cell(40, 10, "Quantity", 1, 0, 'C', True)
    pdf.cell(85, 10, "Delivery Date", 1, 1, 'C', True)
    for item in items_list:
        pdf.cell(60, 10, str(item[0]), 1)
        pdf.cell(40, 10, str(item[1]), 1)
        pdf.cell(85, 10, str(item[2]), 1)
        pdf.ln()
    return pdf.output(dest='S').encode('latin-1')

# -------------------------------------------------------------
# 3. التطبيق الرئيسي وواجهة تسجيل الدخول
# -------------------------------------------------------------
def main():
    initialize_db()
    st.set_page_config(page_title="اكسبو تايم - إدارة المخزون", layout="wide")

    if 'logged_in' not in st.session_state: st.session_state.logged_in = False

    if not st.session_state.logged_in:
        st.title("نظام شركة اكسبو تايم - تسجيل الدخول")
        user_in = st.text_input("اسم المستخدم")
        pass_in = st.text_input("كلمة المرور", type="password")
        if st.button("دخول"):
            h_pass = hashlib.sha256(pass_in.encode()).hexdigest()
            res, _ = fetch_query("SELECT role FROM users WHERE username=? AND password=?", (user_in, h_pass))
            if res:
                st.session_state.logged_in = True
                st.session_state.username = user_in
                st.session_state.role = res[0][0]
                st.rerun()
            else: st.error("بيانات الدخول غير صحيحة")
        return

    st.sidebar.title(f"المستخدم: {st.session_state.username}")
    st.sidebar.write(f"الصلاحية: {st.session_state.role}")
    if st.sidebar.button("خروج"):
        st.session_state.logged_in = False
        st.rerun()

    menu = ["عرض وحذف الأصناف", "إضافة وتحديث صنف", "تعريف منتج مجمع BOM", "تسجيل صرف أصناف", "تسجيل صرف مجمع BOM", "إنشاء طلب شراء PDF", "سجل العمليات", "إدارة المستخدمين"]
    if st.session_state.role != "مدير":
        menu.remove("إدارة المستخدمين")
        
    choice = st.sidebar.selectbox("القائمة الرئيسية", menu)
    st.markdown("---")

    skus_raw, _ = fetch_query("SELECT sku, name FROM items")
    all_skus = [s[0] for s in skus_raw]
    all_names = [s[1] for s in skus_raw]

    # --- 1. إدارة المستخدمين ---
    if choice == "إدارة المستخدمين":
        st.subheader("إدارة الموظفين (الحد الأقصى 10)")
        users_list, _ = fetch_query("SELECT username, role FROM users WHERE role='موظف'")
        c1, c2 = st.columns(2)
        with c1:
            new_u = st.text_input("اسم المستخدم")
            new_p = st.text_input("كلمة المرور", type="password")
            if st.button("إضافة موظف"):
                if len(users_list) >= 10: st.error("عذراً، لا يمكن إضافة أكثر من 10 موظفين")
                elif new_u and new_p:
                    hp = hashlib.sha256(new_p.encode()).hexdigest()
                    if execute_query("INSERT INTO users VALUES (?,?,'موظف')", (new_u, hp)):
                        st.success("تمت الإضافة"); st.rerun()
        with c2:
            u_del = st.selectbox("اختر الحساب للحذف", [""] + [u[0] for u in users_list])
            if st.button("حذف الموظف") and u_del:
                execute_query("DELETE FROM users WHERE username=?", (u_del,))
                st.success("تم الحذف"); st.rerun()

    # --- 2. إضافة وتحديث (مع البادئة الثابتة P-) ---
    elif choice == "إضافة وتحديث صنف":
        st.subheader("إدارة الأصناف")
        if st.session_state.role == "مدير":
            mode = st.radio("نوع العملية", ["إضافة صنف جديد تماماً", "تحديث صنف موجود (مدير)"])
        else:
            st.warning("صلاحية الموظف: إضافة أصناف جديدة فقط.")
            mode = "إضافة صنف جديد تماماً"
        
        with st.form("item_form"):
            if mode == "تحديث صنف موجود (مدير)":
                target_sku = st.selectbox("اختر الصنف للتحديث", [""] + all_skus)
                target_name = ""
            else:
                st.write("أدخل الكود التكميلي بعد البادئة الثابتة:")
                # جعل P- ثابتة كـ Label أمام خانة الإدخال
                c1, c2 = st.columns([1, 10])
                c1.markdown("### **P-**")
                sku_input = c2.text_input("تكملة كود الصنف (مثلاً: 101)", key="sku_input").upper()
                target_sku = f"P-{sku_input}"
                target_name = st.text_input("اسم المنتج الجديد")
            
            qty = st.number_input("الكمية", min_value=0.0)
            price = st.number_input("السعر", min_value=0.0)
            
            if st.form_submit_button("اعتماد"):
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if mode == "إضافة صنف جديد تماماً":
                    if not sku_input:
                        st.error("⚠️ يرجى إدخال رقم أو كود الصنف.")
                    elif target_name in all_names or target_sku in all_skus:
                        st.error(f"⚠️ الصنف {target_sku} أو الاسم '{target_name}' موجود مسبقاً.")
                    else:
                        execute_query("INSERT INTO items VALUES (NULL,?,?,?,5,?,?)", (target_name, target_sku, qty, price, now))
                        execute_query("INSERT INTO transactions VALUES (NULL, ?, 'IN', ?, ?, 'إضافة صنف', ?)", (target_sku, qty, st.session_state.username, now))
                        st.success(f"تم تسجيل الصنف الجديد {target_sku} بنجاح"); st.rerun()
                elif mode == "تحديث صنف موجود (مدير)":
                    if target_sku:
                        execute_query("UPDATE items SET quantity=quantity+?, price=?, last_updated=? WHERE sku=?", (qty, price, now, target_sku))
                        execute_query("INSERT INTO transactions VALUES (NULL, ?, 'IN', ?, ?, 'تحديث إداري', ?)", (target_sku, qty, st.session_state.username, now))
                        st.success("تم التحديث الإداري"); st.rerun()

    # --- (بقية الأقسام: عرض، صرف، PDF، سجل تتبع نفس منطق النسخ السابقة) ---
    elif choice == "عرض وحذف الأصناف":
        search = st.text_input("بحث بالاسم أو الكود")
        data, _ = fetch_query("SELECT name, sku, quantity, price FROM items WHERE name LIKE ? OR sku LIKE ?", (f'%{search}%', f'%{search}%'))
        if data:
            st.table(pd.DataFrame(data, columns=['الاسم', 'SKU', 'الكمية', 'السعر']))
            if st.session_state.role == "مدير":
                to_del = st.selectbox("حذف منتج نهائياً", [""] + [d[1] for d in data])
                if st.button("❌ تأكيد الحذف"):
                    execute_query("DELETE FROM items WHERE sku=?", (to_del,))
                    st.success("حُذف المنتج"); st.rerun()

    elif choice == "تسجيل صرف أصناف":
        if 'iss_rows' not in st.session_state: st.session_state.iss_rows = 1
        if st.button("➕ سطر جديد"): st.session_state.iss_rows += 1
        basket = []
        for i in range(st.session_state.iss_rows):
            c1, c2 = st.columns([3, 1])
            s = c1.selectbox(f"الصنف {i+1}", [""] + all_skus, key=f"is_{i}")
            q = c2.number_input(f"الكمية {i+1}", key=f"iq_{i}")
            if s: basket.append((s, q))
        if st.button("🚀 تنفيذ الصرف"):
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for s, q in basket:
                execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (q, s))
                execute_query("INSERT INTO transactions VALUES (NULL, ?, 'OUT', ?, ?, 'صرف مخزني', ?)", (s, q, st.session_state.username, now))
            st.success("تم الصرف بنجاح"); st.session_state.iss_rows = 1; st.rerun()

    elif choice == "إنشاء طلب شراء PDF":
        if 'po_rows' not in st.session_state: st.session_state.po_rows = 1
        if st.button("➕ صنف للطلب"): st.session_state.po_rows += 1
        po_list = []
        for i in range(st.session_state.po_rows):
            c1, c2, c3 = st.columns([2, 1, 2])
            s = c1.selectbox(f"الصنف {i+1}", [""] + all_skus, key=f"ps_{i}")
            q = c2.number_input(f"الكمية {i+1}", key=f"po_q_{i}")
            d = c3.date_input(f"تاريخ التوريد {i+1}", key=f"po_d_{i}")
            if s: po_list.append((s, q, d.strftime("%Y-%m-%d")))
        if st.button("📄 توليد PDF"):
            now_dt = datetime.now()
            pdf_bytes = create_pdf_content(f"EXPO-PO-{now_dt.strftime('%H%M')}", po_list, now_dt.strftime("%Y-%m-%d"), st.session_state.username)
            st.download_button("📥 تحميل PDF", pdf_bytes, f"PO_{now_dt.strftime('%m%d%H%M')}.pdf", "application/pdf")

    elif choice == "سجل العمليات":
        logs, _ = fetch_query("SELECT timestamp, sku, type, quantity_change, user, reason FROM transactions ORDER BY timestamp DESC")
        st.table(pd.DataFrame(logs, columns=['الوقت', 'الكود', 'العملية', 'الكمية', 'المستخدم', 'البيان']))

if __name__ == "__main__":
    main()
