/**
 * Campus Emergency Response System - Frontend Application
 * Professional implementation with accessibility, validation, and UX best practices
 * Based on ui-ux-pro-max design system: "Accessible & Ethical" style
 */

// ============================================================================
// Configuration & Constants
// ============================================================================

const CONFIG = {
  API_BASE: window.location.origin,
  ENDPOINTS: {
    REGISTER: '/api/v1/auth/register',
    LOGIN: '/api/v1/auth/login',
    REFRESH: '/api/v1/auth/refresh',
    LOGOUT: '/api/v1/auth/logout',
    LOGOUT_ALL: '/api/v1/auth/logout/all',
    ME: '/api/v1/auth/me',
    INCIDENTS: '/api/v1/incidents',
    INCIDENT_IMAGE: (id) => `/api/v1/incidents/${id}/image`,
    INCIDENT_ASSIGN: (id) => `/api/v1/incidents/${id}/assign`,
    INCIDENT_STATUS: (id) => `/api/v1/incidents/${id}/status`,
    ANALYTICS: '/api/v1/incidents/analytics/summary',
  },
  STORAGE_KEYS: {
    TOKEN: 'cer_token',
    USER: 'cer_user',
  },
  VALIDATION: {
    PASSWORD_MIN_LENGTH: 8,
    TITLE_MAX_LENGTH: 150,
    DESCRIPTION_MAX_LENGTH: 3000,
    LOCATION_MAX_LENGTH: 200,
  },
  TOAST_DURATION: 5000,
  DEBOUNCE_DELAY: 300,
};

// ============================================================================
// State Management
// ============================================================================

const state = {
  token: null,
  user: null,
  incidents: [],
  authMode: 'login', // 'login' | 'register'
  isLoading: false,
  lastRequestId: 0,
};

// ============================================================================
// Utility Functions
// ============================================================================

/**
 * Generate a unique request ID for tracking
 */
function generateRequestId() {
  return ++state.lastRequestId;
}

/**
 * Safely get element by ID
 */
function $(id) {
  return document.getElementById(id);
}

/**
 * Debounce function
 */
function debounce(fn, delay) {
  let timeoutId;
  return (...args) => {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(() => fn.apply(this, args), delay);
  };
}

/**
 * Format date for display
 */
