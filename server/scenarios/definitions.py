"""Predefined test scenarios for browser automation, registered by name."""

from dataclasses import dataclass, field
from typing import Dict, Optional, List


@dataclass
class Scenario:
    """A test scenario for browser automation agents."""
    
    name: str
    description: str
    goal: str
    start_url: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    success_criteria: Optional[str] = None  # Explicit criteria for judge to evaluate
    verification_hint: Optional[str] = None  # Tells judge what to focus on in final extraction

    def __str__(self) -> str:
        return f"{self.name}: {self.description}"


SCENARIOS: Dict[str, Scenario] = {}


def register_scenario(scenario: Scenario) -> Scenario:
    SCENARIOS[scenario.name] = scenario
    return scenario


# E-commerce

register_scenario(Scenario(
    name="shipt_add_to_cart",
    description="Set delivery address, search for product, add to cart on Shipt",
    start_url="https://shipt.com",
    tags=["e-commerce", "grocery", "cart"],
    goal="""You are shopping on Shipt (shipt.com).

1. Go to shipt.com.
2. Set the delivery address to "401 S 2nd St, Springfield, IL 62701".
3. Search for "Organic Bananas".
4. Add the first result to your cart.
5. Navigate to the cart/bag page and verify the item is there.

VERIFICATION: After completing the task, navigate to the cart/bag page and report the exact cart contents including each product name, quantity, and price.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. The delivery address was set to 401 S 2nd St, Springfield, IL 62701
2. A search for "Organic Bananas" was performed
3. An organic bananas product was added to the cart
4. The cart was viewed and contains at least one bananas product

The task FAILS if:
- The cart is empty or does not contain bananas
- The agent never verified the cart contents""",
    verification_hint="Look for cart contents showing an organic bananas product with quantity and price. The agent should have opened the cart page."
))

register_scenario(Scenario(
    name="shipt_complex_cart_validation",
    description="Complex multi-item order with strict attribute and quantity logic",
    start_url="https://shipt.com",
    tags=["agentic-flow", "logic-test", "dirty-data"],
    goal="""You are shopping on Shipt (shipt.com).

1. Go to shipt.com.
2. Set the delivery address to "401 S 2nd St, Springfield, IL 62701".

3. Search for "Granny Smith Apples".
   - PREFERRED: Add 6 loose individual Granny Smith apples.
   - ACCEPTABLE SUBSTITUTE: A pre-bagged option totaling approximately 3 lbs (e.g., a 3lb bag) is an acceptable alternative.

4. Search for "Milk".
   - Find a gallon of Whole Milk that is NOT Organic.
   - Add 1 to cart.

5. Search for "Advil".
   - Verify the result is Ibuprofen in tablet/caplet form (avoid liquid gels).
   - Add the smallest pack size available.

6. Navigate to the cart/bag page and verify:
   - Cart contains 3 unique products
   - Apple count is 6 (or ~3 lbs)
   - Milk is Whole and NOT Organic
   - Advil is in tablet/caplet form

VERIFICATION: After completing the task, navigate to the cart/bag page and report the exact cart contents including each product name, quantity, and price.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. Cart contains exactly 3 UNIQUE products
2. Cart contains Granny Smith Apples - either 6 individual apples OR approximately 3 lbs
3. Cart contains a gallon of WHOLE milk that is NOT organic
4. Cart contains Advil (Ibuprofen) in tablet or caplet form (smallest available pack size)

The task FAILS if:
- Any of the 3 products are missing from the cart
- The milk is organic
- The apple quantity is wrong
- The cart verification shows fewer than 3 distinct products""",
    verification_hint="Look for cart contents showing exactly 3 unique products: Granny Smith Apples (6 count or ~3 lbs), whole non-organic milk (gallon), and Advil ibuprofen tablets/caplets. Check that milk is explicitly NOT organic."
))

# VHListings

register_scenario(Scenario(
    name="vhlistings_add_to_cart",
    description="Search for a product on VHListings, add to cart, and verify",
    start_url="https://vhlistings.com",
    tags=["e-commerce", "clothing", "cart"],
    goal="""You are shopping on VHListings (vhlistings.com), a streetwear accessories store.

1. Go to vhlistings.com.
2. Search for "belt".
3. From the search results, select any belt product.
4. Add it to the cart.
5. Navigate to the cart page and verify the item is there.

VERIFICATION: After completing the task, open the cart page and report the exact cart contents including the product name and price.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. A search for "belt" was performed on VHListings
2. A belt product was selected and added to the cart
3. The cart was viewed and contains the belt product

The task FAILS if:
- The cart is empty or does not contain a belt
- The agent never verified the cart contents on the cart page""",
    verification_hint="Look for cart contents showing a belt product with a price. The agent should have opened the cart page and reported the item name."
))

