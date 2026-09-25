name: Govisetha Auto Update

on:
  schedule:
    # Runs every day at 21:15 UTC (~02:45 Sri Lanka time, after the
    # nightly Govisetha draw). Adjust to taste.
    - cron: "15 21 * * *"
  workflow_dispatch: {}   # allows manual "Run workflow" trigger

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run Govisetha updater
        env:
          FIREBASE_CREDENTIALS: ${{ secrets.FIREBASE_CREDENTIALS }}
        run: python govisetha_main.py
