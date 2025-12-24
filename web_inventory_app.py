import streamlit as st
import sqlite3
from datetime import datetime
import pandas as pd
from fpdf import FPDF
import hashlib

# -------------------------------------------------------------
# 1. إعداد قاعدة البيانات (نظام الإصلاح الشامل)
# -------------------------------------------------------------
DATABASE_NAME = 'inventory_control.db'

def initialize_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    # إنشاء الجداول الأساسية
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
    
    # --- فحص وإصلاح الأعمدة لتجنب NOT NULL constraint failed ---
    cursor.execute("PRAGMA table_info(items)")
    cols = [info[1] for info in cursor.fetchall()]
    
    if 'unit' not in cols:
        cursor.execute("ALTER TABLE items ADD COLUMN unit TEXT DEFAULT 'قطعة'")
    if 'supplier_name' not in cols:
        # إذا كان العمود القديم باسم supplier نقوم بتغييره أو إضافة الجديد
        cursor.execute("ALTER TABLE items ADD COLUMN supplier_name TEXT DEFAULT 'غير محدد'")
    
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
        st.error(f"⚠️ خطأ في قاعدة البيانات: {e}")
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
# 2. التطبيق الرئيسي (دمج كافة الامتيازات)
# -------------------------------------------------------------
def main():
    initialize_db()
    st.set_page_config(page_title="اكسبو تايم - النظام المتكامل", layout="wide")

    if 'logged_in' not in st.session_state: st.session_state.logged_in = False

    if not st.session_state.logged_in:
        st.title("🔐 دخول النظام")
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
    if low_stock_data: st.sidebar.error(f"🚨 تنبيه: يوجد {len(low_stock_data)} نواقص!")

    st.sidebar.title(f"👤 {st.session_state.username}")
    menu = ["🔍 المخزون والإدارة", "➕ إضافة صنف جديد", "⚙️ تعريف منتج BOM", "📤 صرف أصناف مجمع", "👥 إدارة المستخدمين", "📜 السجل"]
    if st.session_state.role != "مدير": menu.remove("👥 إدارة المستخدمين")
    choice = st.sidebar.selectbox("القائمة", menu)

    items_raw, _ = fetch_query("SELECT sku, name, quantity, unit, min_stock, price, supplier_name FROM items")
    item_options = [f"{s[1]} ({s[0]}) | وحدة: {s[3]}" for s in items_raw]
    all_names = [s[1] for s in items_raw]

    # --- 1. المخزون والإدارة (صلاحيات المدير) ---
    if choice == "🔍 المخزون والإدارة":
        search = st.text_input("بحث بالاسم أو الكود")
        data, _ = fetch_query("SELECT name, sku, quantity, unit, price, supplier_name, min_stock FROM items WHERE name LIKE ? OR sku LIKE ?", (f'%{search}%', f'%{search}%'))
        if data:
            df = pd.DataFrame(data, columns=['الاسم', 'الكود SKU', 'الكمية', 'الوحدة', 'السعر', 'المورد', 'حد التنبيه'])
            def highlight_low(row):
                return ['background-color: #fff0f0; color: #b30000; font-weight: bold' if row['الكمية'] <= row['حد التنبيه'] else '' for _ in row]
            st.dataframe(df.style.apply(highlight_low, axis=1), use_container_width=True)

            if st.session_state.role == "مدير":
                st.write("🔧 **لوحة تحكم المدير**")
                target = st.selectbox("اختر SKU للتعديل", [""] + [d[1] for d in data])
                if target:
                    c1, c2, c3 = st.columns(3)
                    nq = c1.number_input("تعديل الكمية", value=0)
                    np = c2.number_input("تعديل السعر", value=0.0)
                    ns = c3.text_input("تعديل المورد")
                    if st.button("✅ حفظ التعديلات"):
                        execute_query("UPDATE items SET quantity=?, price=?, supplier_name=? WHERE sku=?", (nq, np, ns, target))
                        st.rerun()
                    if st.button("❌ حذف المنتج نهائياً"):
                        execute_query("DELETE FROM items WHERE sku=?", (target,))
                        st.rerun()

    # --- 2. إضافة صنف جديد (حل مشكلة NOT NULL) ---
    elif choice == "➕ إضافة صنف جديد":
        st.subheader("إضافة منتج جديد")
        with st.form("add_form"):
            name = st.text_input("اسم المنتج")
            col1, col2 = st.columns(2)
            qty = col1.number_input("الكمية", min_value=0, step=1)
            unit = col2.selectbox("الوحدة", ["قطعة", "بكت", "جرام", "درزن", "كيلو"])
            price = st.number_input("السعر", min_value=0.0)
            supplier = st.text_input("اسم المورد", value="غير محدد") # القيمة الافتراضية تمنع الخطأ
            m_stock = st.number_input("حد التنبيه", value=5)
            
            if st.form_submit_button("حفظ المنتج"):
                if name:
                    new_sku = generate_auto_sku()
                    now = datetime.now().strftime("%Y-%m-%d %H:%M")
                    # تم التأكد من ترتيب الأعمدة ومطابقتها لقاعدة البيانات
                    query = "INSERT INTO items (name, sku, quantity, unit, price, supplier_name, min_stock, last_updated) VALUES (?,?,?,?,?,?,?,?)"
                    if execute_query(query, (name, new_sku, int(qty), unit, price, supplier, m_stock, now)):
                        st.success(f"✅ تم الحفظ. الكود المولد: {new_sku}")
                        st.rerun()

    # --- 3. تعريف BOM (7 مكونات) ---
    elif choice == "⚙️ تعريف منتج BOM":
        p_name = st.selectbox("المنتج النهائي المجمع", [""] + all_names)
        if p_name:
            with st.form("bom_form"):
                st.write("أضف المكونات (حتى 7):")
                rows = []
                for i in range(7):
                    c1, c2 = st.columns([3, 1])
                    mat = c1.selectbox(f"المكون {i+1}", [""] + item_options, key=f"m_{i}")
                    m_qty = c2.number_input(f"الكمية {i+1}", min_value=0, key=f"mq_{i}")
                    if mat: rows.append((mat.split("(")[1].split(")")[0], m_qty))
                if st.form_submit_button("حفظ مكونات BOM"):
                    for m_sku, m_q in rows:
                        execute_query("INSERT OR REPLACE INTO bom_recipes (assembled_product_name, raw_material_sku, required_quantity) VALUES (?,?,?)", (p_name, m_sku, m_q))
                    st.success("تم الحفظ بنجاح")

    # --- 4. صرف مجمع (حتى 40 منتج) ---
    elif choice == "📤 صرف أصناف مجمع":
        if 'iss_rows' not in st.session_state: st.session_state.iss_rows = 1
        if st.button("➕ إضافة سطر صرف"): st.session_state.iss_rows += 1
        basket = []
        with st.form("iss_form"):
            for i in range(st.session_state.iss_rows):
                c1, c2 = st.columns([3, 1])
                s = c1.selectbox(f"الصنف {i+1}", [""] + item_options, key=f"is_{i}")
                q = c2.number_input(f"الكمية {i+1}", min_value=1, key=f"iq_{i}")
                if s: basket.append((s.split("(")[1].split(")")[0], q))
            if st.form_submit_button("🚀 تنفيذ الصرف"):
                now = datetime.now()
                ref = f"DO-{now.strftime('%y%m%d%H%M')}"
                for sku, q in basket:
                    execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (q, sku))
                    execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES (?,?,'OUT',?,?,?,?)", (ref, sku, q, st.session_state.username, "صرف مجمع", now.strftime("%Y-%m-%d %H:%M")))
                st.success(f"✅ تم الصرف بالسند: {ref}")
                st.session_state.iss_rows = 1

    # --- 5. إدارة المستخدمين ---
    elif choice == "👥 إدارة المستخدمين":
        st.subheader("إدارة الموظفين")
        u_data, _ = fetch_query("SELECT username, role FROM users")
        st.table(pd.DataFrame(u_data, columns=['المستخدم', 'الدور']))
        with st.form("u_form"):
            nu, np = st.text_input("المستخدم"), st.text_input("كلمة المرور", type="password")
            nr = st.selectbox("الدور", ["موظف", "مدير"])
            if st.form_submit_button("إضافة"):
                hp = hashlib.sha256(np.encode()).hexdigest()
                execute_query("INSERT INTO users VALUES (?,?,?)", (nu, hp, nr))
                st.rerun()

    elif choice == "📜 سجل العمليات":
        logs, _ = fetch_query("SELECT timestamp, ref_code, sku, type, quantity_change, user FROM transactions ORDER BY id DESC")
        st.table(pd.DataFrame(logs, columns=['الوقت', 'السند', 'الكود', 'العملية', 'الكمية', 'المستخدم']))

if __name__ == "__main__":
    main()
