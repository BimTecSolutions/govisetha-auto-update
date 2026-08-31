```yaml
name: NLB Govisetha Auto Updater

on:
  schedule:
    # Every 5 minutes
    - cron: "*/5 * * * *"

  workflow_dispatch:

jobs:

  update-govisetha:

    runs-on: ubuntu-latest

    permissions:
      contents: read

    steps:

      # ----------------------------------------------------
      # Checkout repository
      # ----------------------------------------------------

      - name: Checkout repository
        uses: actions/checkout@v4

      # ----------------------------------------------------
      # Setup Python
      # ----------------------------------------------------

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      # ----------------------------------------------------
      # Install dependencies
      # ----------------------------------------------------

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      # ----------------------------------------------------
      # Run updater
      # ----------------------------------------------------

      - name: Run NLB Govisetha updater
        env:
          FIREBASE_CREDENTIALS: ${{ secrets.FIREBASE_CREDENTIALS }}
        run: |
          python main.py
```