register_scenario(Scenario(
    name="vhlistings_bundle_promo",
    description="Add 3 items to trigger the bundle discount, then apply the SPRING promo code at checkout",
    start_url="https://vhlistings.com",
    tags=["e-commerce", "clothing", "cart", "promo", "logic-test"],
    goal="""You are shopping on VHListings (vhlistings.com), a streetwear accessories store.

VHListings offers a bundle discount: BUY 3 items, GET 10% OFF automatically. There is also a promo code "SPRING" for an additional 15% off.

Your task:
1. Go to vhlistings.com.
2. Search for "sunglasses". Add any one pair to your cart.
3. Search for "wallet". Add any one wallet to your cart.
4. Search for "jewelry". Add any one jewelry item to your cart.
5. Go to the cart page and confirm you have exactly 3 items.
6. Proceed to checkout.
7. Apply the promo code "SPRING" at checkout.
8. Report the final cart total and confirm the promo code was applied.

Do NOT attempt to fill in payment details — stop after applying the promo code.

VERIFICATION: Report the number of items in the cart, the subtotal, and whether the SPRING promo code was accepted.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. Exactly 3 different product categories were added (sunglasses, wallet, jewelry)
2. The cart was verified to contain 3 items before checkout
3. The checkout page was reached
4. The SPRING promo code was applied (accepted without error)
5. The checkout order does NOT contain a VIP Membership subscription (the site adds it to the cart on its own)

The task FAILS if:
- Fewer than 3 items were added to the cart
- The agent did not proceed to checkout
- The promo code was not applied or was rejected
- The agent attempted to complete payment (out of scope)
- A VIP Membership subscription appears in the final checkout order summary""",
    verification_hint="Look for confirmation of 3 cart items across different categories, confirmation that the SPRING promo code was applied at checkout, and verify that VIP Membership is NOT listed in the checkout order summary. The site adds VIP Membership to the cart on its own."
))

register_scenario(Scenario(
    name="vhlistings_product_attribute_search",
    description="Find a specific product matching style and price constraints",
    start_url="https://vhlistings.com",
    tags=["e-commerce", "clothing", "logic-test", "dirty-data"],
    goal="""You are shopping on VHListings (vhlistings.com), a streetwear accessories store.

Your task is to find and add a specific type of belt based on these constraints:
- Must be a CHAIN belt (not a leather belt, not a fabric belt)
- Sale price must be UNDER $35
- Add it to the cart

Steps:
1. Go to vhlistings.com.
2. Search for "chain belt".
3. Review the search results. Look at product names and prices to identify a chain belt under $35.
4. Select a qualifying product and view its detail page.
5. Add it to the cart.
6. Open the cart page and confirm the correct item is there.

Product names in search results describe the item type. Use the name to infer whether it is a chain belt. If no results are under $35, pick the cheapest chain belt available and note that the price constraint could not be met.

VERIFICATION: Report the exact product name, sale price, and confirm it is a chain belt (not leather or fabric).""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. A search for "chain belt" was performed
2. The agent selected a product that is identifiable as a chain belt from its name
3. The product was added to the cart
4. The cart was verified to contain the selected item
5. The agent reported the product name and price

The task FAILS if:
- The agent added a non-chain belt (leather, fabric, etc.)
- The cart is empty or was not verified
- The agent did not report the product name and price""",
    verification_hint="Look for a chain belt product in the cart with its name and price reported. Verify the product name indicates it is a chain-style belt, not leather or fabric."
))

register_scenario(Scenario(
    name="vhlistings_remove_from_cart",
    description="Add a product to the cart on VHListings, then remove it and verify the cart is empty",
    start_url="https://vhlistings.com",
    tags=["e-commerce", "clothing", "cart"],
    goal="""You are shopping on VHListings (vhlistings.com), a streetwear accessories store.

1. Go to vhlistings.com.
2. Search for "belt".
3. Select any belt product and view its detail page.
4. Add it to the cart.
5. Go to the cart page.
6. Remove the item from the cart.
7. Open the cart page again and verify the cart is now empty.

VERIFICATION: After removing the item, open the cart page again and confirm the cart contains zero items.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. A belt was added to the cart
2. The belt was removed from the cart
3. The cart was verified to be empty after removal

The task FAILS if:
- The item was not removed
- The cart still contains items after the remove step
- The agent never verified the empty cart on the cart page""",
    verification_hint="Look for confirmation that the cart is empty after removal. The agent should have checked the cart a second time and reported no cart items."
))

register_scenario(Scenario(
    name="amazon_search",
    description="Search for a product on Amazon and view details",
    start_url="https://amazon.com",
    tags=["e-commerce", "search"],
    goal="""Go to amazon.com.

Search for "wireless bluetooth headphones" using the search bar.

From the search results, click on the first product that:
1. Has at least 4 stars rating
2. Has "Prime" delivery available

On the product page, scroll down to see the product description and customer reviews section.

VERIFICATION: Report your findings clearly, including the product name, price, star rating, and Prime delivery status.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. A search for "wireless bluetooth headphones" was performed on Amazon
2. The agent selected a product with at least 4 stars and Prime delivery
3. The agent navigated to the product detail page
4. The product name and price were reported

The task FAILS if:
- No product was selected from search results
- The selected product does not have 4+ stars or Prime
- The product name or price was not reported""",
    verification_hint="Look for a reported product name and price from Amazon. Verify the agent confirmed the product has 4+ stars and Prime delivery."
))

# Amazon, through server/mappings/amazon.json on the Rindler arm. Live site, signed out, no checkout.

AMAZON_BOT_CHECK_RULE = (
    "If the site asks you to prove you are human (a captcha or an \"I am human\" check) or to sign in, "
    "stop and report that you were blocked by a bot check. A page with only a \"Continue shopping\" "
    "button is not such a check."
)

