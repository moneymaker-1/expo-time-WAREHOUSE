import streamlit as st
import sqlite3
from datetime import datetime
import pandas as pd
import hashlib

# -------------------------------------------------------------
# 1. إعداد قاعدة البيانات الشاملة
# -------------------------------------------------------------
DATABASE_NAME = 'inventory_control.db'

def initialize_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    # الأصناف مع المورد والوحدة
    cursor.execute('''CREATE TABLE IF NOT EXISTS items 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, sku TEXT UNIQUE, quantity INTEGER, 
        unit TEXT, min_stock INTEGER DEFAULT 5, price REAL, supplier TEXT, last_updated TEXT)''')
    # الحركات والسندات
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, ref_code TEXT, sku TEXT, type TEXT, 
        quantity_change INTEGER, user TEXT, reason TEXT, timestamp TEXT)''')
    # وصفات التصنيع (BOM)
    cursor.execute('''CREATE TABLE IF NOT EXISTS bom_recipes 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, assembled_product_name TEXT, raw_material_sku TEXT, required_quantity INTEGER, 
        UNIQUE(assembled_product_name, raw_material_sku))''')
    # المستخدمين
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

def generate_auto_sku():
    res, _ = fetch_query("SELECT MAX(id) FROM items")
    next_id = (res[0][0] + 1) if res and res[0][0] else 1001
    return f"P-{next_id:05d}"

# -------------------------------------------------------------
# 2. التطبيق الرئيسي
# -------------------------------------------------------------
def main():
    initialize_db()
    st.set_page_config(page_title="نظام اكسبو تايم المتكامل", layout="wide")

    if 'logged_in' not in st.session_state: st.session_state.logged_in = False

    if not st.session_state.logged_in:
        st.title("🔐 دخول النظام - شركة اكسبو تايم")
        u, p = st.text_input("المستخدم"), st.text_input("كلمة المرور", type="password")
        if st.button("دخول"):
            hp = hashlib.sha256(p.encode()).hexdigest()
            res, _ = fetch_query("SELECT role FROM users WHERE username=? AND password=?", (u, hp))
            if res:
                st.session_state.logged_in, st.session_state.username, st.session_state.role = True, u, res[0][0]
                st.rerun()
        return

    # تنبيه النواقص الجانبي
    low_stock_data, _ = fetch_query("SELECT name FROM items WHERE quantity <= min_stock")
    if low_stock_data: st.sidebar.error(f"🚨 يوجد {len(low_stock_data)} أصناف تحت حد الأمان!")

    st.sidebar.title(f"👤 {st.session_state.username}")
    menu = ["🔍 المخزون والإدارة", "➕ إضافة صنف جديد", "⚙️ تجميع منتج (BOM)", "📤 صرف أصناف (متعدد)", "👥 إدارة المستخدمين", "📜 السجل"]
    if st.session_state.role != "مدير": menu.remove("👥 إدارة المستخدمين")
    choice = st.sidebar.selectbox("القائمة", menu)

    items_raw, _ = fetch_query("SELECT sku, name, unit, quantity, price, supplier, min_stock FROM items")
    all_names = [x[1] for x in items_raw]
    item_options = [f"{x[1]} ({x[0]})" for x in items_raw]

    # --- 1. المخزون والإدارة (صلاحيات المدير المطلقة) ---
    if choice == "🔍 المخزون والإدارة":
        st.subheader("📦 بيانات المخزون الحالي")
        search = st.text_input("بحث سريع...")
        data, _ = fetch_query("SELECT sku, name, quantity, unit, price, supplier, min_stock FROM items WHERE name LIKE ? OR sku LIKE ?", (f'%{search}%', f'%{search}%'))
        if data:
            df = pd.DataFrame(data, columns=['الكود', 'الاسم', 'الكمية', 'الوحدة', 'السعر', 'المورد', 'الحد الأدنى'])
            def highlight_low(row):
                return ['background-color: #fff0f0; color: #b30000; font-weight: bold' if row['الكمية'] <= row['الحد الأدنى'] else '' for _ in row]
            st.dataframe(df.style.apply(highlight_low, axis=1), use_container_width=True)

            if st.session_state.role == "مدير":
                st.divider()
                st.write("🛠️ **لوحة التحكم المطلقة للمدير**")
                t_sku = st.selectbox("اختر الكود للتعديل/الحذف", [""] + [x[0] for x in data])
                if t_sku:
                    c1, c2, c3 = st.columns(3)
                    nq = c1.number_input("الكمية الجديدة", value=0)
                    np = c2.number_input("السعر الجديد", value=0.0)
                    ns = c3.text_input("المورد الجديد")
                    if st.button("✅ حفظ التعديلات"):
                        execute_query("UPDATE items SET quantity=?, price=?, supplier=? WHERE sku=?", (nq, np, ns, t_sku))
                        st.success("تم التحديث"); st.rerun()
                    if st.button("❌ حذف الصنف نهائياً"):
                        execute_query("DELETE FROM items WHERE sku=?", (t_sku,))
                        st.rerun()

    # --- 2. إضافة صنف جديد (كود تلقائي مخفي) ---
    elif choice == "➕ إضافة صنف جديد":
        st.subheader("إدخال منتج جديد")
        with st.form("add_form"):
            name = st.text_input("اسم المنتج")
            col1, col2 = st.columns(2)
            qty = col1.number_input("الكمية", min_value=0, step=1)
            unit = col2.selectbox("الوحدة", ["قطعة", "بكت", "جرام", "درزن", "كيلو"])
            price = st.number_input("السعر", min_value=0.0)
            supplier = st.text_input("المورد")
            if st.form_submit_button("حفظ"):
                new_sku = generate_auto_sku()
                now = datetime.now().strftime("%Y-%m-%d %H:%M")
                if execute_query("INSERT INTO items (name, sku, quantity, unit, price, supplier, last_updated) VALUES (?,?,?,?,?,?,?)", 
                                 (name, new_sku, int(qty), unit, price, supplier, now)):
                    st.success(f"تم الحفظ بنجاح. الكود: {new_sku}"); st.rerun()

    # --- 3. تجميع منتج BOM (7 مكونات وأكثر) ---
    elif choice == "⚙️ تجميع منتج (BOM)":
        st.subheader("تعريف مكونات المنتج المجمع")
        parent = st.selectbox("اختر المنتج المجمع", [""] + all_names)
        if parent:
            with st.form("bom_form"):
                rows = []
                for i in range(7):
                    c1, c2 = st.columns([3, 1])
                    mat = c1.selectbox(f"المادة الخام {i+1}", [""] + item_options, key=f"b_{i}")
                    mq = c2.number_input(f"الكمية {i+1}", min_value=0, key=f"q_{i}")
                    if mat: rows.append((mat.split("(")[1].split(")")[0], mq))
                if st.form_submit_button("حفظ المكونات"):
                    for m_sku, m_q in rows:
                        execute_query("INSERT OR REPLACE INTO bom_recipes (assembled_product_name, raw_material_sku, required_quantity) VALUES (?,?,?)", (parent, m_sku, int(m_q)))
                    st.success("تم الربط بنجاح")

    # --- 4. صرف أصناف (سلة متعددة حتى 40 صنف) ---
    elif choice == "📤 صرف أصناف (متعدد)":
        st.subheader("إصدار سند صرف (DO)")
        if 'basket' not in st.session_state: st.session_state.basket = []
        c1, c2, c3 = st.columns([3, 1, 1])
        s_item = c1.selectbox("اختر صنفاً", [""] + item_options)
        s_qty = c2.number_input("الكمية", min_value=1)
        if c3.button("➕ إضافة"):
            if s_item:
                sku = s_item.split("(")[1].split(")")[0]
                st.session_state.basket.append({"الكود": sku, "الكمية": int(s_qty)})
        
        if st.session_state.basket:
            st.table(pd.DataFrame(st.session_state.basket))
            if st.button("🚀 تأكيد الصرف وتوليد السند"):
                now = datetime.now()
                ref = f"DO-{now.strftime('%y%m%d%H%M')}"
                for itm in st.session_state.basket:
                    execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (itm['الكمية'], itm['الكود']))
                    execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES (?,?,'OUT',?,?,?,?)", 
                                 (ref, itm['الكود'], itm['الكمية'], st.session_state.username, "صرف مجمع", now.strftime("%Y-%m-%d %H:%M")))
                st.success(f"تم الصرف بالسند: {ref}"); st.session_state.basket = []; st.rerun()

    # --- 5. إدارة المستخدمين (المصلحة) ---
    elif choice == "👥 إدارة المستخدمين":
        st.subheader("🛠️ إدارة طاقم العمل")
        u_data, _ = fetch_query("SELECT username, role FROM users")
        st.table(pd.DataFrame(u_data, columns=['المستخدم', 'الصلاحية']))
        with st.form("new_user"):
            nu, np, nr = st.text_input("مستخدم جديد"), st.text_input("كلمة مرور"), st.selectbox("الدور", ["موظف", "مدير"])
            if st.form_submit_button("إضافة"):
                hp = hashlib.sha256(np.encode()).hexdigest()
                execute_query("INSERT INTO users VALUES (?,?,?)", (nu, hp, nr))
                st.rerun()

    elif choice == "📜 السجل":
        l, _ = fetch_query("SELECT timestamp, ref_code, sku, type, quantity_change, user FROM transactions ORDER BY id DESC")
        st.table(pd.DataFrame(l, columns=['الوقت', 'السند', 'الكود', 'العملية', 'الكمية', 'المستخدم']))

if __name__ == "__main__":
    main()
