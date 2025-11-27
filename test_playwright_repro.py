"""Minimal reproduction script for Playwright timeout issue with event bus."""
import asyncio
import logging
from browser_use import Browser
from browser_use.browser.events import ClickElementEvent
from browser_use.browser.watchdogs.playwright_action_watchdog import PlaywrightActionWatchdog

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def test_playwright_timeout():
    """Test Playwright click through event bus (like real app)."""
    
    # Create browser session (Browser is an alias for BrowserSession)
    session = Browser(headless=False)
    
    logger.info("🚀 Starting browser session...")
    await session.start()
    
    logger.info("✅ Browser started, CDP URL: %s", session.cdp_url)
    
    # Navigate to a simple page
    logger.info("🌐 Navigating to example.com...")
    await session.navigate_to("https://example.com")
    await asyncio.sleep(2)  # Wait for page to load
    
    # Get browser state to find a real element
    logger.info("\n📄 Getting browser state to find clickable element...")
    browser_state = await session.get_browser_state_summary(include_screenshot=False)
    
    if not browser_state.dom_state or not browser_state.dom_state.selector_map:
        logger.error("❌ No elements found on page!")
        await session.kill()
        return
    
    # Log all available elements
    logger.info(f"📋 Found {len(browser_state.dom_state.selector_map)} elements in selector_map:")
    for idx, (backend_node_id, node) in enumerate(list(browser_state.dom_state.selector_map.items())[:10]):
        logger.info(f"   [{idx+1}] backend_node_id={backend_node_id}, tag={node.node_name}, visible={node.is_visible}")
    
    # Try to find h1 first, then fall back to any element
    test_node = None
    for backend_node_id, node in browser_state.dom_state.selector_map.items():
        if node.node_name.lower() == 'h1':
            test_node = node
            logger.info(f"✅ Found h1 element: backend_node_id={backend_node_id}")
            break
    
    # If no h1, use the first available element
    if not test_node:
        first_backend_id = next(iter(browser_state.dom_state.selector_map.keys()))
        test_node = browser_state.dom_state.selector_map[first_backend_id]
        logger.info(f"⚠️ No h1 found, using first element: backend_node_id={first_backend_id}, tag={test_node.node_name}")
    
    if not test_node:
        logger.error("❌ No elements found in selector_map!")
        await session.kill()
        return
    
    # Test 1: Direct Playwright call (like before - should work)
    logger.info("\n📄 Test 1: Direct Playwright call (baseline)...")
    playwright_watchdog = session._default_action_watchdog
    if not playwright_watchdog or not isinstance(playwright_watchdog, PlaywrightActionWatchdog):
        logger.error("❌ PlaywrightActionWatchdog not found!")
        await session.kill()
        return
    
    try:
        page = await playwright_watchdog._get_playwright_page()
        # Try to find h1, or use body if h1 not available
        try:
            locator = page.locator("h1").first
            await locator.wait_for(state='visible', timeout=2000)
        except:
            locator = page.locator("body").first
        await locator.scroll_into_view_if_needed()
        await locator.wait_for(state='visible', timeout=5000)
        box = await locator.bounding_box()
        logger.info(f"✅ Direct call succeeded, bounding box: {box}")
    except Exception as e:
        logger.error(f"❌ Direct call failed: {e}", exc_info=True)
        await session.kill()
        return
    
    # Test 2: Click through event bus (like real app)
    logger.info("\n📄 Test 2: Click through event bus (simulating real app)...")
    logger.info(f"   Target ID: {session.agent_focus_target_id[-8:] if session.agent_focus_target_id else None}")
    logger.info(f"   Node backend_node_id: {test_node.backend_node_id}")
    logger.info(f"   Node target_id: {test_node.target_id[-8:] if test_node.target_id else None}")
    logger.info(f"   Node tag: {test_node.node_name}")
    
    try:
        # Create ClickElementEvent (like Tools._click_by_index does)
        click_event = ClickElementEvent(node=test_node)
        
        logger.info("   Dispatching ClickElementEvent...")
        # Dispatch event (like browser_session.event_bus.dispatch)
        event = session.event_bus.dispatch(click_event)
        
        logger.info("   Awaiting event completion...")
        # Await event (like await event)
        await event
        
        logger.info("   Getting event result...")
        # Get result (like await event.event_result())
        click_metadata = await event.event_result(raise_if_any=True, raise_if_none=False)
        
        logger.info(f"✅ Event bus click succeeded! Metadata: {click_metadata}")
        
    except Exception as e:
        logger.error(f"❌ Event bus click failed: {e}", exc_info=True)
        if 'event' in locals():
            logger.error(f"   Event status: {event.event_status}")
            logger.error(f"   Event results: {event.event_results}")
        await session.kill()
        return
    
    logger.info("\n✅ All tests passed!")
    
    # Keep browser open for inspection
    logger.info("Keeping browser open for 10 seconds...")
    await asyncio.sleep(10)
    
    await session.kill()

if __name__ == "__main__":
    asyncio.run(test_playwright_timeout())

