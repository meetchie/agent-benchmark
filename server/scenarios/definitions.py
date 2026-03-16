"""
Scenario Definitions - Predefined test scenarios for browser automation.

Each scenario contains:
- name: Unique identifier for the scenario
- description: Brief description of what the scenario tests
- goal: The full prompt/instructions for the agent
- start_url: Optional URL to navigate to before starting
- tags: Optional tags for categorization (e.g., "e-commerce", "auth", "search")
"""

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
    
    def __str__(self) -> str:
        return f"{self.name}: {self.description}"


# =============================================================================
# SCENARIO DEFINITIONS
# =============================================================================

SCENARIOS: Dict[str, Scenario] = {}


def register_scenario(scenario: Scenario) -> Scenario:
    """Register a scenario in the global registry."""
    SCENARIOS[scenario.name] = scenario
    return scenario


# -----------------------------------------------------------------------------
# E-Commerce Scenarios
# -----------------------------------------------------------------------------

register_scenario(Scenario(
    name="shipt_add_to_cart",
    description="Set delivery address, search for product, add to cart on Shipt",
    start_url="https://shipt.com",
    tags=["e-commerce", "grocery", "cart"],
    goal="""You are shopping on Shipt using Rindler's semantic commerce tools.

1. Start a session on shipt.com using start_session.
2. Set the delivery address to "1 Main St, Springfield, IL 62701" using update_address or set_address.
3. Search for "Organic Bananas" using search_products.
4. Add the first result to your cart using add_to_cart.
5. Verify the cart has the item by calling view_cart.

Report the cart contents when done."""
))

register_scenario(Scenario(
    name="shipt_complex_cart_validation",
    description="Complex multi-item order with strict attribute and quantity logic",
    start_url="https://shipt.com",
    tags=["agentic-flow", "logic-test", "dirty-data"],
    goal="""You are shopping on Shipt using Rindler's semantic commerce tools.

1. Start a session on shipt.com using start_session.
2. Set the delivery address to "1 Main St, Springfield, IL 62701" using update_address.

3. Search for "Granny Smith Apples" using search_products.
   - Find a loose individual apple (not pre-bagged) and add exactly 6 individual apples (or ~3 lbs if sold by weight).

4. Search for "Milk" using search_products.
   - Find a gallon of Whole Milk that is NOT Organic.
   - Add 1 to cart.

5. Search for "Advil" using search_products.
   - Verify the result is Ibuprofen in tablet/caplet form (avoid liquid gels).
   - Add the smallest pack size available.

6. Call view_cart to verify:
   - Cart contains 3 unique products
   - Apple count is 6 (or ~3 lbs)
   - Milk is Whole and NOT Organic
   - Advil is in tablet/caplet form
""",
    success_criteria="""The task is SUCCESSFUL if and only if ALL of these conditions are met:
1. Cart contains exactly 3 UNIQUE products
2. Cart contains Granny Smith Apples - either 6 individual apples OR approximately 3 lbs
3. Cart contains a gallon of WHOLE milk that is NOT organic
4. Cart contains Advil (Ibuprofen) in tablet or caplet form (smallest available pack size)

The task FAILS if:
- Any of the 3 products are missing from the cart
- The milk is organic
- The apple quantity is wrong
- The cart verification shows fewer than 3 distinct products"""
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

Report the product name and price.
"""
))

register_scenario(Scenario(
    name="target_store_finder",
    description="Find nearest Target store by ZIP code",
    start_url="https://target.com",
    tags=["e-commerce", "store-locator"],
    goal="""Go to target.com.

Find the store locator (usually in the header or footer).
Enter ZIP code: 02139 (Cambridge, MA)

Find the nearest Target store and report:
1. Store address
2. Store hours for today
3. Whether it has Order Pickup available
"""
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
"""
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
3. Location/ZIP: 02139 (Cambridge, MA)
4. Maximum price: $25,000
5. Year: 2020 or newer

Wait for results to load and report:
1. The number of results found
2. The first 3 listings with: Year, Price, Mileage
3. Any "Great Deal" or "Good Deal" badges on these listings
"""
))


# -----------------------------------------------------------------------------
# Food Delivery Scenarios
# -----------------------------------------------------------------------------

register_scenario(Scenario(
    name="doordash_add_to_cart",
    description="Find a restaurant and add food to cart on DoorDash",
    start_url="https://www.doordash.com",
    tags=["food-delivery", "cart", "restaurant"],
    goal="""Go to doordash.com.

First, set your delivery address to: 1 Main St, Springfield, IL 62701
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
"""
))

register_scenario(Scenario(
    name="grubhub_add_to_cart",
    description="Find a restaurant and add food to cart on Grubhub",
    start_url="https://www.grubhub.com",
    tags=["food-delivery", "cart", "restaurant"],
    goal="""Go to grubhub.com.

First, set your delivery address to: 1 Main St, Springfield, IL 62701
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
"""
))

register_scenario(Scenario(
    name="ubereats_add_to_cart",
    description="Find a restaurant and add food to cart on Uber Eats",
    start_url="https://www.ubereats.com",
    tags=["food-delivery", "cart", "restaurant"],
    goal="""Go to ubereats.com.

First, set your delivery address to: 1 Main St, Springfield, IL 62701
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
"""
))

register_scenario(Scenario(
    name="instacart_add_to_cart",
    description="Set store location and add groceries to cart on Instacart",
    start_url="https://www.instacart.com",
    tags=["grocery", "cart", "food-delivery"],
    goal="""Go to instacart.com.

First, set your delivery address to: 1 Main St, Springfield, IL 62701
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
"""
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
"""
))


