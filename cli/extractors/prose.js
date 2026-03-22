// Prose.com page data extractor
// Returns structured JSON with product info, cart contents, and page context.
// Runs via Playwright page.evaluate() after each action.
() => {
  const data = {};

  // Page title from h1
  const h1 = document.querySelector('h1');
  if (h1) data.title = h1.innerText.trim();

  // Section headings (h2) — product names on accessories page, categories elsewhere
  const h2s = [...document.querySelectorAll('h2')]
    .map(h => h.innerText.trim())
    .filter(t => t && t.length < 80);
  if (h2s.length) data.sections = h2s;

  // Prices — leaf elements containing $XX.XX
  const priceEls = [...document.querySelectorAll('*')].filter(el => {
    const t = el.innerText;
    return t && /^\$\d+\.\d{2}/.test(t.trim()) && el.children.length === 0;
  });
  const prices = [...new Set(priceEls.map(el => el.innerText.trim()))];
  if (prices.length) data.prices = prices.slice(0, 10);

  // Product description — first paragraph in main content area
  const mainContent = document.querySelector('main > div:nth-child(2)') || document.querySelector('main');
  if (mainContent) {
    const desc = mainContent.querySelector('p');
    if (desc && desc.innerText.length > 20) {
      data.description = desc.innerText.trim().substring(0, 200);
    }
  }

  // Cart items — find quantity selectors and nearby product info
  const selects = document.querySelectorAll('select');
  const cartItems = [];
  selects.forEach(sel => {
    const label = sel.getAttribute('aria-label') || '';
    if (!label.toLowerCase().includes('quantity')) return;
    const container = sel.closest('div[class]') || sel.parentElement;
    if (!container) return;
    // Walk up to find product name and price
    const wrapper = container.closest('div') || container;
    const paragraphs = wrapper.querySelectorAll('p');
    let name = '', price = '';
    paragraphs.forEach(p => {
      const t = p.innerText.trim();
      if (!name && t && !t.startsWith('$') && t.length < 50) name = t;
      if (!price && /^\$\d/.test(t)) price = t;
    });
    if (name) {
      cartItems.push({ name, price, quantity: sel.value });
    }
  });
  if (cartItems.length) data.cart_items = cartItems;

  // Order summary (subtotal, shipping, total)
  const summaryText = document.body.innerText;
  const subtotalMatch = summaryText.match(/Subtotal.*?\$[\d.]+/);
  const totalMatch = summaryText.match(/Today's total.*?\$[\d.]+/);
  if (subtotalMatch || totalMatch) {
    data.order_summary = {};
    if (subtotalMatch) data.order_summary.subtotal = subtotalMatch[0];
    if (totalMatch) data.order_summary.total = totalMatch[0];
  }

  // Buttons — what actions are visible
  const buttons = [...document.querySelectorAll('button')]
    .map(b => b.innerText.trim())
    .filter(t => t && t.length > 2 && t.length < 40);
  if (buttons.length) data.buttons = [...new Set(buttons)].slice(0, 8);

  return data;
}
