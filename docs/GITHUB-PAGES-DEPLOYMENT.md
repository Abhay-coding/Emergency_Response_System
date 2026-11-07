# GitHub Pages Frontend Deployment Guide

This guide explains how to deploy the Campus Medical Assistance frontend to GitHub Pages while keeping the backend API separate.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    GitHub Pages (Frontend)                   │
│  https://your-username.github.io/emergency-response/         │
│  ├── medical.html  (main SPA)                                │
│  ├── medical.js    (application logic)                       │
│  ├── config.js     (API configuration)                       │
│  ├── medical.css   (styles)                                  │
│  └── index.html    (redirect)                                │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ HTTPS API calls
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Backend API (Separate)                    │
│  https://your-api-domain.com/api/v1/                         │
│  ├── FastAPI application                                     │
│  ├── PostgreSQL database                                     │
│  ├── Redis (token blacklist, rate limiting)                  │
│  └── AWS ECS Fargate / Render / Railway / Fly.io             │
└─────────────────────────────────────────────────────────────┘
```

## Prerequisites

1. **GitHub Repository** - Your code pushed to GitHub
2. **Backend API Deployed** - Your FastAPI backend running somewhere accessible via HTTPS
3. **GitHub Pages Enabled** - In repository Settings → Pages

## Quick Setup

### 1. Enable GitHub Pages

1. Go to your repository on GitHub
2. Settings → Pages (in left sidebar)
3. Source: "GitHub Actions"
4. Save

### 2. Deploy Backend API

Deploy your FastAPI backend to a platform that provides HTTPS:
- **Render.com** - Free tier available
- **Railway.app** - Simple deployment
- **Fly.io** - Good free tier
- **AWS ECS Fargate** - Production ready
- **Google Cloud Run** - Serverless containers

Make sure your API has CORS configured for your GitHub Pages domain.

### 3. Configure API URL

The frontend needs to know where your API is. You have several options:

#### Option A: Set via GitHub Actions (Recommended)

1. Go to Actions tab → "Deploy Frontend to GitHub Pages"
2. Click "Run workflow"
3. Enter your API URL (e.g., `https://your-api.onrender.com`)
4. Click "Run workflow"

#### Option B: Set via URL Parameter (Testing)

Visit: `https://your-username.github.io/emergency-response/?api_url=https://your-api.com`

#### Option C: Set in Browser Console (Persistent)

```javascript
// Run in browser console on your GitHub Pages site
window.CER_CONFIG.setApiUrl('https://your-api.com');
// Reload the page
location.reload();
```

#### Option D: Edit config.production.js (Permanent)

Create a `frontend/config.production.js` file with your API URL and the workflow will use it automatically.

## CORS Configuration (Required!)

Your backend API MUST allow requests from your GitHub Pages domain.

### FastAPI CORS Configuration

Update your `app/core/config.py` or `app/main.py`:

```python
# In config.py - add your GitHub Pages URL
cors_origins: list[str] = [
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "https://your-username.github.io",  # Add this
]

# In main.py - CORS middleware already reads from settings.cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)
```

**Important:** The origin must match exactly (including `https://` and no trailing slash).

## Workflow Details

### Trigger Conditions

The workflow runs on:
- Push to `main` branch with changes to `frontend/**`
- Manual trigger via Actions tab

### Manual Deployment with Custom API URL

1. Go to **Actions** tab
2. Select **"Deploy Frontend to GitHub Pages"**
3. Click **"Run workflow"**
4. Enter your API URL in the `api_url` field (optional)
5. Click **"Run workflow"**

### What the Workflow Does

1. **Checkout** - Gets your code
2. **Verify** - Checks frontend files exist
3. **Create Production Config** - If `api_url` provided, creates `config.js` with your API URL
4. **Build** - Copies frontend files to build directory
4. **Deploy** - Uses GitHub Pages action to deploy

## Local Development

For local development, the default `config.js` uses relative paths (`/api/v1/...`) which works when the frontend is served by FastAPI.

```bash
# Start backend (serves frontend at /)
cd emergency-response
.venv\Scripts\activate  # Windows
python -m uvicorn app.main:app --reload

# Open http://localhost:8000/
```

To test with a different API locally:

```javascript
// In browser console
window.CER_CONFIG.setApiUrl('http://localhost:8000');
location.reload();
```

## Testing Checklist

After deployment, verify:

- [ ] Frontend loads at `https://your-username.github.io/emergency-response/`
- [ ] Sign in works (register/login)
- [ ] Medical alert creation works
- [ ] Admin view loads (if admin user)
- [ ] Staff view loads (if staff user)
- [ ] Geolocation works (HTTPS required)
- [ ] No CORS errors in browser console
- [ ] API requests succeed (check Network tab)

## Troubleshooting

### CORS Errors

```
Access to fetch at 'https://api.example.com/api/v1/...' from origin 'https://username.github.io' has been blocked by CORS policy
```

**Solution:** Add your GitHub Pages URL to `cors_origins` in your backend config and redeploy backend.

### API Not Found (404)

```
GET https://api.example.com/api/v1/medical-alerts 404
```

**Solution:** Verify your API base URL is correct and the API is deployed. Test with curl:
```bash
curl https://your-api.com/api/v1/medical-alerts/config
```

### Mixed Content Errors

```
Mixed Content: The page at 'https://username.github.io/...' was loaded over HTTPS, but requested an insecure resource 'http://api.example.com/...'
```

**Solution:** Your API MUST use HTTPS. GitHub Pages is HTTPS-only.

### Geolocation Not Working

Geolocation API requires HTTPS and user permission. GitHub Pages provides HTTPS, but users must grant permission.

### Token/Storage Issues

The app uses `localStorage` for auth tokens. Ensure:
- Third-party cookies not blocking storage
- User not in private/incognito mode (may clear storage on close)

## Custom Domain (Optional)

If using a custom domain with GitHub Pages:

1. Add CNAME file to `frontend/CNAME` with your domain
2. Configure DNS (CNAME to `username.github.io`)
3. Enable "Enforce HTTPS" in Pages settings
4. Update backend CORS to allow your custom domain

## Security Considerations

1. **Never commit secrets** - API keys, JWT secrets, database URLs stay in backend
2. **HTTPS only** - GitHub Pages enforces this
3. **CORS restrictive** - Only allow your specific frontend origin
4. **Content Security Policy** - Backend sets strict CSP headers
5. **Token storage** - Tokens in localStorage (consider HttpOnly cookies for higher security)

## Updating the Frontend

Simply push changes to `main` branch:
```bash
git add frontend/
git commit -m "feat: update frontend"
git push origin main
# Workflow auto-deploys
```

To change API URL without code changes, use manual workflow dispatch.

## Advanced: Environment-Specific Configs

For staging/production separation:

1. Create `frontend/config.staging.js` and `frontend/config.production.js`
2. Modify workflow to select based on branch/tag
3. Deploy staging from `develop` branch, production from `main`

## Support

- **GitHub Pages docs:** https://docs.github.com/en/pages
- **GitHub Actions docs:** https://docs.github.com/en/actions
- **FastAPI CORS:** https://fastapi.tiangolo.com/tutorial/cors/