function formatDate(dateString) {
  if (!dateString) return '';
  const date = new Date(dateString);
  if (isNaN(date.getTime())) return '';
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * Get priority badge class
 */
function getPriorityClass(priority) {
  return `badge--priority badge--${priority}`;
}

/**
 * Get status badge class
 */
function getStatusClass(status) {
  return `badge--status badge--${status.replace('_', '')}`;
}

/**
 * Capitalize first letter
 */
function capitalize(str) {
  return str.charAt(0).toUpperCase() + str.slice(1);
}

/**
 * Show loading overlay
 */
function showLoading(text = 'Loading...') {
  const overlay = $('loading-overlay');
  const textEl = $('loading-text');
  if (textEl) textEl.textContent = text;
  overlay.classList.remove('hidden');
  overlay.setAttribute('aria-hidden', 'false');
}

/**
 * Hide loading overlay
 */
function hideLoading() {
  const overlay = $('loading-overlay');
  overlay.classList.add('hidden');
  overlay.setAttribute('aria-hidden', 'true');
}

/**
 * Check if user prefers reduced motion
 */
function prefersReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Generate stagger delay for animation
 */
function getStaggerDelay(index, baseDelay = 60) {
  if (prefersReducedMotion()) return 0;
  return Math.min(baseDelay * (index + 1), 300);
}

// ============================================================================
// Toast/Notice System
// ============================================================================

const toastQueue = [];
let toastTimeout = null;

/**
 * Show toast notification
 */
function showToast(message, type = 'info', duration = CONFIG.TOAST_DURATION) {
  // Remove any existing toast of same type to prevent duplicates
  const existingToast = document.querySelector(`.notice.${type}`);
  if (existingToast) {
    existingToast.remove();
  }

  const toast = document.createElement('div');
  toast.className = `notice ${type}`;
  toast.setAttribute('role', 'status');
  toast.setAttribute('aria-live', type === 'error' ? 'assertive' : 'polite');
  toast.setAttribute('aria-atomic', 'true');

  const icons = {
    info: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    success: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
    error: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    warning: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
  };

  toast.innerHTML = `
    <div class="toast-icon" aria-hidden="true">${icons[type] || icons.info}</div>
    <div class="toast-content"></div>
    <button class="toast-close" aria-label="Dismiss" type="button">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
    </button>
  `;
  toast.querySelector('.toast-content').textContent = message;

  // Add close button handler
  const closeBtn = toast.querySelector('.toast-close');
  closeBtn.addEventListener('click', () => removeToast(toast));

  // Add to DOM
  $('toast-container').appendChild(toast);

  // Force reflow for animation
  toast.offsetHeight;

  // Auto-remove after duration
  setTimeout(() => removeToast(toast), duration);

  return toast;
}

/**
 * Remove toast with animation
 */
function removeToast(toast) {
  if (!toast || toast.classList.contains('removing')) return;
  toast.classList.add('removing');
  toast.style.animation = 'slideInUp 0.3s ease-in reverse forwards';
  setTimeout(() => toast.remove(), 300);
}

/**
 * Show error toast (alias for showToast with type 'error')
 */
function showError(message, duration) {
  return showToast(message, 'error', duration);
}

/**
 * Show success toast
 */
function showSuccess(message, duration) {
  return showToast(message, 'success', duration);
}

/**
 * Show warning toast
 */
function showWarning(message, duration) {
  return showToast(message, 'warning', duration);
}

/**
 * Show info toast
 */
function showInfo(message, duration) {
  return showToast(message, 'info', duration);
}

// ============================================================================
// Validation System
// ============================================================================

const Validators = {
  /**
   * Validate email format
   */
  email(value) {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!value) return 'Email is required';
    if (!emailRegex.test(value)) return 'Enter a valid email address';
    return null;
  },

  /**
   * Validate password strength
   */
  password(value) {
    if (!value) return 'Password is required';
    if (value.length < CONFIG.VALIDATION.PASSWORD_MIN_LENGTH) {
      return `Password must be at least ${CONFIG.VALIDATION.PASSWORD_MIN_LENGTH} characters`;
    }
    if (!/[a-z]/.test(value)) return 'Password must contain at least one lowercase letter';
    if (!/[A-Z]/.test(value)) return 'Password must contain at least one uppercase letter';
    if (!/\d/.test(value)) return 'Password must contain at least one number';
    if (!/[@$!%*?&]/.test(value)) return 'Password must contain at least one special character (@$!%*?&)';
    return null;
  },

  /**
   * Validate required field
   */
  required(value, fieldName = 'Field') {
    if (!value || !value.trim()) return `${fieldName} is required`;
    return null;
  },

  /**
   * Validate title
   */
  title(value) {
    const err = this.required(value, 'Title');
    if (err) return err;
    if (value.length > CONFIG.VALIDATION.TITLE_MAX_LENGTH) {
      return `Title must be ${CONFIG.VALIDATION.TITLE_MAX_LENGTH} characters or less`;
    }
    return null;
  },

  /**
   * Validate description
   */
  description(value) {
    const err = this.required(value, 'Description');
    if (err) return err;
    if (value.length > CONFIG.VALIDATION.DESCRIPTION_MAX_LENGTH) {
      return `Description must be ${CONFIG.VALIDATION.DESCRIPTION_MAX_LENGTH} characters or less`;
    }
    if (value.trim().length < 10) {
      return 'Description must be at least 10 characters';
    }
    return null;
  },

  /**
   * Validate location
   */
  location(value) {
    const err = this.required(value, 'Location');
    if (err) return err;
    if (value.length > CONFIG.VALIDATION.LOCATION_MAX_LENGTH) {
      return `Location must be ${CONFIG.VALIDATION.LOCATION_MAX_LENGTH} characters or less`;
    }
    return null;
  },

  /**
   * Validate category
   */
  category(value) {
    if (!value) return 'Please select a category';
    const validCategories = ['Medical', 'Fire', 'Security', 'Infrastructure', 'Other'];
    if (!validCategories.includes(value)) return 'Invalid category';
    return null;
  },

  /**
   * Validate priority
   */
  priority(value) {
    if (!value) return 'Please select a priority';
    const validPriorities = ['low', 'medium', 'high', 'critical'];
    if (!validPriorities.includes(value)) return 'Invalid priority';
    return null;
  },

  /**
   * Validate name
   */
  name(value) {
    const err = this.required(value, 'Name');
    if (err) return err;
    if (value.trim().length < 2) return 'Name must be at least 2 characters';
    if (value.trim().length > 100) return 'Name must be 100 characters or less';
    return null;
  },
};

/**
 * Validate a form and return errors object
 */
function validateForm(formData, rules) {
  const errors = {};

  for (const [field, validator] of Object.entries(rules)) {
    const value = formData[field];
    const error = validator(value);
    if (error) {
      errors[field] = error;
    }
  }

  return errors;
}

/**
 * Show field error
 */
function showFieldError(fieldId, message) {
  const errorEl = $(`${fieldId}-error`);
  const inputEl = $(fieldId);

  if (errorEl) {
    errorEl.textContent = message;
    errorEl.classList.remove('hidden');
  }

  if (inputEl) {
    inputEl.setAttribute('aria-invalid', 'true');
    inputEl.setAttribute('aria-describedby', `${fieldId}-error`);
    inputEl.classList.add('input-error');
  }
}

/**
 * Clear field error
 */
function clearFieldError(fieldId) {
  const errorEl = $(`${fieldId}-error`);
  const inputEl = $(fieldId);

  if (errorEl) {
    errorEl.textContent = '';
    errorEl.classList.add('hidden');
  }

  if (inputEl) {
    inputEl.removeAttribute('aria-invalid');
    inputEl.removeAttribute('aria-describedby');
    inputEl.classList.remove('input-error');
  }
}

/**
 * Clear all field errors in a form
 */
function clearAllFieldErrors(form) {
  const inputs = form.querySelectorAll('input, select, textarea');
  inputs.forEach(input => clearFieldError(input.id));
}

/**
 * Show error summary
 */
