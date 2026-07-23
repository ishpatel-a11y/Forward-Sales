name: Hourly Forward Sales Pipeline

on:
  schedule:
    # Runs at minute 15 of every hour (e.g. 1:15, 2:15, 3:15)
    # Using minute 15 avoids delay congestion at minute 0
    - cron: '15 * * * *'
  workflow_dispatch: # Allows you to manually trigger the run anytime from GitHub UI

jobs:
  run-pipeline:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Install Dependencies
        run: |
          python -m pip install --upgrade pip
          pip install pandas requests gspread google-auth

      - name: Execute Hourly Sync & Forward Sales Calculation
        env:
          SHOPIFY_STORE_URL: ${{ secrets.SHOPIFY_STORE_URL }}
          SHOPIFY_ACCESS_TOKEN: ${{ secrets.SHOPIFY_ACCESS_TOKEN }}
          GOOGLE_SERVICE_ACCOUNT_JSON: ${{ secrets.GOOGLE_SERVICE_ACCOUNT_JSON }}
        run: python process_hourly_sales.py