# -----------------------------------------------------------------------------
# Authentication / Forms Scenarios
# -----------------------------------------------------------------------------

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
"""
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
"""
))


# -----------------------------------------------------------------------------
# Travel / Booking Scenarios
# -----------------------------------------------------------------------------

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
"""
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
"""
))


# -----------------------------------------------------------------------------
# Simple / Quick Scenarios (good for testing)
# -----------------------------------------------------------------------------

register_scenario(Scenario(
    name="google_search",
    description="Simple Google search",
    start_url="https://google.com",
    tags=["search", "simple", "quick"],
    goal="""Go to google.com.

Search for "best programming languages 2024".

Report the first 3 search results with their titles.
"""
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
"""
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
"""
))


# -----------------------------------------------------------------------------
# Multi-Step Form / Modal Scenarios
# -----------------------------------------------------------------------------

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
"""
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
"""
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
"""
))


# -----------------------------------------------------------------------------
# Quantity / Size Selection Scenarios
# -----------------------------------------------------------------------------

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
"""
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
"""
))


# -----------------------------------------------------------------------------
# Multi-Step Navigation Scenarios
# -----------------------------------------------------------------------------

register_scenario(Scenario(
    name="home_depot_store_pickup",
    description="Find a product on Home Depot and check store pickup availability",
    start_url="https://www.homedepot.com",
    tags=["e-commerce", "store-locator", "availability"],
    goal="""Go to homedepot.com.

1. Search for "Phillips screwdriver set" using the search bar.
2. Click on the first relevant product from the results.
3. On the product page, look for store pickup availability.
4. If prompted, enter ZIP code: 94403 to check local store availability.
5. Report whether the item is available for pickup, and at which store.

IMPORTANT - How to verify success:
Look for ANY of these indicators:
1. A store name appears with "Available" or "In Stock" status
2. A "Free Pickup" badge is shown
3. Store pickup details are displayed with a specific store location
"""
))

register_scenario(Scenario(
    name="zillow_home_search",
    description="Search for homes on Zillow with filters",
    start_url="https://www.zillow.com",
    tags=["real-estate", "search", "filters"],
    goal="""Go to zillow.com.

1. Search for homes in "San Mateo, CA" using the search bar.
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
"""
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
"""
))


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_scenario(name: str) -> Scenario:
    """
    Get a scenario by name.
    
    Args:
        name: Scenario name (case-insensitive)
        
    Returns:
        The Scenario object
        
    Raises:
        KeyError: If scenario not found
    """
    name_lower = name.lower()
    
    # Try exact match first
    if name_lower in SCENARIOS:
        return SCENARIOS[name_lower]
    
    # Try case-insensitive match
    for key, scenario in SCENARIOS.items():
        if key.lower() == name_lower:
            return scenario
    
    raise KeyError(f"Scenario '{name}' not found. Available: {list(SCENARIOS.keys())}")


def list_scenarios(tag: Optional[str] = None) -> List[Scenario]:
    """
    List all available scenarios, optionally filtered by tag.
    
    Args:
        tag: Optional tag to filter by
        
    Returns:
        List of Scenario objects
    """
    scenarios = list(SCENARIOS.values())
    
    if tag:
        tag_lower = tag.lower()
        scenarios = [s for s in scenarios if tag_lower in [t.lower() for t in s.tags]]
    
    return scenarios


def create_custom_scenario(goal: str, start_url: Optional[str] = None, 
                          name: str = "custom") -> Scenario:
    """
    Create a custom scenario from a goal string.
    
    Args:
        goal: The goal/prompt for the agent
        start_url: Optional starting URL
        name: Optional name for the scenario
        
    Returns:
        A new Scenario object (not registered globally)
    """
    return Scenario(
        name=name,
        description="Custom scenario",
        goal=goal,
        start_url=start_url,
        tags=["custom"]
    )
