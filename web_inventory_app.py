import streamlit as st
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
from fpdf import FPDF
import hashlib
import os

# -------------------------------------------------------------
# إعداد قاعدة البيانات
# -------------------------------------------------------------
DATABASE_NAME = 'inventory_control.db'

def initialize_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    # جداول النظام
    cursor.execute('CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT UNIQUE, sku TEXT UNIQUE, quantity REAL, unit TEXT, min_stock REAL DEFAULT 5, price REAL, last_updated TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY, sku TEXT, type TEXT, quantity_change REAL, user TEXT, reason TEXT, timestamp TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS bom_recipes (id INTEGER PRIMARY KEY, assembled_product_name TEXT, raw_material_sku TEXT, required_quantity REAL, UNIQUE(assembled_product_name, raw_material_sku))')
    cursor.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, role TEXT)')
    conn.commit()
    conn.close()
    
    # إضافة المدير الافتراضي
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
# دالة إنشاء ملف PDF
# -------------------------------------------------------------
def create_pdf_content(order_ref, items_list, creation_date, created_by):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="EXPO TIME - PURCHASE ORDER", ln=True, align='C')
    pdf.ln(10)
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Order Ref: {order_ref}", ln=True)
    pdf.cell(200, 10, txt=f"Date: {creation_date}", ln=True)
    pdf.cell(200, 10, txt=f"Issuer: {created_by}", ln=True)
    pdf.ln(5)
    pdf.set_fill_color(220, 220, 220)
    pdf.cell(80, 10, "Item Name / SKU", 1, 0, 'C', True)
    pdf.cell(40, 10, "Qty", 1, 0, 'C', True)
    pdf.cell(70, 10, "Date Requested", 1, 1, 'C', True)
    for item in items_list:
        pdf.cell(80, 10, str(item[0]), 1)
        pdf.cell(40, 10, str(item[1]), 1)
        pdf.cell(70, 10, str(item[2]), 1)
        pdf.ln()
    return pdf.output(dest='S').encode('latin-1')

