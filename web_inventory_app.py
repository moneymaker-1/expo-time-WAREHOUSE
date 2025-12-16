import streamlit as st
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
from fpdf import FPDF
import io

# -------------------------------------------------------------
# 🔒 إعداد قاعدة البيانات
# -------------------------------------------------------------
DATABASE_NAME = 'inventory_control.db'

def initialize_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT, sku TEXT UNIQUE, quantity REAL, min_stock REAL DEFAULT 5, price REAL, last_updated TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS purchase_orders (id INTEGER PRIMARY KEY, order_ref TEXT, sku TEXT, quantity REAL, created_at TEXT, required_at TEXT)')
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

# -------------------------------------------------------------
# 📄 دالة إنشاء ملف PDF وحفظه في الذاكرة (Memory)
# -------------------------------------------------------------
def create_pdf_bytes(order_ref, items_list, creation_date):
    pdf = FPDF()
    pdf.add_page()
    
    # عنوان الطلب
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="EXPO TIME - PURCHASE ORDER", ln=True, align='C')
    pdf.ln(10)
    
    # معلومات الطلب
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Order Reference: {order_ref}", ln=True)
    pdf.cell(200, 10, txt=f"Creation Date: {creation_date}", ln=True)
    pdf.ln(5)
    
    # رأس الجدول
    pdf.set_fill_color(230, 230, 230)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(60, 10, "SKU", 1, 0, 'C', True)
    pdf.cell(40, 10, "Quantity", 1, 0, 'C', True)
    pdf.cell(85, 10, "Required Delivery Date", 1, 1, 'C', True)
    
    # بيانات الأصناف
    pdf.set_font("Arial", size=11)
    for item in items_list:
        pdf.cell(60, 10, str(item[0]), 1)
        pdf.cell(40, 10, str(item[1]), 1)
        pdf.cell(85, 10, str(item[2]), 1)
        pdf.ln()
    
    # إخراج الملف كمصفوفة بايتات بدلاً من حفظه على القرص
    return pdf.output(dest='S').encode('latin-1')

# -------------------------------------------------------------
# 🌐 واجهة المستخدم
# -------------------------------------------------------------
def main_streamlit_app():
    initialize_db()
    st.set_page_config(page_title="شركة اكسبو تايم", layout="wide")
    st.title("🏆 نظام المشتريات والتحكم - شركة اكسبو تايم 🏆")

    # تهيئة عدد الأسطر في حالة الجلسة
    if 'po_rows' not in st.session_state: st.session_state.po_rows = 1

    menu = ["📦 إنشاء طلب شراء (PDF)", "🔍 عرض المخزون", "➕ إدخال صنف"]
    choice = st.sidebar.selectbox("القائمة الرئيسية", menu)

    if choice == "📦 إنشاء طلب شراء (PDF)":
        st.subheader("إصدار طلب شراء وتنزيله كملف PDF")
        
        now = datetime.now()
        min_delivery = now + timedelta(hours=3) # شرط الـ 3 ساعات
        order_ref = f"EXPO-{now.strftime('%y%m%d%H%M')}"

        st.info(f"📅 تاريخ الإنشاء الحالي: {now.strftime('%Y-%m-%d %H:%M')}")
        
        col_ctrl = st.columns(5)
        if col_ctrl[0].button("➕ أضف صنف"):
            st.session_state.po_rows += 1
        if col_ctrl[1].button("➖ حذف سطر") and st.session_state.po_rows > 1:
            st.session_state.po_rows -= 1
        
        items_to_order = []
        for i in range(st.session_state.po_rows):
            col1, col2, col3 = st.columns([2, 1, 2])
            sku = col1.text_input(f"كود الصنف {i+1}", key=f"s_{i}").upper()
            qty = col2.number_input(f"الكمية {i+1}", min_value=1.0, key=f"q_{i}")
            delivery = col3.datetime_input(f"وقت التوريد المطلوب {i+1}", value=min_delivery, min_value=min_delivery, key=f"d_{i}")
            if sku:
                items_to_order.append((sku, qty, delivery.strftime("%Y-%m-%d %H:%M")))

        if st.button("🚀 اعتماد وتجهيز ملف PDF"):
            if items_to_order:
                creation_time = now.strftime("%Y-%m-%d %H:%M:%S")
                
                # إنشاء محتوى الـ PDF
                pdf_data = create_pdf_bytes(order_ref, items_to_order, creation_time)
                
                # حفظ البيانات في قاعدة البيانات كمرجع
                for s, q, t in items_to_order:
                    execute_query("INSERT INTO purchase_orders VALUES (NULL, ?,?,?,?,?)", (order_ref, s, q, creation_time, t))
                
                st.success(f"✅ تم اعتماد الطلب رقم {order_ref}. يمكنك الآن تنزيله بالضغط على الزر أدناه.")
                
                # زر التنزيل (يظهر فقط بعد الاعتماد)
                st.download_button(
                    label="📥 تنزيل طلب المشتريات (PDF)",
                    data=pdf_data,
                    file_name=f"Purchase_Order_{order_ref}.pdf",
                    mime="application/pdf"
                )
            else:
                st.warning("يرجى إضافة أكواد الأصناف أولاً")

    elif choice == "🔍 عرض المخزون":
        # عرض المخزون والبحث (اختياري)
        st.write("وظيفة عرض المخزون")

if __name__ == '__main__':
    main_streamlit_app()
