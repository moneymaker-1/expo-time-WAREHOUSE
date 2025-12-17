import streamlit as st
import sqlite3
from datetime import datetime
import pandas as pd
from fpdf import FPDF
import hashlib

# -------------------------------------------------------------
# 1. إعداد قاعدة البيانات (الهيكل المعتمد)
# -------------------------------------------------------------
DATABASE_NAME = 'inventory_control.db'

def initialize_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    # جدول الأصناف: يتضمن المورد والوحدة والترقيم التلقائي
    cursor.execute('''CREATE TABLE IF NOT EXISTS items 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, sku TEXT UNIQUE, quantity INTEGER, 
        unit TEXT, min_stock INTEGER DEFAULT 5, price REAL, supplier TEXT, last_updated TEXT)''')
    
    # جدول العمليات: يسجل كل حركة دخول أو خروج بالسند والمستخدم
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, ref_code TEXT, sku TEXT, type TEXT, 
        quantity_change INTEGER, user TEXT, reason TEXT, timestamp TEXT)''')
    
    # جدول BOM: يربط المنتج المجمع بعدة مواد خام (حتى 40 مادة)
    cursor.execute('''CREATE TABLE IF NOT EXISTS bom_recipes 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, assembled_product_name TEXT, raw_material_sku TEXT, required_quantity INTEGER, 
        UNIQUE(assembled_product_name, raw_material_sku))''')
    
    cursor.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, role TEXT)')
    conn.commit()
    conn.close()
    
    # المدير الافتراضي
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
        st.error(f"خطأ برمي: {e}")
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

# توليد الكود تلقائياً (مخفي عن واجهة الإضافة)
def generate_auto_sku():
    res, _ = fetch_query("SELECT MAX(id) FROM items")
    next_id = (res[0][0] + 1) if res and res[0][0] else 1001
    return f"P-{next_id:05d}"

# -------------------------------------------------------------
# 2. التطبيق الرئيسي
# -------------------------------------------------------------
def main():
    initialize_db()
    st.set_page_config(page_title="اكسبو تايم - النظام المتكامل", layout="wide")

    if 'logged_in' not in st.session_state: st.session_state.logged_in = False

    if not st.session_state.logged_in:
        st.title("🔐 نظام شركة اكسبو تايم")
        u = st.text_input("اسم المستخدم")
        p = st.text_input("كلمة المرور", type="password")
        if st.button("دخول"):
            hp = hashlib.sha256(p.encode()).hexdigest()
            res, _ = fetch_query("SELECT role FROM users WHERE username=? AND password=?", (u, hp))
            if res:
                st.session_state.logged_in, st.session_state.username, st.session_state.role = True, u, res[0][0]
                st.rerun()
        return

    st.sidebar.title(f"👤 {st.session_state.username}")
    menu = ["🔍 المخزون (صلاحيات المدير)", "➕ إضافة منتج جديد", "⚙️ تجميع منتج (BOM)", "📤 صرف أصناف مجمع (PDF)", "📜 السجل"]
    choice = st.sidebar.selectbox("القائمة", menu)

    items_raw, _ = fetch_query("SELECT sku, name, unit, quantity, price, supplier FROM items")
    all_names = [x[1] for x in items_raw]
    item_options = [f"{x[1]} ({x[0]})" for x in items_raw]

    # --- 1. إضافة منتج جديد (كود تلقائي مخفي + اسم المورد) ---
    if choice == "➕ إضافة منتج جديد":
        st.subheader("إدخال صنف جديد إلى النظام")
        with st.form("add_form"):
            name = st.text_input("اسم المنتج")
            col1, col2 = st.columns(2)
            qty = col1.number_input("الكمية الحالية", min_value=0, step=1, format="%d")
            unit = col2.selectbox("وحدة المنتج", ["قطعة", "بكت", "جرام", "درزن", "كيلو"])
            price = st.number_input("قيمة الصنف", min_value=0.0)
            supplier = st.text_input("اسم المورد (المزود)")
            
            if st.form_submit_button("حفظ المنتج"):
                if name:
                    new_sku = generate_auto_sku() # توليد الكود تلقائياً
                    now = datetime.now().strftime("%Y-%m-%d %H:%M")
                    if execute_query("INSERT INTO items (name, sku, quantity, unit, price, supplier, last_updated) VALUES (?,?,?,?,?,?,?)", 
                                     (name, new_sku, int(qty), unit, price, supplier, now)):
                        st.success(f"✅ تم التسجيل بنجاح بالكود المولد: {new_sku}")
                        st.rerun()

    # --- 2. تجميع منتج (BOM المتعدد) ---
    elif choice == "⚙️ تجميع منتج (BOM)":
        st.subheader("تعريف مكونات المنتج المجمع")
        st.info("يمكنك ربط هذا المنتج بأكثر من 7 مواد خام (مكونات)")
        assembled_p = st.selectbox("اختر المنتج النهائي", [""] + all_names)
        
        if assembled_p:
            if 'bom_count' not in st.session_state: st.session_state.bom_count = 7
            if st.button("➕ إضافة سطر مكون آخر"): st.session_state.bom_count += 1
            
            with st.form("bom_full_form"):
                bom_rows = []
                for i in range(st.session_state.bom_count):
                    c1, c2 = st.columns([3, 1])
                    mat = c1.selectbox(f"المادة الخام {i+1}", [""] + item_options, key=f"mat_{i}")
                    m_qty = c2.number_input(f"الكمية {i+1}", min_value=0, step=1, key=f"mq_{i}")
                    if mat: bom_rows.append((mat.split("(")[1].split(")")[0], m_qty))
                
                if st.form_submit_button("اعتماد تركيبة المنتج"):
                    for m_sku, m_q in bom_rows:
                        execute_query("INSERT OR REPLACE INTO bom_recipes (assembled_product_name, raw_material_sku, required_quantity) VALUES (?,?,?)", 
                                     (assembled_p, m_sku, int(m_q)))
                    st.success("✅ تم حفظ التركيبة بنجاح")

    # --- 3. المخزون (صلاحيات المدير المطلقة) ---
    elif choice == "🔍 المخزون (صلاحيات المدير)":
        st.subheader("إدارة بيانات المخزون")
        search = st.text_input("بحث بالاسم أو الكود")
        data, cols = fetch_query("SELECT sku, name, quantity, unit, price, supplier FROM items WHERE name LIKE ? OR sku LIKE ?", (f'%{search}%', f'%{search}%'))
        if data:
            df = pd.DataFrame(data, columns=['الكود', 'الاسم', 'الكمية', 'الوحدة', 'السعر', 'المورد'])
            st.dataframe(df, use_container_width=True)
            
            if st.session_state.role == "مدير":
                st.markdown("---")
                st.write("🛠️ **لوحة التحكم المطلقة للمدير**")
                target_sku = st.selectbox("اختر الكود للتعديل أو الحذف", [""] + [x[0] for x in data])
                if target_sku:
                    col1, col2, col3 = st.columns(3)
                    new_q = col1.number_input("تحديث الكمية", value=0)
                    new_p = col2.number_input("تحديث السعر", value=0.0)
                    new_s = col3.text_input("تحديث المورد")
                    
                    c1, c2 = st.columns(2)
                    if c1.button("✅ حفظ التبديلات"):
                        execute_query("UPDATE items SET quantity=?, price=?, supplier=? WHERE sku=?", (new_q, new_p, new_s, target_sku))
                        st.success("تم التحديث بنجاح"); st.rerun()
                    if c2.button("❌ حذف الصنف نهائياً"):
                        execute_query("DELETE FROM items WHERE sku=?", (target_sku,))
                        st.rerun()

    # --- 4. صرف مجمع مع PDF (حتى 40 منتج) ---
    elif choice == "📤 صرف أصناف مجمع (PDF)":
        st.subheader("إصدار سند صرف مجمع (DO)")
        if 'do_rows' not in st.session_state: st.session_state.do_rows = 1
        if st.button("➕ أضف صنفاً للسند") and st.session_state.do_rows < 40:
            st.session_state.do_rows += 1
        
        with st.form("do_form"):
            do_items = []
            for i in range(st.session_state.do_rows):
                c1, c2 = st.columns([3, 1])
                s = c1.selectbox(f"الصنف {i+1}", [""] + item_options, key=f"dos_{i}")
                q = c2.number_input(f"الكمية {i+1}", min_value=1, step=1, key=f"doq_{i}")
                if s: do_items.append((s, q))
            
            if st.form_submit_button("🚀 تأكيد الصرف وتوليد السند"):
                now = datetime.now()
                ref = f"DO-{now.strftime('%y%m%d%H%M')}"
                for s_full, q in do_items:
                    sku = s_full.split("(")[1].split(")")[0]
                    execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (q, sku))
                    execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES (?,?,'OUT',?,?,?,?)", 
                                 (ref, sku, q, st.session_state.username, "صرف مجمع", now.strftime("%Y-%m-%d %H:%M")))
                st.success(f"تم الصرف بالسند {ref}")
                st.session_state.do_rows = 1
                st.rerun()

if __name__ == "__main__":
    main()
