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
    # جدول الأصناف مع قيود الفرادة على الاسم والكود
    cursor.execute('''CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY, 
        name TEXT UNIQUE, 
        sku TEXT UNIQUE, 
        quantity REAL, 
        min_stock REAL DEFAULT 5, 
        price REAL, 
        last_updated TEXT)''')
    cursor.execute('CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY, sku TEXT, type TEXT, quantity_change REAL, user TEXT, reason TEXT, timestamp TEXT)')
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
        # هنا سيظهر لك سبب الرفض بالتفصيل
        st.error(f"فشلت العملية: {e}")
        return False
    finally:
        conn.close()

def fetch_query(query, params=()):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        return cursor.fetchall(), [d[0] for d in cursor.description]
    except: return [], []
    finally: conn.close()

# -------------------------------------------------------------
# 2. التطبيق الرئيسي
# -------------------------------------------------------------
def main():
    initialize_db()
    
    if 'logged_in' not in st.session_state: st.session_state.logged_in = False

    # --- صفحة الدخول والتسجيل ---
    if not st.session_state.logged_in:
        st.title("🏆 شركة اكسبو تايم - الدخول")
        t1, t2 = st.tabs(["تسجيل الدخول", "إنشاء حساب موظف"])
        
        with t1:
            with st.form("l_f"):
                u = st.text_input("اسم المستخدم")
                p = st.text_input("كلمة المرور", type="password")
                if st.form_submit_button("دخول"):
                    hp = hashlib.sha256(p.encode()).hexdigest()
                    res, _ = fetch_query("SELECT role FROM users WHERE username=? AND password=?", (u, hp))
                    if res:
                        st.session_state.logged_in = True
                        st.session_state.username = u
                        st.session_state.role = res[0][0]
                        st.rerun()
                    else: st.error("خطأ في البيانات")
        
        with t2:
            with st.form("s_f"):
                nu = st.text_input("اسم مستخدم جديد")
                np = st.text_input("كلمة مرور", type="password")
                if st.form_submit_button("تسجيل"):
                    cnt, _ = fetch_query("SELECT COUNT(*) FROM users WHERE role='موظف'")
                    if cnt[0][0] >= 10: st.error("الحد الأقصى للموظفين 10")
                    elif nu and np:
                        hp = hashlib.sha256(np.encode()).hexdigest()
                        if execute_query("INSERT INTO users VALUES (?,?,'موظف')", (nu, hp)):
                            st.success("تم التسجيل! توجه لخانة الدخول")
        return

    # --- القائمة الرئيسية ---
    st.sidebar.success(f"المستخدم: {st.session_state.username}")
    menu = ["📦 عرض المخزون", "➕ إضافة وتحديث", "📤 صرف أصناف", "📄 طلب شراء PDF", "📜 سجل العمليات", "👥 إدارة المستخدمين"]
    if st.session_state.role != "مدير": menu.remove("👥 إدارة المستخدمين")
    choice = st.sidebar.selectbox("القائمة", menu)
    if st.sidebar.button("خروج"):
        st.session_state.logged_in = False
        st.rerun()

    # جلب البيانات الحالية للتحقق
    data_items, _ = fetch_query("SELECT sku, name FROM items")
    all_skus = [x[0] for x in data_items]
    all_names = [x[1] for x in data_items]

    # --- إضافة وتحديث ---
    if choice == "➕ إضافة وتحديث":
        st.subheader("إضافة أو تحديث صنف")
        mode = st.radio("العملية", ["إضافة صنف جديد", "تحديث صنف موجود (مدير)"]) if st.session_state.role == "مدير" else "إضافة صنف جديد"
        
        with st.form("add_form"):
            if mode == "إضافة صنف جديد":
                st.write("الكود يبدأ بـ -P تلقائياً")
                c1, c2 = st.columns([1, 5])
                c1.markdown("### P-")
                sku_suffix = c2.text_input("تكملة الكود (مثال: 501)")
                final_sku = f"P-{sku_suffix}"
                final_name = st.text_input("اسم المنتج الجديد")
            else:
                final_sku = st.selectbox("اختر الصنف", all_skus)
                final_name = "" # لا يحتاج اسم عند التحديث

            qty = st.number_input("الكمية", min_value=0.0)
            price = st.number_input("السعر", min_value=0.0)
            
            if st.form_submit_button("تنفيذ الحفظ"):
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                if mode == "إضافة صنف جديد":
                    if not sku_suffix or not final_name:
                        st.warning("يرجى تعبئة الكود والاسم")
                    elif final_sku in all_skus:
                        st.error(f"الكود {final_sku} موجود مسبقاً! استخدم خيار التحديث.")
                    elif final_name in all_names:
                        st.error(f"الاسم '{final_name}' موجود مسبقاً! لا يمكن تكرار الأسماء.")
                    else:
                        if execute_query("INSERT INTO items VALUES (NULL,?,?,?,5,?,?)", (final_name, final_sku, qty, price, now)):
                            execute_query("INSERT INTO transactions VALUES (NULL, ?,'IN',?,?, 'إضافة جديد', ?)", (final_sku, qty, st.session_state.username, now))
                            st.success("تمت الإضافة بنجاح")
                            st.rerun()
                else:
                    if execute_query("UPDATE items SET quantity=quantity+?, price=?, last_updated=? WHERE sku=?", (qty, price, now, final_sku)):
                        execute_query("INSERT INTO transactions VALUES (NULL, ?,'IN',?,?, 'تحديث كمية', ?)", (final_sku, qty, st.session_state.username, now))
                        st.success("تم تحديث البيانات")
                        st.rerun()

    # --- عرض المخزون ---
    elif choice == "📦 عرض المخزون":
        search = st.text_input("بحث")
        d, _ = fetch_query("SELECT name, sku, quantity, price FROM items WHERE name LIKE ? OR sku LIKE ?", (f'%{search}%', f'%{search}%'))
        st.table(pd.DataFrame(d, columns=['الاسم', 'الكود', 'الكمية', 'السعر']))
        if st.session_state.role == "مدير" and d:
            s_del = st.selectbox("حذف صنف نهائياً", [x[1] for x in d])
            if st.button("تأكيد الحذف"):
                execute_query("DELETE FROM items WHERE sku=?", (s_del,))
                st.rerun()

    # --- سجل العمليات ---
    elif choice == "📜 سجل العمليات":
        l, _ = fetch_query("SELECT timestamp, sku, type, quantity_change, user, reason FROM transactions ORDER BY timestamp DESC")
        st.table(pd.DataFrame(l, columns=['الوقت', 'الكود', 'العملية', 'الكمية', 'المستخدم', 'السبب']))

if __name__ == "__main__":
    main()
