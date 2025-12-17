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
    # جداول النظام - تحديث الهيكل لدعم التوليد التلقائي والمورد
    cursor.execute('''CREATE TABLE IF NOT EXISTS items 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, sku TEXT UNIQUE, quantity REAL, 
        min_stock REAL DEFAULT 5, price REAL, supplier_name TEXT DEFAULT 'غير محدد', last_updated TEXT)''')
    
    # تحديث جدول الحركات لدعم رقم السند الموحد (Ref Code)
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, ref_code TEXT, sku TEXT, type TEXT, 
        quantity_change REAL, user TEXT, reason TEXT, timestamp TEXT)''')
        
    cursor.execute('''CREATE TABLE IF NOT EXISTS bom_recipes 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, parent_sku TEXT, component_sku TEXT, qty_needed REAL, 
        UNIQUE(parent_sku, component_sku))''')
        
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

# دالة لتوليد كود المنتج التالي تلقائياً
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
        tab1, tab2 = st.tabs(["🔐 تسجيل الدخول", "📝 إنشاء حساب موظف"])
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
            with st.form("signup"):
                nu = st.text_input("اسم المستخدم الجديد")
                np = st.text_input("كلمة المرور", type="password")
                if st.form_submit_button("تسجيل"):
                    u_cnt, _ = fetch_query("SELECT COUNT(*) FROM users WHERE role='موظف'")
                    if u_cnt[0][0] >= 10: st.error("الحد الأقصى 10 موظفين")
                    elif nu and np:
                        hp = hashlib.sha256(np.encode()).hexdigest()
                        if execute_query("INSERT INTO users VALUES (?,?,'موظف')", (nu, hp)):
                            st.success("تم التسجيل بنجاح")
        return

    st.sidebar.title(f"مرحباً {st.session_state.username}")
    st.sidebar.info(f"الصلاحية: {st.session_state.role}")
    if st.sidebar.button("تسجيل الخروج"):
        st.session_state.logged_in = False; st.rerun()

    menu = ["🔍 عرض وحذف الأصناف", "➕ إضافة وتحديث صنف", "⚙️ تعريف منتج BOM", "📤 صرف أصناف مدمج (DO)", "📜 سجل العمليات", "👥 إدارة المستخدمين"]
    if st.session_state.role != "مدير": menu.remove("👥 إدارة المستخدمين")
    choice = st.sidebar.selectbox("القائمة الرئيسية", menu)
    st.markdown("---")

    skus_raw, _ = fetch_query("SELECT sku, name, quantity FROM items")
    all_skus = [s[0] for s in skus_raw]
    all_names = [s[1] for s in skus_raw]

    # --- 1. إدارة المستخدمين ---
    if choice == "👥 إدارة المستخدمين":
        st.subheader("إدارة طاقم العمل")
        users_list, _ = fetch_query("SELECT username FROM users WHERE role='موظف'")
        st.write(f"عدد الموظفين: {len(users_list)}/10")
        u_del = st.selectbox("حذف موظف", [""] + [u[0] for u in users_list])
        if st.button("تأكيد الحذف") and u_del:
            execute_query("DELETE FROM users WHERE username=?", (u_del,))
            st.success("تم الحذف"); st.rerun()

    # --- 2. إضافة وتحديث (تلقائي + منع تكرار) ---
    elif choice == "➕ إضافة وتحديث صنف":
        st.subheader("إدارة الأصناف")
        mode = st.radio("نوع العملية", ["تحديث صنف موجود", "إضافة صنف جديد كلياً"]) if st.session_state.role == "مدير" else "إضافة صنف جديد كلياً"
        with st.form("item_form"):
            if mode == "إضافة صنف جديد كلياً":
                next_sku = get_next_sku()
                st.info(f"الكود التلقائي: {next_sku}")
                target_sku, target_name = next_sku, st.text_input("اسم المنتج الجديد")
            else:
                target_sku = st.selectbox("اختر الصنف", [""] + all_skus)
                target_name = ""
            
            qty, price = st.number_input("الكمية", min_value=0.0), st.number_input("السعر", min_value=0.0)
            supplier = st.text_input("المورد", value="غير محدد")
            
            if st.form_submit_button("اعتماد العملية"):
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if mode == "إضافة صنف جديد كلياً":
                    if target_name in all_names: st.error("الاسم موجود مسبقاً")
                    else:
                        execute_query("INSERT INTO items (name, sku, quantity, price, supplier_name, last_updated) VALUES (?,?,?,?,?,?)", (target_name, target_sku, qty, price, supplier, now))
                        execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES ('NEW', ?, 'IN', ?, ?, 'إضافة صنف', ?)", (target_sku, qty, st.session_state.username, now))
                        st.success(f"تم الحفظ بكود: {target_sku}"); st.rerun()
                else:
                    execute_query("UPDATE items SET quantity=quantity+?, price=?, last_updated=? WHERE sku=?", (qty, price, now, target_sku))
                    execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES ('UPDATE', ?, 'IN', ?, ?, 'تحديث كمية', ?)", (target_sku, qty, st.session_state.username, now))
                    st.success("تم التحديث"); st.rerun()

    # --- 3. تعريف BOM ---
    elif choice == "⚙️ تعريف منتج BOM":
        st.subheader("تعريف قائمة المواد (BOM)")
        with st.form("bom"):
            p_sku = st.selectbox("المنتج النهائي", [""] + [f"{x[0]} | {x[1]}" for x in skus_raw]).split(" | ")[0]
            c_sku = st.selectbox("المكون (المادة الخام)", [""] + [f"{x[0]} | {x[1]}" for x in skus_raw]).split(" | ")[0]
            qty_n = st.number_input("الكمية المطلوبة من المكون", min_value=0.01)
            if st.form_submit_button("حفظ المكون"):
                execute_query("INSERT OR REPLACE INTO bom_recipes (parent_sku, component_sku, qty_needed) VALUES (?,?,?)", (p_sku, c_sku, qty_n))
                st.success("تم الربط بنجاح")

    # --- 4. صرف مدمج (سلة صرف واحدة) ---
    elif choice == "📤 صرف أصناف مدمج (DO)":
        st.subheader("إصدار أمر صرف (DO)")
        if 'basket' not in st.session_state: st.session_state.basket = []
        c1, c2 = st.columns([3,1])
        item_sel = c1.selectbox("اختر الصنف", [""] + [f"{x[0]} | {x[1]}" for x in skus_raw])
        qty_sel = c2.number_input("الكمية", min_value=1.0)
        if st.button("➕ أضف للسند"):
            if item_sel: st.session_state.basket.append({"sku": item_sel.split(" | ")[0], "qty": qty_sel})
        
        if st.session_state.basket:
            st.table(pd.DataFrame(st.session_state.basket))
            if st.button("🚀 تأكيد صرف السند بالكامل"):
                now = datetime.now()
                do_ref = f"DO-{now.strftime('%y%m%d%H%M')}"
                for item in st.session_state.basket:
                    sku, qty = item['sku'], item['qty']
                    # فحص BOM
                    comps, _ = fetch_query("SELECT component_sku, qty_needed FROM bom_recipes WHERE parent_sku=?", (sku,))
                    if comps:
                        for c_sku, c_qty in comps:
                            total = c_qty * qty
                            execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (total, c_sku))
                            execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES (?,?,'OUT',?,?,?,?)", (do_ref, c_sku, total, st.session_state.username, f"BOM للمنتج {sku}", now.strftime("%Y-%m-%d %H:%M")))
                    else:
                        execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (qty, sku))
                        execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES (?,?,'OUT',?,?,?,?)", (do_ref, sku, qty, st.session_state.username, "صرف مباشر", now.strftime("%Y-%m-%d %H:%M")))
                st.success(f"تم الصرف بالسند: {do_ref}"); st.session_state.basket = []; st.rerun()

    # --- 5. عرض وحذف ---
    elif choice == "🔍 عرض وحذف الأصناف":
        search = st.text_input("بحث")
        data, _ = fetch_query("SELECT name, sku, quantity, price FROM items WHERE name LIKE ? OR sku LIKE ?", (f'%{search}%', f'%{search}%'))
        if data:
            st.table(pd.DataFrame(data, columns=['الاسم', 'الكود', 'الكمية', 'السعر']))
            if st.session_state.role == "مدير":
                to_del = st.selectbox("حذف SKU", [""] + all_skus)
                if st.button("❌ حذف نهائي"):
                    execute_query("DELETE FROM items WHERE sku=?", (to_del,)); st.rerun()

    # --- 6. سجل العمليات ---
    elif choice == "📜 سجل العمليات":
        st.subheader("سجل الرقابة")
        logs, _ = fetch_query("SELECT timestamp, ref_code, sku, type, quantity_change, user, reason FROM transactions ORDER BY id DESC")
        st.table(pd.DataFrame(logs, columns=['الوقت', 'السند', 'الكود', 'النوع', 'الكمية', 'المستخدم', 'السبب']))

if __name__ == "__main__":
    main()
