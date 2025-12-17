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
    # تحديث جدول الأصناف لدعم الوحدات والترقيم التلقائي
    cursor.execute('''CREATE TABLE IF NOT EXISTS items 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, sku TEXT UNIQUE, quantity INTEGER, 
        unit TEXT, min_stock INTEGER DEFAULT 5, price REAL, last_updated TEXT)''')
    
    # تحديث جدول العمليات لدعم رقم السند الموحد
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

# دالة توليد كود SKU تلقائياً لضمان التسلسل P-01001
def get_next_sku():
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
    st.set_page_config(page_title="اكسبو تايم للمخزون", layout="wide")

    if 'logged_in' not in st.session_state: st.session_state.logged_in = False

    if not st.session_state.logged_in:
        st.title("قفل الأمان - شركة اكسبو تايم")
        tab_login, tab_signup = st.tabs(["🔐 تسجيل الدخول", "📝 إنشاء حساب موظف"])
        with tab_login:
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
        with tab_signup:
            with st.form("signup_form"):
                new_u = st.text_input("اسم المستخدم الجديد")
                new_p = st.text_input("كلمة المرور", type="password")
                if st.form_submit_button("تسجيل"):
                    u_cnt, _ = fetch_query("SELECT COUNT(*) FROM users WHERE role='موظف'")
                    if u_cnt[0][0] >= 10: st.error("الحد الأقصى 10 موظفين")
                    elif new_u and new_p:
                        hp = hashlib.sha256(new_p.encode()).hexdigest()
                        if execute_query("INSERT INTO users VALUES (?,?,'موظف')", (new_u, hp)):
                            st.success("تم إنشاء الحساب بنجاح!")
        return

    # تنبيه النواقص الجانبي
    low_stock_count, _ = fetch_query("SELECT COUNT(*) FROM items WHERE quantity <= min_stock")
    if low_stock_count[0][0] > 0:
        st.sidebar.warning(f"🚨 تنبيه: يوجد {low_stock_count[0][0]} أصناف تحت الحد الأدنى!")

    st.sidebar.title(f"مرحباً {st.session_state.username}")
    st.sidebar.info(f"الصلاحية: {st.session_state.role}")
    if st.sidebar.button("تسجيل الخروج"):
        st.session_state.logged_in = False
        st.rerun()

    menu = ["🔍 عرض وحذف الأصناف", "➕ إضافة وتحديث صنف", "⚙️ تعريف منتج BOM", "📤 صرف أصناف مجمع (DO)", "🏭 صرف BOM", "📦 طلب شراء PDF", "📜 سجل العمليات", "👥 إدارة المستخدمين"]
    if st.session_state.role != "مدير": menu.remove("👥 إدارة المستخدمين")
    choice = st.sidebar.selectbox("القائمة الرئيسية", menu)
    st.markdown("---")

    skus_raw, _ = fetch_query("SELECT sku, name, quantity, unit FROM items")
    all_skus = [s[0] for s in skus_raw]
    all_names = [s[1] for s in skus_raw]

    # --- 1. عرض وحذف الأصناف ---
    if choice == "🔍 عرض وحذف الأصناف":
        search = st.text_input("ابحث بالاسم أو الكود")
        data, _ = fetch_query("SELECT name, sku, quantity, unit, price, min_stock FROM items WHERE name LIKE ? OR sku LIKE ?", (f'%{search}%', f'%{search}%'))
        if data:
            df = pd.DataFrame(data, columns=['الاسم', 'الكود SKU', 'الكمية', 'الوحدة', 'السعر', 'الحد الأدنى'])
            df['الكمية'] = df['الكمية'].astype(int)
            
            def highlight_low(row):
                if row.الكمية <= row['الحد الأدنى']:
                    return ['background-color: #fff0f0; color: #b30000; font-weight: bold'] * len(row)
                return [''] * len(row)
            
            st.dataframe(df.style.apply(highlight_low, axis=1), use_container_width=True)
            
            if st.session_state.role == "مدير":
                st.warning("منطقة حذف الأصناف (للمدير فقط)")
                to_del = st.selectbox("اختر الكود للحذف النهائي", [""] + [d[1] for d in data])
                if st.button("❌ حذف المنتج نهائياً من النظام") and to_del:
                    execute_query("DELETE FROM items WHERE sku=?", (to_del,))
                    st.success("تم الحذف بنجاح"); st.rerun()

    # --- 2. إضافة وتحديث (تلقائي + وحدات) ---
    elif choice == "➕ إضافة وتحديث صنف":
        st.subheader("إدارة الأصناف")
        mode = st.radio("نوع العملية", ["تحديث صنف موجود", "إضافة صنف جديد كلياً"]) if st.session_state.role == "مدير" else "إضافة صنف جديد كلياً"
        
        with st.form("item_form"):
            if mode == "إضافة صنف جديد كلياً":
                auto_sku = get_next_sku()
                st.info(f"كود الصنف التلقائي: {auto_sku}")
                target_sku = auto_sku
                target_name = st.text_input("اسم المنتج الجديد")
                unit = st.selectbox("وحدة المنتج", ["قطعة", "بكت", "جرام", "درزن"])
            else:
                target_sku = st.selectbox("اختر الكود", [""] + all_skus)
                target_name, unit = "", ""
            
            qty = st.number_input("الكمية", min_value=0, step=1, value=0, format="%d")
            m_stock = st.number_input("حد النقصان", value=5, step=1, format="%d")
            price = st.number_input("السعر", min_value=0.0)
            
            if st.form_submit_button("اعتماد العملية"):
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if mode == "إضافة صنف جديد كلياً":
                    if not target_name: st.error("يرجى إدخال اسم المنتج")
                    elif target_name in all_names: st.error("الاسم مكرر مسبقاً")
                    else:
                        execute_query("INSERT INTO items (name, sku, quantity, unit, min_stock, price, last_updated) VALUES (?,?,?,?,?,?,?)", (target_name, target_sku, int(qty), unit, int(m_stock), price, now))
                        execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES ('NEW', ?, 'IN', ?, ?, 'إضافة جديد', ?)", (target_sku, int(qty), st.session_state.username, now))
                        st.success(f"تمت الإضافة بالكود {target_sku}"); st.rerun()
                else:
                    execute_query("UPDATE items SET quantity=quantity+?, price=?, last_updated=? WHERE sku=?", (int(qty), price, now, target_sku))
                    execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES ('UPDATE', ?, 'IN', ?, ?, 'تحديث كمية', ?)", (target_sku, int(qty), st.session_state.username, now))
                    st.success("تم التحديث"); st.rerun()

    # --- 3. صرف أصناف مجمع (DO) ---
    elif choice == "📤 صرف أصناف مجمع (DO)":
        st.subheader("إصدار أمر صرف مجمع (Delivery Order)")
        if 'basket' not in st.session_state: st.session_state.basket = []
        
        col1, col2, col3 = st.columns([3, 1, 1])
        s_sel = col1.selectbox("اختر الصنف", [""] + [f"{x[0]} | {x[1]} ({x[3]})" for x in skus_raw])
        q_sel = col2.number_input("الكمية", min_value=1, step=1, value=1, format="%d")
        if col3.button("➕ أضف للسند"):
            if s_sel:
                st.session_state.basket.append({"sku": s_sel.split(" | ")[0], "qty": int(q_sel), "name": s_sel.split(" | ")[1]})
                st.toast("تمت الإضافة للسلة")
        
        if st.session_state.basket:
            st.table(pd.DataFrame(st.session_state.basket))
            c1, c2 = st.columns(2)
            if c1.button("🚀 تأكيد صرف السند"):
                now = datetime.now()
                do_ref = f"DO-{now.strftime('%y%m%d%H%M')}"
                for item in st.session_state.basket:
                    execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (item['qty'], item['sku']))
                    execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES (?,?,'OUT',?,?,?,?)", (do_ref, item['sku'], item['qty'], st.session_state.username, "صرف مجمع", now.strftime("%Y-%m-%d %H:%M")))
                st.success(f"تم الصرف بالسند: {do_ref}"); st.session_state.basket = []; st.rerun()
            if c2.button("🗑️ إفراغ السلة"):
                st.session_state.basket = []; st.rerun()

    # --- 4. تعريف وصرف BOM ---
    elif choice == "⚙️ تعريف منتج BOM":
        st.subheader("تعريف مكونات المنتج")
        with st.form("bom_reg"):
            p_name = st.selectbox("المنتج المجمع", all_names)
            c_sku = st.selectbox("المكون المادي", all_skus)
            req_qty = st.number_input("الكمية لكل وحدة", min_value=1, step=1, value=1, format="%d")
            if st.form_submit_button("حفظ المكون"):
                execute_query("INSERT OR REPLACE INTO bom_recipes (assembled_product_name, raw_material_sku, required_quantity) VALUES (?,?,?)", (p_name, c_sku, int(req_qty)))
                st.success("تم الحفظ")

    elif choice == "🏭 صرف BOM":
        st.subheader("صرف مكونات الإنتاج")
        p_target = st.selectbox("المنتج المراد تجميعه", all_names)
        p_qty = st.number_input("الكمية المطلوبة", min_value=1, step=1, value=1, format="%d")
        if st.button("🚀 تنفيذ التجميع"):
            comps, _ = fetch_query("SELECT raw_material_sku, required_quantity FROM bom_recipes WHERE assembled_product_name=?", (p_target,))
            if comps:
                now = datetime.now()
                do_ref = f"BOM-{now.strftime('%y%m%d%H%M')}"
                for c_sku, c_req in comps:
                    total = int(c_req * p_qty)
                    execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (total, c_sku))
                    execute_query("INSERT INTO transactions (ref_code, sku, type, quantity_change, user, reason, timestamp) VALUES (?,?,'OUT',?,?,?,?)", (do_ref, c_sku, total, st.session_state.username, f"إنتاج لـ {p_target}", now.strftime("%Y-%m-%d %H:%M")))
                st.success("تم صرف المكونات بنجاح"); st.rerun()
            else: st.error("لم يتم تعريف مكونات BOM")

    # --- 5. طلب شراء PDF ---
    elif choice == "📦 طلب شراء PDF":
        if 'po_rows' not in st.session_state: st.session_state.po_rows = 1
        if st.button("➕ إضافة صنف"): st.session_state.po_rows += 1
        po_list = []
        for i in range(st.session_state.po_rows):
            c1, c2, c3 = st.columns([2,1,2])
            s = c1.selectbox(f"الصنف{i+1}", [""] + all_skus, key=f"po_s_{i}")
            q = c2.number_input(f"الكمية{i+1}", key=f"po_q_{i}", format="%d", value=1, step=1)
            d = c3.date_input(f"تاريخ التوريد {i+1}", key=f"po_d_{i}")
            if s: po_list.append((s, int(q), d.strftime("%Y-%m-%d")))
        if st.button("📄 توليد PDF"):
            now_dt = datetime.now()
            pdf_bytes = create_pdf_content(f"PO-{now_dt.strftime('%H%M')}", po_list, now_dt.strftime("%Y-%m-%d"), st.session_state.username)
            st.download_button("📥 تحميل PDF", pdf_bytes, f"PO_{now_dt.strftime('%m%d')}.pdf", "application/pdf")

    # --- 6. سجل العمليات وإدارة المستخدمين ---
    elif choice == "📜 سجل العمليات":
        st.subheader("سجل الحركات")
        logs, _ = fetch_query("SELECT timestamp, ref_code, sku, type, quantity_change, user, reason FROM transactions ORDER BY id DESC")
        if logs:
            df_logs = pd.DataFrame(logs, columns=['الوقت', 'السند', 'الكود', 'النوع', 'الكمية', 'المستخدم', 'السبب'])
            df_logs['الكمية'] = df_logs['الكمية'].astype(int)
            st.table(df_logs)

    elif choice == "👥 إدارة المستخدمين":
        st.subheader("إدارة طاقم العمل")
        u_list, _ = fetch_query("SELECT username FROM users WHERE role='موظف'")
        u_del = st.selectbox("حذف موظف", [""] + [u[0] for u in u_list])
        if st.button("❌ حذف نهائياً") and u_del:
            execute_query("DELETE FROM users WHERE username=?", (u_del,))
            st.rerun()

if __name__ == "__main__":
    main()
