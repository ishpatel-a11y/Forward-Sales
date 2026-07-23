import os
import re
import datetime
import pandas as pd
import requests

# ==========================================
# 1. SHOPIFY CONFIGURATION
# ==========================================
SHOPIFY_STORE_URL = os.getenv("SHOPIFY_STORE_URL")
SHOPIFY_ACCESS_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN")

def fetch_recent_shopify_orders():
    """
    Fetches orders updated in the last 2 hours directly from Shopify REST API.
    """
    if not SHOPIFY_STORE_URL or not SHOPIFY_ACCESS_TOKEN:
        print("Shopify API environment variables not set. Skipping API pull.")
        return pd.DataFrame()

    since_time = (datetime.datetime.utcnow() - datetime.timedelta(hours=2)).isoformat()
    url = f"https://{SHOPIFY_STORE_URL}/admin/api/2026-04/orders.json?status=any&updated_at_min={since_time}"
    headers = {"X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN}
    
    try:
        res = requests.get(url, headers=headers, timeout=30)
        if res.status_code != 200:
            print(f"Shopify API Error: {res.status_code} - {res.text}")
            return pd.DataFrame()
            
        orders = res.json().get('orders', [])
        records = []
        
        for o in orders:
            name = o.get('name')
            paid_at = o.get('processed_at')
            status = o.get('financial_status')
            
            for item in o.get('line_items', []):
                title = item.get('title', '')
                price = float(item.get('price', 0))
                qty = int(item.get('quantity', 1))
                discount = float(item.get('total_discount', 0))
                net_amt = (price * qty) - discount
                
                records.append({
                    'Name': str(name),
                    'Financial Status': str(status),
                    'Paid at': paid_at[:10] if paid_at else None,
                    'Lineitem name': title,
                    'Net Amount': net_amt,
                    'Order Event Date': parse_event_date(title)
                })
        return pd.DataFrame(records)
    except Exception as e:
        print(f"Failed to fetch Shopify orders: {e}")
        return pd.DataFrame()

def parse_event_date(text):
    """
    Parses dates embedded in line item titles (e.g. 'Wednesday, 1st July 2026').
    """
    patterns = [
        r'(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4})',
        r'([A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})',
        r'(\d{4}-\d{2}-\d{2})'
    ]
    for pattern in patterns:
        match = re.search(pattern, str(text))
        if match:
            try:
                clean_str = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', match.group(1))
                return pd.to_datetime(clean_str).strftime('%Y-%m-%d')
            except Exception:
                continue
    return None

# ==========================================
# 2. LOAD EXISTING CSV OR INITIALIZE
# ==========================================
master_csv_path = 'master_orders.csv'

if os.path.exists(master_csv_path):
    df_existing = pd.read_csv(master_csv_path)
else:
    df_existing = pd.DataFrame(columns=['Name', 'Financial Status', 'Paid at', 'Lineitem name', 'Net Amount', 'Order Event Date'])

df_new = fetch_recent_shopify_orders()

if not df_new.empty:
    df_combined = pd.concat([df_existing, df_new], ignore_index=True)
    df_combined = df_combined.drop_duplicates(subset=['Name', 'Lineitem name', 'Paid at'], keep='last')
else:
    df_combined = df_existing

# Save updated master log to GitHub CSV
df_combined.to_csv(master_csv_path, index=False)

# ==========================================
# 3. CALCULATE DAILY FORWARD SALES LIABILITY
# ==========================================
df_combined['Paid at'] = pd.to_datetime(df_combined['Paid at'], errors='coerce')
df_combined['Order Event Date'] = pd.to_datetime(df_combined['Order Event Date'], errors='coerce')
df_combined['Net Amount'] = pd.to_numeric(df_combined['Net Amount'], errors='coerce').fillna(0)

min_date = df_combined['Paid at'].min()
max_event_date = df_combined['Order Event Date'].max()

if pd.isna(min_date): min_date = pd.Timestamp('2026-01-01')
if pd.isna(max_event_date): max_event_date = pd.Timestamp.today() + pd.Timedelta(days=240)

date_range = pd.date_range(start=min_date, end=max_event_date, freq='D')
daily_results = []

for single_date in date_range:
    # Rule: Cash collected on or before single_date AND Event occurs strictly AFTER single_date
    paid_condition = df_combined['Paid at'] <= single_date
    future_condition = df_combined['Order Event Date'] > single_date
    
    liability_balance = df_combined[paid_condition & future_condition]['Net Amount'].sum()
    
    daily_results.append({
        'As_Of_Date': single_date.strftime('%Y-%m-%d'),
        'Forward_Sales_Liability': round(liability_balance, 2)
    })

df_daily_summary = pd.DataFrame(daily_results)

# Save summary result directly to CSV for GitHub / Looker Studio
summary_csv_path = 'daily_forward_sales.csv'
df_daily_summary.to_csv(summary_csv_path, index=False)

print(f"[{datetime.datetime.utcnow()}] Successfully updated master_orders.csv and daily_forward_sales.csv")
