(() => {
  'use strict';
  let theme = 'dark';
  try {
    const saved = localStorage.getItem('trialmatch-theme');
    if (saved === 'light' || saved === 'dark') theme = saved;
  } catch { /* Storage can be unavailable in private or restricted browsers. */ }
  document.documentElement.dataset.theme = theme;
  document.addEventListener('DOMContentLoaded', () => {
    const buttons = document.querySelectorAll('[data-theme-choice]');
    function apply(next) {
      document.documentElement.dataset.theme = next;
      buttons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.themeChoice === next)));
      try { localStorage.setItem('trialmatch-theme', next); } catch { /* Keep the in-memory selection. */ }
      window.dispatchEvent(new Event('trialmatch:theme'));
    }
    buttons.forEach(button => button.addEventListener('click', () => apply(button.dataset.themeChoice)));
    apply(theme);
  });
})();
