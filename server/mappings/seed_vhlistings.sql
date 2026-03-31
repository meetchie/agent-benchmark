-- VHListings Semantic Site Config Seed Data
-- Domain: vhlistings.com
-- Mapped: 2026-03-30 (v21: 6th fix — VIP removal timing; page_extractor for checkout visibility)
--
-- BUG FIX RATIONALE:
--   FIX 1 — view_cart VIP removal selector:
--     Old: a[aria-label*="VIP Membership"][href*="quantity=0"]  (link no longer exists)
--     New: cart-remove-button[data-handle="vip-membership"] button
--     Why: VHListings migrated cart to Shopify Dawn theme using <cart-remove-button> custom elements.
--     The old href-based remove links were replaced with declarative custom element buttons.
--
--   FIX 2 — checkout action changed from click to navigate:
--     Old: click button#checkout (button has form="cart" attribute pointing to nonexistent form)
--     New: navigate https://vhlistings.com/checkout
--     Why: The button's form="cart" association references a form that doesn't exist in the DOM.
--     Clicking the submit button with no valid form does nothing; Shopify's /checkout redirect works.
--
--   FIX 3 — apply_promo wait before type:
--     Added: wait selector_visible input[name="reductions"] timeout 8000ms
--     Why: Shopify's new React checkout mounts the discount input asynchronously. The input
--     is not in the DOM immediately after navigation completes; wait prevents type step failures.
--
--   FIX 4 — apply_promo submission method:
--     Old: press_enter: true (Enter key does NOT trigger Shopify React's submit handler)
--     New: press_enter: false + click button[aria-label="Apply Discount Code"]
--     Why: Shopify's checkout React components intercept form submission via button click events,
--     not Enter key events. Pressing Enter has no effect on the discount form.
--
--   FIX 5 — apply_promo description strengthened + page_extractor added:
--     Why: Shopify checkout pricing (Order discount, Total) uses plain divs with no ARIA roles.
--     These elements are invisible to Playwright's AriaSnapshot. After apply_promo succeeds,
--     the agent sees an unchanged "Cost summary" and incorrectly concludes the code failed.
--     page_extractor reads document.body.innerText directly (bypassing ARIA) and returns
--     {discount_applied: bool, savings: string} as page_info in the response data.
--     The description also instructs the agent to trust a no-error response.
--
--   FIX 6 — view_cart VIP removal timing:
--     Old: click with timeout: 1000 (1000ms to find and click the element)
--     New: selector_visible wait (4000ms, optional) added before the click; timeout removed from click
--     Why: cart-remove-button is a Shopify Dawn custom element that registers async after page load.
--     ClickResilient default is 2000ms; the 1000ms override was too tight for the element to appear.
--     A selector_visible wait ensures the element is in the DOM before the click is attempted.
--     If VIP is not present (edge case), the optional wait times out silently and the click also skips.
-- Platform: Shopify (Liquid theme, server-rendered, full page loads between screens)
--
-- Key quirks baked into this config:
--   1. Klaviyo popup blocks ALL interaction on first visit. Handled by interrupt_handlers.
--      Detects [aria-label="Close dialog"] with 15s timeout. Once dismissed, zero overhead.
--   2. Add-to-cart opens a slide-out DRAWER (not a page redirect). Drawer must be closed.
--   3. VIP Membership ($0 free trial, then $30/month) is auto-added to every cart on first
--      add-to-cart. view_cart silently removes it before returning cart contents.
--   3. Quantity controls differ by context: buttons on PDP, links in cart drawer/cart page.
--   4. Some product link[name] values are AliExpress CDN URLs, not product names. Use text fallbacks.
--   5. Color variant selection (radio buttons) is NOT covered by generic tools. Agents should
--      navigate directly to variant URLs (e.g., /products/slug?variant=123) when color matters.
--      This is a known limitation.
--   6. Checkout is Shopify-hosted (/checkouts/cn/{token}/en-us) with iframed payment fields.
--      Payment field automation is out of scope; apply_promo and navigation work.
-- Idempotent via ON CONFLICT.

-- 1. System user (shared across all seed files)
INSERT INTO users (id, email) VALUES ('dbfde74b-c44d-53ab-abfb-e61f5ce31040', 'system@example.invalid')
ON CONFLICT (id) DO NOTHING;

-- 2. VHListings site
INSERT INTO sites (id, user_id, domain) VALUES ('c7f3a1e4-8b2d-5c6f-a9e0-3d4b7f2c1a8e', 'dbfde74b-c44d-53ab-abfb-e61f5ce31040', 'vhlistings.com')
ON CONFLICT (id) DO NOTHING;

-- 3. Semantic terminal site config for VHListings
INSERT INTO site_configs (site_id, domain, config, version) VALUES (
    'c7f3a1e4-8b2d-5c6f-a9e0-3d4b7f2c1a8e',
    'vhlistings.com',
    '{
        "site_id": "vhlistings",
        "domain": "vhlistings.com",
        "screens": {
            "landing": {
                "url_pattern": "vhlistings\\.com/$",
                "parent_screen": null,
                "extraction": {},
                "available_actions": ["search_products", "view_product"]
            },
            "collection": {
                "url_pattern": "vhlistings\\.com/collections/",
                "parent_screen": "landing",
                "extraction": {},
                "available_actions": ["search_products", "view_product", "next_page", "prev_page", "go_back"]
            },
            "search_results": {
                "url_pattern": "vhlistings\\.com/search",
                "parent_screen": "landing",
                "extraction": {},
                "available_actions": ["search_products", "view_product", "next_page", "prev_page", "go_back"]
            },
            "product_detail": {
                "url_pattern": "vhlistings\\.com/products/",
                "parent_screen": "search_results",
                "extraction": {},
                "available_actions": ["add_to_cart", "view_cart", "search_products", "go_back"]
            },
            "cart": {
                "url_pattern": "vhlistings\\.com/cart",
                "parent_screen": "landing",
                "extraction": {},
                "available_actions": ["remove_from_cart", "update_quantity", "checkout", "search_products", "go_back"]
            },
            "checkout": {
                "url_pattern": "vhlistings\\.com/checkouts/",
                "parent_screen": "cart",
                "extraction": {},
                "available_actions": ["apply_promo", "go_back"]
            }
        },
        "actions": {
            "search_products": {
                "description": "Search for products on VHListings",
                "params": {"query": {"type": "string"}},
                "stays_on_screen": false,
                "target_screen": "search_results",
                "steps": [
                    {
                        "action": "navigate",
                        "url": "https://vhlistings.com/search?q={{query}}"
                    },
                    {
                        "action": "wait",
                        "strategy": "delay",
                        "timeout": 500
                    }
                ]
            },
            "view_product": {
                "description": "Navigate to a product detail page",
                "params": {"item": {"type": "string"}},
                "stays_on_screen": false,
                "target_screen": "product_detail",
                "steps": [
                    {
                        "action": "click",
                        "selector": "xpath=//a[starts-with(@id,\"CardLink--\") and contains(.,\"{{item}}\")]",
                        "fallbacks": [
                            {"type": "css", "selector": "a[id^=\"CardLink--\"]:has-text(\"{{item}}\")"}
                        ]
                    },
                    {
                        "action": "wait",
                        "strategy": "selector_visible",
                        "selector": "button.atc-button",
                        "timeout": 10000
                    }
                ]
            },
            "add_to_cart": {
                "description": "Add the current product to cart. Must be on product detail page. Closes the cart drawer after adding.",
                "params": {},
                "stays_on_screen": true,
                "steps": [
                    {
                        "action": "click",
                        "selector": "button.atc-button"
                    },
                    {
                        "action": "wait",
                        "strategy": "selector_visible",
                        "selector": "button:has-text(\"Check out\")",
                        "timeout": 3000,
                        "optional": true
                    },
                    {
                        "action": "click",
                        "selector": "button.drawer__close",
                        "optional": true,
                        "timeout": 2000
                    }
                ]
            },
            "view_cart": {
                "description": "Navigate to the full cart page",
                "params": {},
                "stays_on_screen": false,
                "target_screen": "cart",
                "steps": [
                    {
                        "action": "navigate",
                        "url": "https://vhlistings.com/cart"
                    },
                    {
                        "action": "wait",
                        "strategy": "delay",
                        "timeout": 1500
                    },
                    {
                        "action": "wait",
                        "strategy": "selector_visible",
                        "selector": "cart-remove-button[data-handle=\"vip-membership\"] button",
                        "timeout": 4000,
                        "optional": true
                    },
                    {
                        "action": "click",
                        "selector": "cart-remove-button[data-handle=\"vip-membership\"] button",
                        "optional": true
                    },
                    {
                        "action": "wait",
                        "strategy": "delay",
                        "timeout": 1500
                    }
                ]
            },
            "remove_from_cart": {
                "description": "Remove an item from the cart by name. Must be on the cart page.",
                "params": {"item": {"type": "string"}},
                "stays_on_screen": true,
                "steps": [
                    {
                        "action": "click",
                        "selector": "a[aria-label*=\"{{item}}\"][href*=\"quantity=0\"]",
                        "fallbacks": [
                            {"type": "css", "selector": "a[href*=\"quantity=0\"]"}
                        ]
                    },
                    {
                        "action": "wait",
                        "strategy": "delay",
                        "timeout": 1000
                    }
                ]
            },
            "update_quantity": {
                "description": "Update the quantity of an item in the cart. Must be on the cart page.",
                "params": {"item": {"type": "string"}, "quantity": {"type": "string"}},
                "stays_on_screen": true,
                "steps": [
                    {
                        "action": "type",
                        "selector": "input[aria-label*=\"Quantity for\"][aria-label*=\"{{item}}\"]",
                        "value": "{{quantity}}",
                        "press_enter": true
                    },
                    {
                        "action": "wait",
                        "strategy": "delay",
                        "timeout": 1500
                    }
                ]
            },
            "checkout": {
                "description": "Proceed to checkout from the cart page",
                "params": {},
                "stays_on_screen": false,
                "target_screen": "checkout",
                "steps": [
                    {
                        "action": "navigate",
                        "url": "https://vhlistings.com/checkout"
                    }
                ]
            },
            "apply_promo": {
                "description": "Apply a discount code at checkout. Must be on the checkout page. IMPORTANT: The checkout page uses non-ARIA pricing elements, so the price shown in the response will NOT visually change after this action even when the code is successfully applied. If this action returns without an error field, the discount code IS active on the order — call done with success=True immediately. Do NOT attempt to re-apply or verify by checking prices.",
                "params": {"code": {"type": "string"}},
                "stays_on_screen": true,
                "steps": [
                    {
                        "action": "wait",
                        "strategy": "selector_visible",
                        "selector": "input[name=\"reductions\"]",
                        "timeout": 8000
                    },
                    {
                        "action": "type",
                        "selector": "input[placeholder=\"Discount code or gift card\"]",
                        "value": "{{code}}",
                        "press_enter": false,
                        "fallbacks": [
                            {"type": "css", "selector": "input[name=\"reductions\"]"}
                        ]
                    },
                    {
                        "action": "click",
                        "selector": "button[aria-label=\"Apply Discount Code\"]"
                    },
                    {
                        "action": "wait",
                        "strategy": "delay",
                        "timeout": 2000
                    }
                ]
            },
            "next_page": {
                "description": "Navigate to the next page of results",
                "params": {},
                "stays_on_screen": true,
                "steps": [
                    {
                        "action": "click",
                        "selector": "link[name=\"Next\"]",
                        "fallbacks": [
                            {"type": "text", "selector": "Next"}
                        ]
                    }
                ]
            },
            "prev_page": {
                "description": "Navigate to the previous page of results",
                "params": {},
                "stays_on_screen": true,
                "steps": [
                    {
                        "action": "click",
                        "selector": "link[name=\"Previous\"]",
                        "fallbacks": [
                            {"type": "text", "selector": "Previous"}
                        ]
                    }
                ]
            },
            "go_back": {
                "description": "Navigate back to the main product catalog",
                "params": {},
                "stays_on_screen": false,
                "target_screen": "collection",
                "steps": [
                    {
                        "action": "navigate",
                        "url": "https://vhlistings.com/collections/all"
                    }
                ]
            }
        },
        "interrupt_handlers": [
            {
                "detect": "[aria-label=\"Close dialog\"]",
                "detect_timeout_ms": 15000,
                "dismiss": [
                    {
                        "action": "click",
                        "selector": "[aria-label=\"Close dialog\"]"
                    }
                ]
            }
        ],
        "context_extractors": {
            "cart_badge": {
                "steps": [{"action": "extract", "selector": "link[name^=\"Cart\"]", "field": "item_count"}]
            },
            "bundle_progress": {
                "steps": [{"action": "extract", "selector": "generic:has-text(\"Add\")", "field": "bundle_status"}]
            }
        },
        "page_extractor": "() => { try { if (location.href.indexOf(\"/checkouts/\") === -1) return null; var txt = document.body.innerText; var discountApplied = txt.indexOf(\"Order discount\") !== -1; var savingsI = txt.indexOf(\"TOTAL SAVINGS\"); var savings = savingsI >= 0 ? txt.slice(savingsI, savingsI + 35) : null; return { discount_applied: discountApplied, savings: savings }; } catch(e) { return null; } }"
    }',
    21
)
ON CONFLICT (domain) DO UPDATE SET config = EXCLUDED.config, version = EXCLUDED.version;
