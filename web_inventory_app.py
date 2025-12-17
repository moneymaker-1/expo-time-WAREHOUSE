import streamlit as st
import sqlite3
from datetime import datetime
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
    # جداول النظام - تم إضافة supplier_name مع جعلها تقبل القيم الفارغة لتجنب الخطأ
    cursor.execute('''CREATE TABLE IF NOT EXISTS items 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, sku TEXT UNIQUE, quantity REAL, 
        min_stock REAL DEFAULT 5, price REAL, supplier_name TEXT DEFAULT 'غير محدد', last_updated TEXT)''')
    
    # تحديث جدول الحركات ليشمل رقم السند (ref_code)
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, ref_code TEXT, sku TEXT, type TEXT, 
        quantity_change REAL, user TEXT, reason TEXT, timestamp TEXT)''')
        
    cursor.execute('''CREATE TABLE IF NOT EXISTS bom_recipes 
        (id INTEGER PRIMARY KEY, assembled_product_name TEXT, raw_material_sku TEXT, required_quantity REAL, 
        UNIQUE(assembled_product_name, raw_material_sku))''')
        
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

# دالة لتوليد كود المنتج التالي تلقائياً P-1001
def get_next_sku():
    res, _ = fetch_query("SELECT MAX(id) FROM items")
    next_id = (res[0][0] + 1) if res and res[0][0] else 1001
    return f"P-{next_id}"

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
    pdf.cell(60, 10, "SKU", 1, 0, 'C', True)
    pdf.cell(40, 10, "Qty", 1, 0, 'C', True)
    pdf.cell(85, 10, "Delivery Requested", 1, 1, 'C', True)
    for item in items_list:
        pdf.cell(60, 10, str(item[0]), 1)
        pdf.cell(40, 10, str(item[1]), 1)
        pdf.cell(85, 10, str(item[2]), 1)
        pdf.ln()
    return pdf.output(dest='S').encode('latin-1')

# -------------------------------------------------------------
# التطبيق الرئيسي
# -------------------------------------------------------------
def main():
    initialize_db()
    st.set_page_config(page_title="اكسبو تايم للمخزون", layout="wide")

    if 'logged_in' not in st.session_state: st.session_state.logged_in = False

    if not st.session_state.logged_in:
        st.title("قفل الأمان - شركة اكسبو تايم")
        tab1, tab2 = st.tabs(["🔐 تسجيل الدخول", "📝 إنشاء حساب جديد"])
        
        with tab1:
            with st.form("login_form"):
                user_in = st.text_input("اسم المستخدم")
                pass_in = st.text_input("كلمة المرور", type="password")
                if st.form_submit_button("دخول"):
                    h_pass = hashlib.sha256(pass_in.encode()).hexdigest()
                    res, _ = fetch_query("SELECT role FROM users WHERE username=? AND password=?", (user_in, h_pass))
                    if res:
                        st.session_state.logged_in, st.session_state.username, st.session_state.role = True, user_in, res[0][0]
                        st.rerun()
                    else: st.error("بيانات الدخول غير صحيحة")
        
        with tab2:
            with st.form("signup_form"):
                new_u = st.text_input("اسم المستخدم الجديد")
                new_p = st.text_input("كلمة المرور الجديدة", type="password")
                if st.form_submit_button("تسجيل كموظف"):
                    users_list, _ = fetch_query("SELECT username FROM users WHERE role='موظف'")
                    if len(users_list) >= 10: st.error("عذراً، تم الوصول للحد الأقصى للموظفين (10)")
                    elif new_u and new_p:
                        hp = hashlib.sha256(new_p.encode()).hexdigest()
                        if execute_query("INSERT INTO users VALUES (?,?,'موظف')", (new_u, hp)):
                            st.success("تم إنشاء الحساب بنجاح! يمكنك الدخول الآن")
        return

    st.sidebar.title(f"مرحباً {st.session_state.username}")
    st.sidebar.info(f"الصلاحية: {st.session_state.role}")
    if st.sidebar.button("تسجيل الخروج"):
        st.session_state.logged_in = False
        st.rerun()

    menu = ["🔍 عرض وحذف الأصناف", "➕ إضافة وتحديث صنف", "⚙️ تعريف منتج BOM", "📤 صرف أصناف (DO)", "🏭 صرف BOM", "📦 طلب شراء PDF (PO)", "📜 سجل العمليات", "👥 إدارة المستخدمين"]
    if st.session_state.role != "مدير": menu.remove("👥 إدارة المستخدمين")
    choice = st.sidebar.selectbox("القائمة الرئيسية", menu)
    st.markdown("---")

    skus_raw, _ = fetch_query("SELECT sku, name, quantity FROM items")
    all_skus = [s[0] for s in skus_raw]
    all_names = [s[1] for s in skus_raw]

    # --- 1. إدارة المستخدمين ---
    if choice == "👥 إدارة المستخدمين":
        st.subheader("إدارة طاقم العمل")
        users_list, _ = fetch_query("SELECT username, role FROM users WHERE role='موظف'")
        st.write(f"عدد الموظفين الحاليين: {len(users_list)}/10")
        user_to_del = st.selectbox("اختر موظفاً لحذفه", [""] + [u[0] for u in users_list])
        if st.button("تأكيد الحذف") and user_to_del:
            execute_query("DELETE FROM users WHERE username=?", (user_to_del,))
            st.success("تم الحذف"); st.rerun()

    # --- 2. إضافة وتحديث (توليد كود تلقائي + إصلاح المورد) ---
    elif choice == "➕ إضافة وتحديث صنف":
        st.subheader("إدارة الأصناف")
        if st.session_state.role == "مدير":
            mode = st.radio("نوع العملية", ["تحديث صنف موجود", "إضافة صنف جديد كلياً"])
        else:
            st.info("صلاحيتك: إضافة أصناف جديدة فقط")
            mode = "إضافة صنف جديد كلياً"

        with st.form("item_form"):
            if mode == "تحديث صنف موجود":
                target_sku = st.selectbox("اختر الصنف", [""] + all_skus)
                target_name = ""
            else:
                next_sku = get_next_sku()
                st.info(f"الكود التلقائي: {next_sku}")
                target_sku = next_sku
                target_name = st.text_input("اسم المنتج الجديد")
            
            qty = st.number_input("الكمية", min_value=0.0)
            price = st.number_input("السعر", min_value=0.0)
            supplier = st.text_input("المورد", value="غير محدد")
            
            if st.form_submit_button("اعتماد العملية"):
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if mode == "إضافة صنف جديد كلياً":
                    if target_name in all_names: st.error("الاسم موجود مسبقاً")
                    else:
                        execute_query("INSERT INTO items (name, sku, quantity, price, supplier_name, last_updated) VALUES (?,?,?,?,?,?)", 
                                     (target_name, target_sku, qty, price, supplier, now))
                        execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES ('NEW', ?, 'IN', ?, ?, 'إضافة صنف', ?)", 
                                     (target_sku, qty, st.session_state.username, now))
                        st.success(f"تمت الإضافة بالكود: {target_sku}"); st.rerun()
                else:
                    execute_query("UPDATE items SET quantity=quantity+?, price=?, last_updated=? WHERE sku=?", (qty, price, now, target_sku))
                    execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES ('UPDATE', ?, 'IN', ?, ?, 'تحديث كمية', ?)", 
                                     (target_sku, qty, st.session_state.username, now))
                    st.success("تم التحديث"); st.rerun()

    # --- 3. عرض وحذف الأصناف (مع التعديل) ---
    elif choice == "🔍 عرض وحذف الأصناف":
        search = st.text_input("ابحث بالاسم أو الكود")
        data, _ = fetch_query("SELECT id, name, sku, quantity, price FROM items WHERE name LIKE ? OR sku LIKE ?", (f'%{search}%', f'%{search}%'))
        if data:
            df = pd.DataFrame(data, columns=['ID', 'الاسم', 'الكود SKU', 'الكمية', 'السعر'])
            st.table(df)
            if st.session_state.role == "مدير":
                st.divider()
                c1, c2 = st.columns(2)
                with c1:
                    edit_sku = st.selectbox("تعديل بيانات SKU", [""] + all_skus)
                    new_p = st.number_input("السعر الجديد")
                    if st.button("تحديث السعر"):
                        execute_query("UPDATE items SET price=? WHERE sku=?", (new_p, edit_sku))
                        st.success("تم التحديث"); st.rerun()
                with c2:
                    to_del = st.selectbox("حذف SKU نهائياً", [""] + all_skus)
                    if st.button("❌ تأكيد الحذف النهائي"):
                        execute_query("DELETE FROM items WHERE sku=?", (to_del,))
                        st.success("تم الحذف"); st.rerun()

    # --- 4. صرف الأصناف (DO تلقائي) ---
    elif choice == "📤 صرف أصناف (DO)":
        st.subheader("إصدار أمر صرف مخزني")
        if 'iss_rows' not in st.session_state: st.session_state.iss_rows = 1
        if st.button("➕ سطر جديد"): st.session_state.iss_rows += 1
        basket = []
        for i in range(st.session_state.iss_rows):
            c1, c2 = st.columns([3,1])
            s = c1.selectbox(f"الصنف{i+1}", [""] + [f"{x[0]} | {x[1]}" for x in skus_raw], key=f"iss_s_{i}")
            q = c2.number_input(f"الكمية{i+1}", key=f"iss_q_{i}")
            if s: basket.append((s.split(" | ")[0], q))
            
        if st.button("🚀 تأكيد الصرف"):
            now = datetime.now()
            do_ref = f"DO-{now.strftime('%y%m%d%H%M')}"
            for s, q in basket:
                curr_q = [x[2] for x in skus_raw if x[0] == s][0]
                if q > curr_q: st.error(f"الكمية غير كافية لـ {s}"); continue
                execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (q, s))
                execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES (?, ?, 'OUT', ?, ?, 'صرف مخزني', ?)", 
                             (do_ref, s, q, st.session_state.username, now.strftime("%Y-%m-%d %H:%M")))
            st.success(f"تم الصرف بنجاح بالسند: {do_ref}"); st.session_state.iss_rows = 1; st.rerun()

    # --- 5. طلب شراء PDF (PO تلقائي) ---
    elif choice == "📦 طلب شراء PDF (PO)":
        if 'po_rows' not in st.session_state: st.session_state.po_rows = 1
        if st.button("➕ إضافة صنف"): st.session_state.po_rows += 1
        po_list = []
        for i in range(st.session_state.po_rows):
            c1, c2, c3 = st.columns([2,1,2])
            s = c1.selectbox(f"الصنف{i+1}", [""] + all_skus, key=f"po_s_{i}")
            q = c2.number_input(f"الكمية{i+1}", key=f"po_q_{i}")
            d = c3.date_input(f"تاريخ التوريد {i+1}", key=f"po_d_{i}")
            if s: po_list.append((s, q, d.strftime("%Y-%m-%d")))
            
        if st.button("📄 توليد ملف PDF"):
            now_dt = datetime.now()
            po_ref = f"PO-{now_dt.strftime('%y%m%d%H%M')}"
            pdf_bytes = create_pdf_content(po_ref, po_list, now_dt.strftime("%Y-%m-%d"), st.session_state.username)
            st.download_button(f"📥 تحميل {po_ref}", pdf_bytes, f"{po_ref}.pdf", "application/pdf")

    # --- 6. سجل العمليات ---
    elif choice == "📜 سجل العمليات":
        st.subheader("سجل الرقابة والتدقيق")
        logs, _ = fetch_query("SELECT timestamp, ref_code, sku, type, quantity_change, user, reason FROM transactions ORDER BY id DESC")
        if logs:
            st.table(pd.DataFrame(logs, columns=['التاريخ', 'رقم السند', 'الكود', 'العملية', 'الكمية', 'المستخدم', 'السبب']))

if __name__ == "__main__":
    main()
