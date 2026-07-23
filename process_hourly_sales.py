import os
import json
import datetime
import pandas as pd
import requests
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. SETUP GOOGLE SHEETS CONNECTION
# ==========================================
SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds_json = json.loads(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"))
creds = Credentials.from_service_account_info(creds_json, scopes=SCOPE)
gc = gspread.authorize(creds)

# Open Google Sheet Workspace
spreadsheet = gc.open("Shopify_Forward_Sales_Master")
ws_master = spreadsheet.worksheet("Master_Orders")
ws_daily_summary = spreadsheet.worksheet("Daily_Forward_Sales_Summary")

# ==========================================
# 2. FETCH SHOPIFY ORDERS (PAST 2 HOURS)
# ==========================================
SHOPIFY_STORE_URL = os.getenv("SHOPIFY_STORE_URL")
SHOPIFY_ACCESS_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN")

def fetch_hourly_shopify_orders():
    # Look back 2 hours to catch all recent checkouts
    since_time = (datetime.datetime.utcnow() - datetime.timedelta(hours=2)).isoformat()
    url = f"https://{SHOPIFY_STORE_URL}/admin/api/2026-04/orders.json?status=any&updated_at_min={since_time}"
    headers = {"X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN}
    
    res = requests.get(url, headers=headers)
    if res.status_code != 200:
        print(f"Error fetching Shopify orders: {res.text}")
        return pd.DataFrame()
        
    orders = res.json().get('orders', [])
    records = []
    
    for o in orders:
        name = o.get('name')
        paid_at = o.get('processed_at')
        status = o.get('financial_status')
        
        for item in o.get('line_items', []):
            line_title = item.get('title')
            price = float(item.get('price', 0))
            qty = int(item.get('quantity', 1))
            net_amt = price * qty
            
            records.append({
                'Name': str(name),
                'Financial Status': str(status),
                'Paid at': paid_at[:10] if paid_at else None, # YYYY-MM-DD
                'Lineitem name': line_title,
                'Net Amount': net_amt,
                'Order Event Date': parse_event_date(line_title)
            })
            
    return pd.DataFrame(records)

def parse_event_date(text):
    import re
    # Extract date patterns like "1st July 2026" or "2026-07-01"
    match = re.search(r'(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4})', str(text))
    if match:
        try:
            clean_str = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', match.group(1))
            return pd.to_datetime(clean_str, format='%d %B %Y').strftime('%Y-%m-%d')
        except:
            return None
    return None

# ==========================================
# 3. MERGE HOURLY DATA & COMPUTE DAILY NUMBERS
# ==========================================
# Load existing master data
df_existing = pd.DataFrame(ws_master.get_all_records())
df_new = fetch_hourly_shopify_orders()

if not df_new.empty:
    df_combined = pd.concat([df_existing, df_new], ignore_index=True)
    df_combined = df_combined.drop_duplicates(subset=['Name', 'Lineitem name', 'Paid at'], keep='last')
else:
    df_combined = df_existing

# Ensure datetime types
df_combined['Paid at'] = pd.to_datetime(df_combined['Paid at'], errors='coerce')
df_combined['Order Event Date'] = pd.to_datetime(df_combined['Order Event Date'], errors='coerce')
df_combined['Net Amount'] = pd.to_numeric(df_combined['Net Amount'], errors='coerce').fillna(0)

# Save deduplicated master back to Google Sheets
ws_master.clear()
ws_master.update([df_combined.astype(str).columns.values.tolist()] + df_combined.astype(str).values.tolist())

# ==========================================
# 4. GENERATE DAILY FORWARD SALES TABLE
# ==========================================
# Build array of dates from earliest sale to 8 months into future
min_date = df_combined['Paid at'].min()
max_event_date = df_combined['Order Event Date'].max()

if pd.isna(min_date): min_date = pd.Timestamp.today()
if pd.isna(max_event_date): max_event_date = pd.Timestamp.today() + pd.Timedelta(days=240)

date_range = pd.date_range(start=min_date, end=max_event_date, freq='D')
daily_results = []

for single_date in date_range:
    # Rule: Cash collected on/before date AND Event occurs AFTER date
    paid_condition = df_combined['Paid at'] <= single_date
    future_condition = df_combined['Order Event Date'] > single_date
    
    forward_sale_balance = df_combined[paid_condition & future_condition]['Net Amount'].sum()
    
    daily_results.append({
        'As_Of_Date': single_date.strftime('%Y-%m-%d'),
        'Forward_Sales_Liability': round(forward_sale_balance, 2),
        'Last_Updated_UTC': datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    })

df_daily_summary = pd.DataFrame(daily_results)

# Push Daily Summary to Google Sheets for Looker Studio
ws_daily_summary.clear()
ws_daily_summary.update([df_daily_summary.columns.values.tolist()] + df_daily_summary.values.tolist())

print(f"[{datetime.datetime.utcnow()}] Hourly Sync Successful. Processed {len(df_daily_summary)} daily figures.")
