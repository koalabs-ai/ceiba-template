/**
 * koa-patterns-runtime.js — shared runtime for koa-base v1.1.0 patterns
 * Cross-ceiba runtime extracted from NDNS v2.html (2026-04-11).
 *
 * Usage: set window.KOA_CONFIG before loading this script.
 *   window.KOA_CONFIG = {
 *     ceiba_id: 'ndns',        // 'ndns' | 'cartelera' | 'sociales' | 'catrina'
 *     tz: 'America/Mexico_City',
 *     registry_url: '/api/registry/v1/patterns',  // optional
 *     ceiba_json_url: '/ceiba.json',               // optional
 *     installed_patterns: [],                      // optional — for checkPatternUpdates fallback
 *   };
 *   <script src="/koa-base/koa-patterns-runtime.js?v=20260411"></script>
 *
 * Attaches: window.koaPatterns namespace + globals for backward compat.
 */
(function (global) {
  'use strict';

  var CFG = global.KOA_CONFIG || {};
  var TZ = CFG.tz || 'America/Mexico_City';
  var CEIBA_ID = CFG.ceiba_id || 'unknown';
  var REGISTRY_URL = CFG.registry_url || '/api/registry/v1/patterns';
  var CEIBA_JSON_URL = CFG.ceiba_json_url || '/ceiba.json';

  // ─────────────────────────────────────────────────────────────────
  // TIMEZONE HELPERS (pattern: timezone-local-cdmx@1.0.0)
  // Use Intl.DateTimeFormat to get local-day strings without UTC drift.
  // ─────────────────────────────────────────────────────────────────
  function _localDateParts(date, tz) {
    var parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: tz || TZ,
      year: 'numeric', month: '2-digit', day: '2-digit'
    }).formatToParts(date || new Date());
    var y = parts.find(function (p) { return p.type === 'year'; }).value;
    var m = parts.find(function (p) { return p.type === 'month'; }).value;
    var d = parts.find(function (p) { return p.type === 'day'; }).value;
    return y + '-' + m + '-' + d;
  }
  function todayStr() { return _localDateParts(new Date()); }
  function fmtDate(d) {
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }
  function daysAgo(n) {
    var today = todayStr();
    var dt = new Date(today + 'T12:00:00');
    dt.setDate(dt.getDate() - n);
    return fmtDate(dt);
  }
  function monthStart() { return todayStr().slice(0, 7) + '-01'; }

  // ─────────────────────────────────────────────────────────────────
  // APP CONFIG PERSISTENCE (pattern: cog-per-app-config@1.0.0)
  // localStorage + optional backend sync. Emits koa-app-config-changed.
  // ─────────────────────────────────────────────────────────────────
  var APP_CFG_KEY = function (appName) { return 'koa_app_config.' + appName; };

  function getAppConfig(appName) {
    try {
      var raw = localStorage.getItem(APP_CFG_KEY(appName));
      if (raw) return JSON.parse(raw);
    } catch (e) {}
    var reg = global.APPS_REGISTRY_DATA || [];
    var app = reg.find(function (p) { return p.name === appName; });
    return (app && app.config_defaults) ? Object.assign({}, app.config_defaults) : {};
  }

  function saveAppConfig(appName, values) {
    try { localStorage.setItem(APP_CFG_KEY(appName), JSON.stringify(values)); } catch (e) {}
    try {
      fetch('/v1/admin/app-configs/' + encodeURIComponent(appName), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ceiba_id: CEIBA_ID, config_json: values })
      }).catch(function () {});
    } catch (e) {}
    try {
      global.dispatchEvent(new CustomEvent('koa-app-config-changed', { detail: { app: appName, config: values } }));
    } catch (e) {}
  }

  function resetAppConfig(appName) {
    try { localStorage.removeItem(APP_CFG_KEY(appName)); } catch (e) {}
    try {
      fetch('/v1/admin/app-configs/' + encodeURIComponent(appName), { method: 'DELETE' }).catch(function () {});
    } catch (e) {}
  }

  // ─────────────────────────────────────────────────────────────────
  // SEMVER + NAV-VER (pattern: semver-visible@1.0.0)
  // ─────────────────────────────────────────────────────────────────
  function semverCmp(a, b) {
    var pa = String(a || '0.0.0').split('.').map(function (n) { return parseInt(n, 10) || 0; });
    var pb = String(b || '0.0.0').split('.').map(function (n) { return parseInt(n, 10) || 0; });
    for (var i = 0; i < 3; i++) { if (pa[i] !== pb[i]) return pa[i] - pb[i]; }
    return 0;
  }
  function semverMin(arr) { return arr.filter(Boolean).sort(semverCmp)[0] || '0.0.0'; }

  function getNavVerStatus(installedPatterns, registryPatterns) {
    if (!registryPatterns || !registryPatterns.length) return 'legacy';
    var worst = 'ok';
    var rank = { ok: 0, patch: 1, minor: 2, major: 3 };
    installedPatterns.forEach(function (name) {
      var reg = registryPatterns.find(function (p) { return p.name === name; });
      if (!reg) return;
      var installedVer = '1.0.0';
      if (semverCmp(reg.version, installedVer) > 0) {
        var p1 = installedVer.split('.').map(Number);
        var p2 = reg.version.split('.').map(Number);
        var kind = 'patch';
        if (p2[0] > p1[0]) kind = 'major';
        else if (p2[1] > p1[1]) kind = 'minor';
        if (rank[kind] > rank[worst]) worst = kind;
      }
    });
    return worst;
  }

  function applyNavVersions() {
    var registry = global.APPS_REGISTRY_DATA;
    var pageMap = global.PAGE_PATTERN_MAP;
    if (!registry || !registry.length || !pageMap) return;
    Object.keys(pageMap).forEach(function (pageId) {
      var pats = pageMap[pageId] || [];
      if (!pats.length) return;
      var versions = pats.map(function (n) {
        var p = registry.find(function (x) { return x.name === n; });
        return p ? p.version : null;
      }).filter(Boolean);
      if (!versions.length) return;
      var minV = semverMin(versions);
      var status = getNavVerStatus(pats, registry);
      var navItem = document.querySelector('[data-page="' + pageId + '"]');
      if (!navItem) return;
      var ver = navItem.querySelector('.nav-ver');
      if (!ver) return;
      ver.setAttribute('data-status', status);
      ver.dataset.version = 'v' + minV;
      var breakdown = pats.map(function (n) {
        var p = registry.find(function (x) { return x.name === n; });
        return p ? (n + '@' + p.version) : n;
      }).join(' · ');
      navItem.setAttribute('title', 'v' + minV + ' | ' + breakdown);
    });
  }

  // ─────────────────────────────────────────────────────────────────
  // PATTERN UPDATES CHECK (Fase E)
  // ─────────────────────────────────────────────────────────────────
  function checkPatternUpdates(listElId) {
    var listEl = document.getElementById(listElId || 'updates-list');
    if (listEl) listEl.innerHTML = '<em>Checking registry...</em>';
    return fetch(REGISTRY_URL + '?' + Date.now(), { signal: AbortSignal.timeout(5000) })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var registry = data.patterns || [];
        return fetch(CEIBA_JSON_URL).then(function (cr) {
          return cr.ok ? cr.json() : null;
        }).catch(function () { return null; }).then(function (ceiba) {
          var installedMap = {};
          if (ceiba && ceiba._koa_gen && Array.isArray(ceiba._koa_gen.patterns)) {
            ceiba._koa_gen.patterns.forEach(function (p) {
              if (typeof p === 'string') installedMap[p] = '1.0.0';
              else if (p && p.name) installedMap[p.name] = p.version || '1.0.0';
            });
          } else {
            (CFG.installed_patterns || []).forEach(function (n) { installedMap[n] = '1.0.0'; });
          }
          var deltas = [];
          registry.forEach(function (r) {
            var inst = installedMap[r.name];
            if (inst && semverCmp(r.version, inst) > 0) {
              var p1 = inst.split('.').map(Number);
              var p2 = r.version.split('.').map(Number);
              var kind = 'patch';
              if (p2[0] > p1[0]) kind = 'major';
              else if (p2[1] > p1[1]) kind = 'minor';
              deltas.push({ name: r.name, from: inst, to: r.version, kind: kind, description: r.description });
            }
          });
          if (listEl) {
            if (!deltas.length) {
              listEl.innerHTML = '<div style="color:var(--green,#2ecc71)">✓ Todo al dia (catalogo v' + (data.catalog_version || '?') + ', ' + registry.length + ' patterns)</div>';
            } else {
              var rows = deltas.map(function (d) {
                var color = d.kind === 'major' ? 'var(--red,#e74c3c)' : d.kind === 'minor' ? 'var(--gold,#FBCA0B)' : 'var(--green,#2ecc71)';
                return '<div style="display:grid;grid-template-columns:24px 1fr 80px 100px;gap:10px;padding:8px 0;border-bottom:1px solid var(--border,#333);align-items:center">'
                  + '<span style="color:' + color + ';font-weight:700">' + (d.kind === 'major' ? '⚠' : d.kind === 'minor' ? '▲' : '·') + '</span>'
                  + '<div><strong>' + d.name + '</strong><div style="font-size:11px;color:var(--text3,#888)">' + (d.description || '') + '</div></div>'
                  + '<span style="font-family:monospace;font-size:12px;color:var(--text3,#888)">' + d.from + ' → <span style="color:' + color + '">' + d.to + '</span></span>'
                  + '<span style="font-size:11px;text-transform:uppercase;color:' + color + '">' + d.kind + '</span>'
                  + '</div>';
              }).join('');
              listEl.innerHTML = '<div style="margin-bottom:10px">Hay <strong>' + deltas.length + '</strong> updates disponibles en catalogo v' + (data.catalog_version || '?') + '</div>' + rows;
            }
          }
          return deltas;
        });
      }).catch(function (e) {
        if (listEl) listEl.innerHTML = '<div style="color:var(--red,#e74c3c)">Error: ' + e.message + '</div>';
        return [];
      });
  }

  // ─────────────────────────────────────────────────────────────────
  // BRAND-TAG auto-updater (pattern: brand-tag-dynamic@1.0.0)
  // Looks for #koa-brand-tag element and fills with ceiba_id + catalog_version
  // ─────────────────────────────────────────────────────────────────
  function updateBrandTag(catalogVersion) {
    var el = document.getElementById('koa-brand-tag');
    if (!el) return;
    var v = catalogVersion || (global.KOADRO_CATALOG_VERSION) || CFG.catalog_version || '1.1.0';
    el.textContent = CEIBA_ID + ' · koa-base ' + v;
    el.title = 'ceiba: ' + CEIBA_ID + ' · catalog: ' + v + ' · runtime: koa-patterns-runtime.js';
  }

  // Auto-init brand-tag on DOMContentLoaded
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { updateBrandTag(); });
  } else {
    updateBrandTag();
  }

  // ─────────────────────────────────────────────────────────────────
  // Expose to global
  // ─────────────────────────────────────────────────────────────────
  var api = {
    version: '1.1.0',
    config: CFG,
    // tz
    _localDateParts: _localDateParts,
    todayStr: todayStr,
    fmtDate: fmtDate,
    daysAgo: daysAgo,
    monthStart: monthStart,
    // config
    getAppConfig: getAppConfig,
    saveAppConfig: saveAppConfig,
    resetAppConfig: resetAppConfig,
    // semver
    semverCmp: semverCmp,
    semverMin: semverMin,
    getNavVerStatus: getNavVerStatus,
    applyNavVersions: applyNavVersions,
    // updates
    checkPatternUpdates: checkPatternUpdates,
    // brand
    updateBrandTag: updateBrandTag
  };

  global.koaPatterns = api;

  // Backward-compat globals — only define if not already present
  var shims = ['_localDateParts', 'todayStr', 'fmtDate', 'daysAgo', 'monthStart',
               'getAppConfig', 'saveAppConfig', 'resetAppConfig',
               'semverCmp', 'semverMin', 'getNavVerStatus', 'applyNavVersions',
               'checkPatternUpdates'];
  shims.forEach(function (name) {
    if (typeof global[name] === 'undefined') { global[name] = api[name]; }
  });
})(typeof window !== 'undefined' ? window : this);
