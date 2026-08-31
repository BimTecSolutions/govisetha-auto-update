# Govisetha Lottery Auto-Update

Automated system to fetch and update Govisetha lottery results from NLB Sri Lanka to Firebase Firestore.

## Features

- 🔄 Automatically checks for new lottery draws every 5 minutes
- 📊 Fetches draw numbers, symbols, and winning numbers
- 🗄️ Stores data in Firebase Firestore with proper structure
- 🛡️ Prevents duplicate entries
- 📝 Maintains update history and summary
- 🚀 GitHub Actions workflow for automated deployment

## Setup

### 1. Firebase Setup

1. Create a Firebase project at https://console.firebase.google.com/
2. Generate a service account key:
   - Go to Project Settings > Service Accounts
   - Click "Generate new private key"
   - Save the JSON file

### 2. GitHub Setup

1. Create a new repository on GitHub
2. Add your Firebase credentials as a secret:
   - Go to Settings > Secrets and variables > Actions
   - Click "New repository secret"
   - Name: `FIREBASE_CREDENTIALS`
   - Value: Paste the entire JSON from your service account key

### 3. Deploy

The workflow will automatically:
- Run every 5 minutes
- Check for new lottery draws
- Update Firebase with any new results

## Manual Run

You can also trigger the workflow manually:
1. Go to Actions tab in your repository
2. Select "Auto-Update Govisetha Lottery Results"
3. Click "Run workflow"

## Data Structure

The data is stored in Firestore with the following structure:
