import streamlit as st
import sqlite3
from datetime import datetime
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
    # المنتجات
    cursor.execute('''CREATE TABLE IF NOT EXISTS items 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, sku TEXT UNIQUE, quantity REAL, 
        price REAL, supplier_name TEXT DEFAULT 'غير محدد', last_updated TEXT)''')
    # جدول BOM: يربط المنتج النهائي بمكوناته
    cursor.execute('''CREATE TABLE IF NOT EXISTS bom_recipes 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, parent_sku TEXT, component_sku TEXT, qty_needed REAL,
        UNIQUE(parent_sku, component_sku))''')
    # السجل
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, ref_code TEXT, sku TEXT, type TEXT, 
        quantity_change REAL, user TEXT, reason TEXT, timestamp TEXT)''')
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
        st.error(f"خطأ: {e}")
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

# -------------------------------------------------------------
# 2. التطبيق الرئيسي
# -------------------------------------------------------------
def main():
    initialize_db()
    
    if 'logged_in' not in st.session_state: st.session_state.logged_in = False

    if not st.session_state.logged_in:
        st.title("🏆 شركة اكسبو تايم - الدخول")
        t1, t2 = st.tabs(["🔐 دخول", "📝 تسجيل"])
        with t1:
            u = st.text_input("المستخدم")
            p = st.text_input("كلمة المرور", type="password")
            if st.button("دخول"):
                hp = hashlib.sha256(p.encode()).hexdigest()
                res, _ = fetch_query("SELECT role FROM users WHERE username=? AND password=?", (u, hp))
                if res:
                    st.session_state.logged_in, st.session_state.username, st.session_state.role = True, u, res[0][0]
                    st.rerun()
        return

    st.sidebar.title(f"مرحباً {st.session_state.username}")
    menu = ["📦 المخزون", "➕ إضافة منتج", "🛠️ تعريف BOM", "📤 صرف أصناف (مجمع/BOM)", "📜 السجل"]
    choice = st.sidebar.selectbox("القائمة", menu)

    # جلب البيانات
    items_raw, _ = fetch_query("SELECT sku, name, quantity FROM items")
    all_skus = [f"{x[0]} | {x[1]}" for x in items_raw]

    # --- 1. تعريف BOM ---
    if choice == "🛠️ تعريف BOM":
        st.subheader("ربط المكونات بالمنتج النهائي")
        with st.form("bom_form"):
            p_sku = st.selectbox("المنتج النهائي (المجمع)", all_skus).split(" | ")[0]
            c_sku = st.selectbox("المكون (المادة الخام)", all_skus).split(" | ")[0]
            qty_n = st.number_input("الكمية المطلوبة من المكون لكل وحدة", min_value=0.01)
            if st.form_submit_button("حفظ الربط"):
                execute_query("INSERT OR REPLACE INTO bom_recipes (parent_sku, component_sku, qty_needed) VALUES (?,?,?)", (p_sku, c_sku, qty_n))
                st.success("تم تعريف المكون بنجاح")

    # --- 2. صرف أصناف (مجمع/BOM) ---
    elif choice == "📤 صرف أصناف (مجمع/BOM)":
        st.subheader("إصدار أمر صرف (متعدد الأصناف)")
        if 'basket' not in st.session_state: st.session_state.basket = []
        
        col1, col2, col3 = st.columns([3,1,1])
        item_to_add = col1.selectbox("اختر الصنف", [""] + all_skus)
        qty_to_add = col2.number_input("الكمية", min_value=1.0)
        if col3.button("➕ أضف للطلب"):
            if item_to_add:
                st.session_state.basket.append({"sku": item_to_add.split(" | ")[0], "name": item_to_add.split(" | ")[1], "qty": qty_to_add})

        if st.session_state.basket:
            st.write("### الأصناف في السند الحالي:")
            df_basket = pd.DataFrame(st.session_state.basket)
            st.table(df_basket)
            
            if st.button("🚀 تأكيد صرف السند بالكامل"):
                now = datetime.now()
                do_ref = f"DO-{now.strftime('%y%m%d%H%M')}"
                
                for line in st.session_state.basket:
                    sku = line['sku']
                    qty = line['qty']
                    
                    # فحص إذا كان للمنتج BOM (مكونات)
                    components, _ = fetch_query("SELECT component_sku, qty_needed FROM bom_recipes WHERE parent_sku=?", (sku,))
                    
                    if components:
                        # صرف مكونات الـ BOM
                        for c_sku, c_qty in components:
                            total_needed = c_qty * qty
                            execute_query("UPDATE items SET quantity = quantity - ? WHERE sku = ?", (total_needed, c_sku))
                            execute_query("INSERT INTO transactions VALUES (NULL, ?, ?, 'OUT', ?, ?, 'صرف مكونات BOM', ?)", 
                                         (do_ref, c_sku, total_needed, st.session_state.username, now.strftime("%Y-%m-%d %H:%M")))
                        st.success(f"تم صرف مكونات المنتج المجمع {sku}")
                    else:
                        # صرف منتج عادي
                        execute_query("UPDATE items SET quantity = quantity - ? WHERE sku = ?", (qty, sku))
                        execute_query("INSERT INTO transactions VALUES (NULL, ?, ?, 'OUT', ?, ?, 'صرف مباشر', ?)", 
                                     (do_ref, sku, qty, st.session_state.username, now.strftime("%Y-%m-%d %H:%M")))
                
                st.success(f"✅ تم تنفيذ السند بنجاح برقم: {do_ref}")
                st.session_state.basket = []
                st.rerun()

            if st.button("🗑️ إفراغ السلة"):
                st.session_state.basket = []
                st.rerun()

    # --- 3. بقية الأقسام ---
    elif choice == "📦 المخزون":
        d, _ = fetch_query("SELECT sku, name, quantity, price FROM items")
        st.table(pd.DataFrame(d, columns=['SKU', 'الاسم', 'الكمية', 'السعر']))

    elif choice == "➕ إضافة منتج":
        with st.form("add_p"):
            res, _ = fetch_query("SELECT MAX(id) FROM items")
            next_sku = f"P-{res[0][0]+1 if res[0][0] else 1001}"
            st.info(f"الكود: {next_sku}")
            name = st.text_input("اسم المنتج")
            qty = st.number_input("الكمية")
            if st.form_submit_button("حفظ"):
                now = datetime.now().strftime("%Y-%m-%d %H:%M")
                execute_query("INSERT INTO items (name, sku, quantity, last_updated) VALUES (?,?,?,?)", (name, next_sku, qty, now))
                st.success("تم الحفظ")

    elif choice == "📜 السجل":
        l, _ = fetch_query("SELECT timestamp, ref_code, sku, type, quantity_change, user, reason FROM transactions ORDER BY id DESC")
        st.table(pd.DataFrame(l, columns=['الوقت', 'السند', 'الكود', 'النوع', 'الكمية', 'المستخدم', 'السبب']))

if __name__ == "__main__":
    main()
