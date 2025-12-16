import streamlit as st
import sqlite3
from datetime import datetime
import pandas as pd
import os
from twilio.rest import Client
from dotenv import load_dotenv

# -------------------------------------------------------------
# 📞 إعدادات التنبيهات والأمان
# -------------------------------------------------------------
load_dotenv()
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")
DESTINATION_WHATSAPP_NUMBER = os.getenv("DESTINATION_WHATSAPP_NUMBER")

try:
    if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        WHATSAPP_READY = True
    else:
        WHATSAPP_READY = False
except Exception:
    WHATSAPP_READY = False

# -------------------------------------------------------------
# 🔒 إدارة قاعدة البيانات
# -------------------------------------------------------------
DATABASE_NAME = 'inventory_control.db'

def initialize_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            sku TEXT UNIQUE NOT NULL, 
            quantity REAL NOT NULL,
            min_stock REAL NOT NULL DEFAULT 5, 
            price REAL NOT NULL,           
            supplier_name TEXT NOT NULL,
            supplier_phone TEXT,  
            last_updated TEXT NOT NULL
        )
    ''')
    try:
        cursor.execute("SELECT supplier_phone FROM items LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE items ADD COLUMN supplier_phone TEXT")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY,
            sku TEXT NOT NULL,                
            type TEXT NOT NULL,               
            quantity_change REAL NOT NULL, 
            user TEXT NOT NULL,               
            reason TEXT,                      
            timestamp TEXT NOT NULL           
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bom_recipes (
            id INTEGER PRIMARY KEY,
            assembled_product_name TEXT NOT NULL,
            raw_material_sku TEXT NOT NULL,
            required_quantity REAL NOT NULL,
            UNIQUE(assembled_product_name, raw_material_sku)
        )
    ''')
    conn.commit()
    conn.close()

def execute_query(query, params=()):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        conn.commit()
        return True
    except sqlite3.Error as e:
        st.error(f"❌ خطأ قاعدة البيانات: {e}")
        return False
    finally:
        conn.close()

def fetch_query(query, params=()):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        data = cursor.fetchall()
        columns = [description[0] for description in cursor.description]
        return data, columns
    except sqlite3.Error as e:
        return [], []
    finally:
        conn.close()

