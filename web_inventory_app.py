import streamlit as st
import sqlite3
from datetime import datetime
import pandas as pd
from fpdf import FPDF
import hashlib

# -------------------------------------------------------------
# 1. إعداد قاعدة البيانات (تم تحديثها لتشمل المورد)
# -------------------------------------------------------------
DATABASE_NAME = 'inventory_control.db'

def initialize_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    # إضافة عمود supplier_name لتجنب الخطأ الذي ظهر لك
    cursor.execute('''CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        name TEXT UNIQUE, 
        sku TEXT UNIQUE, 
        quantity REAL, 
        min_stock REAL DEFAULT 5, 
        price REAL, 
        supplier_name TEXT, 
        last_updated TEXT)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY, 
        ref_code TEXT,
        sku TEXT, 
        type TEXT, 
        quantity_change REAL, 
        user TEXT, 
        reason TEXT, 
        timestamp TEXT)''')
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
        st.error(f"خطأ في التنفيذ: {e}")
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
# 2. التطبيق الرئيسي
# -------------------------------------------------------------
def main():
    initialize_db()
    if 'logged_in' not in st.session_state: st.session_state.logged_in = False

    if not st.session_state.logged_in:
        st.title("🏆 شركة اكسبو تايم - الدخول")
        u = st.text_input("اسم المستخدم")
        p = st.text_input("كلمة المرور", type="password")
        if st.button("دخول"):
            hp = hashlib.sha256(p.encode()).hexdigest()
            res, _ = fetch_query("SELECT role FROM users WHERE username=? AND password=?", (u, hp))
            if res:
                st.session_state.logged_in = True
                st.session_state.username = u
                st.session_state.role = res[0][0]
                st.rerun()
            else: st.error("بيانات خاطئة")
        return

    st.sidebar.title(f"مرحباً {st.session_state.username}")
    menu = ["📦 عرض وإدارة المخزون", "➕ إضافة منتج جديد", "📤 أمر صرف (DO)", "📄 طلب شراء (PO)", "📜 سجل العمليات"]
    choice = st.sidebar.selectbox("القائمة", menu)
    if st.sidebar.button("خروج"):
        st.session_state.logged_in = False
        st.rerun()

    # --- 1. عرض وإدارة المخزون (تعديل وحذف) ---
    if choice == "📦 عرض وإدارة المخزون":
        st.subheader("إدارة المخزون الحالي")
        data, cols = fetch_query("SELECT id, name, sku, quantity, price, supplier_name FROM items")
        if data:
            df = pd.DataFrame(data, columns=['ID', 'الاسم', 'SKU', 'الكمية', 'السعر', 'المورد'])
            st.dataframe(df, use_container_width=True)
            
            if st.session_state.role == "مدير":
                st.markdown("---")
                col1, col2 = st.columns(2)
                with col1:
                    st.write("🔧 تحديث صنف")
                    edit_id = st.selectbox("اختر ID المنتج للتعديل", df['ID'].tolist())
                    new_q = st.number_input("الكمية الجديدة", value=0.0)
                    new_p = st.number_input("السعر الجديد", value=0.0)
                    if st.button("تحديث البيانات"):
                        execute_query("UPDATE items SET quantity=?, price=? WHERE id=?", (new_q, new_p, edit_id))
                        st.success("تم التحديث بنجاح"); st.rerun()
                with col2:
                    st.write("🗑️ حذف صنف")
                    del_id = st.selectbox("اختر ID المنتج للحذف", df['ID'].tolist())
                    if st.button("حذف نهائي"):
                        execute_query("DELETE FROM items WHERE id=?", (del_id,))
                        st.warning("تم الحذف"); st.rerun()
        else:
            st.info("المخزن فارغ حالياً.")

    # --- 2. إضافة منتج جديد (حل مشكلة المورد) ---
    elif choice == "➕ إضافة منتج جديد":
        st.subheader("إدخال صنف جديد")
        res, _ = fetch_query("SELECT id FROM items ORDER BY id DESC LIMIT 1")
        next_id = (res[0][0] + 1) if res else 1001
        final_sku = f"P-{next_id}"
        
        with st.form("add_item_form"):
            st.info(f"الكود التلقائي: {final_sku}")
            name = st.text_input("اسم المنتج")
            qty = st.number_input("الكمية الأولية", min_value=0.0)
            price = st.number_input("سعر الوحدة", min_value=0.0)
            supplier = st.text_input("اسم المورد (مطلوب)") # الحقل المفقود سابقاً
            
            if st.form_submit_button("حفظ المنتج"):
                if not name or not supplier:
                    st.error("يرجى إدخال الاسم واسم المورد")
                else:
                    now = datetime.now().strftime("%Y-%m-%d %H:%M")
                    # تم إضافة supplier_name في جملة الـ INSERT
                    success = execute_query(
                        "INSERT INTO items (name, sku, quantity, price, supplier_name, last_updated) VALUES (?,?,?,?,?,?)",
                        (name, final_sku, qty, price, supplier, now)
                    )
                    if success:
                        execute_query("INSERT INTO transactions VALUES (NULL, 'NEW', ?, 'IN', ?, ?, 'إضافة صنف', ?)", (final_sku, qty, st.session_state.username, now))
                        st.success(f"تمت الإضافة بنجاح بكود {final_sku}")
                        st.rerun()

    # --- (بقية الأقسام DO, PO, Logs تبقى كما هي في الكود المستقر) ---
    elif choice == "📤 أمر صرف (DO)":
        st.subheader("أمر صرف مخزني")
        items_data, _ = fetch_query("SELECT sku, name, quantity FROM items")
        skus = [f"{x[0]} - {x[1]}" for x in items_data]
        sel = st.selectbox("اختر المنتج", skus)
        q_out = st.number_input("الكمية", min_value=1.0)
        if st.button("تأكيد الصرف"):
            now = datetime.now()
            do_ref = f"DO-{now.strftime('%y%m%d%H%M')}"
            sku_only = sel.split(' - ')[0]
            execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (q_out, sku_only))
            execute_query("INSERT INTO transactions VALUES (NULL, ?, ?, 'OUT', ?, ?, 'صرف', ?)", (do_ref, sku_only, q_out, st.session_state.username, now.strftime("%Y-%m-%d %H:%M")))
            st.success(f"تم الصرف برقم: {do_ref}")

    elif choice == "📜 سجل العمليات":
        l, _ = fetch_query("SELECT timestamp, ref_code, sku, type, quantity_change, user FROM transactions ORDER BY id DESC")
        st.table(pd.DataFrame(l, columns=['الوقت', 'السند', 'الكود', 'النوع', 'الكمية', 'المستخدم']))

if __name__ == "__main__":
    main()
