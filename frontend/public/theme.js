// Run in <head>, before the app/CSS load. This preference is not project state.
(() => {
  let theme = 'dark';
  try { if (localStorage.getItem('boardvision.theme.v1') === 'light') theme = 'light'; } catch {}
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'light' ? '#f3f4f7' : '#0a0b10');
})();
