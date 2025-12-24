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
    # جداول النظام مع إضافة عمود المورد وحد التنبيه
    cursor.execute('''CREATE TABLE IF NOT EXISTS items 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, sku TEXT UNIQUE, quantity INTEGER, 
        unit TEXT, min_stock INTEGER DEFAULT 5, price REAL, supplier TEXT, last_updated TEXT)''')
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

# توليد كود الصنف تلقائياً (مخفي)
def generate_auto_sku():
    res, _ = fetch_query("SELECT MAX(id) FROM items")
    next_id = (res[0][0] + 1) if res and res[0][0] else 1001
    return f"P-{next_id:05d}"

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
    st.set_page_config(page_title="اكسبو تايم المتكامل", layout="wide")

    if 'logged_in' not in st.session_state: st.session_state.logged_in = False

    if not st.session_state.logged_in:
        st.title("🔐 قفل الأمان - شركة اكسبو تايم")
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
        return

    # تنبيه النواقص الجانبي
    low_stock_data, _ = fetch_query("SELECT name FROM items WHERE quantity <= min_stock")
    if low_stock_data:
        st.sidebar.error(f"⚠️ تنبيه: يوجد {len(low_stock_data)} أصناف قاربت على الانتهاء!")

    st.sidebar.title(f"مرحباً {st.session_state.username}")
    st.sidebar.info(f"الصلاحية: {st.session_state.role}")
    if st.sidebar.button("تسجيل الخروج"):
        st.session_state.logged_in = False
        st.rerun()

    menu = ["🔍 عرض المخزون والإدارة", "➕ إضافة صنف جديد", "⚙️ تعريف منتج BOM", "📤 صرف أصناف مجمع", "🏭 صرف BOM", "📦 طلب شراء PDF", "📜 سجل العمليات", "👥 إدارة المستخدمين"]
    if st.session_state.role != "مدير": menu.remove("👥 إدارة المستخدمين")
    choice = st.sidebar.selectbox("القائمة الرئيسية", menu)
    st.markdown("---")

    items_raw, _ = fetch_query("SELECT sku, name, quantity, unit, min_stock, price, supplier FROM items")
    all_skus = [s[0] for s in items_raw]
    all_names = [s[1] for s in items_raw]
    item_options = [f"{s[1]} ({s[0]})" for s in items_raw]

    # --- 1. عرض المخزون والإدارة (صلاحيات مطلقة للمدير) ---
    if choice == "🔍 عرض المخزون والإدارة":
        st.subheader("إدارة بيانات المخزون")
        search = st.text_input("بحث بالاسم أو الكود")
        data, _ = fetch_query("SELECT name, sku, quantity, unit, price, supplier, min_stock FROM items WHERE name LIKE ? OR sku LIKE ?", (f'%{search}%', f'%{search}%'))
        if data:
            df = pd.DataFrame(data, columns=['الاسم', 'الكود SKU', 'الكمية', 'الوحدة', 'السعر', 'المورد', 'حد التنبيه'])
            
            # تلوين النواقص
            def highlight_low(row):
                return ['background-color: #fff0f0; color: #b30000; font-weight: bold' if row['الكمية'] <= row['حد التنبيه'] else '' for _ in row]
            st.dataframe(df.style.apply(highlight_low, axis=1), use_container_width=True)

            if st.session_state.role == "مدير":
                st.write("🔧 **لوحة تحكم المدير (تعديل/حذف)**")
                target = st.selectbox("اختر الكود للتعديل", [""] + [d[1] for d in data])
                if target:
                    c1, c2, c3 = st.columns(3)
                    new_q = c1.number_input("الكمية", value=0)
                    new_p = c2.number_input("السعر", value=0.0)
                    new_s = c3.text_input("المورد")
                    if st.button("✅ حفظ التعديلات المطلقة"):
                        execute_query("UPDATE items SET quantity=?, price=?, supplier=? WHERE sku=?", (new_q, new_p, new_s, target))
                        st.success("تم التحديث"); st.rerun()
                    if st.button("❌ حذف المنتج نهائياً"):
                        execute_query("DELETE FROM items WHERE sku=?", (target,))
                        st.error("تم الحذف"); st.rerun()

    # --- 2. إضافة صنف جديد (ترقيم تلقائي مخفي) ---
    elif choice == "➕ إضافة صنف جديد":
        st.subheader("إدخال صنف جديد")
        with st.form("add_form"):
            name = st.text_input("اسم المنتج الجديد")
            col1, col2 = st.columns(2)
            qty = col1.number_input("الكمية الأولية", min_value=0, step=1)
            unit = col2.selectbox("الوحدة", ["قطعة", "بكت", "جرام", "درزن", "كيلو"])
            price = st.number_input("القيمة (السعر)", min_value=0.0)
            supplier = st.text_input("اسم المورد")
            min_s = st.number_input("حد تنبيه النواقص", value=5)
            
            if st.form_submit_button("حفظ"):
                if name:
                    new_sku = generate_auto_sku()
                    now = datetime.now().strftime("%Y-%m-%d %H:%M")
                    if execute_query("INSERT INTO items (name, sku, quantity, unit, price, supplier, min_stock, last_updated) VALUES (?,?,?,?,?,?,?,?)", 
                                     (name, new_sku, int(qty), unit, price, supplier, min_s, now)):
                        execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES ('NEW', ?, 'IN', ?, ?, 'إضافة صنف', ?)", (new_sku, int(qty), st.session_state.username, now))
                        st.success(f"تم الحفظ بالكود: {new_sku}"); st.rerun()

    # --- 3. تعريف منتج BOM (تعدد المكونات) ---
    elif choice == "⚙️ تعريف منتج BOM":
        st.subheader("تجميع المنتج (أكثر من مادة خام)")
        parent = st.selectbox("المنتج النهائي المجمع", [""] + all_names)
        if parent:
            with st.form("bom_form"):
                st.write("أضف المكونات (حتى 7 مكونات):")
                rows = []
                for i in range(7):
                    c1, c2 = st.columns([3, 1])
                    mat = c1.selectbox(f"المكون {i+1}", [""] + item_options, key=f"m_{i}")
                    m_qty = c2.number_input(f"الكمية {i+1}", min_value=0, key=f"mq_{i}")
                    if mat: rows.append((mat.split("(")[1].split(")")[0], m_qty))
                
                if st.form_submit_button("حفظ تركيبة BOM"):
                    for m_sku, m_q in rows:
                        execute_query("INSERT OR REPLACE INTO bom_recipes (assembled_product_name, raw_material_sku, required_quantity) VALUES (?,?,?)", (parent, m_sku, m_q))
                    st.success("تم الحفظ")

    # --- 4. صرف أصناف مجمع (حتى 40 منتج + PDF) ---
    elif choice == "📤 صرف أصناف مجمع":
        if 'iss_rows' not in st.session_state: st.session_state.iss_rows = 1
        if st.button("➕ إضافة سطر جديد للصرف") and st.session_state.iss_rows < 40:
            st.session_state.iss_rows += 1
            
        basket = []
        with st.form("issue_form"):
            for i in range(st.session_state.iss_rows):
                c1, c2 = st.columns([3, 1])
                s = c1.selectbox(f"الصنف {i+1}", [""] + item_options, key=f"is_{i}")
                q = c2.number_input(f"الكمية {i+1}", key=f"iq_{i}", min_value=1)
                if s: basket.append((s.split("(")[1].split(")")[0], q))
            
            if st.form_submit_button("🚀 تنفيذ الصرف الجماعي"):
                now = datetime.now()
                do_ref = f"DO-{now.strftime('%y%m%d%H%M')}"
                for sku, q in basket:
                    execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (q, sku))
                    execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES (?,?,'OUT',?,?,?,?)", (do_ref, sku, q, st.session_state.username, "صرف مجمع", now.strftime("%Y-%m-%d %H:%M")))
                st.success(f"تم الصرف بالسند: {do_ref}"); st.session_state.iss_rows = 1; st.rerun()

    # --- 5. طلب شراء PDF ---
    elif choice == "📦 طلب شراء PDF":
        if 'po_rows' not in st.session_state: st.session_state.po_rows = 1
        if st.button("➕ إضافة صنف للطلب") and st.session_state.po_rows < 40:
            st.session_state.po_rows += 1
        
        po_list = []
        with st.form("po_form"):
            for i in range(st.session_state.po_rows):
                c1, c2, c3 = st.columns([2,1,2])
                s = c1.selectbox(f"الصنف {i+1}", [""] + item_options, key=f"ps_{i}")
                q = c2.number_input(f"الكمية {i+1}", key=f"pq_{i}", min_value=1)
                d = c3.date_input(f"التوريد {i+1}", key=f"pd_{i}")
                if s: po_list.append((s, q, d.strftime("%Y-%m-%d")))
            
            if st.form_submit_button("📄 توليد ملف PDF"):
                now_dt = datetime.now()
                pdf_bytes = create_pdf_content(f"PO-{now_dt.strftime('%H%M')}", po_list, now_dt.strftime("%Y-%m-%d"), st.session_state.username)
                st.download_button("📥 تحميل PDF", pdf_bytes, f"PO_{now_dt.strftime('%m%d')}.pdf", "application/pdf")

    # --- 6. سجل العمليات ---
    elif choice == "📜 سجل العمليات":
        st.subheader("سجل الرقابة والتدقيق")
        logs, _ = fetch_query("SELECT timestamp, ref_code, sku, type, quantity_change, user, reason FROM transactions ORDER BY id DESC")
        if logs:
            st.table(pd.DataFrame(logs, columns=['الوقت', 'السند', 'الكود', 'العملية', 'الكمية', 'المستخدم', 'السبب']))

if __name__ == "__main__":
    main()
