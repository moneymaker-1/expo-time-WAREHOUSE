import streamlit as st
import sqlite3
from datetime import datetime
import pandas as pd
from fpdf import FPDF
import hashlib
import google.generativeai as genai # مكتبة جوجل للذكاء الاصطناعي
from PIL import Image

# -------------------------------------------------------------
# 1. إعداد قاعدة البيانات ونظام العهدة
# -------------------------------------------------------------
DATABASE_NAME = 'inventory_control.db'

def initialize_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    # جداول المخزون المعتمدة
    cursor.execute('''CREATE TABLE IF NOT EXISTS items 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, sku TEXT UNIQUE, quantity INTEGER, 
        unit TEXT, min_stock INTEGER DEFAULT 5, price REAL, supplier_name TEXT DEFAULT 'غير محدد', last_updated TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, ref_code TEXT, sku TEXT, type TEXT, 
        quantity_change INTEGER, user TEXT, reason TEXT, timestamp TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS bom_recipes 
        (id INTEGER PRIMARY KEY AUTOINCREMENT, assembled_product_name TEXT, raw_material_sku TEXT, required_quantity INTEGER, 
        UNIQUE(assembled_product_name, raw_material_sku))''')
    cursor.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, role TEXT)')
    
    # جداول العهدة
    cursor.execute('CREATE TABLE IF NOT EXISTS custody_balance (username TEXT PRIMARY KEY, current_balance REAL DEFAULT 0)')
    cursor.execute('CREATE TABLE IF NOT EXISTS custody_deposits (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, amount REAL, receipt_img TEXT, timestamp TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS custody_expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, amount REAL, category TEXT, invoice_date TEXT, timestamp TEXT)')

    conn.commit()
    conn.close()

def fetch_query(query, params=()):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        data = cursor.fetchall()
        return data, [d[0] for d in cursor.description]
    except: return [], []
    finally: conn.close()

def execute_query(query, params=()):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        conn.commit()
        return True
    except sqlite3.Error as e:
        st.error(f"⚠️ خطأ: {e}")
        return False
    finally: conn.close()

# -------------------------------------------------------------
# 2. وظيفة الذكاء الاصطناعي لقراءة الفواتير (OCR & Vision)
# -------------------------------------------------------------
def analyze_invoice_with_gemini(api_key, image_file):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash') # موديل الرؤية السريع
        img = Image.open(image_file)
        
        prompt = """
        اقرأ هذه الفاتورة واستخرج البيانات التالية بدقة باللغة العربية بتنسيق JSON فقط:
        {
          "amount": (المبلغ الإجمالي كرققم فقط),
          "date": (تاريخ الفاتورة بتنسيق YYYY-MM-DD),
          "category": (اختر صنف واحد فقط من هذه القائمة: "خشب", "كهرباء", "أدوات", "نقل", "أخرى")
        }
        """
        response = model.generate_content([prompt, img])
        return response.text
    except Exception as e:
        return f"خطأ في التحليل: {e}"

# -------------------------------------------------------------
# 3. التطبيق الرئيسي
# -------------------------------------------------------------
def main():
    initialize_db()
    st.set_page_config(page_title="اكسبو تايم - نظام العهد الذكي", layout="wide")

    # إعداد مفتاح API في الشريط الجانبي
    with st.sidebar:
        st.title("⚙️ إعدادات الذكاء الاصطناعي")
        api_key = st.text_input("أدخل Gemini API Key", type="password")
        if not api_key:
            st.warning("يرجى إدخال مفتاح API لتفعيل ميزة قراءة الفواتير")

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

    # عداد العهدة
    res_bal, _ = fetch_query("SELECT current_balance FROM custody_balance WHERE username=?", (st.session_state.username,))
    balance = res_bal[0][0] if res_bal else 0.0
    st.sidebar.metric("💰 رصيد العهدة (العداد)", f"{balance:,.2f} ريال")

    menu = ["🔍 عرض المخزون", "➕ إضافة صنف", "⚙️ تعريف BOM", "📤 صرف مجمع", "🏭 صرف BOM", "💸 طلب وإغلاق العهدة (AI)", "👥 إدارة المستخدمين"]
    choice = st.sidebar.selectbox("القائمة", menu)

    # --- قسم العهدة الذكي (AI) ---
    if choice == "💸 طلب وإغلاق العهدة (AI)":
        st.subheader("إدارة العهدة باستخدام الذكاء الاصطناعي")
        t1, t2 = st.tabs(["📥 رفع إيصال تحويل", "🧾 إغلاق عهدة (قراءة آلية)"])

        with t1:
            with st.form("dep_form"):
                amount = st.number_input("مبلغ التحويل المستلم", min_value=0.0)
                file = st.file_uploader("ارفع صورة التحويل البنكي")
                if st.form_submit_button("تحديث العداد"):
                    if file:
                        execute_query("INSERT OR IGNORE INTO custody_balance VALUES (?, 0)", (st.session_state.username,))
                        execute_query("UPDATE custody_balance SET current_balance = current_balance + ? WHERE username=?", (amount, st.session_state.username))
                        st.success("✅ تم تحديث العداد بناءً على التحويل")
                        st.rerun()

        with t2:
            st.info("ارفع صورة الفاتورة (خشب أو كهرباء) وسيقوم الذكاء الاصطناعي بقراءة المبلغ والتصنيف تلقائياً")
            invoice_file = st.file_uploader("ارفع الفاتورة هنا", type=['jpg', 'jpeg', 'png'])
            
            if invoice_file and api_key:
                if st.button("🔍 قراءة الفاتورة بالذكاء الاصطناعي"):
                    with st.spinner("جاري تحليل الفاتورة..."):
                        result = analyze_invoice_with_gemini(api_key, invoice_file)
                        st.code(result, language='json')
                        st.warning("يرجى التأكد من البيانات أعلاه ثم الضغط على تأكيد الخصم")
                        # ملاحظة: في النسخة الاحترافية يتم تحويل النص المستخرج لبيانات تلقائية
                        # سأقوم بوضع خانات تأكيد لضمان الدقة
                        
            with st.form("confirm_expense"):
                st.write("### تأكيد بيانات المصروف")
                final_amt = st.number_input("المبلغ المقروء", min_value=0.0)
                final_cat = st.selectbox("تصنيف الفاتورة", ["خشب", "كهرباء", "أدوات", "نقل", "أخرى"])
                final_date = st.date_input("تاريخ الفاتورة")
                
                if st.form_submit_button("✅ خصم من العهدة وإغلاق"):
                    if balance >= final_amt:
                        execute_query("UPDATE custody_balance SET current_balance = current_balance - ? WHERE username=?", (final_amt, st.session_state.username))
                        execute_query("INSERT INTO custody_expenses (username, amount, category, invoice_date, timestamp) VALUES (?,?,?,?,?)", 
                                     (st.session_state.username, final_amt, final_cat, str(final_date), datetime.now().strftime("%Y-%m-%d %H:%M")))
                        st.success(f"تم خصم {final_amt} ريال بنجاح")
                        st.rerun()
                    else:
                        st.error("❌ الرصيد في العداد لا يكفي!")

    # بقية خيارات المخزون كما هي في الكود المعتمد...
    elif choice == "🔍 عرض المخزون":
        data, _ = fetch_query("SELECT sku, name, quantity, unit, supplier_name FROM items")
        st.table(pd.DataFrame(data, columns=['SKU', 'الاسم', 'الكمية', 'الوحدة', 'المورد']))

if __name__ == "__main__":
    main()