register_scenario(Scenario(
    name="amazon_add_cable",
    description="Find a USB-C to USB-C charging cable under $15 on Amazon, add it to the cart and confirm it there",
    start_url="https://www.amazon.com",
    tags=["e-commerce", "cart", "amazon"],
    goal=f"""You are shopping on Amazon (amazon.com). Do not sign in and do not check out.

1. Go to amazon.com.
2. Find a USB-C to USB-C charging cable (USB-C on both ends) that costs less than $15.
3. Add one to the cart.
4. Open the cart and confirm the cable is there.

{AMAZON_BOT_CHECK_RULE}

VERIFICATION: After completing the task, open the cart and report the cable's name, its price and the quantity as the cart shows them.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. A product search for a USB-C to USB-C cable was run on Amazon
2. A USB-C to USB-C cable (USB-C on both ends) priced under $15 was added to the cart
3. The cart was opened after the cable was added, and it shows that cable
4. The agent reported the cable's name and its price from the cart, and the price is under $15

The task FAILS if:
- The cart was never opened, or it does not show a USB-C to USB-C cable
- The item is not a USB-C to USB-C cable (for example a USB-A to USB-C cable, a charger or an adapter)
- The reported price is $15 or more, or no price was reported
- The agent signed in, started checkout or placed an order
- A bot check or captcha stopped the run""",
    verification_hint="Look for the cart contents: a USB-C to USB-C cable with a price under $15. The agent must have opened the cart after adding the cable and reported the name and price it shows.",
))

register_scenario(Scenario(
    name="amazon_add_book",
    description="Add the paperback of Atomic Habits by James Clear to the Amazon cart and confirm it there",
    start_url="https://www.amazon.com",
    tags=["e-commerce", "cart", "books", "amazon"],
    goal=f"""You are shopping on Amazon (amazon.com). Do not sign in and do not check out.

1. Go to amazon.com.
2. Find the book "Atomic Habits" by James Clear.
3. Choose its paperback edition (not the hardcover, Kindle or audiobook edition).
4. Add one copy to the cart.
5. Open the cart and confirm the paperback is there.

{AMAZON_BOT_CHECK_RULE}

VERIFICATION: After completing the task, open the cart and report the book's title, its format, its price and the quantity as the cart shows them.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. The book "Atomic Habits" by James Clear was found on Amazon
2. One copy of its paperback edition was added to the cart
3. The cart was opened after the book was added, and it shows Atomic Habits
4. The agent reported the title, the format (paperback) and the price from the cart

The task FAILS if:
- The cart was never opened, or it does not show Atomic Habits
- The item is another book, such as a workbook, a summary or a study guide
- The item is the hardcover, Kindle or audiobook edition, or the paperback format was not confirmed
- More than one copy is in the cart, or no price was reported
- The agent signed in, started checkout or placed an order
- A bot check or captcha stopped the run""",
    verification_hint="Look for the cart contents: Atomic Habits by James Clear in paperback, quantity 1, with its price. The agent must have opened the cart after adding the book and reported the format it shows.",
))

register_scenario(Scenario(
    name="target_store_finder",
    description="Find nearest Target store by ZIP code",
    start_url="https://target.com",
    tags=["e-commerce", "store-locator"],
    goal="""Go to target.com.

Find the store locator (usually in the header or footer).
Enter ZIP code: 62701 (Springfield, IL)

Find the nearest Target store and report:
1. Store address
2. Store hours for today
3. Whether it has Order Pickup available

VERIFICATION: Report your findings clearly, including all requested data points.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. The store locator was accessed on target.com
2. ZIP code 62701 was entered
3. At least one store result was found
4. The store address, hours, and Order Pickup availability were reported

The task FAILS if:
- No store was found or reported
- Store address or hours are missing from the report""",
    verification_hint="Look for a Target store address near Springfield, IL (ZIP 62701), today's store hours, and whether Order Pickup is available."
))

register_scenario(Scenario(
    name="patagonia_add_to_cart",
    description="Search for a product on Patagonia and add to cart",
    start_url="https://www.patagonia.com",
    tags=["e-commerce", "apparel", "cart"],
    goal="""Go to patagonia.com.

Search for "Better Sweater Fleece Jacket" using the search functionality.

From the search results, click on the first Men's jacket result.

On the product page:
1. Select size "M" (Medium)
2. Select any available color
3. Click "Add to Cart"

IMPORTANT - How to verify success:
After clicking add to cart, look for ANY of these success indicators:
1. A cart/bag icon shows an updated count (e.g., "1")
2. A slide-out cart panel appears showing the item
3. A confirmation message appears saying the item was added
4. You're taken to a cart page showing the jacket

VERIFICATION: After completing the task, navigate to the cart/bag page and report the exact cart contents including each product name, quantity, and price.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. A search for "Better Sweater Fleece Jacket" was performed on Patagonia
2. A Men's jacket was selected from results
3. Size "M" was selected
4. A color was selected
5. The item was added to cart and a success indicator was observed

The task FAILS if:
- No jacket was found or selected
- Size M was not selected
- No add-to-cart confirmation was observed""",
    verification_hint="Look for cart contents showing a Patagonia Better Sweater Fleece Jacket in size M with a color and price. Check for any add-to-cart confirmation."
))

