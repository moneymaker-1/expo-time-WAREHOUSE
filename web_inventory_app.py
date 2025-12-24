import streamlit as st
import sqlite3
from datetime import datetime
import pandas as pd
from fpdf import FPDF
import hashlib

# -------------------------------------------------------------
# 1. إعداد قاعدة البيانات (نظام الإصلاح التلقائي)
# -------------------------------------------------------------
DATABASE_NAME = 'inventory_control.db'

def initialize_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    # الجداول الأساسية
    cursor.execute('''CREATE TABLE IF NOT EXISTS items 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, sku TEXT UNIQUE, quantity INTEGER, 
        unit TEXT, min_stock INTEGER DEFAULT 5, price REAL, supplier_name TEXT DEFAULT 'غير محدد', last_updated TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, ref_code TEXT, sku TEXT, type TEXT, 
        quantity_change INTEGER, user TEXT, reason TEXT, timestamp TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS bom_recipes 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, assembled_product_name TEXT, raw_material_sku TEXT, required_quantity INTEGER, 
        UNIQUE(assembled_product_name, raw_material_sku))''')
    cursor.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, role TEXT)')
    # التحقق من الأعمدة
    cursor.execute("PRAGMA table_info(items)")
    cols = [info[1] for info in cursor.fetchall()]
    if 'unit' not in cols: cursor.execute("ALTER TABLE items ADD COLUMN unit TEXT DEFAULT 'قطعة'")
    if 'supplier_name' not in cols: cursor.execute("ALTER TABLE items ADD COLUMN supplier_name TEXT DEFAULT 'غير محدد'")
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
        st.error(f"⚠️ خطأ: {e}")
        return False
    finally: conn.close()

def fetch_query(query, params=()):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        data = cursor.fetchall()
        return data, [d[0] for d in cursor.description]
    except: return [], []
    finally: conn.close()

def generate_auto_sku():
    res, _ = fetch_query("SELECT MAX(id) FROM items")
    next_id = (res[0][0] + 1) if res and res[0][0] else 1001
    return f"P-{next_id:05d}"

