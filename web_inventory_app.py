import streamlit as st
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
from fpdf import FPDF
import os

# -------------------------------------------------------------
# إعداد قاعدة البيانات
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
        st.error(f"Error: {e}")
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
# دالة إنشاء ملف PDF
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
# الواجهة الرئيسية (القائمة كاملة بدون رموز تعبيرية)
# -------------------------------------------------------------
def main_streamlit_app():
    initialize_db()
    st.set_page_config(page_title="Expo Time Management", layout="wide")
    st.title("Expo Time Inventory Management System")

    if 'po_rows' not in st.session_state: st.session_state.po_rows = 1
    if 'issue_rows' not in st.session_state: st.session_state.issue_rows = 1
    if 'bom_rows' not in st.session_state: st.session_state.bom_rows = 1

    options = [
        "1. View Inventory and Search",
        "2. Add or Update Item",
        "3. Define Assembled Products (BOM)",
        "4. Register Multiple Item Issue",
        "5. Register Assembled Product Issue (BOM)",
        "6. Create Purchase Order PDF",
        "7. Low Stock Alerts",
        "8. Total Value Report",
        "9. Audit Log"
    ]
    
    choice = st.sidebar.selectbox("Main Menu:", options)
    st.markdown("---")

    # 1. عرض المخزون
    if choice == "1. View Inventory and Search":
        search = st.text_input("Search by Name or SKU:")
        data, cols = fetch_query("SELECT id, name, sku, quantity, min_stock, price FROM items WHERE name LIKE ? OR sku LIKE ?", (f'%{search}%', f'%{search}%'))
        if data: st.dataframe(pd.DataFrame(data, columns=['ID', 'Name', 'SKU', 'Quantity', 'Min Stock', 'Price']).set_index('ID'), use_container_width=True)

    # 2. إدخال/تحديث
    elif choice == "2. Add or Update Item":
        with st.form("add_f"):
            n, s, p, q, user = st.text_input("Name"), st.text_input("SKU (must start with P-)").upper(), st.number_input("Price"), st.number_input("Quantity"), st.text_input("User")
            if st.form_submit_button("Save") and s.startswith("P-"):
                t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                check, _ = fetch_query("SELECT quantity FROM items WHERE sku=?", (s,))
                if check: execute_query("UPDATE items SET quantity=quantity+?, price=?, last_updated=? WHERE sku=?", (q, p, t, s))
                else: execute_query("INSERT INTO items (name, sku, quantity, price, last_updated, supplier_name) VALUES (?,?,?,?,?,?)", (n, s, q, p, t, "N/A"))
                execute_query("INSERT INTO transactions VALUES (NULL, ?, 'IN', ?, ?, 'Restock', ?)", (s, q, user, t))
                st.success("Success: Data Updated")

    # 3. تعريف BOM
    elif choice == "3. Define Assembled Products (BOM)":
        name_bom = st.text_input("Assembled Product Name:")
        c1, c2 = st.columns(2)
        if c1.button("Add Row"): st.session_state.bom_rows += 1
        if c2.button("Remove Row") and st.session_state.bom_rows > 1: st.session_state.bom_rows -= 1
        bom_l = []
        for i in range(st.session_state.bom_rows):
            cc1, cc2 = st.columns(2)
            ss, qq = cc1.text_input(f"Raw Material SKU {i+1}", key=f"bs_{i}"), cc2.number_input(f"Quantity {i+1}", key=f"bq_{i}")
            if ss: bom_l.append((ss, qq))
        if st.button("Save BOM Recipe"):
            execute_query("DELETE FROM bom_recipes WHERE assembled_product_name=?", (name_bom,))
            for s, q in bom_l: execute_query("INSERT INTO bom_recipes VALUES (NULL,?,?,?)", (name_bom, s, q))
            st.success("BOM Recipe Saved")

    # 4. صرف متعدد
    elif choice == "4. Register Multiple Item Issue":
        u = st.text_input("Person in Charge")
        if st.button("Add to Cart"): st.session_state.issue_rows += 1
        iss_list = []
        for i in range(st.session_state.issue_rows):
            cc1, cc2 = st.columns(2); s = cc1.text_input(f"SKU {i+1}", key=f"is_{i}").upper(); q = cc2.number_input(f"Qty {i+1}", key=f"iq_{i}")
            if s: iss_list.append((s, q))
        if st.button("Confirm Issue"):
            t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for s, q in iss_list:
                execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (q, s))
                execute_query("INSERT INTO transactions VALUES (NULL, ?, 'OUT', ?, ?, 'Manual Issue', ?)", (s, q, u, t))
            st.success("Issue Completed Successfully")

    # 5. صرف مجمع BOM
    elif choice == "5. Register Assembled Product Issue (BOM)":
        bom_list, _ = fetch_query("SELECT DISTINCT assembled_product_name FROM bom_recipes")
        sel = st.selectbox("Select Product", [b[0] for b in bom_list] if bom_list else [""])
        qp, u = st.number_input("Quantity to Assemble", min_value=1), st.text_input("User")
        if st.button("Execute BOM Deduction"):
            recipe, _ = fetch_query("SELECT raw_material_sku, required_quantity FROM bom_recipes WHERE assembled_product_name=?", (sel,))
            t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for rs, rq in recipe:
                tot = rq * qp
                execute_query("UPDATE items SET quantity=quantity-? WHERE sku=?", (tot, rs))
                execute_query("INSERT INTO transactions VALUES (NULL, ?, 'OUT_BOM', ?, ?, ?, ?)", (rs, tot, u, f"Assembled: {sel}", t))
            st.success("Deduction Done")

    # 6. طلب مشتريات PDF
    elif choice == "6. Create Purchase Order PDF":
        now = datetime.now(); min_del = now + timedelta(hours=3); ref = f"PO-{now.strftime('%y%m%d%H%M')}"
        if st.button("Add Item to PO"): st.session_state.po_rows += 1
        po_l = []
        for i in range(st.session_state.po_rows):
            cc1, cc2, cc3 = st.columns([2, 1, 2])
            ss, qq = cc1.text_input(f"SKU {i+1}", key=f"ps_{i}").upper(), cc2.number_input(f"Qty {i+1}", key=f"pq_{i}")
            dd = cc3.datetime_input(f"Requested Date {i+1}", value=min_del, min_value=min_del, key=f"pd_{i}")
            if ss: po_l.append((ss, qq, dd.strftime("%Y-%m-%d %H:%M")))
        if st.button("Generate and Prepare PDF"):
            creation = now.strftime("%Y-%m-%d %H:%M:%S")
            pdf_b = create_pdf_content(ref, po_l, creation)
            st.success(f"PO {ref} Authorized")
            st.download_button("Download PO (PDF)", pdf_b, f"PO_{ref}.pdf", "application/pdf")

    # 7. التنبيهات
    elif choice == "7. Low Stock Alerts":
        d, _ = fetch_query("SELECT name, sku, quantity, min_stock FROM items WHERE quantity <= min_stock")
        if d: st.table(d)
        else: st.success("All stock levels are safe")

    # 8. القيمة الإجمالية
    elif choice == "8. Total Value Report":
        d, _ = fetch_query("SELECT name, quantity, price FROM items")
        df = pd.DataFrame(d, columns=['Name', 'Quantity', 'Price'])
        st.metric("Total Warehouse Value", f"{(df['Quantity'] * df['Price']).sum():,.2f}")

    # 9. السجل
    elif choice == "9. Audit Log":
        d, _ = fetch_query("SELECT timestamp, sku, type, quantity_change, user, reason FROM transactions ORDER BY timestamp DESC")
        st.table(d)

if __name__ == '__main__':
    main_streamlit_app()