# -------------------------------------------------------------
# التطبيق الرئيسي
# -------------------------------------------------------------
def main():
    initialize_db()
    st.set_page_config(page_title="اكسبو تايم للمخزون", layout="wide")

    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False

    if not st.session_state.logged_in:
        st.title("قفل الأمان - شركة اكسبو تايم")
        with st.form("login_form"):
            user_in = st.text_input("اسم المستخدم")
            pass_in = st.text_input("كلمة المرور", type="password")
            if st.form_submit_button("دخول"):
                h_pass = hashlib.sha256(pass_in.encode()).hexdigest()
                res, _ = fetch_query("SELECT role FROM users WHERE username=? AND password=?", (user_in, h_pass))
                if res:
                    st.session_state.logged_in = True
                    st.session_state.username = user_in
                    st.session_state.role = res[0][0]
                    st.rerun()
                else:
                    st.error("بيانات الدخول غير صحيحة")
        return

    # القائمة الجانبية
    st.sidebar.title(f"مرحباً {st.session_state.username}")
    st.sidebar.info(f"الصلاحية: {st.session_state.role}")
    if st.sidebar.button("تسجيل الخروج"):
        st.session_state.logged_in = False
        st.rerun()

    menu = ["🔍 عرض وحذف الأصناف", "➕ إضافة وتحديث صنف", "⚙️ تعريف منتج BOM", "📤 صرف أصناف", "🏭 صرف BOM", "📦 طلب شراء PDF", "📜 سجل العمليات", "👥 إدارة المستخدمين"]
    if st.session_state.role != "مدير": menu.remove("👥 إدارة المستخدمين")
    choice = st.sidebar.selectbox("القائمة الرئيسية", menu)
    st.markdown("---")

    # جلب الأكواد والأسماء للبحث
    items_raw, _ = fetch_query("SELECT sku, name, unit FROM items")
    all_skus = [s[0] for s in items_raw]
    all_names = [s[1] for s in items_raw]
    item_options = [f"{s[1]} ({s[0]}) - {s[2]}" for s in items_raw]

    # --- 1. إدارة المستخدمين ---
    if choice == "👥 إدارة المستخدمين":
        st.subheader("إدارة طاقم العمل")
        users_list, _ = fetch_query("SELECT username, role FROM users WHERE role='موظف'")
        col1, col2 = st.columns(2)
        with col1:
            st.write("إضافة موظف جديد")
            new_u = st.text_input("اسم المستخدم")
            new_p = st.text_input("كلمة المرور", type="password")
            if st.button("حفظ الموظف"):
                if len(users_list) >= 10: st.error("وصلت للحد الأقصى (10)")
                elif new_u and new_p:
                    hp = hashlib.sha256(new_p.encode()).hexdigest()
                    if execute_query("INSERT INTO users VALUES (?,?,'موظف')", (new_u, hp)):
                        st.success("تمت الإضافة"); st.rerun()
        with col2:
            st.write("حذف موظف")
            user_to_del = st.selectbox("اختر موظفاً", [""] + [u[0] for u in users_list])
            if st.button("تأكيد الحذف") and user_to_del:
                execute_query("DELETE FROM users WHERE username=?", (user_to_del,))
                st.success("تم الحذف"); st.rerun()

    # --- 2. إضافة وتحديث (إدخال يدوي للكود) ---
    elif choice == "➕ إضافة وتحديث صنف":
        st.subheader("إدخال مخزني جديد أو تحديث")
        with st.form("item_form"):
            mode = st.radio("نوع العملية", ["تحديث صنف موجود", "إضافة صنف جديد"])
            if mode == "تحديث صنف موجود":
                target_sku = st.selectbox("اختر الصنف", [""] + all_skus)
                target_name = ""
                unit_val = ""
            else:
                target_sku = st.text_input("أدخل كود الصنف (SKU)").upper()
                target_name = st.text_input("اسم المنتج الجديد")
                unit_val = st.selectbox("الوحدة", ["قطعة", "درزن", "بكت", "جرام", "كيلو", "لتر"])
            
            qty = st.number_input("الكمية", min_value=0, step=1, value=0)
            price = st.number_input("السعر الحالي", min_value=0.0)
            
            if st.form_submit_button("اعتماد العملية"):
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if mode == "إضافة صنف جديد":
                    if target_name in all_names or target_sku in all_skus:
                        st.error("الاسم أو الكود موجود مسبقاً")
                    elif not target_sku or not target_name:
                        st.error("يرجى ملء كافة الحقول")
                    else:
                        execute_query("INSERT INTO items VALUES (NULL,?,?,?,?,?,?)", (target_name, target_sku, qty, unit_val, 5, price, now))
                        execute_query("INSERT INTO transactions VALUES (NULL, ?,'IN',?,?, 'إضافة جديد', ?)", (target_sku, qty, st.session_state.username, now))
                        st.success("تمت الإضافة"); st.rerun()
                else:
                    execute_query("UPDATE items SET quantity=quantity+?, price=?, last_updated=? WHERE sku=?", (qty, price, now, target_sku))
                    execute_query("INSERT INTO transactions VALUES (NULL, ?,'IN',?,?, 'تحديث كمية', ?)", (target_sku, qty, st.session_state.username, now))
                    st.success("تم التحديث"); st.rerun()

    # --- 3. عرض وحذف الأصناف ---
    elif choice == "🔍 عرض وحذف الأصناف":
        search = st.text_input("ابحث بالاسم أو الكود")
        data, _ = fetch_query("SELECT name, sku, quantity, unit, price FROM items WHERE name LIKE ? OR sku LIKE ?", (f'%{search}%', f'%{search}%'))
        if data:
            df = pd.DataFrame(data, columns=['الاسم', 'الكود SKU', 'الكمية', 'الوحدة', 'السعر'])
            st.table(df)
            if st.session_state.role == "مدير":
                to_del = st.selectbox("اختر الكود للحذف النهائي", [""] + [d[1] for d in data])
                if st.button("❌ حذف المنتج نهائياً") and to_del:
                    execute_query("DELETE FROM items WHERE sku=?", (to_del,))
                    st.success("تم الحذف"); st.rerun()

    # --- 4. تعريف BOM (ربط المكونات من القائمة) ---
    elif choice == "⚙️ تعريف منتج BOM":
        st.subheader("تعريف مكونات المنتج النهائي")
        with st.form("bom_form"):
            assembled_product = st.selectbox("المنتج النهائي المجمع", [""] + all_names)
            raw_material = st.selectbox("المكون المادي (المادة الخام)", [""] + item_options)
            required_qty = st.number_input("الكمية المطلوبة من المكون", min_value=1, step=1, value=1)
            
            if st.form_submit_button("حفظ المكون"):
                if assembled_product and raw_material:
                    raw_sku = raw_material.split("(")[1].split(")")[0]
                    execute_query("INSERT OR REPLACE INTO bom_recipes VALUES (NULL, ?, ?, ?)", (assembled_product, raw_sku, required_qty))
                    st.success("تم ربط المكون بنجاح")

    # --- 5. صرف الأصناف (حتى 40 منتج) ---
    elif choice == "📤 صرف أصناف":
        if 'iss_rows' not in st.session_state: st.session_state.iss_rows = 1
        if st.button("➕ إضافة صنف جديد للصرف") and st.session_state.iss_rows < 40:
            st.session_state.iss_rows += 1
        
        basket = []
        for i in range(st.session_state.iss_rows):
            c1, c2 = st.columns([3,1])
            s = c1.selectbox(f"الصنف {i+1}", [""] + item_options, key=f"iss_s_{i}")
            q = c2.number_input(f"الكمية {i+1}", key=f"iss_q_{i}", min_value=1, step=1, value=1)
            if s: basket.append((s.split("(")[1].split(")")[0], q))
            
        if st.button("🚀 تأكيد الصرف"):
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for sku, q in basket:
                execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (q, sku))
                execute_query("INSERT INTO transactions VALUES (NULL, ?,'OUT',?,?, 'صرف يدوي', ?)", (sku, q, st.session_state.username, now))
            st.success("تم الصرف بنجاح"); st.session_state.iss_rows = 1; st.rerun()

    # --- 6. طلب شراء PDF ---
    elif choice == "📦 طلب شراء PDF":
        if 'po_rows' not in st.session_state: st.session_state.po_rows = 1
        if st.button("➕ إضافة صنف جديد للطلب") and st.session_state.po_rows < 40:
            st.session_state.po_rows += 1
            
        po_list = []
        for i in range(st.session_state.po_rows):
            c1, c2, c3 = st.columns([2,1,2])
            s = c1.selectbox(f"الصنف {i+1}", [""] + item_options, key=f"po_s_{i}")
            q = c2.number_input(f"الكمية {i+1}", key=f"po_q_{i}", min_value=1, step=1, value=1)
            d = c3.date_input(f"تاريخ التوريد {i+1}", key=f"po_d_{i}")
            if s: po_list.append((s, q, d.strftime("%Y-%m-%d")))
            
        if st.button("📄 توليد ملف PDF"):
            now_dt = datetime.now()
            pdf_bytes = create_pdf_content(f"PO-{now_dt.strftime('%H%M')}", po_list, now_dt.strftime("%Y-%m-%d"), st.session_state.username)
            st.download_button("📥 تحميل ملف PDF", pdf_bytes, f"PO_{now_dt.strftime('%m%d%H%M')}.pdf", "application/pdf")

    # --- 7. سجل العمليات ---
    elif choice == "📜 سجل العمليات":
        logs, _ = fetch_query("SELECT timestamp, sku, type, quantity_change, user, reason FROM transactions ORDER BY timestamp DESC")
        if logs:
            st.table(pd.DataFrame(logs, columns=['الوقت', 'الكود', 'العملية', 'الكمية', 'المستخدم', 'السبب']))

if __name__ == "__main__":
    main()
