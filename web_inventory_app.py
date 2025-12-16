import streamlit as st
import sqlite3
from datetime import datetime
import pandas as pd
import os
from twilio.rest import Client
from dotenv import load_dotenv

# -------------------------------------------------------------
# 📞 تحميل الإعدادات السرية
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
# ⚙️ دالة إعادة التشغيل الذكية (تحل مشكلة AttributeError)
# -------------------------------------------------------------
def universal_rerun():
    """هذه الدالة تختار طريقة إعادة التشغيل المناسبة لإصدار Streamlit لديك"""
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

# -------------------------------------------------------------
# 🔒 إعداد قاعدة البيانات
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
            quantity INTEGER NOT NULL,
            min_stock INTEGER NOT NULL DEFAULT 5, 
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
            quantity_change INTEGER NOT NULL, 
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
        st.error(f"❌ خطأ: {e}")
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

def log_transaction(sku, type, quantity_change, user, reason=""):
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    query = 'INSERT INTO transactions (sku, type, quantity_change, user, reason, timestamp) VALUES (?, ?, ?, ?, ?, ?)'
    execute_query(query, (sku, type, quantity_change, user, reason, current_time))

# -------------------------------------------------------------
# 🌐 واجهة المستخدم
# -------------------------------------------------------------
def main_streamlit_app():
    initialize_db()
    st.set_page_config(page_title="شركة اكسبو تايم", layout="wide")
    st.title("🏆 شركة اكسبو تايم لادارة المخزون 🏆")

    if 'bom_components' not in st.session_state:
        st.session_state.bom_components = [{'raw_sku': '', 'qty': 0.0}]

    menu = ["🔍 عرض المخزون", "➕ إدخال صنف", "⚙️ تعريف BOM", "🏭 صرف منتج مجمع", "📜 سجل الحركات"]
    choice = st.sidebar.selectbox("القائمة الرئيسية", menu)

    if choice == "🔍 عرض المخزون":
        search = st.text_input("ابحث عن صنف (الاسم أو الكود):")
        data, cols = fetch_query("SELECT id, name, sku, quantity, min_stock, price, supplier_phone FROM items WHERE name LIKE ? OR sku LIKE ?", (f'%{search}%', f'%{search}%'))
        if data:
            df = pd.DataFrame(data, columns=cols)
            st.dataframe(df, use_container_width=True)

    elif choice == "➕ إدخال صنف":
        with st.form("add_form"):
            name = st.text_input("اسم الصنف")
            sku = st.text_input("الكود (P-...)").upper()
            qty = st.number_input("الكمية", min_value=1)
            price = st.number_input("السعر")
            sup = st.text_input("المورد")
            phone = st.text_input("رقم المورد")
            user = st.text_input("المستخدم")
            if st.form_submit_button("حفظ"):
                if sku.startswith("P-"):
                    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    item_data, _ = fetch_query("SELECT quantity FROM items WHERE sku=?", (sku,))
                    if item_data:
                        new_qty = item_data[0][0] + qty
                        execute_query('UPDATE items SET quantity=?, price=?, supplier_name=?, supplier_phone=?, last_updated=? WHERE sku=?', (new_qty, price, sup, phone, current_time, sku))
                    else:
                        execute_query('INSERT INTO items (name, sku, quantity, price, supplier_name, supplier_phone, last_updated) VALUES (?,?,?,?,?,?,?)', (name, sku, qty, price, sup, phone, current_time))
                    log_transaction(sku, 'IN', qty, user, 'إدخال مخزون')
                    st.success("✅ تم الحفظ")
                else:
                    st.error("⚠️ الكود يجب أن يبدأ بـ P-")

    elif choice == "⚙️ تعريف BOM":
        st.subheader("⚙️ تعريف المنتجات المجمعة")
        name_bom = st.text_input("اسم المنتج النهائي (مثل: جدار خشب):")
        
        for i, comp in enumerate(st.session_state.bom_components):
            c1, c2, c3 = st.columns([2, 1, 0.5])
            st.session_state.bom_components[i]['raw_sku'] = c1.text_input(f"كود الخام {i+1}", value=comp['raw_sku'], key=f"sku_{i}")
            st.session_state.bom_components[i]['qty'] = c2.number_input(f"الكمية {i+1}", value=float(comp['qty']), key=f"qty_{i}")
            if c3.button("🗑️", key=f"del_{i}"):
                st.session_state.bom_components.pop(i)
                universal_rerun() # استخدام الدالة الجديدة هنا
        
        if st.button("➕ إضافة مكون"):
            st.session_state.bom_components.append({'raw_sku': '', 'qty': 0.0})
            universal_rerun() # استخدام الدالة الجديدة هنا

        if st.button("💾 حفظ الوصفة"):
            if name_bom:
                execute_query("DELETE FROM bom_recipes WHERE assembled_product_name=?", (name_bom,))
                for c in st.session_state.bom_components:
                    if c['raw_sku'] and c['qty'] > 0:
                        execute_query("INSERT INTO bom_recipes (assembled_product_name, raw_material_sku, required_quantity) VALUES (?,?,?)", (name_bom, c['raw_sku'], c['qty']))
                st.success("✅ تم الحفظ")

    elif choice == "🏭 صرف منتج مجمع":
        bom_list, _ = fetch_query("SELECT DISTINCT assembled_product_name FROM bom_recipes")
        if bom_list:
            selected = st.selectbox("اختر المنتج", [b[0] for b in bom_list])
            qty_to_make = st.number_input("الكمية", min_value=1)
            user = st.text_input("المسؤول")
            if st.button("🚀 تنفيذ الصرف"):
                recipe, _ = fetch_query("SELECT raw_material_sku, required_quantity FROM bom_recipes WHERE assembled_product_name=?", (selected,))
                for r_sku, r_qty in recipe:
                    total_needed = r_qty * qty_to_make
                    execute_query("UPDATE items SET quantity = quantity - ? WHERE sku = ?", (total_needed, r_sku))
                    log_transaction(r_sku, 'OUT_BOM', total_needed, user, f'تصنيع {selected}')
                st.success("✅ تم التنفيذ")

    elif choice == "📜 سجل الحركات":
        data, cols = fetch_query("SELECT timestamp, sku, type, quantity_change, user, reason FROM transactions ORDER BY timestamp DESC")
        if data:
            st.table(pd.DataFrame(data, columns=cols))

if __name__ == '__main__':
    main_streamlit_app()
