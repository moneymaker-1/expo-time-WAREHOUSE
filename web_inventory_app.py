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
    cursor.execute('''CREATE TABLE IF NOT EXISTS items 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, sku TEXT UNIQUE, quantity REAL, 
        min_stock REAL DEFAULT 5, price REAL, supplier_name TEXT DEFAULT 'غير محدد', last_updated TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, ref_code TEXT, sku TEXT, type TEXT, 
        quantity_change REAL, user TEXT, reason TEXT, timestamp TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS bom_recipes 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, parent_sku TEXT, component_sku TEXT, qty_needed REAL, 
        UNIQUE(parent_sku, component_sku))''')
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
        if "UNIQUE" in str(e):
            st.error("⚠️ هذا الاسم أو الكود موجود مسبقاً!")
        else:
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
    st.set_page_config(page_title="اكسبو تايم - نظام المخزون المتكامل", layout="wide")

    if 'logged_in' not in st.session_state: st.session_state.logged_in = False

    if not st.session_state.logged_in:
        st.title("🏆 شركة اكسبو تايم - الدخول")
        t1, t2 = st.tabs(["🔐 دخول", "📝 تسجيل موظف"])
        with t1:
            u = st.text_input("اسم المستخدم")
            p = st.text_input("كلمة المرور", type="password")
            if st.button("دخول للنظام"):
                hp = hashlib.sha256(p.encode()).hexdigest()
                res, _ = fetch_query("SELECT role FROM users WHERE username=? AND password=?", (u, hp))
                if res:
                    st.session_state.logged_in, st.session_state.username, st.session_state.role = True, u, res[0][0]
                    st.rerun()
        with t2:
            nu = st.text_input("اسم مستخدم جديد")
            np = st.text_input("كلمة مرور جديدة", type="password")
            if st.button("إنشاء حساب"):
                cnt, _ = fetch_query("SELECT COUNT(*) FROM users WHERE role='موظف'")
                if cnt[0][0] >= 10: st.error("الحد الأقصى 10 موظفين")
                else:
                    hp = hashlib.sha256(np.encode()).hexdigest()
                    execute_query("INSERT INTO users VALUES (?,?,'موظف')", (nu, hp))
                    st.success("تم التسجيل بنجاح")
        return

    # محرك التنبيهات الجانبي
    low_stock_data, _ = fetch_query("SELECT name, quantity, min_stock FROM items WHERE quantity <= min_stock")
    if low_stock_data:
        st.sidebar.warning(f"🚨 تنبيه: يوجد {len(low_stock_data)} أصناف تحت الحد الأدنى!")

    st.sidebar.title(f"مرحباً {st.session_state.username}")
    menu = ["📦 المخزون الحالي", "➕ إضافة منتج جديد", "🚨 تنبيهات النواقص", "📤 صرف مدمج (DO)", "⚙️ تعريف BOM", "📜 سجل العمليات"]
    if st.session_state.role != "مدير":
        pass # هنا يمكن تقييد خيارات إضافية للمدير فقط لاحقاً
    
    choice = st.sidebar.selectbox("القائمة", menu)
    if st.sidebar.button("تسجيل الخروج"):
        st.session_state.logged_in = False; st.rerun()

    items_raw, _ = fetch_query("SELECT sku, name, quantity, price FROM items")
    all_options = [f"{x[0]} | {x[1]}" for x in items_raw]

    # --- 1. المخزون الحالي ---
    if choice == "📦 المخزون الحالي":
        st.subheader("عرض المخزون")
        if items_raw:
            df = pd.DataFrame(items_raw, columns=['SKU', 'الاسم', 'الكمية', 'السعر'])
            st.dataframe(df.style.apply(lambda x: ['background-color: #ffcccc' if i < 5 else '' for i in x], axis=1), use_container_width=True)
            
            if st.session_state.role == "مدير":
                st.divider()
                st.write("🔧 أدوات التعديل والحذف (مدير)")
                to_mod = st.selectbox("اختر الصنف للتعديل/الحذف", [""] + [x[0] for x in items_raw])
                if to_mod:
                    new_p = st.number_input("تحديث السعر")
                    if st.button("تحديث السعر"):
                        execute_query("UPDATE items SET price=? WHERE sku=?", (new_p, to_mod))
                        st.rerun()
                    if st.button("❌ حذف المنتج نهائياً"):
                        execute_query("DELETE FROM items WHERE sku=?", (to_mod,))
                        st.rerun()
        else: st.info("المخزن فارغ")

    # --- 2. إضافة منتج جديد ---
    elif choice == "➕ إضافة منتج جديد":
        st.subheader("إدخال صنف جديد")
        res, _ = fetch_query("SELECT MAX(id) FROM items")
        next_sku = f"P-{res[0][0]+1 if res[0][0] else 1001}"
        with st.form("add_p"):
            st.info(f"الكود التلقائي: {next_sku}")
            name = st.text_input("اسم المنتج")
            qty = st.number_input("الكمية الأولية", min_value=0.0)
            m_stock = st.number_input("حد التنبيه (أقل كمية مسموحة)", value=5.0)
            price = st.number_input("السعر")
            if st.form_submit_button("حفظ المنتج"):
                now = datetime.now().strftime("%Y-%m-%d %H:%M")
                if execute_query("INSERT INTO items (name, sku, quantity, min_stock, price, last_updated) VALUES (?,?,?,?,?,?)", (name, next_sku, qty, m_stock, price, now)):
                    execute_query("INSERT INTO transactions VALUES (NULL, 'NEW', ?, 'IN', ?, ?, 'إضافة صنف', ?)", (next_sku, qty, st.session_state.username, now))
                    st.success("تم الحفظ"); st.rerun()

    # --- 3. تنبيهات النواقص ---
    elif choice == "🚨 تنبيهات النواقص":
        st.subheader("الأصناف التي قاربت على النفاد")
        if low_stock_data:
            st.table(pd.DataFrame(low_stock_data, columns=['اسم المنتج', 'الكمية المتوفرة', 'الحد الأدنى']))
        else: st.success("لا توجد نواقص حالياً")

    # --- 4. صرف مدمج (سلة صرف) ---
    elif choice == "📤 صرف مدمج (DO)":
        st.subheader("إصدار سند صرف (Delivery Order)")
        if 'basket' not in st.session_state: st.session_state.basket = []
        c1, c2 = st.columns([3,1])
        sel = c1.selectbox("اختر الصنف", [""] + all_options)
        q_sel = c2.number_input("الكمية", min_value=1.0)
        if st.button("➕ أضف للسلة"):
            if sel: st.session_state.basket.append({"sku": sel.split(" | ")[0], "qty": q_sel})
        
        if st.session_state.basket:
            st.write("محتويات السند الحالي:")
            st.table(pd.DataFrame(st.session_state.basket))
            if st.button("🚀 تنفيذ الصرف الجماعي"):
                now = datetime.now()
                do_ref = f"DO-{now.strftime('%y%m%d%H%M')}"
                for item in st.session_state.basket:
                    sku, q = item['sku'], item['qty']
                    # فحص BOM تلقائي
                    comps, _ = fetch_query("SELECT component_sku, qty_needed FROM bom_recipes WHERE parent_sku=?", (sku,))
                    if comps:
                        for c_sku, c_qty in comps:
                            total = c_qty * q
                            execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (total, c_sku))
                            execute_query("INSERT INTO transactions VALUES (NULL, ?, ?, 'OUT', ?, ?, 'BOM الصرف', ?)", (do_ref, c_sku, total, st.session_state.username, now.strftime("%Y-%m-%d %H:%M")))
                    else:
                        execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (q, sku))
                        execute_query("INSERT INTO transactions VALUES (NULL, ?, ?, 'OUT', ?, ?, 'صرف مباشر', ?)", (do_ref, sku, q, st.session_state.username, now.strftime("%Y-%m-%d %H:%M")))
                st.success(f"تم تنفيذ السند: {do_ref}"); st.session_state.basket = []; st.rerun()

    # --- 5. تعريف BOM ---
    elif choice == "⚙️ تعريف BOM":
        st.subheader("قائمة مواد التصنيع")
        with st.form("bom_f"):
            p = st.selectbox("المنتج المجمع", all_options).split(" | ")[0]
            c = st.selectbox("المكون المادي", all_options).split(" | ")[0]
            qn = st.number_input("الكمية المطلوبة من المكون", min_value=0.01)
            if st.form_submit_button("ربط المكون"):
                execute_query("INSERT OR REPLACE INTO bom_recipes (parent_sku, component_sku, qty_needed) VALUES (?,?,?)", (p, c, qn))
                st.success("تم الربط")

    # --- 6. سجل العمليات ---
    elif choice == "📜 سجل العمليات":
        st.subheader("سجل الرقابة")
        l, _ = fetch_query("SELECT timestamp, ref_code, sku, type, quantity_change, user FROM transactions ORDER BY id DESC")
        st.table(pd.DataFrame(l, columns=['الوقت', 'السند', 'الكود', 'النوع', 'الكمية', 'المستخدم']))

if __name__ == "__main__":
    main()