register_scenario(Scenario(
    name="cargurus_search",
    description="Search for a used car on CarGurus",
    start_url="https://www.cargurus.com",
    tags=["automotive", "search", "marketplace"],
    goal="""Go to cargurus.com.

Search for used cars with these criteria:
1. Make: Toyota
2. Model: Camry
3. Location/ZIP: 62701 (Springfield, IL)
4. Maximum price: $25,000
5. Year: 2020 or newer

Wait for results to load and report:
1. The number of results found
2. The first 3 listings with: Year, Price, Mileage
3. Any "Great Deal" or "Good Deal" badges on these listings

VERIFICATION: Report your findings clearly, including all requested data points.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. A search was performed on CarGurus for Toyota Camry near ZIP 62701
2. Filters were applied (max $25,000, 2020 or newer)
3. The total number of results was reported
4. At least 3 listings were reported with year, price, and mileage
5. Deal badges were mentioned if present

The task FAILS if:
- The search was not performed with the correct criteria
- Fewer than 3 listings were reported
- Year, price, or mileage is missing from listings""",
    verification_hint="Look for at least 3 Toyota Camry listings (2020+, under $25k) with year, price, mileage, and any deal badges. Verify the total result count was reported."
))


# Food delivery

register_scenario(Scenario(
    name="doordash_add_to_cart",
    description="Find a restaurant and add food to cart on DoorDash",
    start_url="https://www.doordash.com",
    tags=["food-delivery", "cart", "restaurant"],
    goal="""Go to doordash.com.

First, set your delivery address to: 401 S 2nd St, Springfield, IL 62701
Wait for the address to be confirmed and restaurants to load.

Search for "pizza" restaurants in your area.

From the search results:
1. Click on the first pizza restaurant that has a rating of 4+ stars
2. Select a popular/featured item (like a large cheese pizza or pepperoni pizza)
3. Add it to your cart

IMPORTANT - How to verify success:
After adding to cart, look for ANY of these success indicators:
1. A cart icon shows the item count (e.g., "1")
2. A cart summary appears at the bottom of the screen
3. A "View Cart" or "Checkout" button appears with the item total

VERIFICATION: After completing the task, navigate to the cart/bag page and report the exact cart contents including each product name, quantity, and price.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. The delivery address was set to 401 S 2nd St, Springfield, IL 62701
2. A search for "pizza" restaurants was performed
3. A pizza restaurant with 4+ stars was selected
4. A pizza item was added to the cart
5. A cart success indicator was observed (item count, cart summary, or checkout button)

The task FAILS if:
- No restaurant was selected
- No item was added to cart
- No cart confirmation was observed""",
    verification_hint="Look for a cart summary or confirmation showing a pizza item from a DoorDash restaurant. The agent should have observed a cart icon count, cart summary, or checkout button."
))

register_scenario(Scenario(
    name="grubhub_add_to_cart",
    description="Find a restaurant and add food to cart on Grubhub",
    start_url="https://www.grubhub.com",
    tags=["food-delivery", "cart", "restaurant"],
    goal="""Go to grubhub.com.

First, set your delivery address to: 401 S 2nd St, Springfield, IL 62701
Wait for the address to be confirmed.

Search for "Chinese food" restaurants.

From the search results:
1. Click on the first Chinese restaurant that has a good rating (4+ stars)
2. Browse the menu and select a popular dish (like General Tso's Chicken or Orange Chicken)
3. Add it to your cart

IMPORTANT - How to verify success:
After adding to cart, look for ANY of these success indicators:
1. A cart/bag icon shows the item count
2. A cart panel appears on the side showing your order
3. A "Checkout" or "View order" button becomes visible

VERIFICATION: After completing the task, navigate to the cart/bag page and report the exact cart contents including each product name, quantity, and price.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. The delivery address was set to 401 S 2nd St, Springfield, IL 62701
2. A search for "Chinese food" restaurants was performed
3. A Chinese restaurant with good rating was selected
4. A dish (e.g., General Tso's Chicken or similar) was added to the cart
5. A cart success indicator was observed (item count, cart panel, or checkout button)

The task FAILS if:
- No restaurant was selected
- No item was added to cart
- No cart confirmation was observed""",
    verification_hint="Look for a cart panel or confirmation showing a Chinese food dish from a Grubhub restaurant. The agent should have observed a cart icon count, order panel, or checkout button."
))

register_scenario(Scenario(
    name="ubereats_add_to_cart",
    description="Find a restaurant and add food to cart on Uber Eats",
    start_url="https://www.ubereats.com",
    tags=["food-delivery", "cart", "restaurant"],
    goal="""Go to ubereats.com.

First, set your delivery address to: 401 S 2nd St, Springfield, IL 62701
Wait for the address to be confirmed and nearby restaurants to load.

Search for "burger" restaurants.

From the search results:
1. Click on the first burger restaurant that appears to be well-rated
2. Select a popular burger item from their menu
3. Add it to your cart (with default options if any customization is required)

IMPORTANT - How to verify success:
After adding to cart, look for ANY of these success indicators:
1. A cart icon appears with a number badge
2. A cart summary shows at the bottom of the screen
3. A "Go to checkout" or similar button appears

VERIFICATION: After completing the task, navigate to the cart/bag page and report the exact cart contents including each product name, quantity, and price.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. The delivery address was set to 401 S 2nd St, Springfield, IL 62701
2. A search for "burger" restaurants was performed
3. A burger restaurant was selected
4. A burger item was added to the cart
5. A cart success indicator was observed (cart icon, cart summary, or checkout button)

The task FAILS if:
- No restaurant was selected
- No item was added to cart
- No cart confirmation was observed""",
    verification_hint="Look for a cart summary or confirmation showing a burger item from an Uber Eats restaurant. The agent should have observed a cart icon badge, cart summary, or checkout button."
))

