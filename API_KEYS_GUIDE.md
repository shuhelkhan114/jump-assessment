# API Keys Setup Guide

This guide will walk you through obtaining all the required API keys for the Financial Agent application.

## 🔑 Required API Keys

You'll need to obtain the following API keys:
1. **Google OAuth** - For Gmail and Calendar access
2. **HubSpot OAuth** - For CRM integration
3. **OpenAI API Key** - For AI functionality

---

## 📧 1. Google OAuth Setup

### Step 1: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click "Select a project" → "New Project"
3. Enter project name: `financial-agent`
4. Click "Create"

### Step 2: Enable Required APIs

1. In the Google Cloud Console, go to **APIs & Services** → **Library**
2. Search for and enable the following APIs:
   - **Gmail API**
   - **Google Calendar API**
   - **Google People API** (for user info)

### Step 3: Create OAuth 2.0 Credentials

1. Go to **APIs & Services** → **Credentials**
2. Click **"+ CREATE CREDENTIALS"** → **OAuth client ID**
3. If prompted, configure the OAuth consent screen:
   - Choose **External** (for testing)
   - Fill in required fields:
     - **App name**: `Financial Agent`
     - **User support email**: Your email
     - **Developer contact email**: Your email
   - Click **Save and Continue**
   - **Scopes**: Click **Save and Continue** (we'll add scopes in code)
   - **Test users**: Add `webshookeng@gmail.com` and your email
   - Click **Save and Continue**

4. Back to **Credentials**, click **"+ CREATE CREDENTIALS"** → **OAuth client ID**
5. Choose **Web application**
6. Name: `Financial Agent Web Client`
7. **Authorized redirect URIs**: Add these URLs:
   ```
   http://localhost:8000/auth/google/callback
   http://localhost:3000/auth/callback
   ```
8. Click **Create**
9. **Copy the Client ID and Client Secret** - you'll need these!

### Step 4: Add Test Users

1. Go to **APIs & Services** → **OAuth consent screen**
2. Scroll down to **Test users**
3. Click **+ ADD USERS**
4. Add: `webshookeng@gmail.com`
5. Add your own email address
6. Click **Save**

### 🎯 What you need from Google:
- `GOOGLE_CLIENT_ID` - The Client ID from step 3
- `GOOGLE_CLIENT_SECRET` - The Client Secret from step 3

---

## 🏢 2. HubSpot OAuth Setup

### Step 1: Create HubSpot Developer Account

1. Go to [HubSpot Developer Portal](https://developers.hubspot.com/)
2. Sign up for a free account or log in
3. Click **"Create app"**

### Step 2: Create HubSpot App

1. **App name**: `Financial Agent`
2. **Description**: `AI Assistant for Financial Advisors`
3. Click **Create app**

### Step 3: Configure OAuth Settings

1. In your app dashboard, go to **Auth** tab
2. **Redirect URLs**: Add these URLs:
   ```
   http://localhost:8000/auth/hubspot/callback
   http://localhost:3000/auth/hubspot/callback
   ```
3. **Scopes**: Select the following scopes:
   - `crm.objects.contacts.read`
   - `crm.objects.contacts.write`
   - `crm.objects.companies.read`
   - `crm.objects.companies.write`
   - `crm.objects.deals.read`
   - `crm.objects.deals.write`

### Step 4: Get Your Credentials

1. Go to **App info** tab
2. **Copy the Client ID and Client Secret**

### Step 5: Create Test HubSpot Account

1. Go to [HubSpot](https://www.hubspot.com/)
2. Sign up for a **free** HubSpot account
3. This will be your test CRM with sample data

### 🎯 What you need from HubSpot:
- `HUBSPOT_CLIENT_ID` - The Client ID from your app
- `HUBSPOT_CLIENT_SECRET` - The Client Secret from your app

---

## 🤖 3. OpenAI API Key Setup

### Step 1: Create OpenAI Account

1. Go to [OpenAI Platform](https://platform.openai.com/)
2. Sign up for an account or log in
3. You'll get $5 in free credits to start

### Step 2: Create API Key

1. Go to **API Keys** section
2. Click **"+ Create new secret key"**
3. Name: `Financial Agent`
4. Click **Create secret key**
5. **Copy the API key immediately** - you won't be able to see it again!

### Step 3: Add Payment Method (Optional)

1. Go to **Billing** → **Payment methods**
2. Add a credit card for usage beyond free credits
3. Set usage limits if desired

### 🎯 What you need from OpenAI:
- `OPENAI_API_KEY` - The API key from step 2

---

## 🔧 4. Environment Setup

### Step 1: Create Environment File

1. Copy `env.example` to `.env`:
   ```bash
   cp env.example .env
   ```

### Step 2: Fill in Your API Keys

Edit the `.env` file with your credentials:

```env
# Database
DATABASE_URL=postgresql://postgres:password@db:5432/financial_agent

# Authentication
SECRET_KEY=your-super-secret-key-here-change-this-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Google OAuth
GOOGLE_CLIENT_ID=your-google-client-id-here
GOOGLE_CLIENT_SECRET=your-google-client-secret-here

# HubSpot OAuth
HUBSPOT_CLIENT_ID=your-hubspot-client-id-here
HUBSPOT_CLIENT_SECRET=your-hubspot-client-secret-here

# OpenAI
OPENAI_API_KEY=your-openai-api-key-here

# Frontend URL
FRONTEND_URL=http://localhost:3000

# Redis (for background tasks)
REDIS_URL=redis://localhost:6379

# Application
APP_NAME=Financial Agent
DEBUG=true
```

### Step 3: Generate Secret Key

For the `SECRET_KEY`, generate a secure random string:

```bash
# Option 1: Using OpenSSL
openssl rand -hex 32

# Option 2: Using Python
python -c "import secrets; print(secrets.token_hex(32))"

# Option 3: Online generator (use a secure one)
# Visit: https://randomkeygen.com/
```

---

## 🚀 5. Test Your Setup

### Step 1: Start the Application

```bash
docker-compose up --build
```

### Step 2: Test Each Integration

1. **Frontend**: Visit `http://localhost:3000`
2. **Backend**: Visit `http://localhost:8000/docs`
3. **Redis**: Available at `localhost:6379`
4. **PostgreSQL**: Available at `localhost:5432`
5. **Google OAuth**: Try the login flow
6. **HubSpot OAuth**: Connect your HubSpot account
7. **OpenAI**: Send a test message in the chat

### Step 3: Check Logs

```bash
# View backend logs
docker-compose logs backend

# View frontend logs
docker-compose logs frontend

# View database logs
docker-compose logs db

# View Redis logs
docker-compose logs redis

# View Celery worker logs
docker-compose logs celery_worker
```

---

## 🔒 6. Security Notes

### For Development:
- Keep your `.env` file secure and never commit it to version control
- Use the test users feature for Google OAuth
- Use HubSpot's free tier for testing

### For Production:
- Use environment variables instead of `.env` files
- Regenerate all API keys
- Set up proper OAuth consent screens
- Use HTTPS for all redirect URLs
- Implement proper error handling and logging

---

## 📋 7. Troubleshooting

### Common Issues:

**Google OAuth Error: "redirect_uri_mismatch"**
- Check that your redirect URIs match exactly in Google Console
- Ensure no trailing slashes
- Verify HTTP vs HTTPS

**HubSpot OAuth Error: "invalid_redirect_uri"**
- Verify redirect URIs in your HubSpot app settings
- Check for typos in the URLs

**OpenAI API Error: "Incorrect API key"**
- Ensure the API key is copied correctly
- Check that the API key hasn't expired
- Verify you have credits remaining

**Database Connection Error**
- Ensure PostgreSQL is running
- Check DATABASE_URL format
- Verify pgvector extension is installed

---

## 📞 8. Support

If you encounter issues:

1. **Google OAuth**: [Google OAuth Documentation](https://developers.google.com/identity/protocols/oauth2)
2. **HubSpot OAuth**: [HubSpot OAuth Documentation](https://developers.hubspot.com/docs/api/oauth-quickstart-guide)
3. **OpenAI API**: [OpenAI API Documentation](https://platform.openai.com/docs)

---

## ✅ Final Checklist

Before proceeding, make sure you have:

- [ ] Google Client ID and Secret
- [ ] HubSpot Client ID and Secret  
- [ ] OpenAI API Key
- [ ] Added `webshookeng@gmail.com` as Google test user
- [ ] Created test HubSpot account
- [ ] Filled in `.env` file with all credentials
- [ ] Generated secure SECRET_KEY
- [ ] Tested Docker setup

**You're ready to build the AI agent! 🚀** 