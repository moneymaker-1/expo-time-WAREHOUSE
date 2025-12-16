import streamlit as st
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
from fpdf import FPDF
import os

# -------------------------------------------------------------
# اعداد قاعدة البيانات
# -------------------------------------------------------------
DATABASE_NAME = 'inventory_control.db'

def initialize_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT, sku TEXT UNIQUE, quantity REAL, min_stock REAL DEFAULT 5, price REAL, supplier_name TEXT, supplier_phone TEXT, last_updated TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY, sku TEXT, type TEXT, quantity_change REAL, user TEXT, reason TEXT, timestamp TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS bom_recipes (id INTEGER PRIMARY KEY, assembled_product_name TEXT, raw_material_sku TEXT, required_quantity REAL, UNIQUE(assembled_product_name, raw_material_sku))')
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
        columns = [description[0] for description in cursor.description]
        return data, columns
    except sqlite3.Error as e: return [], []
    finally: conn.close()

# -------------------------------------------------------------
# دالة انشاء ملف PDF لطلب المشتريات
# -------------------------------------------------------------
def create_pdf_content(order_ref, items_list, creation_date):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="EXPO TIME - PURCHASE ORDER", ln=True, align='C')
    pdf.ln(10)
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Order Reference: {order_ref}", ln=True)
    pdf.cell(200, 10, txt=f"Creation Date: {creation_date}", ln=True)
    pdf.ln(5)
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(60, 10, "SKU", 1, 0, 'C', True)
    pdf.cell(40, 10, "Quantity", 1, 0, 'C', True)
    pdf.cell(85, 10, "Required Delivery Time", 1, 1, 'C', True)
    pdf.set_font("Arial", size=11)
    for item in items_list:
        pdf.cell(60, 10, str(item[0]), 1)
        pdf.cell(40, 10, str(item[1]), 1)
        pdf.cell(85, 10, str(item[2]), 1)
        pdf.ln()
    return pdf.output(dest='S').encode('latin-1')

# -------------------------------------------------------------
# الواجهة الرئيسية باللغة العربية
# -------------------------------------------------------------
def main_streamlit_app():
    initialize_db()
    st.set_page_config(page_title="شركة اكسبو تايم لادارة المخزون", layout="wide")
    st.title("نظام شركة اكسبو تايم لادارة المخزون والمشتريات")

    if 'po_rows' not in st.session_state: st.session_state.po_rows = 1
    if 'issue_rows' not in st.session_state: st.session_state.issue_rows = 1
    if 'bom_rows' not in st.session_state: st.session_state.bom_rows = 1

    options = [
        "1. عرض المخزون والبحث",
        "2. ادخال صنف او تحديث كمية",
        "3. تعريف المنتجات المجمعة BOM",
        "4. تسجيل صرف متعدد للاصناف",
        "5. تسجيل صرف منتج مجمع BOM",
        "6. انشاء طلب شراء PDF",
        "7. تنبيهات نقص المخزون",
        "8. تقرير القيمة الاجمالية",
        "9. سجل العمليات Audit Log"
    ]
    
    choice = st.sidebar.selectbox("القائمة الرئيسية:", options)
    st.markdown("---")

    # 1. عرض المخزون
    if choice == "1. عرض المخزون والبحث":
        search = st.text_input("ابحث عن صنف بالاسم او الكود:")
        data, cols = fetch_query("SELECT id, name, sku, quantity, min_stock, price FROM items WHERE name LIKE ? OR sku LIKE ?", (f'%{search}%', f'%{search}%'))
        if data: st.dataframe(pd.DataFrame(data, columns=['ID', 'الاسم', 'الكود SKU', 'الكمية', 'الحد الادنى', 'السعر']).set_index('ID'), use_container_width=True)

    # 2. ادخال/تحديث
    elif choice == "2. ادخال صنف او تحديث كمية":
        with st.form("add_f"):
            n = st.text_input("اسم الصنف")
            s = st.text_input("كود الصنف - يجب ان يبدأ بـ P-").upper()
            p = st.number_input("السعر")
            q = st.number_input("الكمية")
            user = st.text_input("اسم المستخدم")
            if st.form_submit_button("حفظ البيانات") and s.startswith("P-"):
                t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                check, _ = fetch_query("SELECT quantity FROM items WHERE sku=?", (s,))
                if check: execute_query("UPDATE items SET quantity=quantity+?, price=?, last_updated=? WHERE sku=?", (q, p, t, s))
                else: execute_query("INSERT INTO items (name, sku, quantity, price, last_updated, supplier_name) VALUES (?,?,?,?,?,?)", (n, s, q, p, t, "غير محدد"))
                execute_query("INSERT INTO transactions VALUES (NULL, ?, 'IN', ?, ?, 'توريد', ?)", (s, q, user, t))
                st.success("تم الحفظ وتحديث البيانات بنجاح")

    # 3. تعريف BOM
    elif choice == "3. تعريف المنتجات المجمعة BOM":
        st.subheader("اعداد وصفات تجميع المنتجات")
        name_bom = st.text_input("اسم المنتج النهائي:")
        c1, c2 = st.columns(2)
        if c1.button("اضافة مكون"): st.session_state.bom_rows += 1
        if c2.button("حذف مكون") and st.session_state.bom_rows > 1: st.session_state.bom_rows -= 1
        bom_l = []
        for i in range(st.session_state.bom_rows):
            cc1, cc2 = st.columns(2)
            ss, qq = cc1.text_input(f"كود المادة الخام {i+1}", key=f"bs_{i}"), cc2.number_input(f"الكمية المطلوبة {i+1}", key=f"bq_{i}")
            if ss: bom_l.append((ss, qq))
        if st.button("حفظ وصفة المنتج"):
            execute_query("DELETE FROM bom_recipes WHERE assembled_product_name=?", (name_bom,))
            for s, q in bom_l: execute_query("INSERT INTO bom_recipes VALUES (NULL,?,?,?)", (name_bom, s, q))
            st.success("تم حفظ وصفة المنتج بنجاح")

    # 4. صرف متعدد للاصناف
    elif choice == "4. تسجيل صرف متعدد للاصناف":
        u = st.text_input("المسؤول عن الصرف")
        if st.button("اضافة صنف للسلة"): st.session_state.issue_rows += 1
        iss_list = []
        for i in range(st.session_state.issue_rows):
            cc1, cc2 = st.columns(2); s = cc1.text_input(f"كود الصنف {i+1}", key=f"is_{i}").upper(); q = cc2.number_input(f"الكمية المصروفة {i+1}", key=f"iq_{i}")
            if s: iss_list.append((s, q))
        if st.button("تأكيد عملية الصرف"):
            t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for s, q in iss_list:
                execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (q, s))
                execute_query("INSERT INTO transactions VALUES (NULL, ?, 'OUT', ?, ?, 'صرف مباشر', ?)", (s, q, u, t))
            st.success("تمت عملية الخصم من المخزون بنجاح")

    # 5. صرف مجمع BOM
    elif choice == "5. تسجيل صرف منتج مجمع BOM":
        bom_list, _ = fetch_query("SELECT DISTINCT assembled_product_name FROM bom_recipes")
        sel = st.selectbox("اختر المنتج المراد تجميعه", [b[0] for b in bom_list] if bom_list else [""])
        qp, u = st.number_input("العدد المراد انتاجه", min_value=1), st.text_input("المسؤول")
        if st.button("تنفيذ الخصم التلقائي للمواد الخام"):
            recipe, _ = fetch_query("SELECT raw_material_sku, required_quantity FROM bom_recipes WHERE assembled_product_name=?", (sel,))
            t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for rs, rq in recipe:
                tot = rq * qp
                execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (tot, rs))
                execute_query("INSERT INTO transactions VALUES (NULL, ?, 'OUT_BOM', ?, ?, ?, ?)", (rs, tot, u, f"انتاج: {sel}", t))
            st.success("تم خصم كافة المكونات بناء على الوصفة")

    # 6. طلب مشتريات PDF
    elif choice == "6. انشاء طلب شراء PDF":
        st.subheader("اصدار طلب شراء جديد وتنزيله")
        now = datetime.now(); min_del = now + timedelta(hours=3); ref = f"PO-{now.strftime('%y%m%d%H%M')}"
        if st.button("اضافة صنف للطلب"): st.session_state.po_rows += 1
        po_l = []
        for i in range(st.session_state.po_rows):
            cc1, cc2, cc3 = st.columns([2, 1, 2])
            ss, qq = cc1.text_input(f"كود الصنف {i+1}", key=f"ps_{i}").upper(), cc2.number_input(f"الكمية {i+1}", key=f"pq_{i}")
            dd = cc3.datetime_input(f"تاريخ التوريد المطلوب {i+1}", value=min_del, min_value=min_del, key=f"pd_{i}")
            if ss: po_l.append((ss, qq, dd.strftime("%Y-%m-%d %H:%M")))
        if st.button("اعتماد الطلب وانشاء ملف PDF"):
            creation = now.strftime("%Y-%m-%d %H:%M:%S")
            pdf_b = create_pdf_content(ref, po_l, creation)
            st.success(f"تم اعتماد الطلب رقم {ref}")
            st.download_button("تنزيل ملف طلب الشراء (PDF)", pdf_b, f"Order_{ref}.pdf", "application/pdf")

    # 7. التنبيهات
    elif choice == "7. تنبيهات نقص المخزون":
        d, _ = fetch_query("SELECT name, sku, quantity, min_stock FROM items WHERE quantity <= min_stock")
        if d: st.table(pd.DataFrame(d, columns=['الاسم', 'الكود', 'الكمية الحالية', 'الحد الادنى']))
        else: st.success("جميع مستويات المخزون سليمة")

    # 8. تقرير القيمة المالية
    elif choice == "8. تقرير القيمة الاجمالية":
        d, _ = fetch_query("SELECT name, quantity, price FROM items")
        df = pd.DataFrame(d, columns=['الاسم', 'الكمية', 'السعر'])
        st.metric("قيمة المخزون الكلية في المستودع", f"{(df['الكمية'] * df['السعر']).sum():,.2f}")

    # 9. سجل العمليات
    elif choice == "9. سجل العمليات Audit Log":
        d, _ = fetch_query("SELECT timestamp, sku, type, quantity_change, user, reason FROM transactions ORDER BY timestamp DESC")
        st.table(pd.DataFrame(d, columns=['التاريخ', 'الكود SKU', 'النوع', 'الكمية', 'المستخدم', 'السبب']))

if __name__ == '__main__':
    main_streamlit_app()