register_scenario(Scenario(
    name="instacart_add_to_cart",
    description="Set store location and add groceries to cart on Instacart",
    start_url="https://www.instacart.com",
    tags=["grocery", "cart", "food-delivery"],
    goal="""Go to instacart.com.

First, set your delivery address to: 401 S 2nd St, Springfield, IL 62701
Wait for nearby stores to load.

Select a store (preferably a major grocery store like Stop & Shop, Whole Foods, or similar).

Once in the store:
1. Search for "milk" or browse to the dairy section
2. Select a gallon of whole milk (or 2% milk)
3. Add it to your cart

IMPORTANT - How to verify success:
After clicking add to cart, look for ANY of these success indicators:
1. The cart icon shows an updated count
2. A "View cart" button appears
3. The item shows "In cart" or similar confirmation
4. A cart panel slides open showing the item

VERIFICATION: After completing the task, navigate to the cart/bag page and report the exact cart contents including each product name, quantity, and price.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. The delivery address was set to 401 S 2nd St, Springfield, IL 62701
2. A grocery store was selected
3. Milk was searched for or found in the dairy section
4. A gallon of whole or 2% milk was added to the cart
5. A cart success indicator was observed (cart count, view cart button, or in-cart confirmation)

The task FAILS if:
- No store was selected
- No milk product was added to cart
- No cart confirmation was observed""",
    verification_hint="Look for cart contents showing a gallon of milk (whole or 2%) from an Instacart store. The agent should have observed a cart icon count, view cart button, or in-cart status."
))

register_scenario(Scenario(
    name="opentable_reservation",
    description="Search for a restaurant and start a reservation on OpenTable",
    start_url="https://www.opentable.com",
    tags=["restaurant", "booking", "reservation"],
    goal="""Go to opentable.com.

Search for restaurants with these criteria:
1. Location: Boston, MA
2. Party size: 2 people
3. Date: Select a date that's 1 week from today
4. Time: 7:00 PM (or closest available dinner time)
5. Cuisine: Italian

From the search results:
1. Click on a well-rated restaurant (4+ stars)
2. On the restaurant page, look for available time slots
3. Click on an available time slot to proceed toward booking

IMPORTANT - How to verify success:
Look for ANY of these success indicators:
1. A reservation form appears asking for your details
2. The selected time slot is highlighted/confirmed
3. You see a "Complete reservation" or similar button
4. A guest information form appears

NOTE: Do NOT complete the actual reservation - just get to the point where you would enter your details.

VERIFICATION: Report the restaurant name, available time slot selected, party size, and date. Confirm you reached the reservation details form.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. A restaurant search was performed in Boston, MA for Italian cuisine
2. Party size was set to 2 and a date ~1 week out was selected
3. A dinner time around 7:00 PM was targeted
4. A restaurant with 4+ stars was selected
5. An available time slot was clicked
6. The agent reached a reservation form or confirmation page (without completing the booking)

The task FAILS if:
- No restaurant was found or selected
- The agent did not reach the reservation details form
- Search criteria were significantly wrong (wrong city, wrong cuisine)""",
    verification_hint="Look for evidence the agent reached an OpenTable reservation form showing restaurant name, party size of 2, a date ~1 week out, and an evening time slot. The booking should NOT have been completed."
))


# Auth and forms

register_scenario(Scenario(
    name="github_explore",
    description="Navigate GitHub and explore trending repositories",
    start_url="https://github.com/explore",
    tags=["navigation", "tech"],
    goal="""Go to github.com/explore.

Find the "Trending" section or navigate to trending repositories.

Filter by:
1. Language: Python
2. Date range: This week

Report the top 3 trending Python repositories with:
- Repository name
- Number of stars
- Brief description

VERIFICATION: Report your findings clearly, including all requested data points.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. The agent navigated to GitHub trending repositories
2. Results were filtered by Python language and "This week" timeframe
3. At least 3 trending Python repositories were reported
4. Each reported repository includes name, star count, and description

The task FAILS if:
- Fewer than 3 repositories were reported
- Repository names, stars, or descriptions are missing
- The results were not filtered by Python""",
    verification_hint="Look for 3 trending Python repositories from GitHub with name, star count, and description. Verify the agent filtered by Python and weekly timeframe."
))

register_scenario(Scenario(
    name="weather_lookup",
    description="Look up weather forecast",
    start_url="https://weather.com",
    tags=["information", "utility"],
    goal="""Go to weather.com.

Search for the weather in "San Francisco, CA".

Report:
1. Current temperature
2. Current conditions (sunny, cloudy, etc.)
3. High and low temperatures for today
4. Tomorrow's forecast summary

VERIFICATION: Report your findings clearly, including all requested data points.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. The agent navigated to weather.com
2. Weather was searched for "San Francisco, CA"
3. Current temperature was reported
4. Current conditions (e.g., sunny, cloudy) were reported
5. Today's high and low temperatures were reported
6. Tomorrow's forecast summary was reported

The task FAILS if:
- The weather is for the wrong city
- Current temperature or conditions are missing
- Today's high/low or tomorrow's forecast are missing""",
    verification_hint="Look for San Francisco weather data including current temperature, current conditions, today's high/low, and tomorrow's forecast. All four data points must be present."
))


# Travel and booking