# -------------------------------------------------------------
# 🌐 واجهة المستخدم الاحترافية (القائمة الكاملة)
# -------------------------------------------------------------
def main_streamlit_app():
    initialize_db()
    st.set_page_config(page_title="شركة اكسبو تايم", layout="wide")
    st.title("🏆 شركة اكسبو تايم لادارة المخزون 🏆")

    if 'num_rows' not in st.session_state:
        st.session_state.num_rows = 1

    # القائمة الكاملة كما طلبت
    options = [
        "🔍 عرض المخزون والبحث",
        "➕ إدخال صنف/تحديث",
        "⚙️ تعريف المنتجات المجمعة (BOM)",
        "📤 تسجيل صرف مواد (مفرد)",
        "🏭 تسجيل صرف منتج مُجمَّع (BOM)",
        "🚨 تنبيهات نقص المخزون",
        "💵 تقرير القيمة الإجمالية",
        "📜 سجل التدقيق (Audit Log)"
    ]
    
    choice = st.sidebar.selectbox("اختر الإجراء:", options)
    st.markdown("---")

    # 1. عرض المخزون والبحث
    if choice == "🔍 عرض المخزون والبحث":
        search = st.text_input("ابحث بالاسم أو الكود (SKU):")
        query = "SELECT id, name, sku, quantity, min_stock, price, supplier_name, supplier_phone FROM items WHERE name LIKE ? OR sku LIKE ?"
        data, cols = fetch_query(query, (f'%{search}%', f'%{search}%'))
        if data:
            df = pd.DataFrame(data, columns=['ID', 'الاسم', 'SKU', 'الكمية', 'الحد الأدنى', 'السعر', 'المورد', 'رقم المورد'])
            st.dataframe(df.set_index('ID'), use_container_width=True)

    # 2. إدخال صنف/تحديث
    elif choice == "➕ إدخال صنف/تحديث":
        with st.form("add_item_form"):
            name = st.text_input("اسم الصنف")
            sku = st.text_input("الكود (يجب أن يبدأ بـ P-)").upper()
            price = st.number_input("سعر الوحدة", min_value=0.0)
            qty = st.number_input("الكمية المضافة", min_value=0.1)
            sup = st.text_input("اسم المورد")
            phone = st.text_input("رقم المورد")
            user = st.text_input("المستخدم")
            if st.form_submit_button("حفظ البيانات"):
                if sku.startswith("P-"):
                    curr_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    item_check, _ = fetch_query("SELECT quantity FROM items WHERE sku=?", (sku,))
                    if item_check:
                        new_qty = item_check[0][0] + qty
                        execute_query('UPDATE items SET quantity=?, price=?, supplier_name=?, supplier_phone=?, last_updated=? WHERE sku=?', (new_qty, price, sup, phone, curr_time, sku))
                    else:
                        execute_query('INSERT INTO items (name, sku, quantity, price, supplier_name, supplier_phone, last_updated) VALUES (?,?,?,?,?,?,?)', (name, sku, qty, price, sup, phone, curr_time))
                    execute_query('INSERT INTO transactions (sku, type, quantity_change, user, reason, timestamp) VALUES (?,?,?,?,?,?)', (sku, 'IN', qty, user, 'إدخال مخزون', curr_time))
                    st.success("✅ تم التحديث بنجاح")
                else:
                    st.error("⚠️ الكود يجب أن يبدأ بـ P-")

    # 3. تعريف BOM (الطريقة الممتازة التي أعجبتك)
    elif choice == "⚙️ تعريف المنتجات المجمعة (BOM)":
        st.subheader("⚙️ إعداد وصفات التجميع")
        name_bom = st.text_input("اسم المنتج النهائي (مثل: جدار خشب):")
        col_btns = st.columns([1, 1, 5])
        if col_btns[0].button("➕ إضافة"): st.session_state.num_rows += 1
        if col_btns[1].button("➖ تقليل") and st.session_state.num_rows > 1: st.session_state.num_rows -= 1
        
        bom_data = []
        for i in range(st.session_state.num_rows):
            c1, c2 = st.columns(2)
            sku_val = c1.text_input(f"كود الخام {i+1}", key=f"s_{i}")
            qty_val = c2.number_input(f"الكمية {i+1}", min_value=0.0, key=f"q_{i}")
            if sku_val: bom_data.append((sku_val, qty_val))

        if st.button("💾 حفظ الوصفة"):
            if name_bom and bom_data:
                execute_query("DELETE FROM bom_recipes WHERE assembled_product_name=?", (name_bom,))
                for s, q in bom_data:
                    execute_query("INSERT INTO bom_recipes (assembled_product_name, raw_material_sku, required_quantity) VALUES (?,?,?)", (name_bom, s, q))
                st.success("✅ تم حفظ الوصفة")

    # 4. تسجيل صرف مواد (مفرد)
    elif choice == "📤 تسجيل صرف مواد (مفرد)":
        with st.form("issue_single"):
            sku = st.text_input("كود الصنف المصروف (SKU)").upper()
            qty = st.number_input("الكمية المصروفة", min_value=0.1)
            user = st.text_input("المستخدم")
            reason = st.text_input("السبب")
            if st.form_submit_button("تسجيل الصرف"):
                curr_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                execute_query("UPDATE items SET quantity = quantity - ? WHERE sku = ?", (qty, sku))
                execute_query('INSERT INTO transactions (sku, type, quantity_change, user, reason, timestamp) VALUES (?,?,?,?,?,?)', (sku, 'OUT', qty, user, reason, curr_time))
                st.success("✅ تم صرف المادة بنجاح")

    # 5. تسجيل صرف منتج مُجمَّع (BOM)
    elif choice == "🏭 تسجيل صرف منتج مُجمَّع (BOM)":
        bom_list, _ = fetch_query("SELECT DISTINCT assembled_product_name FROM bom_recipes")
        selected = st.selectbox("اختر المنتج", [b[0] for b in bom_list])
        qty_produce = st.number_input("الكمية المراد إنتاجها", min_value=1)
        user = st.text_input("المسؤول")
        if st.button("🚀 تنفيذ الخصم التلقائي"):
            recipe, _ = fetch_query("SELECT raw_material_sku, required_quantity FROM bom_recipes WHERE assembled_product_name=?", (selected,))
            curr_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for r_sku, r_qty in recipe:
                total_needed = r_qty * qty_produce
                execute_query("UPDATE items SET quantity = quantity - ? WHERE sku = ?", (total_needed, r_sku))
                execute_query('INSERT INTO transactions (sku, type, quantity_change, user, reason, timestamp) VALUES (?,?,?,?,?,?)', (r_sku, 'OUT_BOM', total_needed, user, f'إنتاج {selected}', curr_time))
            st.success("✅ تم تنفيذ الخصم التلقائي")

    # 6. تنبيهات نقص المخزون
    elif choice == "🚨 تنبيهات نقص المخزون":
        data, _ = fetch_query("SELECT name, sku, quantity, min_stock FROM items WHERE quantity <= min_stock")
        if data:
            st.warning("⚠️ الأصناف التالية تحت الحد الأدنى:")
            st.table(pd.DataFrame(data, columns=['الاسم', 'SKU', 'الكمية الحالية', 'الحد الأدنى']))
        else:
            st.success("✅ المخزون سليم")

    # 7. تقرير القيمة الإجمالية
    elif choice == "💵 تقرير القيمة الإجمالية":
        data, _ = fetch_query("SELECT name, quantity, price FROM items")
        if data:
            df = pd.DataFrame(data, columns=['الاسم', 'الكمية', 'السعر'])
            df['الإجمالي'] = df['الكمية'] * df['السعر']
            st.metric("إجمالي قيمة المخزون", f"{df['الإجمالي'].sum():,.2f} ريال")
            st.dataframe(df, use_container_width=True)

    # 8. سجل التدقيق (Audit Log)
    elif choice == "📜 سجل التدقيق (Audit Log)":
        data, cols = fetch_query("SELECT timestamp, sku, type, quantity_change, user, reason FROM transactions ORDER BY timestamp DESC")
        if data:
            st.table(pd.DataFrame(data, columns=['التاريخ', 'SKU', 'النوع', 'الكمية', 'المستخدم', 'السبب']))

if __name__ == '__main__':
    main_streamlit_app()
