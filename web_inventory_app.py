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
    # تحديث الجدول ليشمل المورد (supplier)
    cursor.execute('''CREATE TABLE IF NOT EXISTS items 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, sku TEXT UNIQUE, quantity INTEGER, 
        unit TEXT, min_stock INTEGER DEFAULT 5, price REAL, supplier TEXT, last_updated TEXT)''')
    cursor.execute('CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, ref_code TEXT, sku TEXT, type TEXT, quantity_change INTEGER, user TEXT, reason TEXT, timestamp TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS bom_recipes (id INTEGER PRIMARY KEY AUTOINCREMENT, assembled_product_name TEXT, raw_material_sku TEXT, required_quantity INTEGER, UNIQUE(assembled_product_name, raw_material_sku))')
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

# دالة توليد الكود تلقائياً (مخفي)
def generate_auto_sku():
    res, _ = fetch_query("SELECT MAX(id) FROM items")
    next_id = (res[0][0] + 1) if res and res[0][0] else 1001
    return f"P-{next_id:05d}"

# -------------------------------------------------------------
# التطبيق الرئيسي
# -------------------------------------------------------------
def main():
    initialize_db()
    st.set_page_config(page_title="نظام اكسبو تايم المتطور", layout="wide")

    if 'logged_in' not in st.session_state: st.session_state.logged_in = False

    if not st.session_state.logged_in:
        st.title("🔐 دخول النظام - شركة اكسبو تايم")
        with st.form("login"):
            u, p = st.text_input("المستخدم"), st.text_input("كلمة المرور", type="password")
            if st.form_submit_button("دخول"):
                hp = hashlib.sha256(p.encode()).hexdigest()
                res, _ = fetch_query("SELECT role FROM users WHERE username=? AND password=?", (u, hp))
                if res:
                    st.session_state.logged_in, st.session_state.username, st.session_state.role = True, u, res[0][0]
                    st.rerun()
        return

    st.sidebar.title(f"👤 {st.session_state.username}")
    menu = ["🔍 المخزون والإدارة", "➕ إضافة صنف جديد", "⚙️ تجميع منتج (BOM)", "📤 صرف أصناف", "📜 سجل العمليات", "👥 الموظفين"]
    if st.session_state.role != "مدير": menu.remove("👥 الموظفين")
    choice = st.sidebar.selectbox("القائمة", menu)

    items_raw, _ = fetch_query("SELECT sku, name, unit, quantity, price, supplier FROM items")
    all_names = [x[1] for x in items_raw]
    item_options = [f"{x[1]} ({x[0]})" for x in items_raw]

    # --- 1. إضافة صنف جديد (كود تلقائي مخفي + مورد) ---
    if choice == "➕ إضافة صنف جديد":
        st.subheader("إضافة منتج جديد للمخزن")
        with st.form("add_item_form"):
            name = st.text_input("اسم المنتج")
            col1, col2 = st.columns(2)
            qty = col1.number_input("الكمية", min_value=0, step=1)
            unit = col2.selectbox("الوحدة", ["قطعة", "بكت", "جرام", "درزن", "كيلو"])
            price = st.number_input("القيمة (السعر)", min_value=0.0)
            supplier = st.text_input("اسم المورد")
            
            if st.form_submit_button("تسجيل المنتج"):
                if name:
                    new_sku = generate_auto_sku()
                    now = datetime.now().strftime("%Y-%m-%d %H:%M")
                    if execute_query("INSERT INTO items (name, sku, quantity, unit, price, supplier, last_updated) VALUES (?,?,?,?,?,?,?)", 
                                     (name, new_sku, int(qty), unit, price, supplier, now)):
                        st.success(f"تم تسجيل المنتج بنجاح. الكود المولد: {new_sku}")
                        st.rerun()

    # --- 2. تجميع منتج BOM (أكثر من مادة خام) ---
    elif choice == "⚙️ تجميع منتج (BOM)":
        st.subheader("تعريف المكونات للمنتج المجمع")
        st.info("يمكنك إضافة حتى 10 مواد خام لإنتاج منتج واحد")
        assembled_p = st.selectbox("اختر المنتج النهائي المجمع", [""] + all_names)
        
        if assembled_p:
            with st.form("bom_multiple"):
                rows = []
                for i in range(7): # دعم حتى 7 مكونات كما طلبت
                    c1, c2 = st.columns([3, 1])
                    mat = c1.selectbox(f"المادة الخام {i+1}", [""] + item_options, key=f"mat_{i}")
                    m_qty = c2.number_input(f"الكمية {i+1}", min_value=0, step=1, key=f"mqty_{i}")
                    if mat: rows.append((mat.split("(")[1].split(")")[0], m_qty))
                
                if st.form_submit_button("حفظ تركيبة المنتج"):
                    for m_sku, m_q in rows:
                        execute_query("INSERT OR REPLACE INTO bom_recipes (assembled_product_name, raw_material_sku, required_quantity) VALUES (?,?,?)", 
                                     (assembled_p, m_sku, int(m_q)))
                    st.success(f"تم حفظ مكونات {assembled_p}")

    # --- 3. المخزون والإدارة (صلاحيات مطلقة للمدير) ---
    elif choice == "🔍 المخزون والإدارة":
        st.subheader("بيانات المخزون")
        search = st.text_input("بحث بالاسم أو الكود")
        data, _ = fetch_query("SELECT id, sku, name, quantity, unit, price, supplier FROM items WHERE name LIKE ? OR sku LIKE ?", (f'%{search}%', f'%{search}%'))
        if data:
            df = pd.DataFrame(data, columns=['ID', 'الكود SKU', 'الاسم', 'الكمية', 'الوحدة', 'السعر', 'المورد'])
            st.dataframe(df, use_container_width=True)
            
            if st.session_state.role == "مدير":
                st.divider()
                st.write("🛠️ **صلاحيات المدير (تحديث / تعديل / حذف)**")
                target_sku = st.selectbox("اختر الكود للتعديل عليه", [""] + [x[1] for x in data])
                if target_sku:
                    col1, col2, col3 = st.columns(3)
                    new_q = col1.number_input("تعديل الكمية", value=0)
                    new_p = col2.number_input("تعديل السعر", value=0.0)
                    new_s = col3.text_input("تعديل المورد")
                    
                    c1, c2 = st.columns(2)
                    if c1.button("✅ حفظ التعديلات"):
                        execute_query("UPDATE items SET quantity=?, price=?, supplier=? WHERE sku=?", (new_q, new_p, new_s, target_sku))
                        st.success("تم التحديث"); st.rerun()
                    if c2.button("❌ حذف المنتج نهائياً"):
                        execute_query("DELETE FROM items WHERE sku=?", (target_sku,))
                        st.error("تم الحذف"); st.rerun()

    # --- 4. صرف أصناف وصرف BOM (مدمج) ---
    elif choice == "📤 صرف أصناف":
        st.subheader("إصدار أمر صرف")
        p_target = st.selectbox("اختر المنتج", [""] + all_names)
        p_qty = st.number_input("الكمية المطلوبة", min_value=1, step=1)
        
        if st.button("🚀 تنفيذ الصرف"):
            # التحقق إذا كان منتج مجمع
            comps, _ = fetch_query("SELECT raw_material_sku, required_quantity FROM bom_recipes WHERE assembled_product_name=?", (p_target,))
            now = datetime.now()
            ref = f"DO-{now.strftime('%y%m%d%H%M')}"
            
            if comps:
                for c_sku, c_req in comps:
                    total = c_req * p_qty
                    execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (total, c_sku))
                    execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES (?,?,'OUT',?,?,?,?)", 
                                 (ref, c_sku, total, st.session_state.username, f"إنتاج مجمع {p_target}", now.strftime("%Y-%m-%d %H:%M")))
                st.success(f"تم صرف مكونات المنتج المجمع بنجاح بالسند {ref}")
            else:
                # صرف عادي
                target_sku = [x[0] for x in items_raw if x[1] == p_target][0]
                execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (p_qty, target_sku))
                execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES (?,?,'OUT',?,?,?,?)", 
                             (ref, target_sku, p_qty, st.session_state.username, "صرف مباشر", now.strftime("%Y-%m-%d %H:%M")))
                st.success(f"تم الصرف المباشر بالسند {ref}")
            st.rerun()

    # --- 5. سجل العمليات ---
    elif choice == "📜 سجل العمليات":
        logs, _ = fetch_query("SELECT timestamp, ref_code, sku, type, quantity_change, user, reason FROM transactions ORDER BY id DESC")
        if logs:
            st.table(pd.DataFrame(logs, columns=['الوقت', 'السند', 'الكود', 'العملية', 'الكمية', 'المستخدم', 'السبب']))

if __name__ == "__main__":
    main()