register_scenario(Scenario(
    name="kayak_flight_search",
    description="Search for flights on Kayak",
    start_url="https://kayak.com",
    tags=["travel", "search", "booking"],
    goal="""Go to kayak.com.

Search for round-trip flights:
- From: SFO (San Francisco)
- To: JFK (New York)
- Departure: 2 weeks from today
- Return: 3 weeks from today
- Passengers: 1 adult

Wait for results to load and report:
1. The cheapest flight option
2. The fastest flight option
3. Price range shown

VERIFICATION: Report your findings clearly, including all requested data points.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. A flight search was performed on Kayak for SFO to JFK round-trip
2. Departure and return dates were approximately correct (~2 and ~3 weeks out)
3. At least one flight result was found
4. The cheapest flight option was reported with price
5. The fastest flight option was reported
6. A price range was mentioned

The task FAILS if:
- No flight results were found or reported
- The route is wrong (not SFO to JFK)
- Neither cheapest nor fastest option was reported""",
    verification_hint="Look for Kayak flight search results for SFO to JFK round-trip. The agent should report the cheapest option, fastest option, and overall price range. Exact prices will vary - focus on whether results were found and reported."
))

register_scenario(Scenario(
    name="yelp_restaurant_search",
    description="Find restaurants on Yelp",
    start_url="https://yelp.com",
    tags=["local", "search", "food"],
    goal="""Go to yelp.com.

Search for "sushi restaurants" in "Seattle, WA".

Filter results to show only:
- 4+ star rating
- Open now (if available)

Report the top 3 results with:
1. Restaurant name
2. Rating
3. Price range
4. Neighborhood/location

VERIFICATION: Report your findings clearly, including all requested data points.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. A search for "sushi restaurants" in "Seattle, WA" was performed on Yelp
2. Results were filtered to 4+ stars (or an attempt was made)
3. At least 3 restaurant results were reported
4. Each result includes name, rating, price range, and neighborhood/location

The task FAILS if:
- Fewer than 3 restaurants were reported
- Results are not sushi restaurants in Seattle
- Restaurant name or rating is missing from results""",
    verification_hint="Look for at least 3 sushi restaurants in Seattle, WA from Yelp with name, rating (4+ stars), price range, and neighborhood. Exact restaurants will vary."
))


# Simple and quick (good for testing)

register_scenario(Scenario(
    name="google_search",
    description="Simple Google search",
    start_url="https://google.com",
    tags=["search", "simple", "quick"],
    goal="""Go to google.com.

Search for "best programming languages 2024".

Report the first 3 search results with their titles.

VERIFICATION: Report your findings clearly, including all requested data points.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. A Google search for "best programming languages 2024" was performed
2. At least 3 search result titles were reported

The task FAILS if:
- The search was not performed
- Fewer than 3 result titles were reported""",
    verification_hint="Look for 3 Google search result titles related to 'best programming languages 2024'. The exact results will vary but should be relevant to the query."
))

register_scenario(Scenario(
    name="wikipedia_lookup",
    description="Look up information on Wikipedia",
    start_url="https://wikipedia.org",
    tags=["information", "simple", "quick"],
    goal="""Go to wikipedia.org.

Search for "Artificial Intelligence".

Report:
1. The first paragraph of the article
2. The number of sections in the table of contents

VERIFICATION: Report your findings clearly, including all requested data points.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. The agent navigated to Wikipedia and searched for "Artificial Intelligence"
2. The first paragraph of the article was reported
3. The number of table of contents sections was reported

The task FAILS if:
- The article was not found
- The first paragraph content is missing
- The table of contents section count is missing""",
    verification_hint="Look for the first paragraph of the Wikipedia 'Artificial Intelligence' article and a count of table of contents sections. Both data points must be present."
))

register_scenario(Scenario(
    name="hacker_news_browse",
    description="Browse Hacker News front page",
    start_url="https://news.ycombinator.com",
    tags=["tech", "news", "simple"],
    goal="""Go to news.ycombinator.com (Hacker News).

Report the top 5 stories on the front page with:
1. Title
2. Points/score
3. Number of comments

VERIFICATION: Report your findings clearly, including all requested data points.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. The agent navigated to Hacker News front page
2. At least 5 stories were reported
3. Each story includes title, points/score, and number of comments

The task FAILS if:
- Fewer than 5 stories were reported
- Story titles are missing
- Points or comment counts are missing from most stories""",
    verification_hint="Look for 5 Hacker News front page stories with title, points/score, and comment count. The exact stories will vary but all three data points should be present for each."
))


# Multi-step forms and modals

register_scenario(Scenario(
    name="costco_add_to_cart",
    description="Search for a product on Costco and add to cart",
    start_url="https://www.costco.com",
    tags=["e-commerce", "cart", "warehouse"],
    goal="""Go to costco.com.

1. Search for "Kirkland Signature Olive Oil" using the search bar.
2. From the search results, click on the first relevant product.
3. On the product page, click "Add to Cart".
4. If a modal or popup appears (e.g., warranty offer, membership prompt), dismiss it or click "No Thanks" / "Continue".

IMPORTANT - How to verify success:
After adding to cart, look for ANY of these success indicators:
1. A cart icon in the header shows an updated item count
2. A confirmation modal says "Added to Cart" or similar
3. The button changes to "Added" or shows a checkmark
4. You are redirected to the cart page showing the item

VERIFICATION: After completing the task, navigate to the cart/bag page and report the exact cart contents including each product name, quantity, and price.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. A search for "Kirkland Signature Olive Oil" was performed on Costco
2. A relevant olive oil product was selected
3. The item was added to cart
4. A cart success indicator was observed (cart count, confirmation modal, or cart page)

The task FAILS if:
- No product was found or selected
- The add-to-cart action was not performed
- No cart confirmation was observed""",
    verification_hint="Look for cart contents showing a Kirkland Signature Olive Oil product with price. The agent should have dismissed any warranty/membership popups and observed a cart confirmation."
))

