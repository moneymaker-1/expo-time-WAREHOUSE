import streamlit as st
import sqlite3
from datetime import datetime
import pandas as pd
import os
from twilio.rest import Client
from dotenv import load_dotenv

# -------------------------------------------------------------
# 📞 تحميل الإعدادات من ملف .env
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
        st.error(f"❌ خطأ في قاعدة البيانات: {e}")
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
# 🌐 واجهة المستخدم الرئيسية (بدون أوامر rerun)
# -------------------------------------------------------------
def main_streamlit_app():
    initialize_db()
    st.set_page_config(page_title="شركة اكسبو تايم", layout="wide")
    st.title("🏆 شركة اكسبو تايم لادارة المخزون 🏆")

    # تهيئة عدد خانات المكونات في حالة الجلسة
    if 'num_rows' not in st.session_state:
        st.session_state.num_rows = 1

    menu = ["🔍 عرض المخزون", "➕ إدخال صنف", "⚙️ تعريف BOM", "🏭 صرف منتج مجمع", "📜 سجل الحركات"]
    choice = st.sidebar.selectbox("القائمة الرئيسية", menu)

    st.markdown("---")

    if choice == "🔍 عرض المخزون":
        search = st.text_input("ابحث عن صنف (الاسم أو الكود):")
        data, cols = fetch_query("SELECT id, name, sku, quantity, min_stock, price, supplier_phone FROM items WHERE name LIKE ? OR sku LIKE ?", (f'%{search}%', f'%{search}%'))
        if data:
            st.dataframe(pd.DataFrame(data, columns=cols), use_container_width=True)

    elif choice == "➕ إدخال صنف":
        with st.form("add_form"):
            name = st.text_input("اسم الصنف")
            sku = st.text_input("الكود (P-...)").upper()
            qty = st.number_input("الكمية المضافة", min_value=1)
            price = st.number_input("سعر الوحدة")
            sup = st.text_input("اسم المورد")
            phone = st.text_input("رقم المورد")
            user = st.text_input("اسم المستخدم المسؤول")
            if st.form_submit_button("حفظ البيانات"):
                if sku.startswith("P-"):
                    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    item_data, _ = fetch_query("SELECT quantity FROM items WHERE sku=?", (sku,))
                    if item_data:
                        new_qty = item_data[0][0] + qty
                        execute_query('UPDATE items SET quantity=?, price=?, supplier_name=?, supplier_phone=?, last_updated=? WHERE sku=?', (new_qty, price, sup, phone, current_time, sku))
                    else:
                        execute_query('INSERT INTO items (name, sku, quantity, price, supplier_name, supplier_phone, last_updated) VALUES (?,?,?,?,?,?,?)', (name, sku, qty, price, sup, phone, current_time))
                    
                    execute_query('INSERT INTO transactions (sku, type, quantity_change, user, reason, timestamp) VALUES (?,?,?,?,?,?)', (sku, 'IN', qty, user, 'إدخال مخزون', current_time))
                    st.success("✅ تم حفظ البيانات وتحديث المخزون بنجاح")
                else:
                    st.error("⚠️ خطأ: يجب أن يبدأ الكود بالبادئة P-")

    elif choice == "⚙️ تعريف BOM":
        st.subheader("⚙️ تعريف المنتجات المجمعة (قائمة المواد)")
        name_bom = st.text_input("اسم المنتج النهائي (مثلاً: جدار خشب 2.44م):")
        
        # أزرار للتحكم في عدد الخانات (تعمل تلقائياً في Streamlit بدون rerun)
        col_btns = st.columns([1, 1, 5])
        if col_btns[0].button("➕ إضافة"):
            st.session_state.num_rows += 1
        if col_btns[1].button("➖ تقليل") and st.session_state.num_rows > 1:
            st.session_state.num_rows -= 1

        bom_data_list = []
        for i in range(st.session_state.num_rows):
            c1, c2 = st.columns(2)
            sku_val = c1.text_input(f"كود المادة الخام {i+1}", key=f"sku_bom_{i}")
            qty_val = c2.number_input(f"الكمية المطلوبة {i+1}", min_value=0.0, format="%.2f", key=f"qty_bom_{i}")
            if sku_val:
                bom_data_list.append((sku_val, qty_val))

        if st.button("💾 حفظ وصفة المنتج المجمع"):
            if name_bom and bom_data_list:
                execute_query("DELETE FROM bom_recipes WHERE assembled_product_name=?", (name_bom,))
                for s, q in bom_data_list:
                    if q > 0:
                        execute_query("INSERT INTO bom_recipes (assembled_product_name, raw_material_sku, required_quantity) VALUES (?,?,?)", (name_bom, s, q))
                st.success(f"✅ تم حفظ وصفة المنتج المجمع '{name_bom}' بنجاح")
            else:
                st.error("يرجى التأكد من إدخال اسم المنتج وأكواد المواد الخام المطلوبة")

    elif choice == "🏭 صرف منتج مجمع":
        bom_list, _ = fetch_query("SELECT DISTINCT assembled_product_name FROM bom_recipes")
        if bom_list:
            selected = st.selectbox("اختر المنتج المراد إنتاجه", [b[0] for b in bom_list])
            qty_produce = st.number_input("العدد المطلوب إنتاجه", min_value=1)
            user_op = st.text_input("المسؤول عن العملية")
            if st.button("🚀 تنفيذ الخصم التلقائي للمخزون"):
                recipe, _ = fetch_query("SELECT raw_material_sku, required_quantity FROM bom_recipes WHERE assembled_product_name=?", (selected,))
                curr_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for r_sku, r_qty in recipe:
                    total_needed = r_qty * qty_produce
                    execute_query("UPDATE items SET quantity = quantity - ? WHERE sku = ?", (total_needed, r_sku))
                    execute_query('INSERT INTO transactions (sku, type, quantity_change, user, reason, timestamp) VALUES (?,?,?,?,?,?)', (r_sku, 'OUT_BOM', total_needed, user_op, f'إنتاج {selected}', curr_time))
                st.success(f"✅ تم بنجاح خصم كافة المواد الخام اللازمة لإنتاج {qty_produce} وحدة")
        else:
            st.warning("⚠️ لا توجد منتجات مجمعة مسجلة حالياً. يرجى استخدام 'تعريف BOM' أولاً.")

    elif choice == "📜 سجل الحركات":
        st.subheader("📜 سجل تدقيق حركات المخزون")
        data, cols = fetch_query("SELECT timestamp, sku, type, quantity_change, user, reason FROM transactions ORDER BY timestamp DESC")
        if data:
            st.table(pd.DataFrame(data, columns=cols))

if __name__ == '__main__':
    main_streamlit_app()
