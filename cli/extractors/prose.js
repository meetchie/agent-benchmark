// Prose.com page data extractor
// Returns structured JSON with product info, cart contents, and page context.
// Runs via Playwright page.evaluate() after each action.
//
// Site quirks it handles:
// - cart line items are plain divs (no <p>), so each row is found from its quantity <select>
// - "Subtotal (n items)" and "Today's total" sit on separate lines and the apostrophe is curly
// - product_cards pairs each accessory with its own price (the price list is de-duplicated, and
//   the three brushes share one price)
// - main_text is the gift card page's own text (amounts and how gifting works are plain text)
() => {
  const data = {};
  const clean = t => (t || '').replace(/\s+/g, ' ').trim();

  const h1 = document.querySelector('h1');
  if (h1) data.title = h1.innerText.trim();

  // Section headings (h2): product names on the accessories page, categories elsewhere
  const h2List = [...document.querySelectorAll('h2')];
  const h2s = h2List.map(h => h.innerText.trim()).filter(t => t && t.length < 80);
  if (h2s.length) data.sections = h2s;

  // Prices: leaf elements containing $XX.XX
  const priceEls = [...document.querySelectorAll('*')].filter(el => {
    const t = el.innerText;
    return t && /^\$\d+\.\d{2}/.test(t.trim()) && el.children.length === 0;
  });
  const prices = [...new Set(priceEls.map(el => el.innerText.trim()))];
  if (prices.length) data.prices = prices.slice(0, 10);

  // Product cards on the accessories grid: each h2 with the first price shown before the next h2
  if (location.pathname.startsWith('/products/accessories')) {
    const cardPrices = [...document.querySelectorAll('*')].filter(el => {
      const t = el.innerText;
      return t && /^(From\s+)?\$\d+\.\d{2}$/.test(t.trim()) && el.children.length === 0;
    });
    const cards = [];
    h2List.forEach((h, i) => {
      const next = h2List[i + 1];
      const price = cardPrices.find(el =>
        (h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) &&
        (!next || (next.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_PRECEDING)));
      if (price) cards.push({ name: clean(h.innerText), price: clean(price.innerText) });
    });
    if (cards.length) data.product_cards = cards;
  }

  const mainContent = document.querySelector('main > div:nth-child(2)') || document.querySelector('main');
  if (mainContent) {
    const desc = mainContent.querySelector('p');
    if (desc && desc.innerText.length > 20) {
      data.description = desc.innerText.trim().substring(0, 200);
    }
  }

  // Cart items, one per quantity selector. The row is the nearest ancestor that holds both the
  // item's name (first line that is not a number, price or "Remove") and its price.
  const cartItems = [];
  document.querySelectorAll('select').forEach(sel => {
    const label = (sel.getAttribute('aria-label') || '').toLowerCase();
    if (!label.includes('quantity')) return;
    let row = sel.parentElement;
    while (row && row !== document.body) {
      if (row.querySelectorAll('select').length > 1) break;  // gone past this item into the whole list
      const lines = (row.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
      const name = lines.find(t => !/^\$/.test(t) && !/^[\d\s]+$/.test(t) && !/^remove$/i.test(t) && t.length < 60);
      const price = lines.find(t => /^\$\d/.test(t));
      if (name && price) {
        cartItems.push({ name, price, quantity: sel.value });
        break;
      }
      row = row.parentElement;
    }
  });
  if (cartItems.length) data.cart_items = cartItems;

  // Order summary (subtotal, shipping, total), only on a page that has one
  const bodyText = clean(document.body.innerText);
  const orderAt = bodyText.search(/ORDER SUMMARY/i);
  if (orderAt >= 0) {
    const summaryText = bodyText.slice(orderAt);
    const subtotalMatch = summaryText.match(/Subtotal.{0,40}?\$[\d,.]+/);
    const shippingMatch = summaryText.match(/Shipping.{0,20}?(?:\$[\d,.]+|FREE)/);
    const totalMatch = summaryText.match(/Today.s total.{0,40}?\$[\d,.]+/);
    data.order_summary = {};
    if (subtotalMatch) data.order_summary.subtotal = subtotalMatch[0];
    if (shippingMatch) data.order_summary.shipping = shippingMatch[0];
    if (totalMatch) data.order_summary.total = totalMatch[0];
  }

  // The gift card page is mostly plain text (amounts, how gifting works): hand over the main
  // text, starting at the page heading so the site navigation is not in it
  if (location.pathname.startsWith('/gift')) {
    const main = document.querySelector('main');
    let text = clean(main ? main.innerText : document.body.innerText);
    const at = data.title ? text.toLowerCase().indexOf(clean(data.title).toLowerCase()) : -1;
    if (at > 0) text = text.slice(at);
    if (text) data.main_text = text.substring(0, 1500);
  }

  const buttons = [...document.querySelectorAll('button')]
    .map(b => b.innerText.trim())
    .filter(t => t && t.length > 2 && t.length < 40);
  if (buttons.length) data.buttons = [...new Set(buttons)].slice(0, 8);

  return data;
}