register_scenario(Scenario(
    name="bestbuy_add_to_cart",
    description="Search for electronics on Best Buy and add to cart",
    start_url="https://www.bestbuy.com",
    tags=["e-commerce", "electronics", "cart"],
    goal="""Go to bestbuy.com.

1. Search for "USB-C cable" using the search bar.
2. From the search results, click on the first product that is available for shipping (not "Sold Out").
3. On the product page, click "Add to Cart".
4. If a popup appears offering accessories or protection plans, dismiss it.

IMPORTANT - How to verify success:
After adding to cart, look for ANY of these success indicators:
1. A green "Added to Cart" confirmation appears
2. The cart icon in the header updates with a count
3. A slide-out cart panel shows the item
4. A "Go to Cart" button appears

VERIFICATION: After completing the task, navigate to the cart/bag page and report the exact cart contents including each product name, quantity, and price.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. A search for "USB-C cable" was performed on Best Buy
2. An available (not sold out) product was selected
3. The item was added to cart
4. A cart success indicator was observed (green confirmation, cart count, slide-out panel, or Go to Cart button)

The task FAILS if:
- No product was found or selected
- A sold-out product was selected
- No cart confirmation was observed""",
    verification_hint="Look for cart contents showing a USB-C cable product from Best Buy with price. The agent should have observed an 'Added to Cart' confirmation or cart icon update."
))

register_scenario(Scenario(
    name="walgreens_add_to_cart",
    description="Find a product on Walgreens and add to cart",
    start_url="https://www.walgreens.com",
    tags=["e-commerce", "pharmacy", "cart"],
    goal="""Go to walgreens.com.

1. Search for "Advil 50 count" using the search bar.
2. From the results, click on the first Advil Ibuprofen product (tablets or caplets).
3. On the product page, click "Add to Cart" or the cart/bag button.

IMPORTANT - How to verify success:
After adding to cart, look for ANY of these success indicators:
1. The cart icon shows an updated count
2. A "View Cart" or confirmation message appears
3. The product shows "In Cart" status

VERIFICATION: After completing the task, navigate to the cart/bag page and report the exact cart contents including each product name, quantity, and price.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. A search for "Advil 50 count" was performed on Walgreens
2. An Advil Ibuprofen product (tablets or caplets) was selected
3. The item was added to cart
4. A cart success indicator was observed (cart count, view cart button, or in-cart status)

The task FAILS if:
- No Advil product was found or selected
- The add-to-cart action was not performed
- No cart confirmation was observed""",
    verification_hint="Look for cart contents showing an Advil Ibuprofen product from Walgreens with price. The agent should have observed a cart icon update, View Cart button, or In Cart status."
))


# Quantity and size selection

register_scenario(Scenario(
    name="nike_add_to_cart",
    description="Find shoes on Nike, select size, and add to cart",
    start_url="https://www.nike.com",
    tags=["e-commerce", "apparel", "cart", "size-selection"],
    goal="""Go to nike.com.

1. Search for "Air Force 1" using the search bar.
2. Click on the first Men's shoe result.
3. On the product page:
   - Select size "10" (US Men's)
   - Click "Add to Bag"

IMPORTANT - How to verify success:
After clicking "Add to Bag", look for ANY of these success indicators:
1. A slide-out cart panel shows the shoe with size 10
2. The bag icon in the header shows an item count
3. A confirmation message appears
4. A "View Bag" or "Checkout" button becomes visible

VERIFICATION: After completing the task, navigate to the cart/bag page and report the exact cart contents including each product name, quantity, and price.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. A search for "Air Force 1" was performed on Nike
2. A Men's shoe was selected from results
3. Size 10 (US Men's) was selected
4. The item was added to bag
5. A cart success indicator was observed (slide-out cart, bag icon count, confirmation, or View Bag button)

The task FAILS if:
- No shoe was found or selected
- Size 10 was not selected
- No add-to-bag confirmation was observed""",
    verification_hint="Look for cart/bag contents showing Nike Air Force 1 Men's shoe in size 10 with price. The agent should have observed a slide-out cart, bag icon update, or View Bag button."
))

register_scenario(Scenario(
    name="uniqlo_add_to_cart",
    description="Find clothing on Uniqlo, select size and color, add to cart",
    start_url="https://www.uniqlo.com/us/en/",
    tags=["e-commerce", "apparel", "cart", "size-selection"],
    goal="""Go to uniqlo.com.

1. Search for "Airism T-Shirt" using the search bar.
2. Click on the first Men's t-shirt result.
3. On the product page:
   - Select color: any available color
   - Select size: "M" (Medium)
   - Click "Add to Cart" or "Add to Bag"

IMPORTANT - How to verify success:
After adding to cart, look for ANY of these success indicators:
1. A cart confirmation slide-out or modal appears
2. The cart icon in the header updates with a count
3. A "View Cart" or "Checkout" button appears

VERIFICATION: After completing the task, navigate to the cart/bag page and report the exact cart contents including each product name, quantity, and price.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. A search for "Airism T-Shirt" was performed on Uniqlo
2. A Men's t-shirt was selected from results
3. A color was selected
4. Size M (Medium) was selected
5. The item was added to cart/bag
6. A cart success indicator was observed (confirmation modal, cart count, or View Cart button)

The task FAILS if:
- No t-shirt was found or selected
- Size M was not selected
- No add-to-cart confirmation was observed""",
    verification_hint="Look for cart contents showing a Uniqlo Airism T-Shirt in size M with a color and price. The agent should have observed a cart confirmation or cart icon update."
))


