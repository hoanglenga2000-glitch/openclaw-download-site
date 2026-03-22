// OpenClaw Download Site - Interactive Features (v3.0 Platform Analytics + Dynamic Rendering)
(function() {
  'use strict';

  var API_BASE = '/api';

  function qs(sel, root){ return (root || document).querySelector(sel); }
  function qsa(sel, root){ return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function esc(s){ return String(s || ''); }
  function formatSize(bytes){ if(!bytes && bytes !== 0) return '-'; var mb = bytes / 1024 / 1024; return mb.toFixed(1) + ' MB'; }
  function shortDate(s){ if(!s) return '-'; return String(s).replace('T',' ').slice(0,16); }
  function getPageType(){
    var p = location.pathname;
    if (p === '/' || p === '') return 'home';
    if (p.indexOf('/downloads/') === 0) return 'downloads';
    if (p.indexOf('/guide/') === 0) return 'guide';
    if (p.indexOf('/security/') === 0) return 'security';
    if (p.indexOf('/releases/') === 0) return 'releases';
    if (p.indexOf('/community/') === 0) return 'community';
    if (p.indexOf('/dashboard/') === 0) return 'dashboard';
    if (p.indexOf('/admin/') === 0) return 'admin';
    return 'other';
  }


  function randomId(prefix){ return prefix + '_' + Math.random().toString(36).slice(2) + Date.now().toString(36); }
  function getOrCreateVisitorId(){
    var key='oc_visitor_id';
    var v=localStorage.getItem(key);
    if(!v){ v=randomId('v'); localStorage.setItem(key,v); }
    return v;
  }
  function getOrCreateSessionId(){
    var key='oc_session_id';
    var tsKey='oc_session_ts';
    var now=Date.now();
    var last=parseInt(sessionStorage.getItem(tsKey)||'0',10);
    var s=sessionStorage.getItem(key);
    if(!s || !last || (now-last)>30*60*1000){ s=randomId('s'); sessionStorage.setItem(key,s); }
    sessionStorage.setItem(tsKey,String(now));
    return s;
  }
  function enrichEventData(data){
    var obj = data || {};
    obj.visitor_id = getOrCreateVisitorId();
    obj.session_id = getOrCreateSessionId();
    return obj;
  }

  function track(eventType, data) {
    fetch(API_BASE + '/analytics/event', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_type: eventType, event_data: enrichEventData(data || {}) })
    }).catch(function(){});
  }

  function trackPageView() {
    track('page_view', { page: getPageType(), path: location.pathname, title: document.title, referrer: document.referrer || '' });
  }

  function bindCtaTracking() {
    qsa('a.btn, .nav-cta, .post-action, .sort-tab').forEach(function(el) {
      el.addEventListener('click', function() {
        track('cta_click', {
          page: getPageType(),
          text: (el.textContent || '').trim().slice(0, 120),
          href: el.getAttribute('href') || '',
          className: el.className || ''
        });
      });
    });
  }

  function initScrollReveal() {
    if (!('IntersectionObserver' in window)) return;
    var observer = new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('revealed');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });

    qsa('.card, .dl-card, .release-card, .feature-card, .post-card, .notice, .section-header, .hero-stat, .community-stat, .req-item, .step').forEach(function(el) {
      el.classList.add('scroll-reveal');
      observer.observe(el);
    });
  }

  function animateNumber(el, target, duration) {
    if (!el || isNaN(target)) return;
    var startTime = null;
    function step(timestamp) {
      if (!startTime) startTime = timestamp;
      var progress = Math.min((timestamp - startTime) / duration, 1);
      var eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = Math.floor(eased * target).toLocaleString();
      if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function initMagneticButtons() {
    qsa('.btn-primary, .btn-lg, .nav-cta').forEach(function(btn) {
      btn.addEventListener('mousemove', function(e) {
        var rect = btn.getBoundingClientRect();
        var x = e.clientX - rect.left - rect.width / 2;
        var y = e.clientY - rect.top - rect.height / 2;
        btn.style.transform = 'translate(' + x * 0.15 + 'px,' + y * 0.15 + 'px)';
      });
      btn.addEventListener('mouseleave', function() { btn.style.transform = ''; });
    });
  }

  function initParallax() {
    var hero = qs('.hero');
    if (!hero) return;
    var ticking = false;
    window.addEventListener('scroll', function() {
      if (!ticking) {
        requestAnimationFrame(function() {
          var scrolled = window.pageYOffset;
          if (scrolled < window.innerHeight) hero.style.backgroundPositionY = scrolled * 0.3 + 'px';
          ticking = false;
        });
        ticking = true;
      }
    });
  }

  function initCursorGlow() {
    if (window.innerWidth < 769) return;
    var glow = document.createElement('div');
    glow.className = 'cursor-glow';
    document.body.appendChild(glow);
    var mx = 0, my = 0, cx = 0, cy = 0;
    document.addEventListener('mousemove', function(e) { mx = e.clientX; my = e.clientY; });
    function animate() {
      cx += (mx - cx) * 0.08;
      cy += (my - cy) * 0.08;
      glow.style.left = cx + 'px';
      glow.style.top = cy + 'px';
      requestAnimationFrame(animate);
    }
    animate();
  }

  function initCardTilt() {
    qsa('.dl-card, .brand-hero-card').forEach(function(card) {
      card.addEventListener('mousemove', function(e) {
        var rect = card.getBoundingClientRect();
        var x = (e.clientX - rect.left) / rect.width - 0.5;
        var y = (e.clientY - rect.top) / rect.height - 0.5;
        card.style.transform = 'perspective(800px) rotateY(' + x * 6 + 'deg) rotateX(' + -y * 6 + 'deg) scale(1.01)';
      });
      card.addEventListener('mouseleave', function() {
        card.style.transform = '';
        card.style.transition = 'transform 0.5s ease';
        setTimeout(function() { card.style.transition = ''; }, 500);
      });
    });
  }

  function initTypingEffect() {
    var badge = qs('.hero-badge');
    if (!badge) return;
    var dot = badge.querySelector('.dot');
    if (dot) dot.style.boxShadow = '0 0 8px rgba(34,197,94,.6)';
  }

  function extractVersion(href) {
    var m = (href || '').match(/Setup[_-](\d+\.\d+\.\d+)/i) || (href || '').match(/[_-]v?(\d+\.\d+\.\d+)/i);
    return m ? m[1] : 'unknown';
  }

  function logDownload(version, platform) {
    fetch(API_BASE + '/download/log', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(enrichEventData({ version: version, platform: platform }))
    }).catch(function(){});
    track('download_click', { version: version, platform: platform, page: getPageType() });
  }

  function renderLatestVersion(v) {
    if (!v || !v.version) return;
    var downloadPath = v.file_path || ('/downloads/' + v.file_name);
    var sizeHuman = formatSize(v.size_bytes);
    var dateText = shortDate(v.published_at);

    qsa('[data-dynamic="latest-version"]').forEach(function(el){ el.textContent = 'v' + v.version; });
    qsa('[data-dynamic="latest-version-plain"]').forEach(function(el){ el.textContent = v.version; });
    qsa('[data-dynamic="latest-file-name"]').forEach(function(el){ el.textContent = v.file_name; });
    qsa('[data-dynamic="latest-size"]').forEach(function(el){ el.textContent = sizeHuman; });
    qsa('[data-dynamic="latest-date"]').forEach(function(el){ el.textContent = dateText; });
    qsa('[data-dynamic="latest-sha-full"]').forEach(function(el){ el.textContent = v.sha256; });
    qsa('[data-dynamic="latest-sha-short"]').forEach(function(el){ el.textContent = (v.sha256 || '').slice(0, 10) + '...' + (v.sha256 || '').slice(-8); });
    qsa('[data-dynamic="latest-download-label"]').forEach(function(el){ el.textContent = '下载 Windows 安装包 (' + sizeHuman + ')'; });
    qsa('[data-dynamic="latest-download-short"]').forEach(function(el){ el.textContent = '下载 v' + v.version + ' (' + sizeHuman + ')'; });
    qsa('[data-dynamic="latest-hero-badge"]').forEach(function(el){ el.textContent = 'v' + v.version + ' 正式发布'; });
    qsa('[data-dynamic="latest-powershell"]').forEach(function(el){ el.textContent = 'Get-FileHash "' + v.file_name + '" -Algorithm SHA256'; });
    qsa('[data-dynamic-href="latest-download"]').forEach(function(el){ el.setAttribute('href', downloadPath); });

    var meta = qs('#live-version-meta');
    if (meta) {
      meta.innerHTML = '' +
        '<div class="dl-meta-row"><span class="meta-label">文件名</span><span class="meta-value" data-dynamic="latest-file-name">' + esc(v.file_name) + '</span></div>' +
        '<div class="dl-meta-row"><span class="meta-label">平台</span><span class="meta-value">Windows 10 / 11 (x64)</span></div>' +
        '<div class="dl-meta-row"><span class="meta-label">文件大小</span><span class="meta-value" data-dynamic="latest-size">' + esc(sizeHuman) + '</span></div>' +
        '<div class="dl-meta-row"><span class="meta-label">发布日期</span><span class="meta-value" data-dynamic="latest-date">' + esc(dateText) + '</span></div>' +
        '<div class="dl-meta-row"><span class="meta-label">SHA256</span><span class="meta-value mono" data-dynamic="latest-sha-full">' + esc(v.sha256) + '</span></div>';
    }

    qsa('.meta-value.mono').forEach(function(el) {
      el.style.cursor = 'pointer';
      el.title = 'Click to copy';
      el.onclick = function() {
        navigator.clipboard.writeText(el.textContent.trim()).then(function() {
          var orig = el.textContent;
          el.textContent = 'Copied!';
          el.style.color = '#22c55e';
          setTimeout(function() { el.textContent = orig; el.style.color = ''; }, 1500);
        });
      };
    });
  }

  
  function renderReleaseList(versions) {
    var wrap = qs('#release-dynamic-list');
    if (!wrap || !versions || !versions.length) return;
    wrap.innerHTML = versions.map(function(v){
      var sizeHuman = formatSize(v.size_bytes);
      return '<div class="release-card ' + (v.is_latest ? 'latest' : '') + '" style="margin-bottom:24px;">' +
        '<div class="release-header"><h3>v' + esc(v.version) + '</h3>' +
        (v.is_latest ? '<span class="tag tag-latest">Latest</span>' : '') +
        '<span class="tag tag-stable">' + esc(v.platform) + '</span><span class="tag tag-date">' + esc(shortDate(v.published_at)) + '</span></div>' +
        '<div class="grid grid-2" style="gap:24px;"><div><ul class="release-body"><li>' + esc(v.release_notes || 'Release published') + '</li></ul>' +
        '<div class="release-footer"><a class="btn btn-primary" href="' + esc(v.file_path) + '">下载 ' + esc(v.file_name) + '</a><a class="btn btn-secondary" href="/security/">校验信息</a></div></div>' +
        '<div><div class="dl-meta"><div class="dl-meta-row"><span class="meta-label">文件名</span><span class="meta-value">' + esc(v.file_name) + '</span></div>' +
        '<div class="dl-meta-row"><span class="meta-label">大小</span><span class="meta-value">' + esc(sizeHuman) + '</span></div>' +
        '<div class="dl-meta-row"><span class="meta-label">SHA256</span><span class="meta-value mono">' + esc(v.sha256) + '</span></div></div></div></div></div>';
    }).join('');
  }

  function loadVersionsList() {
    return fetch(API_BASE + '/versions')
      .then(function(res){ return res.json(); })
      .then(function(data){ renderReleaseList(data.versions || []); return data.versions || []; })
      .catch(function(err){ console.error('Failed to load versions list:', err); return []; });
  }

function loadLatestVersion() {
    return fetch(API_BASE + '/versions/latest?platform=windows-x64')
      .then(function(res){ return res.json(); })
      .then(function(v){ renderLatestVersion(v); return v; })
      .catch(function(err){ console.error('Failed to load latest version:', err); return null; });
  }

  function loadStats() {
    fetch(API_BASE + '/stats')
      .then(function(res) { return res.json(); })
      .then(function(data) {
        qsa('.dl-count').forEach(function(el) {
          if (data.total > 0) {
            el.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> ' + data.total.toLocaleString() + ' 次下载';
            el.style.display = 'inline-flex';
          }
        });
        qsa('.hero-stat .num').forEach(function(el) {
          var text = (el.textContent || '').trim();
          var num = parseInt(text.replace(/[^\d]/g, ''));
          if (!isNaN(num) && num > 0 && text.indexOf('MB') === -1) animateNumber(el, num, 1200);
        });
      })
      .catch(function(err) { console.error('Failed to load stats:', err); });
  }

  function bindDownloadLogging() {
    qsa('a[href*=".exe"], a[data-dynamic-href="latest-download"]').forEach(function(link) {
      link.addEventListener('click', function() {
        var version = extractVersion(link.getAttribute('href'));
        logDownload(version, 'windows-x64');
        var toast = document.createElement('div');
        toast.className = 'download-toast';
        toast.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> 下载已开始...';
        document.body.appendChild(toast);
        setTimeout(function() { toast.classList.add('show'); }, 10);
        setTimeout(function() { toast.classList.remove('show'); setTimeout(function() { toast.remove(); }, 300); }, 3000);
      });
    });
  }

  function copyToClipboard(text, btn) {
    navigator.clipboard.writeText((text || '').trim()).then(function() {
      var orig = btn.innerHTML;
      btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> Copied!';
      btn.classList.add('copied');
      setTimeout(function() { btn.innerHTML = orig; btn.classList.remove('copied'); }, 2000);
    });
  }

  function bindCopyButtons() {
    qsa('.code-block, .verify-cmd').forEach(function(block) {
      if (block.querySelector('.copy-btn')) return;
      var btn = document.createElement('button');
      btn.className = 'copy-btn';
      btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg> Copy';
      btn.onclick = function(e) {
        e.preventDefault();
        var label = block.querySelector('.code-label');
        var text = block.textContent;
        if (label) text = text.replace(label.textContent, '');
        copyToClipboard(text, btn);
      };
      block.style.position = 'relative';
      block.appendChild(btn);
    });
  }

  function initOsDetect() {
    var osDetects = qsa('[id="os-detect"]');
    if (!osDetects.length) return;
    var ua = navigator.userAgent;
    var os = 'Unknown';
    if (ua.indexOf('Win') !== -1) os = 'Windows';
    else if (ua.indexOf('Mac') !== -1) os = 'macOS';
    else if (ua.indexOf('Linux') !== -1) os = 'Linux';
    else if (ua.indexOf('Android') !== -1) os = 'Android';
    else if (ua.indexOf('iPhone') !== -1 || ua.indexOf('iPad') !== -1) os = 'iOS';

    osDetects.forEach(function(el) {
      if (os === 'Windows') {
        el.innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><path d="M0 3.449L9.75 2.1v9.451H0m10.949-9.602L24 0v11.4H10.949M0 12.6h9.75v9.451L0 20.699M10.949 12.6H24V24l-12.9-1.801"/></svg> Detected: ' + os + ' — this installer is for you!';
        el.style.display = 'inline-flex';
      } else if (os !== 'Unknown') {
        el.innerHTML = '⚠️ Detected: ' + os + ' — Windows version only. ' + os + ' coming soon.';
        el.style.display = 'inline-flex';
        el.style.background = 'rgba(245,158,11,0.1)';
        el.style.borderColor = 'rgba(245,158,11,0.2)';
        el.style.color = '#fcd68d';
      }
    });
  }

  function bindAnchors() {
    qsa('a[href^="#"]').forEach(function(a) {
      a.addEventListener('click', function(e) {
        var target = qs(a.getAttribute('href'));
        if (target) {
          e.preventDefault();
          target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      });
    });
  }

  function init() {
    trackPageView();
    bindCtaTracking();
    initScrollReveal();
    initMagneticButtons();
    initParallax();
    initCursorGlow();
    initCardTilt();
    initTypingEffect();
    bindCopyButtons();
    initOsDetect();
    bindAnchors();
    loadLatestVersion().then(function(){ bindDownloadLogging(); });
    loadVersionsList();
    loadStats();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
