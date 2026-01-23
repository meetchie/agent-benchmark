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
    goal="""Go to shipt.com.

First, you need to set a delivery address before you can search for products.
Find the address input field (it says "Find stores near you") and enter: 1 Main St, Springfield, IL 62701
Wait for the autocomplete dropdown and click the first suggestion.

Once on the main shopping page, search for "Organic Bananas" and add the first result to your cart.

IMPORTANT - How to verify success:
After clicking the add-to-cart button, look for ANY of these success indicators:
1. The product card shows "X in cart" (e.g., "1 in cart") with a checkmark
2. The cart icon in the top-right shows a number badge (like "1")
3. A toast/notification appears saying the item was added
"""
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
