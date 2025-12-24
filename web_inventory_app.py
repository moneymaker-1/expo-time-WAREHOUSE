import streamlit as st
import sqlite3
from datetime import datetime
import pandas as pd
import hashlib

# -------------------------------------------------------------
# 1. إعداد قاعدة البيانات
# -------------------------------------------------------------
DATABASE_NAME = 'inventory_control.db'

def initialize_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS items 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, sku TEXT UNIQUE, quantity INTEGER, 
        unit TEXT, min_stock INTEGER DEFAULT 5, price REAL, supplier TEXT, last_updated TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, ref_code TEXT, sku TEXT, type TEXT, 
        quantity_change INTEGER, user TEXT, reason TEXT, timestamp TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
        (username TEXT PRIMARY KEY, password TEXT, role TEXT)''')
    conn.commit()
    conn.close()
    
    # إضافة المدير الافتراضي إذا لم يكن موجوداً
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
        st.title("🔐 دخول النظام")
        u, p = st.text_input("المستخدم"), st.text_input("كلمة المرور", type="password")
        if st.button("دخول"):
            hp = hashlib.sha256(p.encode()).hexdigest()
            res, _ = fetch_query("SELECT role FROM users WHERE username=? AND password=?", (u, hp))
            if res:
                st.session_state.logged_in, st.session_state.username, st.session_state.role = True, u, res[0][0]
                st.rerun()
        return

    st.sidebar.title(f"👤 {st.session_state.username}")
    menu = ["🔍 المخزون", "➕ إضافة صنف", "📤 صرف مجمع", "👥 إدارة المستخدمين", "📜 السجل"]
    
    # حماية القسم: الموظف العادي لا يرى خيار إدارة المستخدمين
    if st.session_state.role != "مدير":
        menu.remove("👥 إدارة المستخدمين")
        
    choice = st.sidebar.selectbox("القائمة", menu)

    # --- القسم المصحح: إدارة المستخدمين ---
    if choice == "👥 إدارة المستخدمين":
        st.subheader("🛠️ التحكم في طاقم العمل")
        
        # 1. عرض جدول المستخدمين الحاليين
        users_data, _ = fetch_query("SELECT username, role FROM users")
        st.table(pd.DataFrame(users_data, columns=['اسم المستخدم', 'الصلاحية']))

        col1, col2 = st.columns(2)
        
        # 2. إضافة مستخدم جديد
        with col1:
            st.write("### ➕ إضافة موظف جديد")
            with st.form("add_user_form"):
                new_u = st.text_input("اسم المستخدم الجديد")
                new_p = st.text_input("كلمة المرور", type="password")
                new_r = st.selectbox("الصلاحية", ["موظف", "مدير"])
                if st.form_submit_button("حفظ الحساب"):
                    if new_u and new_p:
                        hp = hashlib.sha256(new_p.encode()).hexdigest()
                        if execute_query("INSERT INTO users VALUES (?, ?, ?)", (new_u, hp, new_r)):
                            st.success(f"تم إنشاء حساب {new_u} بنجاح!")
                            st.rerun()
                    else:
                        st.warning("يرجى ملء جميع الحقول")

        # 3. حذف أو تعديل مستخدم
        with col2:
            st.write("### ❌ حذف / تعديل")
            target_user = st.selectbox("اختر المستخدم", [u[0] for u in users_data if u[0] != st.session_state.username])
            
            if st.button("حذف هذا المستخدم نهائياً"):
                if target_user:
                    execute_query("DELETE FROM users WHERE username=?", (target_user,))
                    st.error(f"تم حذف الحساب {target_user}")
                    st.rerun()
            
            st.divider()
            st.write("🔄 **تغيير كلمة المرور**")
            new_pass = st.text_input("كلمة مرور جديدة للمستخدم المختار", type="password")
            if st.button("تحديث كلمة المرور"):
                if target_user and new_pass:
                    hp = hashlib.sha256(new_pass.encode()).hexdigest()
                    execute_query("UPDATE users SET password=? WHERE username=?", (hp, target_user))
                    st.success("تم تحديث كلمة المرور")

    # بقية الأقسام (المخزون، الصرف، الإضافة) تظل تعمل كما هي في الكود المعتمد...
    elif choice == "🔍 المخزون":
        st.subheader("عرض بيانات المخزن")
        data, _ = fetch_query("SELECT sku, name, quantity, unit, price, supplier FROM items")
        st.dataframe(pd.DataFrame(data, columns=['SKU', 'الاسم', 'الكمية', 'الوحدة', 'السعر', 'المورد']), use_container_width=True)

if __name__ == "__main__":
    main()