function showErrorSummary(summaryId, errors) {
  const summaryEl = $(summaryId);
  const listEl = summaryEl?.querySelector('ul');

  if (!summaryEl || !listEl) return;

  listEl.innerHTML = '';

  for (const [field, message] of Object.entries(errors)) {
    const li = document.createElement('li');
    const link = document.createElement('a');
    link.href = `#${field}`;
    link.textContent = message;
    link.addEventListener('click', (e) => {
      e.preventDefault();
      const input = $(field);
      if (input) {
        input.focus({ preventScroll: false });
        input.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    });
    li.appendChild(link);
    listEl.appendChild(li);
  }

  summaryEl.classList.remove('hidden');
  summaryEl.focus();
}

/**
 * Hide error summary
 */
function hideErrorSummary(summaryId) {
  const summaryEl = $(summaryId);
  if (summaryEl) {
    summaryEl.classList.add('hidden');
  }
}

// ============================================================================
// API Client
// ============================================================================

class ApiClient {
  constructor() {
    this.baseURL = CONFIG.API_BASE;
    this.token = null;
  }

  setToken(token) {
    this.token = token;
  }

  async request(path, options = {}) {
    const requestId = generateRequestId();
    const headers = new Headers(options.headers || {});

    if (this.token) {
      headers.set('Authorization', `Bearer ${this.token}`);
    }

    if (options.body && !(options.body instanceof FormData)) {
      headers.set('Content-Type', 'application/json');
    }

    // Add request ID for tracing
    headers.set('X-Request-ID', requestId.toString());

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);

    try {
      const response = await fetch(`${this.baseURL}${path}`, {
        ...options,
        headers,
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      const text = await response.text();
      let data = null;

      if (text) {
        try {
          data = JSON.parse(text);
        } catch {
          data = text;
        }
      }

      if (!response.ok) {
        const detail = data && typeof data === 'object'
          ? data.detail || data.message
          : null;

        // Handle 401 - token expired
        if (response.status === 401) {
          await this.handleUnauthorized();
          throw new Error('Session expired. Please sign in again.');
        }

        throw new Error(detail || `Request failed (${response.status})`);
      }

      return data;
    } catch (error) {
      clearTimeout(timeoutId);

      if (error.name === 'AbortError') {
        throw new Error('Request timed out. Please try again.');
      }

      if (error instanceof TypeError && error.message.includes('fetch')) {
        throw new Error('Network error. Please check your connection.');
      }

      throw error;
    }
  }

  async handleUnauthorized() {
    this.token = null;
    state.token = null;
    state.user = null;
    this.clearAuthState();
    showError('Your session has expired. Please sign in again.');
    setTimeout(() => {
      showAuthSection();
      hideDashboard();
    }, 1500);
  }

  clearAuthState() {
    try {
      localStorage.removeItem(CONFIG.STORAGE_KEYS.TOKEN);
      localStorage.removeItem(CONFIG.STORAGE_KEYS.USER);
    } catch (e) {
      // Ignore storage errors
    }
  }

  // Auth endpoints
  async register(name, email, password) {
    return this.request(CONFIG.ENDPOINTS.REGISTER, {
      method: 'POST',
      body: JSON.stringify({ name, email, password }),
    });
  }

  async login(email, password) {
    const form = new URLSearchParams();
    form.set('username', email);
    form.set('password', password);

    const response = await fetch(`${this.baseURL}${CONFIG.ENDPOINTS.LOGIN}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: form.toString(),
    });

    const text = await response.text();
    let data = null;
    if (text) {
      try { data = JSON.parse(text); } catch { data = text; }
    }

    if (!response.ok) {
      const detail = data && typeof data === 'object' ? data.detail : null;
      throw new Error(detail || 'Login failed');
    }

    return data;
  }

  async getMe() {
    return this.request(CONFIG.ENDPOINTS.ME);
  }

  async logout() {
    return this.request(CONFIG.ENDPOINTS.LOGOUT, { method: 'POST' });
  }

  async logoutAll() {
    return this.request(CONFIG.ENDPOINTS.LOGOUT_ALL, { method: 'POST' });
  }

  // Incident endpoints
  async getIncidents(params = {}) {
    const searchParams = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        searchParams.set(key, value);
      }
    });
    const query = searchParams.toString();
    return this.request(`${CONFIG.ENDPOINTS.INCIDENTS}${query ? `?${query}` : ''}`);
  }

  async createIncident(data) {
    return this.request(CONFIG.ENDPOINTS.INCIDENTS, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getIncident(id) {
    return this.request(`${CONFIG.ENDPOINTS.INCIDENTS}/${id}`);
  }

  async uploadImage(id, file) {
    const formData = new FormData();
    formData.append('file', file);
    return this.request(`${CONFIG.ENDPOINTS.INCIDENTS}/${id}/image`, {
      method: 'POST',
      body: formData,
    });
  }

  async assignIncident(id, responderId) {
    return this.request(`${CONFIG.ENDPOINTS.INCIDENTS}/${id}/assign`, {
      method: 'PATCH',
      body: JSON.stringify({ responder_id: responderId }),
    });
  }

  async updateStatus(id, status) {
    return this.request(`${CONFIG.ENDPOINTS.INCIDENTS}/${id}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    });
  }

  async getAnalytics() {
    return this.request(CONFIG.ENDPOINTS.ANALYTICS);
  }
}

// ============================================================================
// Main Application Controller
// ============================================================================

const api = new ApiClient();

// Initialize auth state from storage
function initAuthFromStorage() {
  try {
    const token = localStorage.getItem(CONFIG.STORAGE_KEYS.TOKEN);
    const userStr = localStorage.getItem(CONFIG.STORAGE_KEYS.USER);

    if (token && userStr) {
      api.setToken(token);
      state.token = token;
      state.user = JSON.parse(userStr);
      return true;
    }
  } catch (e) {
    console.warn('Failed to restore auth from storage:', e);
  }
  return false;
}

// ============================================================================
// UI State Management
// ============================================================================

function showAuthSection() {
  $('auth-section').classList.remove('hidden');
  $('dashboard').classList.add('hidden');
  $('logout-button').classList.add('hidden');
  $('logout-button').setAttribute('hidden', '');
  $('user-label').textContent = 'Not signed in';
  setAuthMode('login');
}

function hideAuthSection() {
  $('auth-section').classList.add('hidden');
}

function showDashboard() {
  $('dashboard').classList.remove('hidden');
  $('auth-section').classList.add('hidden');
  $('logout-button').classList.remove('hidden');
  $('logout-button').removeAttribute('hidden');
  if (state.user) {
    $('user-label').textContent = state.user.name || state.user.email;
  }
}

function hideDashboard() {
  $('dashboard').classList.add('hidden');
}

function setAuthMode(mode) {
  state.authMode = mode;
  const isRegister = mode === 'register';

  $('login-tab').classList.toggle('tab--active', !isRegister);
  $('login-tab').setAttribute('aria-selected', !isRegister);
  $('login-tab').setAttribute('tabindex', isRegister ? '-1' : '0');

  $('register-tab').classList.toggle('tab--active', isRegister);
  $('register-tab').setAttribute('aria-selected', isRegister);
  $('register-tab').setAttribute('tabindex', isRegister ? '0' : '-1');

  $('register-fields').classList.toggle('hidden', !isRegister);

  $('name').required = isRegister;
  $('password').autocomplete = isRegister ? 'new-password' : 'current-password';
  $('password-hint').classList.toggle('hidden', !isRegister);
  $('auth-submit').querySelector('.button-text').textContent = isRegister ? 'Create account' : 'Sign in';

  // Clear errors when switching modes
  clearAllFieldErrors($('auth-form'));
  hideErrorSummary('form-error-summary');
}

// ============================================================================
// Auth Handlers
// ============================================================================

async function handleRegister(formData) {
  const submitBtn = $('auth-submit');
  setButtonLoading(submitBtn, true);
  hideErrorSummary('form-error-summary');
  clearAllFieldErrors($('auth-form'));

  try {
    const user = await api.register(
      formData.name.trim(),
      formData.email.trim().toLowerCase(),
      formData.password
    );

    showSuccess('Account created successfully. You can now sign in.');
    setAuthMode('login');
    $('password').value = '';
    $('name').value = '';
  } catch (error) {
    if (error.message.includes('duplicate') || error.message.includes('already')) {
      showFieldError('email', 'This email is already registered');
      showErrorSummary('form-error-summary', { email: 'This email is already registered' });
    } else {
      showError(error.message);
    }
  } finally {
    setButtonLoading(submitBtn, false);
  }
}

async function handleLogin(formData) {
  const submitBtn = $('auth-submit');
  setButtonLoading(submitBtn, true);
  hideErrorSummary('form-error-summary');
  clearAllFieldErrors($('auth-form'));

  try {
    const result = await api.login(
      formData.email.trim().toLowerCase(),
      formData.password
    );

    if (!result.access_token) {
      throw new Error('No access token received');
    }

    // Save token and user
    api.setToken(result.access_token);
    state.token = result.access_token;

    const user = await api.getMe();
    state.user = user;

    // Persist to localStorage
    try {
      localStorage.setItem(CONFIG.STORAGE_KEYS.TOKEN, result.access_token);
      localStorage.setItem(CONFIG.STORAGE_KEYS.USER, JSON.stringify(user));
    } catch (e) {
      console.warn('Failed to persist auth:', e);
    }

    showSuccess('Signed in successfully.');
    hideAuthSection();
    showDashboard();
    await loadIncidents();
  } catch (error) {
    if (error.message.includes('Incorrect') || error.message.includes('invalid')) {
      showFieldError('password', 'Incorrect email or password');
      showErrorSummary('form-error-summary', { password: 'Incorrect email or password' });
    } else {
      showError(error.message);
    }
  } finally {
    setButtonLoading($('auth-submit'), false);
  }
}

async function handleLogout() {
  try {
    await api.logout();
  } catch (e) {
    console.warn('Logout request failed:', e);
  } finally {
    api.clearAuthState();
    api.setToken(null);
    state.token = null;
    state.user = null;
    state.incidents = [];
    showInfo('You have signed out.');
    showAuthSection();
    hideDashboard();
  }
}

async function handleLogoutAll() {
  try {
    await api.logoutAll();
  } catch (e) {
    console.warn('Logout all request failed:', e);
  } finally {
    api.clearAuthState();
    api.setToken(null);
    state.token = null;
    state.user = null;
    state.incidents = [];
    showInfo('Signed out from all devices.');
    showAuthSection();
    hideDashboard();
  }
}

/**
 * Set button loading state
 */
function setButtonLoading(button, loading) {
  if (!button) return;

  const loader = button.querySelector('.button-loader');
  const text = button.querySelector('.button-text');

  if (loading) {
    button.disabled = true;
    if (text) text.classList.add('hidden');
    if (loader) loader.classList.remove('hidden');
  } else {
    button.disabled = false;
    if (text) text.classList.remove('hidden');
    if (loader) loader.classList.add('hidden');
  }
}

// ============================================================================
// Incident Management
// ============================================================================

async function loadIncidents() {
  const refreshBtn = $('refresh-button');
  if (refreshBtn) refreshBtn.disabled = true;

  try {
    const result = await api.getIncidents({ limit: 100, category: 'Medical' });
    state.incidents = Array.isArray(result?.items) ? result.items : [];
    updateStats(state.incidents);
    $('total-count').title = `${result?.total ?? state.incidents.length} total records`;
    renderIncidents();
  } catch (error) {
    showError(`Failed to load incidents: ${error.message}`);
  } finally {
    if (refreshBtn) refreshBtn.disabled = false;
  }
}

async function handleCreateIncident(formData) {
  const submitBtn = $('incident-form').querySelector('button[type="submit"]');
  setButtonLoading(submitBtn, true);
  hideErrorSummary('incident-error-summary');
  clearAllFieldErrors($('incident-form'));

  try {
    const { image, ...incidentData } = formData;
    const incident = await api.createIncident(incidentData);
    if (image instanceof File && image.size > 0) {
      try {
        await api.uploadImage(incident.id, image);
      } catch (uploadError) {
        showWarning(`Report saved, but the photo could not be uploaded: ${uploadError.message}`);
      }
    }
    showSuccess('Medical request sent successfully.');
    $('incident-form').reset();
    $('image-upload').dispatchEvent(new Event('change'));
    $('incident-form').dispatchEvent(new Event('incident-reset'));
    await loadIncidents();
  } catch (error) {
    // Try to parse validation errors
    if (error.message && error.message.includes('validation')) {
      // Try to parse field-specific errors
      try {
        const errorData = JSON.parse(error.message.replace(/.*?({.*)/, '$1'));
        if (errorData.detail && Array.isArray(errorData.detail)) {
          const fieldErrors = {};
          errorData.detail.forEach(err => {
            if (err.loc && err.loc[1]) {
              fieldErrors[err.loc[1]] = err.msg;
            }
          });
          if (Object.keys(fieldErrors).length > 0) {
            Object.entries(fieldErrors).forEach(([field, msg]) => {
              showFieldError(field, msg);
            });
            showErrorSummary('incident-error-summary', fieldErrors);
            return;
          }
        }
      } catch (e) {
        // Ignore parse errors
      }
    }
    showError(`Failed to send medical request: ${error.message}`);
  } finally {
    setButtonLoading(submitBtn, false);
  }
}

function updateStats(incidents) {
  const total = incidents.length;
  const reported = incidents.filter(i => i.status === 'reported').length;
  const inProgress = incidents.filter(i =>
    ['assigned', 'in_progress'].includes(i.status)
  ).length;
  const resolved = incidents.filter(i => i.status === 'resolved').length;

  animateCount('total-count', total);
  animateCount('reported-count', reported);
  animateCount('progress-count', inProgress);
  animateCount('resolved-count', resolved);

  const countEl = $('incident-count');
  if (countEl) {
    countEl.textContent = `${total} record${total !== 1 ? 's' : ''}`;
  }
}

/**
 * Animate counter value
 */
function animateCount(elementId, target) {
  const el = $(elementId);
  if (!el) return;

  const current = parseInt(el.textContent) || 0;
  if (current === target) return;

  const duration = 500;
  const startTime = performance.now();

  function animate(now) {
    const elapsed = now - startTime;
    const progress = Math.min(elapsed / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3); // easeOutCubic
    const value = Math.round(current + (target - current) * eased);
    el.textContent = value;

    if (progress < 1) {
      requestAnimationFrame(animate);
    }
  }

  requestAnimationFrame(animate);
}

function renderIncidents() {
  const list = $('incident-list');
  if (!list) return;
  const status = $('status-filter')?.value;
  const priority = $('priority-filter')?.value;
  const sort = $('sort-by')?.value;
  const incidents = state.incidents.filter(incident =>
    (!status || incident.status === status) && (!priority || incident.priority === priority)
  );

  if (!incidents || !incidents.length) {
    list.innerHTML = `
      <div class="empty-state" aria-hidden="true">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
          <line x1="16" y1="13" x2="8" y2="13"/>
          <line x1="16" y1="17" x2="8" y2="17"/>
          <polyline points="10 9 9 9 8 9"/>
        </svg>
        <p>No medical requests yet</p>
        <p class="empty-hint">Use the form to request assistance</p>
      </div>
    `;
    return;
  }

  // Sort by created_at descending
  const sorted = [...incidents].sort((a, b) => {
    const dateDelta = new Date(b.created_at) - new Date(a.created_at);
    const ranks = { critical: 4, high: 3, medium: 2, low: 1 };
    if (sort === 'priority_desc' || sort === 'priority_asc') {
      const priorityDelta = (ranks[b.priority] || 0) - (ranks[a.priority] || 0);
      return (sort === 'priority_asc' ? -priorityDelta : priorityDelta) || dateDelta;
    }
    return sort === 'created_asc' ? -dateDelta : dateDelta;
  });

  list.innerHTML = sorted.map((incident, index) => `
    <article class="incident-card stagger-in" style="animation-delay: ${getStaggerDelay(index)}ms" role="listitem" tabindex="0">
      <div class="incident-top">
        <div>
          <h3>${escapeHtml(incident.title || `Incident #${incident.id}`)}</h3>
          <div class="incident-meta">
            <span>#${incident.id}</span>
            <span>${escapeHtml(incident.location || 'Location not specified')}</span>
          </div>
        </div>
      </div>

      ${incident.description ? `<p>${escapeHtml(incident.description)}</p>` : ''}

      <div class="badges">
        <span class="badge badge--priority badge--${incident.priority}">${capitalize(incident.priority)}</span>
        <span class="badge badge--status badge--${incident.status.replace('_', '')}">${capitalize(incident.status.replace('_', ' '))}</span>
        <span class="badge">${escapeHtml(incident.category || 'Other')}</span>
      </div>

      ${incident.created_at ? `
        <div class="incident-date">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
            <line x1="16" y1="2" x2="16" y2="6"/>
            <line x1="8" y1="2" x2="8" y2="6"/>
            <line x1="3" y1="10" x2="21" y2="10"/>
          </svg>
          Submitted: ${formatDate(incident.created_at)}
        </div>
      ` : ''}
    </article>
  `).join('');

  // Trigger stagger animations
  if (!prefersReducedMotion()) {
    requestAnimationFrame(() => {
      const cards = list.querySelectorAll('.stagger-in');
      cards.forEach((card, i) => {
        card.style.animationDelay = `${getStaggerDelay(i)}ms`;
      });
    });
  }
}

// ============================================================================
// Password Toggle
// ============================================================================

function initPasswordToggle() {
  const toggles = document.querySelectorAll('.password-toggle');

  toggles.forEach(toggle => {
    toggle.addEventListener('click', () => {
      const wrapper = toggle.closest('.password-wrapper');
      const input = wrapper?.querySelector('input');
      const eyeIcon = toggle.querySelector('.icon-eye');
      const eyeOffIcon = toggle.querySelector('.icon-eye-off');
      const isPassword = input?.type === 'password';

      if (input) {
        input.type = isPassword ? 'text' : 'password';
      }
      if (eyeIcon) eyeIcon.classList.toggle('hidden', isPassword);
      if (eyeOffIcon) eyeOffIcon.classList.toggle('hidden', !isPassword);
      toggle.setAttribute('aria-pressed', !isPassword);
      toggle.setAttribute('aria-label', isPassword ? 'Hide password' : 'Show password');
    });
  });
}

// ============================================================================
// Form Validation on Blur
// ============================================================================

function initFormValidation() {
  // Auth form
  const authForm = $('auth-form');
  if (authForm) {
    const inputs = authForm.querySelectorAll('input, select, textarea');
    inputs.forEach(input => {
      input.addEventListener('blur', debounce(() => validateField(input), 100));
      input.addEventListener('input', () => {
        if (input.classList.contains('input-error')) {
          validateField(input);
        }
      });
    });

    authForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      hideErrorSummary('form-error-summary');
      clearAllFieldErrors(authForm);

      const formData = new FormData(authForm);
      const data = Object.fromEntries(formData);

      // Validate all fields
      const rules = {
        email: v => Validators.email(v),
        password: v => state.authMode === 'register' ? Validators.password(v) : Validators.required(v, 'Password'),
      };

      if (state.authMode === 'register') {
        rules.name = v => Validators.name(v);
      }

      const errors = validateForm(data, rules);

      if (Object.keys(errors).length > 0) {
        Object.entries(errors).forEach(([field, msg]) => showFieldError(field, msg));
        showErrorSummary('form-error-summary', errors);
        return;
      }

      if (state.authMode === 'register') {
        await handleRegister(data);
      } else {
        await handleLogin(data);
      }
    });
  }

  // Incident form
  const incidentForm = $('incident-form');
  if (incidentForm) {
    const inputs = incidentForm.querySelectorAll('input, select, textarea');
    inputs.forEach(input => {
      input.addEventListener('blur', debounce(() => validateField(input), 100));
      input.addEventListener('input', () => {
        if (input.classList.contains('input-error')) {
          validateField(input);
        }
      });
    });

    incidentForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      hideErrorSummary('incident-error-summary');
      clearAllFieldErrors(incidentForm);

      const formData = new FormData(incidentForm);
      const data = Object.fromEntries(formData);

      const rules = {
        title: v => Validators.title(v),
        description: v => Validators.description(v),
        category: v => Validators.category(v),
        location: v => Validators.location(v),
        priority: v => Validators.priority(v),
      };

      const errors = validateForm(data, rules);

      if (Object.keys(errors).length > 0) {
        Object.entries(errors).forEach(([field, msg]) => showFieldError(field, msg));
        showErrorSummary('incident-error-summary', errors);
        return;
      }

      await handleCreateIncident(data);
    });
  }
}

/**
 * Validate a single field
 */
function validateField(input) {
  if (!input || !input.id) return true;

  const fieldId = input.id;
  let error = null;
  const value = input.type === 'checkbox' ? input.checked : input.value;

  // Determine validator based on field
  switch (fieldId) {
    case 'email':
      error = Validators.email(value);
      break;
    case 'password':
      error = state.authMode === 'register' ? Validators.password(value) : Validators.required(value, 'Password');
      break;
    case 'name':
      error = Validators.name(value);
      break;
    case 'title':
      error = Validators.title(value);
      break;
    case 'description':
      error = Validators.description(value);
      break;
    case 'location':
      error = Validators.location(value);
      break;
    case 'category':
      error = Validators.category(value);
      break;
    case 'priority':
      error = Validators.priority(value);
      break;
    default:
      if (input.required && !value) {
        error = Validators.required(value, input.labels?.[0]?.textContent?.replace('*', '').trim() || 'Field');
      }
  }

  if (error) {
    showFieldError(fieldId, error);
    return false;
  } else {
    clearFieldError(fieldId);
    return true;
  }
}

// ============================================================================
// Incident Form Step Navigation
// ============================================================================

const FORM_STEPS = 4;

function initIncidentFormNavigation() {
  const form = $('incident-form');
  if (!form) return;

  // Next/Previous buttons
  const nextBtn = $('next-step-btn');
  const prevBtn = $('prev-step-btn');
  const prevBtnReview = $('prev-step');
  const formSteps = form.querySelectorAll('.form-step-content');
  const stepIndicators = form.querySelectorAll('.form-step');

  function showStep(stepNumber) {
    // Validate current step before proceeding
    const currentStepContent = form.querySelector(`.form-step-content[data-step="${getCurrentStep()}"]`);
    if (currentStepContent && stepNumber > getCurrentStep()) {
      const inputs = currentStepContent.querySelectorAll('input[required], select[required], textarea[required]');
      let valid = true;
      inputs.forEach(input => {
        if (!validateField(input)) valid = false;
      });
      if (!valid) return;
    }

    // Hide all steps
    formSteps.forEach(step => step.classList.add('hidden'));
    // Show target step
    const targetStep = form.querySelector(`.form-step-content[data-step="${stepNumber}"]`);
    if (targetStep) targetStep.classList.remove('hidden');

    // Update step indicators
    stepIndicators.forEach((indicator, index) => {
      const stepNum = index + 1;
      indicator.classList.remove('form-step--active', 'form-step--complete');
      indicator.removeAttribute('aria-current');
      if (stepNum === stepNumber) {
        indicator.classList.add('form-step--active');
        indicator.setAttribute('aria-current', 'step');
      } else if (stepNum < stepNumber) {
        indicator.classList.add('form-step--complete');
      }
    });

    // Update navigation buttons
    if (prevBtn) prevBtn.classList.toggle('hidden', stepNumber === 1);
    if (prevBtn) prevBtn.disabled = stepNumber === 1;
    if (nextBtn) {
      if (stepNumber === FORM_STEPS) {
        nextBtn.classList.add('hidden');
      } else {
        nextBtn.classList.remove('hidden');
      }
    }
    if (prevBtnReview) {
      prevBtnReview.classList.toggle('hidden', stepNumber !== FORM_STEPS);
    }

    // Populate review step if on last step
    if (stepNumber === FORM_STEPS) {
      populateReviewSummary();
    }

    updateFormCompletion();
  }

  function getCurrentStep() {
    const visibleStep = form.querySelector('.form-step-content:not(.hidden)');
    if (visibleStep) {
      return parseInt(visibleStep.dataset.step, 10);
    }
    return 1;
  }

  function populateReviewSummary() {
    const title = $('title')?.value || '—';
    const priority = $('priority')?.value || '—';
    const location = $('location')?.value || '—';
    const description = $('description')?.value || '—';
    const imageInput = $('image-upload');
    const imageFile = imageInput?.files?.[0];

    $('review-title') && ($('review-title').textContent = title);
    $('review-priority') && ($('review-priority').textContent = priority);
    $('review-location') && ($('review-location').textContent = location);
    $('review-description') && ($('review-description').textContent = description);
    $('review-image') && ($('review-image').textContent = imageFile ? imageFile.name : 'No image');
  }

  function updateFormCompletion() {
    let filled = 0;
    let total = 0;

    formSteps.forEach(step => {
      const inputs = step.querySelectorAll('input[required], select[required], textarea[required]');
      inputs.forEach(input => {
        if (input.type === 'hidden') return;
        total++;
        if (input.type === 'file') {
          if (input.files && input.files.length > 0) filled++;
        } else if (input.value && input.value.trim()) {
          filled++;
        }
      });
    });

    const percentage = total > 0 ? Math.round((filled / total) * 100) : 0;
    $('form-completion') && ($('form-completion').textContent = `${percentage}%`);
  }

  // Character counters
  function initCharacterCounters() {
    const counters = [
      { input: 'title', max: 150, countEl: 'title-count' },
      { input: 'description', max: 3000, countEl: 'description-count' },
      { input: 'location', max: 200, countEl: 'location-count' },
    ];

    counters.forEach(({ input: inputId, max, countEl: countId }) => {
      const input = $(inputId);
      const countEl = $(countId);
      if (input && countEl) {
        const updateCount = () => {
          countEl.textContent = input.value.length;
          countEl.classList.toggle('text-warning', input.value.length > max * 0.9);
          countEl.classList.toggle('text-error', input.value.length > max);
        };
        input.addEventListener('input', updateCount);
        updateCount();
      }
    });
  }

  // Image preview
  function initImagePreview() {
    const imageInput = $('image-upload');
    const preview = $('image-preview');
    const previewImg = $('preview-image');
    const removeBtn = preview?.querySelector('.image-remove');

    if (imageInput && preview && previewImg) {
      imageInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) {
          // Validate file
          if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
            showFieldError('image-upload', 'Please select a JPEG, PNG, or WebP image');
            imageInput.value = '';
            return;
          }
          if (file.size > 5 * 1024 * 1024) {
            showFieldError('image-upload', 'Image must be less than 5MB');
            imageInput.value = '';
            return;
          }
          clearFieldError('image-upload');

          const reader = new FileReader();
          reader.onload = (event) => {
            previewImg.src = event.target.result;
            preview.classList.remove('hidden');
            updateFormCompletion();
          };
          reader.readAsDataURL(file);
        } else {
          preview.classList.add('hidden');
          previewImg.src = '';
          updateFormCompletion();
        }
      });

      if (removeBtn) {
        removeBtn.addEventListener('click', () => {
          imageInput.value = '';
          preview.classList.add('hidden');
          previewImg.src = '';
          clearFieldError('image-upload');
          updateFormCompletion();
        });
      }
    }
  }

  // Event listeners for navigation
  if (nextBtn) {
    nextBtn.addEventListener('click', () => {
      const current = getCurrentStep();
      if (current < FORM_STEPS) {
        showStep(current + 1);
      }
    });
  }

  if (prevBtn) {
    prevBtn.addEventListener('click', () => {
      const current = getCurrentStep();
      if (current > 1) {
        showStep(current - 1);
      }
    });
  }

  if (prevBtnReview) {
    prevBtnReview.addEventListener('click', () => {
      showStep(FORM_STEPS - 1);
    });
  }

  // Initialize
  initCharacterCounters();
  initImagePreview();
  updateFormCompletion();
  showStep(1);
  form.addEventListener('incident-reset', () => {
    showStep(1);
    for (const id of ['title-count', 'description-count', 'location-count']) $(id).textContent = '0';
    updateFormCompletion();
  });
}

// ============================================================================
// UI Helpers
// ============================================================================

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/**
 * Initialize all event listeners
 */
function initEventListeners() {
  // Auth tabs
  $('login-tab')?.addEventListener('click', () => setAuthMode('login'));
  $('register-tab')?.addEventListener('click', () => setAuthMode('register'));

  // Password toggles
  initPasswordToggle();

  // Form validation
  initFormValidation();

  // Incident form navigation
  initIncidentFormNavigation();

  // Logout buttons
  $('logout-button')?.addEventListener('click', handleLogout);
  // Could add logout all to a dropdown or context menu

  // Refresh button
  $('refresh-button')?.addEventListener('click', loadIncidents);
  ['status-filter', 'priority-filter', 'sort-by'].forEach(id => {
    $(id)?.addEventListener('change', renderIncidents);
  });

  // Keyboard navigation for tabs
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        tab.click();
      }
    });
  });

  // Close toast on click outside
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.notice')) {
      // Could add toast dismissal logic here
    }
  });

  // Escape key to close modals/overlays
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      // Close any open modals
      const overlay = $('loading-overlay');
      if (overlay && !overlay.classList.contains('hidden')) {
        hideLoading();
      }
    }
  });
}

/**
 * Check if user is already authenticated
 */
async function checkAuth() {
  if (initAuthFromStorage()) {
    try {
      api.setToken(state.token);
      const user = await api.getMe();
      state.user = user;
      localStorage.setItem(CONFIG.STORAGE_KEYS.USER, JSON.stringify(user));
      hideAuthSection();
      showDashboard();
      await loadIncidents();
    } catch (error) {
      console.warn('Auth check failed:', error);
      api.clearAuthState();
      state.token = null;
      state.user = null;
      showAuthSection();
    }
  } else {
    showAuthSection();
  }
}

// ============================================================================
// Initialization
// ============================================================================

async function init() {
  // Initialize event listeners
  initEventListeners();

  // Set initial auth mode
  setAuthMode('login');

  if (window.location.protocol === 'file:') {
    showAuthSection();
    $('local-file-notice').classList.remove('hidden');
    $('auth-form').querySelectorAll('input, button').forEach(control => { control.disabled = true; });
    console.info('Open the app through the FastAPI server to use medical requests.');
    return;
  }

  // Check for existing auth
  await checkAuth();

  console.log('Campus Medical Assistance initialized');
}

// Start the application when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}

// Export for debugging
window.CER = {
  state,
  api,
  showToast,
  showError,
  showSuccess,
  showWarning,
  showInfo,
  loadIncidents,
};
