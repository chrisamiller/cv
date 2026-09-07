// ============================================================================
// site.js — ported from sbryngelson/academic-website-template + a custom
// navbar toggle (replaces Bootstrap's collapse). Vanilla, no dependencies.
// ============================================================================

(function () {
  'use strict';

  // ----- Dark mode toggle -----
  var toggle = document.getElementById('darkModeToggle');
  var icon = document.getElementById('themeIcon');

  function updateIcon() {
    if (!icon) return;
    var theme = document.documentElement.getAttribute('data-bs-theme');
    icon.className = theme === 'dark' ? 'fa-solid fa-moon' : 'fa-solid fa-sun';
  }

  if (toggle) {
    updateIcon();
    toggle.addEventListener('click', function () {
      var current = document.documentElement.getAttribute('data-bs-theme');
      var next = current === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-bs-theme', next);
      try { localStorage.setItem('theme', next); } catch (e) {}
      updateIcon();
    });
  }

  // ----- Mobile navbar toggle (replaces Bootstrap collapse) -----
  var navToggler = document.querySelector('.navbar-toggler');
  var navCollapse = document.getElementById('navbarNav');

  function closeNav() {
    if (!navCollapse) return;
    navCollapse.classList.remove('show');
    if (navToggler) navToggler.setAttribute('aria-expanded', 'false');
  }

  if (navToggler && navCollapse) {
    navToggler.addEventListener('click', function (e) {
      e.stopPropagation();
      var open = navCollapse.classList.toggle('show');
      navToggler.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    navCollapse.addEventListener('click', function (e) {
      if (e.target.closest('.nav-link')) closeNav();
    });
    document.addEventListener('click', function (e) {
      if (navCollapse.classList.contains('show') &&
          !e.target.closest('.navbar')) closeNav();
    });
    window.addEventListener('resize', function () {
      if (window.innerWidth >= 768) closeNav();
    });
  }

  // ----- Publication BIB / abstract expand-collapse -----
  document.addEventListener('click', function (e) {
    var button = e.target.closest('[data-toggle-target]');
    if (!button) return;
    var target = document.getElementById(button.getAttribute('data-toggle-target'));
    if (target) target.classList.toggle('show');
  });

  // ----- Publication filter -----
  var searchInput = document.getElementById('pubSearch');
  if (searchInput) {
    searchInput.addEventListener('input', function () {
      var query = this.value.toLowerCase().trim();
      var shown = 0;
      var entries = document.querySelectorAll('[data-pub-searchable]');
      entries.forEach(function (entry) {
        var hit = !query || entry.textContent.toLowerCase().indexOf(query) !== -1;
        entry.style.display = hit ? '' : 'none';
        if (hit) shown++;
      });
      var counter = document.getElementById('pubCount');
      if (counter) {
        counter.textContent = query
          ? shown + ' of ' + entries.length + ' publications'
          : entries.length + ' publications';
      }
    });
  }

  // ----- Publication sort (date | citations) -----
  var pubSort = document.getElementById('pubSort');
  var pubList = document.getElementById('pubList');
  if (pubSort && pubList) {
    pubSort.addEventListener('change', function () {
      var byCites = this.value === 'cites';
      var items = Array.prototype.slice.call(pubList.querySelectorAll('.pub-entry'));
      items.sort(function (a, b) {
        var an = +a.getAttribute('data-n') || 0;
        var bn = +b.getAttribute('data-n') || 0;
        if (byCites) {
          var ac = +a.getAttribute('data-cites') || 0;
          var bc = +b.getAttribute('data-cites') || 0;
          if (ac !== bc) return bc - ac;
        }
        return bn - an;
      });
      items.forEach(function (el) {
        pubList.appendChild(el);
        el.classList.add('visible');  // don't leave a reordered entry mid-fade
      });
    });
  }

  // ----- Copy BibTeX buttons -----
  document.querySelectorAll('.pub-collapse').forEach(function (collapse) {
    if (!collapse.id || collapse.id.indexOf('bib-') !== 0) return;
    var pre = collapse.querySelector('pre');
    if (!pre) return;
    var wrapper = document.createElement('div');
    wrapper.className = 'copy-wrapper';
    var btn = document.createElement('button');
    btn.className = 'copy-btn';
    btn.innerHTML = '<i class="fa-regular fa-copy"></i>';
    btn.title = 'Copy to clipboard';
    btn.addEventListener('click', function () {
      navigator.clipboard.writeText(pre.textContent.trim()).then(function () {
        btn.innerHTML = '<i class="fa-solid fa-check"></i>';
        btn.classList.add('copied');
        setTimeout(function () {
          btn.innerHTML = '<i class="fa-regular fa-copy"></i>';
          btn.classList.remove('copied');
        }, 2000);
      });
    });
    pre.parentNode.insertBefore(wrapper, pre);
    wrapper.appendChild(pre);
    wrapper.appendChild(btn);
  });

  // ----- Publication year badges (fallback if not pre-rendered) -----
  document.querySelectorAll('.pub-entry').forEach(function (entry) {
    if (entry.querySelector('.year-badge')) return;
    var year = entry.getAttribute('data-year');
    if (!year) {
      var m = entry.textContent.match(/\((\d{4})\)/) || entry.textContent.match(/\b(19|20)\d{2}\b/);
      year = m && m[0];
    }
    if (year) {
      var badge = document.createElement('span');
      badge.className = 'year-badge';
      badge.textContent = year;
      entry.insertBefore(badge, entry.firstChild);
    }
  });

  // ----- Back to top -----
  var topBtn = document.createElement('button');
  topBtn.className = 'back-to-top';
  topBtn.innerHTML = '<i class="fa-solid fa-arrow-up"></i>';
  topBtn.setAttribute('aria-label', 'Back to top');
  document.body.appendChild(topBtn);
  topBtn.addEventListener('click', function () {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });

  // ----- Navbar scroll shadow -----
  var navbar = document.querySelector('.navbar');
  window.addEventListener('scroll', function () {
    if (navbar) navbar.classList.toggle('scrolled', window.scrollY > 10);
    topBtn.classList.toggle('visible', window.scrollY > 400);
  }, { passive: true });

  // ----- Fade-in on scroll -----
  var fadeElements = document.querySelectorAll('.fade-in-section');
  if (fadeElements.length && 'IntersectionObserver' in window) {
    // threshold 0: any sliver visible reveals it — a percentage threshold
    // never fires for elements taller than (100 / pct)% of the viewport.
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0, rootMargin: '0px 0px -40px 0px' });
    fadeElements.forEach(function (el) { observer.observe(el); });
    // Safety net: anything still hidden after load (observer never fired,
    // e.g. layout quirks) gets revealed so content is never stuck invisible.
    window.addEventListener('load', function () {
      setTimeout(function () {
        fadeElements.forEach(function (el) {
          var r = el.getBoundingClientRect();
          if (r.top < window.innerHeight) el.classList.add('visible');
        });
      }, 200);
    });
  } else {
    fadeElements.forEach(function (el) { el.classList.add('visible'); });
  }

  // ----- Site search overlay (Cmd/Ctrl+K) -----
  var searchToggleBtn = document.getElementById('searchToggle');
  var searchOverlay = document.getElementById('searchOverlay');
  var searchInputEl = document.getElementById('searchInput');
  var searchResultsEl = document.getElementById('searchResults');
  var searchData = null;

  function openSearch() {
    if (!searchOverlay) return;
    searchOverlay.classList.add('open');
    setTimeout(function () { if (searchInputEl) searchInputEl.focus(); }, 80);
  }
  function closeSearch() {
    if (!searchOverlay) return;
    searchOverlay.classList.remove('open');
    if (searchInputEl) searchInputEl.value = '';
    if (searchResultsEl) searchResultsEl.innerHTML = '';
  }
  if (searchToggleBtn) searchToggleBtn.addEventListener('click', openSearch);
  if (searchOverlay) {
    searchOverlay.addEventListener('click', function (e) {
      if (e.target === searchOverlay) closeSearch();
    });
  }
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && searchOverlay && searchOverlay.classList.contains('open')) closeSearch();
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      if (searchOverlay && searchOverlay.classList.contains('open')) closeSearch();
      else openSearch();
    }
  });

  function loadSearchData(cb) {
    if (searchData) { cb(searchData); return; }
    fetch('assets/search.json')
      .then(function (r) { return r.json(); })
      .then(function (d) { searchData = d; cb(d); })
      .catch(function () {
        if (searchResultsEl) searchResultsEl.innerHTML =
          '<div class="search-no-results">Could not load search index.</div>';
      });
  }
  function esc(s) {
    return s.replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function renderResults(query, data) {
    if (!query) { searchResultsEl.innerHTML = ''; return; }
    var q = query.toLowerCase();
    var matches = data.filter(function (item) {
      return item.title.toLowerCase().indexOf(q) !== -1 ||
             item.content.toLowerCase().indexOf(q) !== -1;
    });
    if (!matches.length) {
      searchResultsEl.innerHTML = '<div class="search-no-results">No results for &ldquo;' + esc(query) + '&rdquo;</div>';
      return;
    }
    searchResultsEl.innerHTML = matches.map(function (item) {
      return '<a href="' + item.url + '" class="search-result-item">' +
        '<div class="search-result-title">' + esc(item.title) + '</div>' +
        '<div class="search-result-snippet">' + esc(item.content.substring(0, 150).trim()) + '&hellip;</div>' +
        '</a>';
    }).join('');
  }
  if (searchInputEl) {
    var debounceTimer;
    searchInputEl.addEventListener('input', function () {
      var query = this.value.trim();
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function () {
        loadSearchData(function (data) { renderResults(query, data); });
      }, 150);
    });
  }
})();