# -------------------------------------------------------------
# دالة إنشاء ملف PDF لطلب الشراء
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
    pdf.cell(80, 10, "SKU / Name", 1, 0, 'C', True)
    pdf.cell(40, 10, "Qty", 1, 0, 'C', True)
    pdf.cell(70, 10, "Delivery Date", 1, 1, 'C', True)
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
    st.set_page_config(page_title="اكسبو تايم المتكامل", layout="wide")

    if 'logged_in' not in st.session_state: st.session_state.logged_in = False

    if not st.session_state.logged_in:
        st.title("🔐 قفل الأمان - شركة اكسبو تايم")
        with st.form("login"):
            u, p = st.text_input("اسم المستخدم"), st.text_input("كلمة المرور", type="password")
            if st.form_submit_button("دخول"):
                hp = hashlib.sha256(p.encode()).hexdigest()
                res, _ = fetch_query("SELECT role FROM users WHERE username=? AND password=?", (u, hp))
                if res:
                    st.session_state.logged_in, st.session_state.username, st.session_state.role = True, u, res[0][0]
                    st.rerun()
        return

    # تنبيه النواقص
    low_stock_data, _ = fetch_query("SELECT name FROM items WHERE quantity <= min_stock")
    if low_stock_data: st.sidebar.error(f"🚨 تنبيه: يوجد {len(low_stock_data)} نواقص!")

    st.sidebar.title(f"👤 {st.session_state.username}")
    
    # القائمة الكاملة (8 خيارات)
    menu = [
        "🔍 عرض وحذف الأصناف", 
        "➕ إضافة وتحديث صنف", 
        "⚙️ تعريف منتج BOM", 
        "📤 صرف أصناف مجمع", 
        "🏭 صرف BOM", 
        "📦 طلب شراء PDF", 
        "📜 سجل العمليات", 
        "👥 إدارة المستخدمين"
    ]
    if st.session_state.role != "مدير":
        if "👥 إدارة المستخدمين" in menu: menu.remove("👥 إدارة المستخدمين")
    
    choice = st.sidebar.selectbox("القائمة الرئيسية", menu)
    if st.sidebar.button("تسجيل الخروج"): st.session_state.logged_in = False; st.rerun()

    items_raw, _ = fetch_query("SELECT sku, name, quantity, unit, price, supplier_name, min_stock FROM items")
    item_options = [f"{s[1]} ({s[0]}) | وحدة: {s[3]}" for s in items_raw]
    all_names = [s[1] for s in items_raw]

    # --- 1. عرض وحذف الأصناف ---
    if choice == "🔍 عرض وحذف الأصناف":
        search = st.text_input("بحث سريع")
        data, _ = fetch_query("SELECT name, sku, quantity, unit, price, supplier_name, min_stock FROM items WHERE name LIKE ? OR sku LIKE ?", (f'%{search}%', f'%{search}%'))
        if data:
            df = pd.DataFrame(data, columns=['الاسم', 'الكود SKU', 'الكمية', 'الوحدة', 'السعر', 'المورد', 'حد التنبيه'])
            def highlight_low(row):
                return ['background-color: #fff0f0; color: #b30000; font-weight: bold' if row['الكمية'] <= row['حد التنبيه'] else '' for _ in row]
            st.dataframe(df.style.apply(highlight_low, axis=1), use_container_width=True)
            if st.session_state.role == "مدير":
                st.write("🔧 **لوحة تحكم المدير**")
                target = st.selectbox("اختر SKU للتعديل/الحذف", [""] + [d[1] for d in data])
                if target:
                    c1, c2, c3 = st.columns(3)
                    nq, np, ns = c1.number_input("الكمية"), c2.number_input("السعر"), c3.text_input("المورد")
                    if st.button("✅ حفظ"): execute_query("UPDATE items SET quantity=?, price=?, supplier_name=? WHERE sku=?", (nq, np, ns, target)); st.rerun()
                    if st.button("❌ حذف"): execute_query("DELETE FROM items WHERE sku=?", (target,)); st.rerun()

    # --- 2. إضافة وتحديث صنف ---
    elif choice == "➕ إضافة وتحديث صنف":
        with st.form("add_form"):
            name = st.text_input("اسم المنتج")
            col1, col2 = st.columns(2)
            qty = col1.number_input("الكمية", min_value=0, step=1)
            unit = col2.selectbox("الوحدة", ["قطعة", "بكت", "جرام", "درزن", "كيلو"])
            price = st.number_input("السعر", min_value=0.0)
            supplier = st.text_input("المورد", value="غير محدد")
            if st.form_submit_button("حفظ"):
                new_sku = generate_auto_sku()
                execute_query("INSERT INTO items (name, sku, quantity, unit, price, supplier_name, last_updated) VALUES (?,?,?,?,?,?,?)", (name, new_sku, int(qty), unit, price, supplier, datetime.now().strftime("%Y-%m-%d")))
                st.success(f"تم الحفظ بالكود: {new_sku}")

    # --- 3. طلب شراء PDF (المطلوب) ---
    elif choice == "📦 طلب شراء PDF":
        st.subheader("توليد طلب شراء (Purchase Order)")
        if 'po_rows' not in st.session_state: st.session_state.po_rows = 1
        if st.button("➕ إضافة صنف جديد للطلب") and st.session_state.po_rows < 40:
            st.session_state.po_rows += 1
            st.rerun()
        
        po_items = []
        with st.form("po_form"):
            for i in range(st.session_state.po_rows):
                c1, c2, c3 = st.columns([2,1,2])
                s = c1.selectbox(f"الصنف {i+1}", [""] + item_options, key=f"ps_{i}")
                q = c2.number_input(f"الكمية {i+1}", min_value=1, key=f"pq_{i}", step=1)
                d = c3.date_input(f"التوريد {i+1}", key=f"pd_{i}")
                if s: po_items.append((s.split(" | ")[0], int(q), d.strftime("%Y-%m-%d")))
            
            if st.form_submit_button("📄 توليد وحفظ PDF"):
                if po_items:
                    now_dt = datetime.now()
                    pdf_bytes = create_pdf_content(f"PO-{now_dt.strftime('%H%M')}", po_items, now_dt.strftime("%Y-%m-%d"), st.session_state.username)
                    st.download_button("📥 تحميل طلب الشراء", pdf_bytes, f"PO_{now_dt.strftime('%m%d')}.pdf", "application/pdf")
                else: st.warning("السلة فارغة")

    # --- بقية الخيارات (BOM، صرف، سجل، مستخدمين) ---
    elif choice == "⚙️ تعريف منتج BOM":
        p_name = st.selectbox("المنتج النهائي", [""] + all_names)
        if p_name:
            with st.form("bom_form"):
                rows = []
                for i in range(7):
                    c1, c2 = st.columns([3, 1])
                    mat = c1.selectbox(f"المكون {i+1}", [""] + item_options, key=f"m_{i}")
                    m_qty = c2.number_input(f"الكمية {i+1}", min_value=0, key=f"mq_{i}")
                    if mat: rows.append((mat.split(" | ")[0], m_qty))
                if st.form_submit_button("حفظ"):
                    for m_sku, m_qty in rows: execute_query("INSERT OR REPLACE INTO bom_recipes (assembled_product_name, raw_material_sku, required_quantity) VALUES (?,?,?)", (p_name, m_sku, m_qty))
                    st.success("تم الحفظ")

    elif choice == "📤 صرف أصناف مجمع":
        if 'iss_rows' not in st.session_state: st.session_state.iss_rows = 1
        if st.button("➕ أضف سطر"): st.session_state.iss_rows += 1; st.rerun()
        basket = []
        with st.form("iss_form"):
            for i in range(st.session_state.iss_rows):
                c1, c2 = st.columns([3, 1])
                s = c1.selectbox(f"الصنف {i+1}", [""] + item_options, key=f"is_{i}")
                q = c2.number_input(f"الكمية {i+1}", min_value=1, key=f"iq_{i}")
                if s: basket.append((s.split(" | ")[0].split("(")[1].split(")")[0], q))
            if st.form_submit_button("🚀 تنفيذ الصرف"):
                now, ref = datetime.now(), f"DO-{datetime.now().strftime('%y%m%d%H%M')}"
                for sku, q in basket:
                    execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (q, sku))
                    execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES (?,?,'OUT',?,?,?,?)", (ref, sku, q, st.session_state.username, "صرف مجمع", now.strftime("%Y-%m-%d %H:%M")))
                st.success("تم الصرف")

    elif choice == "🏭 صرف BOM":
        p_target = st.selectbox("المنتج النهائي", all_names)
        p_qty = st.number_input("كمية الإنتاج", min_value=1, step=1)
        if st.button("🚀 تجميع وصرف"):
            comps, _ = fetch_query("SELECT raw_material_sku, required_quantity FROM bom_recipes WHERE assembled_product_name=?", (p_target,))
            if comps:
                now, ref = datetime.now(), f"BOM-{datetime.now().strftime('%H%M')}"
                for c_sku, c_req in comps:
                    execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (int(c_req * p_qty), c_sku))
                    execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES (?,?,'OUT',?,?,?,?)", (ref, c_sku, int(c_req * p_qty), st.session_state.username, f"إنتاج {p_target}", now.strftime("%Y-%m-%d %H:%M")))
                st.success("تم صرف المكونات")

    elif choice == "👥 إدارة المستخدمين":
        u_data, _ = fetch_query("SELECT username, role FROM users")
        st.table(pd.DataFrame(u_data, columns=['المستخدم', 'الدور']))
        with st.form("u_form"):
            nu, np, nr = st.text_input("مستخدم جديد"), st.text_input("كلمة مرور", type="password"), st.selectbox("الدور", ["موظف", "مدير"])
            if st.form_submit_button("إضافة"): execute_query("INSERT INTO users VALUES (?,?,?)", (nu, hashlib.sha256(np.encode()).hexdigest(), nr)); st.rerun()

    elif choice == "📜 سجل العمليات":
        logs, _ = fetch_query("SELECT timestamp, ref_code, sku, type, quantity_change, user FROM transactions ORDER BY id DESC")
        st.table(pd.DataFrame(logs, columns=['الوقت', 'السند', 'الكود', 'النوع', 'الكمية', 'المستخدم']))

if __name__ == "__main__":
    main()