# Multi-step navigation

register_scenario(Scenario(
    name="home_depot_store_pickup",
    description="Find a product on Home Depot and check store pickup availability",
    start_url="https://www.homedepot.com",
    tags=["e-commerce", "store-locator", "availability"],
    goal="""Go to homedepot.com.

1. Search for "Phillips screwdriver set" using the search bar.
2. Click on the first relevant product from the results.
3. On the product page, look for store pickup availability.
4. If prompted, enter ZIP code: 62701 to check local store availability.
5. Report whether the item is available for pickup, and at which store.

IMPORTANT - How to verify success:
Look for ANY of these indicators:
1. A store name appears with "Available" or "In Stock" status
2. A "Free Pickup" badge is shown
3. Store pickup details are displayed with a specific store location

VERIFICATION: Report your findings clearly, including the product name, pickup availability status, and store name/location.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. A search for "Phillips screwdriver set" was performed on Home Depot
2. A relevant product was selected from results
3. Store pickup availability was checked for ZIP 62701
4. The agent reported whether the item is available for pickup and at which store

The task FAILS if:
- No product was found or selected
- Store pickup availability was not checked
- No store name or availability status was reported""",
    verification_hint="Look for a Home Depot product page showing store pickup availability for a Phillips screwdriver set near ZIP 62701. The agent should report the store name and availability status (in stock or not)."
))

register_scenario(Scenario(
    name="zillow_home_search",
    description="Search for homes on Zillow with filters",
    start_url="https://www.zillow.com",
    tags=["real-estate", "search", "filters"],
    goal="""Go to zillow.com.

1. Search for homes in "Springfield, IL" using the search bar.
2. Apply filters:
   - For Sale
   - Price: Max $1,500,000
   - Bedrooms: 3+
3. Wait for results to load.

Report the first 3 listings with:
1. Address
2. Price
3. Number of bedrooms and bathrooms
4. Square footage (if shown)

VERIFICATION: Report your findings clearly, including all requested data points.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. A search for homes in "Springfield, IL" was performed on Zillow
2. Filters were applied (For Sale, max $1,500,000, 3+ bedrooms)
3. At least 3 home listings were reported
4. Each listing includes address, price, and bedroom/bathroom counts

The task FAILS if:
- Fewer than 3 listings were reported
- Listings are not in Springfield, IL
- Address or price is missing from most listings""",
    verification_hint="Look for at least 3 Zillow home listings in Springfield, IL with address, price (under $1.5M), bedrooms (3+), bathrooms, and optionally square footage. Exact listings will vary."
))

register_scenario(Scenario(
    name="linkedin_job_search",
    description="Search for jobs on LinkedIn",
    start_url="https://www.linkedin.com/jobs",
    tags=["jobs", "search", "professional"],
    goal="""Go to linkedin.com/jobs.

1. Search for "Software Engineer" in the job search field.
2. Set location to "San Francisco Bay Area".
3. Apply filter: "Past week" for date posted (if available).

Report the first 3 job listings with:
1. Job title
2. Company name
3. Location
4. Whether it's Remote, Hybrid, or On-site (if shown)

VERIFICATION: Report your findings clearly, including all requested data points.""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. A job search for "Software Engineer" was performed on LinkedIn
2. Location was set to "San Francisco Bay Area"
3. Date filter "Past week" was applied (or attempted)
4. At least 3 job listings were reported
5. Each listing includes job title, company name, and location

The task FAILS if:
- Fewer than 3 job listings were reported
- Job title or company name is missing from most listings
- The search was not for Software Engineer roles""",
    verification_hint="Look for at least 3 LinkedIn job listings for Software Engineer in the San Francisco Bay Area with job title, company name, location, and optionally remote/hybrid/on-site status. Exact listings will vary."
))


def get_scenario(name: str) -> Scenario:
    """Get a scenario by name, case-insensitive. Raises KeyError if there is none."""
    name_lower = name.lower()
    
    if name_lower in SCENARIOS:
        return SCENARIOS[name_lower]
    
    for key, scenario in SCENARIOS.items():
        if key.lower() == name_lower:
            return scenario
    
    raise KeyError(f"Scenario '{name}' not found. Available: {list(SCENARIOS.keys())}")


def list_scenarios(tag: Optional[str] = None) -> List[Scenario]:
    """All scenarios, optionally filtered by tag."""
    scenarios = list(SCENARIOS.values())
    
    if tag:
        tag_lower = tag.lower()
        scenarios = [s for s in scenarios if tag_lower in [t.lower() for t in s.tags]]
    
    return scenarios


def create_custom_scenario(goal: str, start_url: Optional[str] = None, 
                          name: str = "custom") -> Scenario:
    """A new Scenario from a goal string. It is not registered globally."""
    return Scenario(
        name=name,
        description="Custom scenario",
        goal=goal,
        start_url=start_url,
        tags=["custom"]
    )
