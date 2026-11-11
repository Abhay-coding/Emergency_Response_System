/**
 * Campus Medical Assistance - Frontend Configuration
 *
 * This file should be loaded BEFORE medical.js
 * Configure the API_BASE_URL to point to your deployed backend API
 *
 * For GitHub Pages deployment:
 * - Development: 'http://localhost:8000' or ''
 * - Production: 'https://your-api-domain.com' or use relative if API is on same domain
 * - Custom: Set to your API URL
 * - GitHub Pages: published unchanged by the deployment workflow.
 */

window.CER_CONFIG = {
  // API base URL - MUST end without trailing slash
  // Examples:
  // - Local development: 'http://localhost:8000'
  // - Production API: 'https://api.yourdomain.com'
  // - Same domain (if API is served from same origin): ''
  // - GitHub Pages with separate API: 'https://your-backend.onrender.com'
  API_BASE_URL: 'https://myypbjkalj.execute-api.ap-south-1.amazonaws.com',

  // API version path
  API_VERSION: '/api/v1',

  // Feature flags
  FEATURES: {
    ENABLE_GEOLOCATION: true,
    ENABLE_NOTIFICATIONS: true,
    ENABLE_MESSAGES: false,
    ENABLE_LOCATION_UPDATES: true,
  },

  // Build info (populated at build time)
  BUILD: {
    VERSION: '1.0.0',
    BUILD_TIME: new Date().toISOString(),
    ENVIRONMENT: 'production', // 'development', 'staging', 'production'
  },

  // Validate and get the full API URL
  getApiUrl(path) {
    const base = this.API_BASE_URL || window.location.origin;
    const version = this.API_VERSION;
    return `${base}${version}${path}`;
  },

  // GitHub Pages is static. It needs an explicit HTTPS API URL before alert
  // requests can be sent. Local FastAPI development keeps using same-origin.
  isApiConfigured() {
    return Boolean(this.API_BASE_URL) || !window.location.hostname.endsWith('.github.io');
  },

  // Initialize config from environment or URL params (for easy testing)
  init() {
    // Production pages must not accept a query-string or localStorage URL:
    // that could send credentials and alert details to an unrelated server.
    const localPage = ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname);
    const localApi = (value) => {
      try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname) && !url.username && !url.password; }
      catch { return false; }
    };
    // Check for URL parameter override (useful for testing)
    const urlParams = new URLSearchParams(window.location.search);
    const apiUrlParam = urlParams.get('api_url');
    if (localPage && apiUrlParam && localApi(apiUrlParam)) {
      this.API_BASE_URL = apiUrlParam;
      console.log('[CER_CONFIG] API URL overridden via URL param:', this.API_BASE_URL);
    }

    // Check for localStorage override (persisted user preference)
    try {
      const stored = localStorage.getItem('cer_api_url');
      if (localPage && stored && !apiUrlParam && localApi(stored)) {
        this.API_BASE_URL = stored;
        console.log('[CER_CONFIG] API URL loaded from localStorage:', this.API_BASE_URL);
      }
    } catch (e) {
      // Ignore localStorage errors
    }

    // Auto-detect if we're on GitHub Pages (username.github.io/repo-name)
    const isGitHubPages = window.location.hostname.endsWith('.github.io');
    if (isGitHubPages && !this.API_BASE_URL && !apiUrlParam) {
      console.warn('[CER_CONFIG] Running on GitHub Pages but no API_BASE_URL configured. Set window.CER_CONFIG.API_BASE_URL before loading medical.js');
      // You can set a default here for your deployed API:
      // this.API_BASE_URL = 'https://your-api-domain.com';
    }

    console.log('[CER_CONFIG] Initialized:', {
      API_BASE_URL: this.API_BASE_URL || '(same origin)',
      API_VERSION: this.API_VERSION,
      ENVIRONMENT: this.BUILD.ENVIRONMENT,
    });

    return this;
  },

  // Set API URL programmatically (call before app init)
  setApiUrl(url) {
    const parsed = new URL(url);
    if (!['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname) || !['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname) || !['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) throw new Error('API overrides are only available for local development');
    this.API_BASE_URL = url.replace(/\/$/, ''); // Remove trailing slash
    try {
      localStorage.setItem('cer_api_url', this.API_BASE_URL);
    } catch (e) {
      // Ignore
    }
    console.log('[CER_CONFIG] API URL set to:', this.API_BASE_URL);
  },

  // Clear stored API URL
  clearApiUrl() {
    this.API_BASE_URL = '';
    try {
      localStorage.removeItem('cer_api_url');
    } catch (e) {
      // Ignore
    }
  }
};

// Auto-initialize if not in a module context
if (typeof module === 'undefined') {
  window.CER_CONFIG.init();
}
