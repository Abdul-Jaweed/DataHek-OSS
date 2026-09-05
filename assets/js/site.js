/* Shared site JS — nav toggle, scroll reveal, demo form, footer year. */
(function () {
  'use strict';

  var toggle = document.querySelector('.nav-toggle');
  var links = document.querySelector('.nav-links');
  if (toggle && links) {
    toggle.addEventListener('click', function () {
      links.classList.toggle('open');
      toggle.setAttribute('aria-expanded', String(links.classList.contains('open')));
    });
    links.querySelectorAll('a').forEach(function (a) {
      a.addEventListener('click', function () { links.classList.remove('open'); });
    });
  }

  // Scroll reveal
  var revealEls = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add('visible'); io.unobserve(e.target); }
      });
    }, { threshold: 0.12 });
    revealEls.forEach(function (el) { io.observe(el); });
  } else {
    revealEls.forEach(function (el) { el.classList.add('visible'); });
  }

  // Demo email capture (no backend — shows confirmation only)
  var form = document.querySelector('.cta-form');
  if (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var input = form.querySelector('input');
      var note = form.parentElement.querySelector('.cta-note');
      if (!input.value) return;
      form.style.display = 'none';
      if (note) note.textContent = "Thanks — you're on the list. We'll be in touch soon.";
    });
  }

  // Footer year
  document.querySelectorAll('.js-year').forEach(function (el) {
    el.textContent = String(new Date().getFullYear());
  });
})();