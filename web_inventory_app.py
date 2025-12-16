import streamlit as st
import sqlite3
from datetime import datetime
import pandas as pd
import os
from twilio.rest import Client # يجب تثبيت مكتبة twilio

# -------------------------------------------------------------
# 📞 إعدادات API لتنبيهات WhatsApp (Twilio)
# -------------------------------------------------------------
# ⚠️ يجب ملء هذه البيانات من حساب Twilio الخاص بك ليعمل التنبيه عبر WhatsApp
TWILIO_ACCOUNT_SID = "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" 
TWILIO_AUTH_TOKEN = "your_auth_token_here"
TWILIO_WHATSAPP_NUMBER = "whatsapp:+14150000000" # رقم Twilio الخاص بك (يبدأ بـ whatsapp:+)
DESTINATION_WHATSAPP_NUMBER = "whatsapp:+9665xxxxxxxx" # رقم WhatsApp الذي سيتلقى التنبيهات

# حاول تهيئة العميل مرة واحدة فقط
try:
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    WHATSAPP_READY = True
except Exception:
    WHATSAPP_READY = False
# -------------------------------------------------------------

# -------------------------------------------------------------
# 🔒 إعداد قاعدة البيانات ودوَالها الأساسية
# -------------------------------------------------------------

DATABASE_NAME = 'inventory_control.db'

def initialize_db():
    """تهيئة قاعدة البيانات وإنشاء جداول Items, Transactions, و BOM_Recipes."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    # جدول Items (الأصناف)
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
    
    # التحقق من وجود عمود supplier_phone وإضافته إذا لم يكن موجوداً
    try:
        cursor.execute("SELECT supplier_phone FROM items LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE items ADD COLUMN supplier_phone TEXT")
        
    # جدول Transactions (سجل الحركات)
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
    
    # جدول BOM_Recipes (قوائم المواد المُجمَّعة)
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
    """دالة مساعدة لتنفيذ الاستعلامات."""
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
    """دالة مساعدة لجلب البيانات."""
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
    """تسجيل تفاصيل الحركة في جدول Transactions."""
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    query = '''
        INSERT INTO transactions (sku, type, quantity_change, user, reason, timestamp) 
        VALUES (?, ?, ?, ?, ?, ?)
    '''
    return execute_query(query, (sku, type, quantity_change, user, reason, current_time))

# -------------------------------------------------------------
# 📞 دوال تنبيهات واتساب
# -------------------------------------------------------------

def send_whatsapp_alert(message_body):
    """
    إرسال رسالة تنبيه عبر WhatsApp باستخدام Twilio.
    """
    if not WHATSAPP_READY:
        # لا نستخدم st.error هنا لتجنب تكرار الرسالة عند إعادة التشغيل
        return

    try:
        message = client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            body=message_body,
            to=DESTINATION_WHATSAPP_NUMBER
        )
        # st.info(f"✅ تم إرسال تنبيه WhatsApp بنجاح: {message.sid}")
    except Exception as e:
        # يمكن إظهار خطأ هنا إذا أردت
        pass

# -------------------------------------------------------------
# 📈 دوال إدارة المخزون
# -------------------------------------------------------------

def save_bom_recipe(assembled_name, raw_sku, required_quantity):
    """حفظ أو تحديث مقادير منتج مُجمَّع."""
    # نستخدم INSERT OR REPLACE لضمان تحديث الكمية إذا كان اسم المنتج وكوده موجودان
    query = '''
        INSERT OR REPLACE INTO bom_recipes (assembled_product_name, raw_material_sku, required_quantity) 
        VALUES (?, ?, ?)
    '''
    return execute_query(query, (assembled_name, raw_sku, required_quantity))

def add_or_update_item(name, sku, price, quantity, supplier_name, supplier_phone, user_source="المستخدم"):
    """إضافة صنف جديد أو تحديث كمية صنف موجود بالفعل."""
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # التحقق من بادئة P- 
    if not sku.startswith("P-"):
        st.error("⚠️ فشل الإدخال: يجب أن يبدأ الكود التعريفي (SKU) بالبادئة P-")
        return

    item_data, _ = fetch_query("SELECT quantity FROM items WHERE sku=?", (sku,))
    
    if item_data:
        current_quantity = item_data[0][0]
        new_quantity = current_quantity + quantity
        
        query = 'UPDATE items SET quantity = ?, price=?, supplier_name=?, supplier_phone=?, last_updated = ? WHERE sku = ?'
        if execute_query(query, (new_quantity, price, supplier_name, supplier_phone, current_time, sku)):
            st.success(f"✅ تم تحديث كمية الصنف **{name}** (SKU: {sku}). الكمية الجديدة: **{new_quantity}**")
            log_transaction(sku, 'IN', quantity, user_source, 'إدخال يدوي')
        
    else:
        min_stock = 5 
        query = '''
            INSERT INTO items (name, sku, quantity, min_stock, price, supplier_name, supplier_phone, last_updated) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        '''
        if execute_query(query, (name, sku, quantity, min_stock, price, supplier_name, supplier_phone, current_time)):
            st.success(f"➕ تم إضافة صنف جديد: **{name}** (SKU: {sku}) بكمية: **{quantity}**")
            log_transaction(sku, 'IN', quantity, user_source, 'إدخال صنف جديد')

def issue_item_out(sku, quantity_out, user, reason):
    """تسجيل عملية صرف/إخراج من المخزون."""
    item_data, _ = fetch_query("SELECT quantity, name, min_stock FROM items WHERE sku=?", (sku,))
    
    if not item_data:
        st.error(f"❌ لم يتم العثور على صنف بالكود: {sku}")
        return False

    current_quantity, name, min_stock = item_data[0]

    if quantity_out <= 0 or quantity_out > current_quantity:
        st.error(f"⚠️ خطأ: الكمية المطلوبة ({quantity_out}) غير صالحة أو أكبر من المتاح ({current_quantity}).")
        return False

    # تحديث الكمية
    new_quantity = current_quantity - quantity_out
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    update_query = 'UPDATE items SET quantity = ?, last_updated = ? WHERE sku = ?'
    if execute_query(update_query, (new_quantity, current_time, sku)):
        st.success(f"✅ تم تحديث المخزون. تم صرف **{quantity_out}** من **{name}**. الكمية الجديدة: **{new_quantity}**")
        log_transaction(sku, 'OUT', quantity_out, user, reason)

        # التحقق وإرسال تنبيه WhatsApp بعد الصرف
        if new_quantity <= min_stock:
            alert_message = f"🚨 تنبيه نقص المخزون! الصنف: {name} (SKU: {sku}) انخفض إلى {new_quantity}. الحد الأدنى للطلب هو {min_stock}."
            st.warning(alert_message)
            send_whatsapp_alert(alert_message) 
            
        return True
    return False

def issue_assembled_product(assembled_name, units_to_issue, user, reason):
    """صرف عدد من المنتجات المجمعة، وخصم المواد الخام أوتوماتيكياً."""
    st.subheader(f"خصم المواد الخام لـ **{units_to_issue}** وحدة من **{assembled_name}**")
    
    recipe_query = 'SELECT raw_material_sku, required_quantity FROM bom_recipes WHERE assembled_product_name = ?'
    recipe_data, _ = fetch_query(recipe_query, (assembled_name,))
    
    if not recipe_data:
        st.error(f"❌ لم يتم العثور على وصفة تجميع (BOM) للمنتج: {assembled_name}")
        return False
        
    total_mats_to_issue = []
    can_issue = True
    
    # 2. حساب إجمالي المواد المطلوبة والتحقق من التوفر
    for raw_sku, required_per_unit in recipe_data:
        total_required = required_per_unit * units_to_issue
        
        item_data, _ = fetch_query("SELECT quantity, name FROM items WHERE sku=?", (raw_sku,))
        if not item_data:
            st.error(f"❌ المادة الخام {raw_sku} غير موجودة في المخزون.")
            can_issue = False
            break
            
        current_quantity, raw_name = item_data[0]
        
        if total_required > current_quantity:
            st.error(f"⚠️ نقص في المادة الخام: {raw_name} ({raw_sku}). مطلوب {total_required:.2f} والمتاح {current_quantity}.")
            can_issue = False
            break
            
        total_mats_to_issue.append({
            'sku': raw_sku,
            'name': raw_name,
            'required': total_required
        })
        
    if not can_issue:
        return False

    # 3. خصم المواد الخام وتسجيل الحركات
    issue_successful = True
    for mat in total_mats_to_issue:
        current_data, _ = fetch_query("SELECT quantity, min_stock FROM items WHERE sku=?", (mat['sku'],))
        current_qty = current_data[0][0]
        min_stock = current_data[0][1]
        new_qty = current_qty - mat['required']
        
        update_query = 'UPDATE items SET quantity = ? WHERE sku = ?'
        if execute_query(update_query, (new_qty, mat['sku'])):
            log_transaction(mat['sku'], 'BOM_OUT', mat['required'], user, f'خصم لتصنيع {units_to_issue} من {assembled_name} - السبب: {reason}')
            st.success(f"✅ تم خصم {mat['required']:.2f} من {mat['name']} (SKU: {mat['sku']}). المتبقي: {new_qty:.2f}")
            
            # التحقق من نقص المخزون بعد الخصم
            if new_qty <= min_stock:
                alert_message = f"🚨 تنبيه BOM: المادة الخام {mat['name']} ({mat['sku']}) انخفضت إلى مستوى حرج ({new_qty:.2f}) بعد الخصم لتصنيع {assembled_name}."
                st.warning(alert_message)
                send_whatsapp_alert(alert_message) 
        else:
            issue_successful = False
            st.error(f"❌ فشل خصم {mat['sku']}")
            
    if issue_successful:
        st.success(f"🎉 نجاح! تم خصم جميع المواد الخام المطلوبة لتصنيع {units_to_issue} من {assembled_name}.")
    
    return issue_successful

# -------------------------------------------------------------
# 🖥️ وظائف واجهة Streamlit
# -------------------------------------------------------------

def get_matching_skus(search_term):
    """جلب قائمة بالأكواد وأسماء الأصناف المطابقة للبحث."""
    if not search_term:
        return []
    
    term = f'%{search_term}%'
    query = "SELECT sku, name FROM items WHERE sku LIKE ? OR name LIKE ? LIMIT 10"
    items, _ = fetch_query(query, (term, term))
    
    return [f"{sku} - {name}" for sku, name in items]

def inventory_display_view(search_term=""):
    """عرض جدول المخزون الحالي مع التصفية والبحث التفاعلي."""
    st.subheader("🔍 قائمة المخزون الحالي")
    
    # عرض نتائج البحث التفاعلي أولاً
    if search_term:
        matching_items = get_matching_skus(search_term)
        if matching_items:
            st.markdown("---")
            st.markdown("##### 📝 نتائج البحث السريعة (الكود والاسم):")
            st.info(", ".join(matching_items))
            st.markdown("---")
    
    # الأعمدة المطلوبة هي 9 أعمدة من جدول items
    select_cols = 'id, name, sku, quantity, min_stock, price, supplier_name, supplier_phone, last_updated'
    
    if search_term:
        term = f'%{search_term}%'
        query = f'''
            SELECT {select_cols}
            FROM items 
            WHERE name LIKE ? OR sku LIKE ?
        '''
        items, columns = fetch_query(query, (term, term))
    else:
        query = f'SELECT {select_cols} FROM items'
        items, columns = fetch_query(query)

    if items:
        df = pd.DataFrame(items, columns=columns)
        
        # إضافة عمود الحالة للرقابة البصرية (العمود العاشر)
        df['Status'] = df.apply(lambda row: '🚨 نقص!' if row['quantity'] <= row['min_stock'] else '✅ آمن', axis=1)
        
        # إعادة تسمية الأعمدة للعرض بالعربية (10 أعمدة الآن)
        df.columns = ['ID', 'الاسم', 'الكود (SKU)', 'الكمية', 'الحد الأدنى', 'السعر', 'المورد', 'رقم المورد', 'آخر تحديث', 'الحالة']
        
        st.dataframe(df.set_index('ID'), use_container_width=True)
    else:
        st.info("⚠️ لم يتم العثور على أصناف.")

def low_stock_view():
    """عرض الأصناف التي تقل عن الحد الأدنى للطلب."""
    st.subheader("🚨 تنبيهات نقص المخزون (Low Stock) 🚨")
    
    query = '''
        SELECT name, sku, quantity, min_stock, last_updated 
        FROM items 
        WHERE quantity <= min_stock
        ORDER BY quantity ASC
    '''
    low_stock_items, columns = fetch_query(query)

    if low_stock_items:
        df = pd.DataFrame(low_stock_items, columns=columns)
        df.columns = ['الاسم', 'الكود (SKU)', 'الكمية الحالية', 'الحد الأدنى', 'آخر تحديث']
        st.warning("الأصناف التالية بحاجة إلى طلب عاجل:")
        st.dataframe(df, use_container_width=True)

        st.markdown("---")
        if st.button("📞 إرسال تقرير نقص المخزون الآن عبر WhatsApp"):
            alert_summary = "🚨 تقرير نقص المخزون العاجل:\n\n"
            for index, row in df.iterrows():
                alert_summary += f"- {row['الاسم']} ({row['الكود (SKU)']}) الكمية: {row['الكمية الحالية']} (تحت الحد {row['الحد الأدنى']})\n"
            send_whatsapp_alert(alert_summary)
            
    else:
        st.success("✅ لا توجد أصناف تحت الحد الأدنى للطلب. المخزون آمن.")

def audit_log_view():
    """عرض سجل تدقيق الحركات (Transactions)."""
    st.subheader("📜 سجل تدقيق حركات المخزون")
    
    query = "SELECT timestamp, sku, type, quantity_change, user, reason FROM transactions ORDER BY timestamp DESC LIMIT 100"
    data, columns = fetch_query(query)

    if data:
        df = pd.DataFrame(data, columns=columns)
        df.columns = ['التاريخ والوقت', 'الكود (SKU)', 'النوع', 'الكمية', 'المستخدم', 'السبب']
        st.dataframe(df, use_container_width=True)
    else:
        st.info("⚠️ لا توجد حركات مسجلة.")

def total_value_view():
    """حساب وعرض القيمة الإجمالية للمخزون."""
    st.subheader("💵 تقرير القيمة الإجمالية للمخزون")
    
    query = 'SELECT name, quantity, price FROM items'
    items, columns = fetch_query(query)

    if items:
        df = pd.DataFrame(items, columns=['name', 'quantity', 'price'])
        df['Value'] = df['quantity'] * df['price']
        
        total_value = df['Value'].sum()
        
        st.metric(label="💰 القيمة الإجمالية الكلية للمخزون", value=f"{total_value:,.2f}")
        
        df.columns = ['الاسم', 'الكمية', 'سعر الوحدة', 'القيمة الإجمالية للصنف']
        st.dataframe(df.set_index('الاسم'), use_container_width=True)
    else:
        st.info("⚠️ لا توجد أصناف مسجلة لحساب القيمة.")

# -------------------------------------------------------------
# 🌐 التخطيط الرئيسي لواجهة Streamlit
# -------------------------------------------------------------

def main_streamlit_app():
    initialize_db()

    st.set_page_config(
        page_title="شركة اكسبو تايم ادارة المخزون", 
        layout="wide",
        initial_sidebar_state="expanded"
    )

    st.title("🏆 شركة اكسبو تايم ادارة المخزون 🏆") 
    st.markdown("---")
    
    # تهيئة حالة الجلسة لمكونات BOM
    if 'bom_components' not in st.session_state:
        st.session_state.bom_components = [{'raw_sku': '', 'required_quantity': 0.0}]
        
    def add_component():
        st.session_state.bom_components.append({'raw_sku': '', 'required_quantity': 0.0})

    def remove_component(index):
        if len(st.session_state.bom_components) > 1:
            st.session_state.bom_components.pop(index)
        else:
            st.error("يجب أن يحتوي المنتج المجمع على مكون واحد على الأقل.")
    
    st.sidebar.title("قائمة النظام")
    
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

    # ---------------------------------------------
    # عرض الأقسام بناءً على الاختيار (تم تصحيح الـ Indentation)
    # ---------------------------------------------
    
    if choice == "🔍 عرض المخزون والبحث":
        search_term = st.text_input("ابحث بالاسم أو الكود (SKU) (البحث تفاعلي):")
        inventory_display_view(search_term)

    elif choice == "➕ إدخال صنف/تحديث":
        st.subheader("➕ إدخال بيانات صنف جديد أو تحديث كميته")
        with st.form(key='add_item_form'):
            name = st.text_input("اسم الصنف:")
            sku = st.text_input("الكود التعريفي (SKU) - (يجب أن يبدأ بـ P-):").upper()
            price = st.number_input("سعر الوحدة:", min_value=0.0, format="%.2f")
            quantity = st.number_input("الكمية المضافة:", min_value=1, step=1)
            supplier_name = st.text_input("اسم المورد:")
            supplier_phone = st.text_input("رقم المورد (اختياري):") 
            user = st.text_input("اسم المستخدم المسؤول عن الإدخال:")
            
            submit_button = st.form_submit_button(label='إضافة/تحديث الصنف')

            if submit_button:
                if name and sku and price > 0 and quantity > 0 and user:
                    add_or_update_item(name, sku, price, quantity, supplier_name, supplier_phone, user)
                else:
                    st.error("الرجاء ملء جميع الحقول المطلوبة (باستثناء رقم المورد) والتأكد من أن الكمية والسعر موجبان.")

    elif choice == "⚙️ تعريف المنتجات المجمعة (BOM)":
        st.subheader("⚙️ تعريف مقادير المنتجات المُجمَّعة (قائمة المواد BOM)")
        st.markdown("يرجى تحديد المنتج المُجمَّع والمواد الخام المتعددة التي يحتاجها كل وحدة.")
        
        all_skus_data, _ = fetch_query("SELECT sku, name FROM items")
        all_skus_dict = {f"{sku} - {name}": sku for sku, name in all_skus_data}
        all_skus_options = ["(اختر الكود الصحيح)"] + list(all_skus_dict.keys())

        # -------------------------------------------------------------
        # واجهة المكونات الديناميكية (خارج النموذج للتعامل مع st.button)
        # -------------------------------------------------------------
        st.markdown("---")
        st.markdown("##### 📦 المكونات الخام المطلوبة لكل وحدة من المنتج المُجمَّع")

        for i, component in enumerate(st.session_state.bom_components):
            cols = st.columns([0.4, 0.4, 0.2])
            
            selected_sku_name = cols[0].selectbox(
                f"المكون {i+1} (كود وصنف)",
                options=all_skus_options,
                # محاولة تحديد القيمة الافتراضية إذا كانت موجودة
                index=all_skus_options.index(next((k for k,v in all_skus_dict.items() if v == component['raw_sku']), all_skus_options[0])),
                key=f"sku_{i}",
                label_visibility="collapsed"
            )
            
            if selected_sku_name != "(اختر الكود الصحيح)":
                raw_sku_for_save = all_skus_dict.get(selected_sku_name, selected_sku_name.split(' - ')[0])
            else:
                raw_sku_for_save = ""

            required_quantity = cols[1].number_input(
                f"الكمية المطلوبة من المادة الخام لكل 1 وحدة:",
                min_value=0.0,
                format="%.3f",
                key=f"qty_{i}",
                label_visibility="collapsed",
                value=component['required_quantity']
            )
            
            # تحديث حالة الجلسة
            st.session_state.bom_components[i]['raw_sku'] = raw_sku_for_save
            st.session_state.bom_components[i]['required_quantity'] = required_quantity
            
            # الزر الآن خارج نطاق st.form 
            if cols[2].button("حذف", key=f"remove_{i}"):
                remove_component(i)
                st.experimental_rerun()
        
        st.button("➕ إضافة مكون خام آخر", on_click=add_component)
        st.markdown("---")
        
        # -------------------------------------------------------------
        # النموذج يبدأ الآن ويحتوي على اسم المنتج وزر التقديم فقط
        # -------------------------------------------------------------
        with st.form(key='bom_recipe_form'):
            assembled_name = st.text_input("اسم المنتج المُجمَّع (مثل: جدار 2.44x1م):")
            
            submit_button = st.form_submit_button(label='حفظ الوصفة النهائية')
            
            if submit_button:
                if not assembled_name:
                    st.error("الرجاء إدخال اسم المنتج المُجمَّع.")
                    
                valid_components = [
                    comp for comp in st.session_state.bom_components 
                    if comp['raw_sku'] and comp['required_quantity'] > 0
                ]
                
                if not valid_components:
                    st.error("الرجاء إدخال مكون واحد صحيح على الأقل بكمية موجبة.")
                else:
                    # 1. مسح الوصفات القديمة لنفس المنتج (لضمان التحديث)
                    execute_query("DELETE FROM bom_recipes WHERE assembled_product_name = ?", (assembled_name,))
                    
                    # 2. حفظ المكونات الجديدة
                    all_successful = True
                    for comp in valid_components:
                        if not save_bom_recipe(assembled_name, comp['raw_sku'], comp['required_quantity']):
                            all_successful = False
                            
                    if all_successful:
                        st.success(f"✅ تم حفظ وصفة التجميع **{assembled_name}** بنجاح وتضمين {len(valid_components)} مكون.")
                        st.session_state.bom_components = [{'raw_sku': '', 'required_quantity': 0.0}]
                        st.experimental_rerun()
                    else:
                        st.error("حدث خطأ أثناء حفظ بعض المكونات.")
        
    elif choice == "📤 تسجيل صرف مواد (مفرد)":
        st.subheader("📤 تسجيل صرف مواد (مفرد)")
        with st.form(key='issue_item_form'):
            sku_out = st.text_input("الكود التعريفي (SKU) للصنف المصروف:").upper()
            quantity_out = st.number_input("الكمية المراد صرفها:", min_value=1, step=1)
            user_out = st.text_input("اسم المستخدم المسؤول عن الصرف:")
            reason_out = st.text_area("سبب الصرف (بيع، تلف، استخدام داخلي):")

            submit_button = st.form_submit_button(label='تسجيل عملية الصرف')

            if submit_button:
                if sku_out and quantity_out > 0 and user_out and reason_out:
                    issue_item_out(sku_out, quantity_out, user_out, reason_out)
                else:
                    st.error("الرجاء ملء جميع الحقول.")

    elif choice == "🏭 تسجيل صرف منتج مُجمَّع (BOM)":
        st.subheader("🏭 صرف المنتجات المُجمَّعة (خصم تلقائي للمواد الخام)")
        
        bom_names_data, _ = fetch_query("SELECT DISTINCT assembled_product_name FROM bom_recipes")
        bom_names = [row[0] for row in bom_names_data]
        
        if not bom_names:
            st.warning("⚠️ لا توجد وصفات تجميع مسجلة. يرجى البدء من '⚙️ تعريف المنتجات المجمعة'.")
            return
            
        with st.form(key='issue_assembled_form'):
            selected_product = st.selectbox("اختر المنتج المُجمَّع الذي تريد صرفه:", bom_names)
            units_to_issue = st.number_input(f"عدد وحدات {selected_product} المطلوب صرفها (الكمية المصنعة):", min_value=1, step=1)
            user = st.text_input("اسم المستخدم المسؤول عن الصرف:")
            reason = st.text_area("سبب الصرف (مثل: بيع، تركيب، نقل):")

            submit_button = st.form_submit_button(label='خصم المواد وصرف المنتج المُجمَّع')

            if submit_button:
                if selected_product and units_to_issue > 0 and user and reason:
                    issue_assembled_product(selected_product, units_to_issue, user, reason)
                else:
                    st.error("الرجاء ملء جميع الحقول المطلوبة.")

    elif choice == "🚨 تنبيهات نقص المخزون":
        low_stock_view()
        
    elif choice == "💵 تقرير القيمة الإجمالية":
        total_value_view()

    elif choice == "📜 سجل التدقيق (Audit Log)":
        audit_log_view()

if __name__ == '__main__':
    main_streamlit_app()