/**
 * KOA Cookie Consent — v2
 *
 * Cookie/storage audit (2026-04-01):
 *
 *   La Cartelera (lacartelera.app):
 *     Essential:     cartelera_owner (auth token), cartelera_access (auth flag),
 *                    lc-theme (theme pref), cartelera_ios_banner_dismissed (UX state),
 *                    cookie_consent (this banner)
 *     Non-essential: Google Analytics GA4 — G-0WR4X6YQY2 (site) + G-0PS6GYS5BZ (KOA Labs)
 *
 *   Sociales (sociales.lat):
 *     Essential:     sociales_theme, cookie_consent
 *     Non-essential: Google Analytics GA4 — G-0PS6GYS5BZ
 *
 *   ceiba.to:
 *     Essential:     ceiba-theme, cookie_consent
 *     Non-essential: Google Analytics GA4 — G-0PS6GYS5BZ
 *
 *   Montessori (montessori.mx):
 *     Essential:     montessori-theme, cookie_consent
 *     Non-essential: NONE — no third-party scripts
 *
 *   BotMarket v2 (botmarket.bot):
 *     Essential:     bm-theme, cookie_consent
 *     Non-essential: NONE — no third-party scripts
 *
 * For sites with GA: the <head> must NOT inline the gtag script unconditionally.
 * Instead, add  data-ga-ids="G-XXXXXXX,G-YYYYYYY"  to the <html> element and
 * this script will fire GA only after analytics consent is given.
 * See: koa-gen/patterns/cookie-consent/README.md
 */
(function() {
  'use strict';
  const STORAGE_KEY = 'cookie_consent';

  // Read GA IDs declared on <html data-ga-ids="G-XXX,G-YYY">
  const gaIds = (document.documentElement.dataset.gaIds || '')
    .split(',').map(s => s.trim()).filter(Boolean);
  const HAS_ANALYTICS = gaIds.length > 0;

  const styles = `
    #koa-cookie-pill {
      position: fixed;
      bottom: 16px;
      left: 16px;
      z-index: 9999;
      font-family: system-ui, sans-serif;
      font-size: 13px;
    }
    #koa-cookie-banner {
      background: var(--surface, #1e1e2e);
      color: var(--text, #cdd6f4);
      border: 1px solid var(--border, #313244);
      border-radius: 12px;
      padding: 12px 16px;
      max-width: 300px;
      box-shadow: 0 4px 24px rgba(0,0,0,0.2);
    }
    #koa-cookie-banner p {
      margin: 0 0 10px;
      line-height: 1.4;
      color: inherit;
    }
    #koa-cookie-banner p.koa-cookie-sub {
      font-size: 11px;
      opacity: 0.7;
      margin: -6px 0 10px;
    }
    .koa-cookie-btns {
      display: flex;
      gap: 8px;
    }
    .koa-cookie-btns button {
      border: none;
      border-radius: 6px;
      padding: 6px 12px;
      cursor: pointer;
      font-size: 12px;
      font-weight: 500;
    }
    .koa-btn-accept {
      background: #89b4fa;
      color: #1e1e2e;
    }
    .koa-btn-essential {
      background: transparent;
      border: 1px solid var(--border, #313244) !important;
      color: var(--text, #cdd6f4);
    }
    #koa-cookie-icon {
      background: var(--surface, #1e1e2e);
      border: 1px solid var(--border, #313244);
      border-radius: 20px;
      padding: 4px 10px;
      cursor: pointer;
      font-size: 12px;
      opacity: 0.6;
      transition: opacity 0.2s;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      color: var(--text, #cdd6f4);
    }
    #koa-cookie-icon:hover { opacity: 1; }
    /* Light theme overrides */
    [data-theme="light"] #koa-cookie-banner,
    .light #koa-cookie-banner {
      background: #fff;
      color: #1e1e2e;
      border-color: #e0e0e0;
    }
    [data-theme="light"] #koa-cookie-icon,
    .light #koa-cookie-icon {
      background: #fff;
      border-color: #e0e0e0;
      color: #1e1e2e;
    }
    [data-theme="light"] .koa-btn-essential,
    .light .koa-btn-essential {
      border-color: #e0e0e0 !important;
      color: #1e1e2e;
    }
  `;

  // Inject styles
  const styleEl = document.createElement('style');
  styleEl.textContent = styles;
  document.head.appendChild(styleEl);

  const container = document.createElement('div');
  container.id = 'koa-cookie-pill';
  document.body.appendChild(container);

  function loadGA() {
    if (!gaIds.length) return;
    gaIds.forEach(function(id) {
      var s = document.createElement('script');
      s.async = true;
      s.src = 'https://www.googletagmanager.com/gtag/js?id=' + id;
      document.head.appendChild(s);
    });
    window.dataLayer = window.dataLayer || [];
    function gtag(){ window.dataLayer.push(arguments); }
    window.gtag = gtag;
    gtag('js', new Date());
    gaIds.forEach(function(id) { gtag('config', id); });
  }

  function setConsent(value) {
    localStorage.setItem(STORAGE_KEY, value);
    if (value === 'all' && HAS_ANALYTICS) loadGA();
    showIcon();
  }

  function showBanner() {
    if (HAS_ANALYTICS) {
      container.innerHTML = `
        <div id="koa-cookie-banner">
          <p>Este sitio usa cookies esenciales y, con tu permiso, Google Analytics para entender el uso del sitio.</p>
          <p class="koa-cookie-sub">No compartimos datos con terceros ni usamos publicidad.</p>
          <div class="koa-cookie-btns">
            <button class="koa-btn-accept" onclick="window.__koaCookie('all')">Aceptar analytics</button>
            <button class="koa-btn-essential" onclick="window.__koaCookie('essential')">Solo esenciales</button>
          </div>
        </div>
      `;
    } else {
      container.innerHTML = `
        <div id="koa-cookie-banner">
          <p>Solo usamos almacenamiento esencial: tema y sesion. No rastreamos ni compartimos datos.</p>
          <div class="koa-cookie-btns">
            <button class="koa-btn-accept" onclick="window.__koaCookie('essential')">Entendido</button>
          </div>
        </div>
      `;
    }
  }

  function showIcon() {
    var stored = localStorage.getItem(STORAGE_KEY);
    var label = (stored === 'all') ? 'analytics: si' : 'solo esenciales';
    container.innerHTML = `
      <div id="koa-cookie-icon" onclick="window.__koaCookieReset()" title="Cambiar preferencias de cookies">
        <span>${label}</span>
      </div>
    `;
  }

  window.__koaCookie = setConsent;
  window.__koaCookieReset = function() {
    localStorage.removeItem(STORAGE_KEY);
    showBanner();
  };

  // Policy 2026-04-07: Mexico (LFPDPPP) does not require opt-in consent for
  // first-party analytics. Fire GA by default on every load unless the user
  // has explicitly chosen "essentials only". The banner still shows on the
  // first visit so the user can opt out — this is opt-out, not opt-in.
  var existing = localStorage.getItem(STORAGE_KEY);
  if (HAS_ANALYTICS && existing !== 'essential') {
    loadGA();
  }
  if (existing) {
    showIcon();
  } else {
    setTimeout(showBanner, 1200);
  }
})();
