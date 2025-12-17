import streamlit as st
import sqlite3
from datetime import datetime
import pandas as pd
from fpdf import FPDF
import hashlib

# -------------------------------------------------------------
# 1. إعداد قاعدة البيانات (تحديث عمود المورد)
# -------------------------------------------------------------
DATABASE_NAME = 'inventory_control.db'

def initialize_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    # التأكد من وجود عمود المورد لتجنب خطأ الإضافة
    cursor.execute('''CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        name TEXT UNIQUE, 
        sku TEXT UNIQUE, 
        quantity REAL, 
        min_stock REAL DEFAULT 5, 
        price REAL, 
        supplier_name TEXT DEFAULT 'غير محدد', 
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
    
    # حساب المدير الافتراضي (admin / admin123)
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
# 2. واجهة الدخول (تشمل تسجيل الدخول + إنشاء حساب جديد)
# -------------------------------------------------------------
def auth_page():
    st.title("🏆 نظام شركة اكسبو تايم - بوابة الوصول")
    
    # استخدام تبويبات واضحة للتنقل بين الدخول والتسجيل
    tab_login, tab_signup = st.tabs(["🔐 تسجيل الدخول", "📝 إنشاء حساب موظف جديد"])
    
    with tab_login:
        with st.form("login_form"):
            u = st.text_input("اسم المستخدم")
            p = st.text_input("كلمة المرور", type="password")
            if st.form_submit_button("دخول للنظام"):
                hp = hashlib.sha256(p.encode()).hexdigest()
                res, _ = fetch_query("SELECT role FROM users WHERE username=? AND password=?", (u, hp))
                if res:
                    st.session_state.logged_in = True
                    st.session_state.username = u
                    st.session_state.role = res[0][0]
                    st.rerun()
                else: st.error("❌ بيانات الدخول غير صحيحة")

    with tab_signup:
        st.info("ملاحظة: النظام يسمح بحد أقصى 10 موظفين فقط.")
        with st.form("signup_form"):
            new_u = st.text_input("اسم مستخدم جديد")
            new_p = st.text_input("كلمة مرور قوية", type="password")
            confirm_p = st.text_input("تأكيد كلمة المرور", type="password")
            if st.form_submit_button("إنشاء الحساب الآن"):
                cnt, _ = fetch_query("SELECT COUNT(*) FROM users WHERE role='موظف'")
                if cnt[0][0] >= 10:
                    st.error("🚫 عذراً، تم الوصول للحد الأقصى للموظفين (10).")
                elif new_p != confirm_p:
                    st.error("❌ كلمات المرور غير متطابقة.")
                elif new_u and new_p:
                    hp = hashlib.sha256(new_p.encode()).hexdigest()
                    if execute_query("INSERT INTO users VALUES (?, ?, 'موظف')", (new_u, hp)):
                        st.success("✅ تم إنشاء الحساب بنجاح! توجه لتبويب تسجيل الدخول.")
                else: st.warning("⚠️ يرجى ملء كافة الخانات.")

# -------------------------------------------------------------
# 3. التطبيق الرئيسي (بعد الدخول)
# -------------------------------------------------------------
def main():
    initialize_db()
    
    if 'logged_in' not in st.session_state: st.session_state.logged_in = False

    if not st.session_state.logged_in:
        auth_page()
        return

    # الشريط الجانبي
    st.sidebar.success(f"المستخدم: {st.session_state.username} | {st.session_state.role}")
    menu = ["📦 إدارة وعرض المخزون", "➕ إضافة منتج جديد", "📤 أمر صرف (DO)", "📄 طلب شراء (PO)", "📜 سجل العمليات", "👥 إدارة الموظفين"]
    if st.session_state.role != "مدير": menu.remove("👥 إدارة الموظفين")
    choice = st.sidebar.selectbox("القائمة الرئيسية", menu)
    
    if st.sidebar.button("تسجيل الخروج"):
        st.session_state.logged_in = False
        st.rerun()

    # جلب البيانات الحالية
    data_items, cols_items = fetch_query("SELECT id, name, sku, quantity, price, supplier_name FROM items")
    all_skus = [f"{x[2]}" for x in data_items]

    # --- 1. إدارة المخزون (تعديل وحذف) ---
    if choice == "📦 إدارة وعرض المخزون":
        st.subheader("لوحة تحكم المخزون")
        if data_items:
            df = pd.DataFrame(data_items, columns=['ID', 'الاسم', 'SKU', 'الكمية', 'السعر', 'المورد'])
            st.dataframe(df, use_container_width=True)
            
            if st.session_state.role == "مدير":
                st.markdown("---")
                st.subheader("🛠️ عمليات المدير")
                col1, col2 = st.columns(2)
                with col1:
                    st.write("🔧 تحديث بيانات صنف")
                    edit_sku = st.selectbox("اختر SKU", all_skus, key="edit_sku")
                    new_q = st.number_input("الكمية الفعلية الجديدة", value=0.0)
                    new_p = st.number_input("السعر الجديد", value=0.0)
                    if st.button("حفظ التعديلات"):
                        execute_query("UPDATE items SET quantity=?, price=? WHERE sku=?", (new_q, new_p, edit_sku))
                        st.success("✅ تم تحديث بيانات الصنف بنجاح"); st.rerun()
                with col2:
                    st.write("🗑️ حذف صنف من النظام")
                    del_sku = st.selectbox("اختر SKU للحذف", all_skus, key="del_sku")
                    if st.button("❌ حذف الصنف نهائياً"):
                        execute_query("DELETE FROM items WHERE sku=?", (del_sku,))
                        st.warning("⚠️ تم حذف الصنف بنجاح"); st.rerun()
        else: st.info("المخزن فارغ حالياً.")

    # --- 2. إضافة صنف جديد (حل مشكلة المورد) ---
    elif choice == "➕ إضافة منتج جديد":
        st.subheader("إدخال صنف جديد إلى المستودع")
        res, _ = fetch_query("SELECT id FROM items ORDER BY id DESC LIMIT 1")
        next_id = (res[0][0] + 1) if res else 1001
        final_sku = f"P-{next_id}"
        
        with st.form("add_item_form"):
            st.info(f"كود الصنف التلقائي: {final_sku}")
            name = st.text_input("اسم المنتج")
            qty = st.number_input("الكمية الحالية", min_value=0.0)
            price = st.number_input("سعر التكلفة", min_value=0.0)
            supplier = st.text_input("اسم المورد", value="شركة اكسبو")
            
            if st.form_submit_button("حفظ الصنف"):
                if name and supplier:
                    now = datetime.now().strftime("%Y-%m-%d %H:%M")
                    if execute_query("INSERT INTO items (name, sku, quantity, price, supplier_name, last_updated) VALUES (?,?,?,?,?,?)", 
                                     (name, final_sku, qty, price, supplier, now)):
                        execute_query("INSERT INTO transactions VALUES (NULL, 'NEW', ?, 'IN', ?, ?, 'إضافة صنف جديد', ?)", (final_sku, qty, st.session_state.username, now))
                        st.success(f"✅ تم حفظ الصنف بنجاح بالكود: {final_sku}"); st.rerun()
                else: st.error("❌ يرجى تعبئة كافة الحقول المطلوبة.")

    # --- بقية الأقسام المعتادة ---
    elif choice == "📤 أمر صرف (DO)":
        st.subheader("إصدار أمر صرف")
        # نفس منطق الصرف السابق...
        pass

    elif choice == "📜 سجل العمليات":
        st.subheader("سجل الرقابة")
        l, _ = fetch_query("SELECT timestamp, ref_code, sku, type, quantity_change, user FROM transactions ORDER BY id DESC")
        st.table(pd.DataFrame(l, columns=['الوقت', 'السند', 'الكود', 'النوع', 'الكمية', 'المستخدم']))

if __name__ == "__main__":
    main()
