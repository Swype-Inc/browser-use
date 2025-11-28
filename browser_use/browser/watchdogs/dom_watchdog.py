"""DOM watchdog for browser DOM tree management using CDP."""

import asyncio
import time
from typing import TYPE_CHECKING

from browser_use.browser.events import (
	BrowserErrorEvent,
	BrowserStateRequestEvent,
	ScreenshotEvent,
	TabCreatedEvent,
)
from browser_use.browser.watchdog_base import BaseWatchdog
from browser_use.dom.service import DomService
from browser_use.dom.views import (
	EnhancedDOMTreeNode,
	SerializedDOMState,
)
from browser_use.observability import observe_debug
from browser_use.utils import create_task_with_error_handling, time_execution_async

if TYPE_CHECKING:
	from browser_use.browser.views import BrowserStateSummary, NetworkRequest, PageInfo, PaginationButton


class DOMWatchdog(BaseWatchdog):
	"""Handles DOM tree building, serialization, and element access via CDP.

	This watchdog acts as a bridge between the event-driven browser session
	and the DomService implementation, maintaining cached state and providing
	helper methods for other watchdogs.
	"""

	LISTENS_TO = [TabCreatedEvent, BrowserStateRequestEvent]
	EMITS = [BrowserErrorEvent]

	# Public properties for other watchdogs
	selector_map: dict[int, EnhancedDOMTreeNode] | None = None
	current_dom_state: SerializedDOMState | None = None
	enhanced_dom_tree: EnhancedDOMTreeNode | None = None

	# Internal DOM service
	_dom_service: DomService | None = None

	# Network tracking - maps request_id to (url, start_time, method, resource_type)
	_pending_requests: dict[str, tuple[str, float, str, str | None]] = {}

	async def on_TabCreatedEvent(self, event: TabCreatedEvent) -> None:
		# self.logger.debug('Setting up init scripts in browser')
		return None

	def _get_recent_events_str(self, limit: int = 10) -> str | None:
		"""Get the most recent events from the event bus as JSON.

		Args:
			limit: Maximum number of recent events to include

		Returns:
			JSON string of recent events or None if not available
		"""
		import json

		try:
			# Get all events from history, sorted by creation time (most recent first)
			all_events = sorted(
				self.browser_session.event_bus.event_history.values(), key=lambda e: e.event_created_at.timestamp(), reverse=True
			)

			# Take the most recent events and create JSON-serializable data
			recent_events_data = []
			for event in all_events[:limit]:
				event_data = {
					'event_type': event.event_type,
					'timestamp': event.event_created_at.isoformat(),
				}
				# Add specific fields for certain event types
				if hasattr(event, 'url'):
					event_data['url'] = getattr(event, 'url')
				if hasattr(event, 'error_message'):
					event_data['error_message'] = getattr(event, 'error_message')
				if hasattr(event, 'target_id'):
					event_data['target_id'] = getattr(event, 'target_id')
				recent_events_data.append(event_data)

			return json.dumps(recent_events_data)  # Return empty array if no events
		except Exception as e:
			self.logger.debug(f'Failed to get recent events: {e}')

		return json.dumps([])  # Return empty JSON array on error

	async def _get_pending_network_requests(self) -> list['NetworkRequest']:
		"""Get list of currently pending network requests.

		Uses document.readyState and performance API to detect pending requests.
		Filters out ads, tracking, and other noise.

		Returns:
			List of NetworkRequest objects representing currently loading resources
		"""
		from browser_use.browser.views import NetworkRequest

		try:
			# get_or_create_cdp_session() now handles focus validation automatically
			cdp_session = await self.browser_session.get_or_create_cdp_session(focus=True)

			# Use performance API to get pending requests
			js_code = """
(function() {
	const now = performance.now();
	const resources = performance.getEntriesByType('resource');
	const pending = [];

	// Check document readyState
	const docLoading = document.readyState !== 'complete';

	// Common ad/tracking domains and patterns to filter out
	const adDomains = [
		// Standard ad/tracking networks
		'doubleclick.net', 'googlesyndication.com', 'googletagmanager.com',
		'facebook.net', 'analytics', 'ads', 'tracking', 'pixel',
		'hotjar.com', 'clarity.ms', 'mixpanel.com', 'segment.com',
		// Analytics platforms
		'demdex.net', 'omtrdc.net', 'adobedtm.com', 'ensighten.com',
		'newrelic.com', 'nr-data.net', 'google-analytics.com',
		// Social media trackers
		'connect.facebook.net', 'platform.twitter.com', 'platform.linkedin.com',
		// CDN/image hosts (usually not critical for functionality)
		'.cloudfront.net/image/', '.akamaized.net/image/',
		// Common tracking paths
		'/tracker/', '/collector/', '/beacon/', '/telemetry/', '/log/',
		'/events/', '/eventBatch', '/track.', '/metrics/'
	];

	// Get resources that are still loading (responseEnd is 0)
	let totalResourcesChecked = 0;
	let filteredByResponseEnd = 0;
	const allDomains = new Set();

	for (const entry of resources) {
		totalResourcesChecked++;

		// Track all domains from recent resources (for logging)
		try {
			const hostname = new URL(entry.name).hostname;
			if (hostname) allDomains.add(hostname);
		} catch (e) {}

		if (entry.responseEnd === 0) {
			filteredByResponseEnd++;
			const url = entry.name;

			// Filter out ads and tracking
			const isAd = adDomains.some(domain => url.includes(domain));
			if (isAd) continue;

			// Filter out data: URLs and very long URLs (often inline resources)
			if (url.startsWith('data:') || url.length > 500) continue;

			const loadingDuration = now - entry.startTime;

			// Skip requests that have been loading for >10 seconds (likely stuck/polling)
			if (loadingDuration > 10000) continue;

			const resourceType = entry.initiatorType || 'unknown';

			// Filter out non-critical resources (images, fonts, icons) if loading >3 seconds
			const nonCriticalTypes = ['img', 'image', 'icon', 'font'];
			if (nonCriticalTypes.includes(resourceType) && loadingDuration > 3000) continue;

			// Filter out image URLs even if type is unknown
			const isImageUrl = /\\.(jpg|jpeg|png|gif|webp|svg|ico)(\\?|$)/i.test(url);
			if (isImageUrl && loadingDuration > 3000) continue;

			pending.push({
				url: url,
				method: 'GET',
				loading_duration_ms: Math.round(loadingDuration),
				resource_type: resourceType
			});
		}
	}

	return {
		pending_requests: pending,
		document_loading: docLoading,
		document_ready_state: document.readyState,
		debug: {
			total_resources: totalResourcesChecked,
			with_response_end_zero: filteredByResponseEnd,
			after_all_filters: pending.length,
			all_domains: Array.from(allDomains)
		}
	};
})()
"""

			result = await cdp_session.cdp_client.send.Runtime.evaluate(
				params={'expression': js_code, 'returnByValue': True}, session_id=cdp_session.session_id
			)

			if result.get('result', {}).get('type') == 'object':
				data = result['result'].get('value', {})
				pending = data.get('pending_requests', [])
				doc_state = data.get('document_ready_state', 'unknown')
				doc_loading = data.get('document_loading', False)
				debug_info = data.get('debug', {})

				# Get all domains that had recent activity (from JS)
				all_domains = debug_info.get('all_domains', [])
				all_domains_str = ', '.join(sorted(all_domains)[:5]) if all_domains else 'none'
				if len(all_domains) > 5:
					all_domains_str += f' +{len(all_domains) - 5} more'

				# Debug logging
				self.logger.debug(
					f'🔍 Network check: document.readyState={doc_state}, loading={doc_loading}, '
					f'total_resources={debug_info.get("total_resources", 0)}, '
					f'responseEnd=0: {debug_info.get("with_response_end_zero", 0)}, '
					f'after_filters={len(pending)}, domains=[{all_domains_str}]'
				)

				# Convert to NetworkRequest objects
				network_requests = []
				for req in pending[:20]:  # Limit to 20 to avoid overwhelming the context
					network_requests.append(
						NetworkRequest(
							url=req['url'],
							method=req.get('method', 'GET'),
							loading_duration_ms=req.get('loading_duration_ms', 0.0),
							resource_type=req.get('resource_type'),
						)
					)

				return network_requests

		except Exception as e:
			self.logger.debug(f'Failed to get pending network requests: {e}')

		return []

	@time_execution_async('wait_for_page_stability')
	async def wait_for_page_stability(self) -> None:
		"""Public method to wait for page stability (network + DOM) before LLM requests.
		
		This ensures the page is fully loaded and stable before proceeding.
		Should be called after navigation or any action that might change the page state.
		"""
		page_url = await self.browser_session.get_current_page_url()
		
		# Check if we should skip for non-HTTP pages
		not_a_meaningful_website = page_url.lower().split(':', 1)[0] not in ('http', 'https')
		if not_a_meaningful_website:
			return
		
		self.logger.debug('🔍 DOMWatchdog.wait_for_page_stability: ⏳ Waiting for page stability...')
		
		try:
			# Check for pending network requests BEFORE waiting
			pending_requests_before_wait = []
			try:
				pending_requests_before_wait = await self._get_pending_network_requests()
				if pending_requests_before_wait:
					self.logger.debug(f'🔍 Found {len(pending_requests_before_wait)} pending requests before stability wait')
			except Exception as e:
				self.logger.debug(f'Failed to get pending requests before wait: {e}')
			
			# Run network wait and DOM stability wait in parallel
			async def wait_for_network():
				"""Wait for network requests to finish (up to 3 seconds)"""
				if pending_requests_before_wait:
					max_network_wait = 3.0
					check_interval = 0.2
					elapsed_time = 0.0
					
					while elapsed_time < max_network_wait:
						current_pending = await self._get_pending_network_requests()
						
						if not current_pending:
							self.logger.debug(
								f'🔍 wait_for_page_stability: ✅ All network requests finished '
								f'after {elapsed_time:.2f}s'
							)
							return elapsed_time
						
						await asyncio.sleep(check_interval)
						elapsed_time += check_interval
					
					final_pending = await self._get_pending_network_requests()
					if final_pending:
						self.logger.debug(
							f'🔍 wait_for_page_stability: ⏱️  Network wait timeout. '
							f'Still {len(final_pending)} pending requests'
						)
					return elapsed_time
				else:
					self.logger.debug('🔍 wait_for_page_stability: No pending requests, skipping network wait')
					return 0.0
			
			async def wait_for_dom():
				"""Wait for DOM to stabilize (no mutations for 2 seconds, max 5 seconds)"""
				self.logger.debug('🔍 wait_for_page_stability: ⏳ Waiting for DOM stability...')
				dom_stable = await self._wait_for_dom_stability(max_wait_time=5.0, stability_period=2.0)
				
				if dom_stable:
					self.logger.debug('🔍 wait_for_page_stability: ✅ DOM stabilized')
				else:
					self.logger.debug('🔍 wait_for_page_stability: ⚠️  DOM stability timeout, proceeding anyway')
				
				return dom_stable
			
			# Run both waits in parallel and wait for both to complete
			network_task = create_task_with_error_handling(
				wait_for_network(),
				name='wait_for_network',
				logger_instance=self.logger,
				suppress_exceptions=True,
			)
			dom_task = create_task_with_error_handling(
				wait_for_dom(),
				name='wait_for_dom',
				logger_instance=self.logger,
				suppress_exceptions=True,
			)
			
			# Wait for both to complete (they run in parallel)
			network_time, dom_result = await asyncio.gather(network_task, dom_task, return_exceptions=True)
			
			# Handle exceptions
			if isinstance(network_time, Exception):
				self.logger.warning(f'Network wait failed: {network_time}')
				network_time = 0.0
			if isinstance(dom_result, Exception):
				self.logger.warning(f'DOM wait failed: {dom_result}')
				dom_result = False
			
			# Calculate total wait time (max of network and DOM wait)
			network_elapsed = network_time if isinstance(network_time, (int, float)) else 0.0
			# DOM wait always takes at least stability_period (2s) if stable, or max_wait_time (5s) if timeout
			total_wait_time = max(network_elapsed, 2.0)  # At least 2s for DOM stability period
			
			self.logger.debug(
				f'🔍 wait_for_page_stability: ✅ Page stability complete '
				f'(network: {network_elapsed:.2f}s, DOM: {"stable" if dom_result else "timeout"}, total: {total_wait_time:.2f}s)'
			)
			
		except Exception as e:
			self.logger.warning(
				f'🔍 wait_for_page_stability: Stability waiting failed: {e}, continuing anyway...'
			)

	@time_execution_async('wait_for_dom_stability')
	async def _wait_for_dom_stability(self, max_wait_time: float = 5.0, stability_period: float = 2.0) -> bool:
		"""Wait for DOM to stabilize (no mutations for stability_period seconds).
		
		Uses MutationObserver to detect when DOM stops changing.
		
		Args:
			max_wait_time: Maximum time to wait in seconds
			stability_period: Time period (in seconds) with no mutations to consider DOM stable
			
		Returns:
			True if DOM stabilized, False if max_wait_time reached
		"""
		try:
			cdp_session = await self.browser_session.get_or_create_cdp_session(focus=True)
			
			# JavaScript code to set up MutationObserver and wait for stability
			js_code = f"""
			(function() {{
				return new Promise((resolve) => {{
					let mutationCount = 0;
					let lastMutationTime = Date.now();
					let stabilityTimer = null;
					const maxWaitMs = {int(max_wait_time * 1000)};
					const stabilityPeriodMs = {int(stability_period * 1000)};
					const startTime = Date.now();
					
					const observer = new MutationObserver((mutations) => {{
						mutationCount += mutations.length;
						lastMutationTime = Date.now();
						
						// Clear existing timer
						if (stabilityTimer) {{
							clearTimeout(stabilityTimer);
						}}
						
						// Set new timer - if no mutations for stability_period, resolve
						stabilityTimer = setTimeout(() => {{
							observer.disconnect();
							resolve({{
								stable: true,
								mutation_count: mutationCount,
								elapsed_ms: Date.now() - startTime
							}});
						}}, stabilityPeriodMs);
					}});
					
					// Start observing
					observer.observe(document.body, {{
						childList: true,
						subtree: true,
						attributes: true,
						attributeOldValue: false,
						characterData: true
					}});
					
					// Set initial timer
					stabilityTimer = setTimeout(() => {{
						observer.disconnect();
						resolve({{
							stable: true,
							mutation_count: mutationCount,
							elapsed_ms: Date.now() - startTime
						}});
					}}, stabilityPeriodMs);
					
					// Max wait timeout
					setTimeout(() => {{
						observer.disconnect();
						if (stabilityTimer) clearTimeout(stabilityTimer);
						resolve({{
							stable: false,
							mutation_count: mutationCount,
							elapsed_ms: maxWaitMs
						}});
					}}, maxWaitMs);
				}});
			}})()
			"""
			
			result = await cdp_session.cdp_client.send.Runtime.evaluate(
				params={'expression': js_code, 'returnByValue': True, 'awaitPromise': True},
				session_id=cdp_session.session_id
			)
			
			if result.get('result', {}).get('type') == 'object':
				data = result['result'].get('value', {})
				stable = data.get('stable', False)
				mutation_count = data.get('mutation_count', 0)
				elapsed_ms = data.get('elapsed_ms', 0)
				
				if stable:
					self.logger.debug(
						f'🔍 DOM stability: ✅ DOM stabilized after {elapsed_ms:.0f}ms '
						f'({mutation_count} mutations observed)'
					)
				else:
					self.logger.debug(
						f'🔍 DOM stability: ⏱️  Max wait time reached ({elapsed_ms:.0f}ms). '
						f'DOM may still be changing ({mutation_count} mutations observed)'
					)
				
				return stable
			
			return False
			
		except Exception as e:
			self.logger.debug(f'Failed to wait for DOM stability: {e}')
			return False

	@observe_debug(ignore_input=True, ignore_output=True, name='browser_state_request_event')
	async def on_BrowserStateRequestEvent(self, event: BrowserStateRequestEvent) -> 'BrowserStateSummary':
		"""Handle browser state request by coordinating DOM building and screenshot capture.

		This is the main entry point for getting the complete browser state.

		Args:
			event: The browser state request event with options

		Returns:
			Complete BrowserStateSummary with DOM, screenshot, and target info
		"""
		from browser_use.browser.views import BrowserStateSummary, PageInfo

		self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: STARTING browser state request')
		page_url = await self.browser_session.get_current_page_url()
		self.logger.debug(f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Got page URL: {page_url}')

		# Get focused session for logging (validation already done by get_current_page_url)
		if self.browser_session.agent_focus_target_id:
			self.logger.debug(f'Current page URL: {page_url}, target_id: {self.browser_session.agent_focus_target_id}')

		# check if we should skip DOM tree build for pointless pages
		not_a_meaningful_website = page_url.lower().split(':', 1)[0] not in ('http', 'https')

		# Check for pending network requests BEFORE waiting (so we can see what's loading)
		pending_requests_before_wait = []
		if not not_a_meaningful_website:
			try:
				pending_requests_before_wait = await self._get_pending_network_requests()
				if pending_requests_before_wait:
					self.logger.debug(f'🔍 Found {len(pending_requests_before_wait)} pending requests before stability wait')
			except Exception as e:
				self.logger.debug(f'Failed to get pending requests before wait: {e}')
		
		# Wait for page stability: network requests AND DOM stability (run in parallel, wait for max)
		if not not_a_meaningful_website:
			self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: ⏳ Waiting for page stability...')
			try:
				# Run network wait and DOM stability wait in parallel
				async def wait_for_network():
					"""Wait for network requests to finish (up to 3 seconds)"""
					if pending_requests_before_wait:
						max_network_wait = 3.0
						check_interval = 0.2
						elapsed_time = 0.0
						
						while elapsed_time < max_network_wait:
							current_pending = await self._get_pending_network_requests()
							
							if not current_pending:
								self.logger.debug(
									f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: ✅ All network requests finished '
									f'after {elapsed_time:.2f}s'
								)
								return elapsed_time
							
							await asyncio.sleep(check_interval)
							elapsed_time += check_interval
						
						final_pending = await self._get_pending_network_requests()
						if final_pending:
							self.logger.debug(
								f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: ⏱️  Network wait timeout. '
								f'Still {len(final_pending)} pending requests'
							)
						return elapsed_time
					else:
						self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: No pending requests, skipping network wait')
						return 0.0
				
				async def wait_for_dom():
					"""Wait for DOM to stabilize (no mutations for 2 seconds, max 5 seconds)"""
					self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: ⏳ Waiting for DOM stability...')
					dom_stable = await self._wait_for_dom_stability(max_wait_time=5.0, stability_period=2.0)
					
					if dom_stable:
						self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: ✅ DOM stabilized')
					else:
						self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: ⚠️  DOM stability timeout, proceeding anyway')
					
					return dom_stable
				
				# Run both waits in parallel and wait for both to complete
				network_task = create_task_with_error_handling(
					wait_for_network(),
					name='wait_for_network',
					logger_instance=self.logger,
					suppress_exceptions=True,
				)
				dom_task = create_task_with_error_handling(
					wait_for_dom(),
					name='wait_for_dom',
					logger_instance=self.logger,
					suppress_exceptions=True,
				)
				
				# Wait for both to complete (they run in parallel)
				network_time, dom_result = await asyncio.gather(network_task, dom_task, return_exceptions=True)
				
				# Handle exceptions
				if isinstance(network_time, Exception):
					self.logger.warning(f'Network wait failed: {network_time}')
					network_time = 0.0
				if isinstance(dom_result, Exception):
					self.logger.warning(f'DOM wait failed: {dom_result}')
					dom_result = False
				
				# Calculate total wait time (max of network and DOM wait)
				network_elapsed = network_time if isinstance(network_time, (int, float)) else 0.0
				# DOM wait always takes at least stability_period (2s) if stable, or max_wait_time (5s) if timeout
				# We don't track exact DOM wait time, but we know it's at least 2s if stable
				total_wait_time = max(network_elapsed, 2.0)  # At least 2s for DOM stability period
				
				self.logger.debug(
					f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: ✅ Page stability complete '
					f'(network: {network_elapsed:.2f}s, DOM: {"stable" if dom_result else "timeout"}, total: {total_wait_time:.2f}s)'
				)
				
			except Exception as e:
				self.logger.warning(
					f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Stability waiting failed: {e}, continuing anyway...'
				)
		
		# Get final pending requests for the summary
		pending_requests = []
		if not not_a_meaningful_website:
			try:
				pending_requests = await self._get_pending_network_requests()
			except Exception as e:
				self.logger.debug(f'Failed to get final pending requests: {e}')

		# Get tabs info once at the beginning for all paths
		self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: Getting tabs info...')
		tabs_info = await self.browser_session.get_tabs()
		self.logger.debug(f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Got {len(tabs_info)} tabs')
		self.logger.debug(f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Tabs info: {tabs_info}')

		# Get viewport / scroll position info, remember changing scroll position should invalidate selector_map cache because it only includes visible elements
		# cdp_session = await self.browser_session.get_or_create_cdp_session(focus=True)
		# scroll_info = await cdp_session.cdp_client.send.Runtime.evaluate(
		# 	params={'expression': 'JSON.stringify({y: document.body.scrollTop, x: document.body.scrollLeft, width: document.documentElement.clientWidth, height: document.documentElement.clientHeight})'},
		# 	session_id=cdp_session.session_id,
		# )
		# self.logger.debug(f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Got scroll info: {scroll_info["result"]}')

		try:
			# Fast path for empty pages
			if not_a_meaningful_website:
				self.logger.debug(f'⚡ Skipping BuildDOMTree for empty target: {page_url}')
				self.logger.debug(f'📸 Not taking screenshot for empty page: {page_url} (non-http/https URL)')

				# Create minimal DOM state
				content = SerializedDOMState(_root=None, selector_map={})

				# Skip screenshot for empty pages
				screenshot_b64 = None

				# Try to get page info from CDP, fall back to defaults if unavailable
				try:
					page_info = await self._get_page_info()
				except Exception as e:
					self.logger.debug(f'Failed to get page info from CDP for empty page: {e}, using fallback')
					# Use default viewport dimensions
					viewport = self.browser_session.browser_profile.viewport or {'width': 1280, 'height': 720}
					page_info = PageInfo(
						viewport_width=viewport['width'],
						viewport_height=viewport['height'],
						page_width=viewport['width'],
						page_height=viewport['height'],
						scroll_x=0,
						scroll_y=0,
						pixels_above=0,
						pixels_below=0,
						pixels_left=0,
						pixels_right=0,
					)

				return BrowserStateSummary(
					dom_state=content,
					url=page_url,
					title='Empty Tab',
					tabs=tabs_info,
					screenshot=screenshot_b64,
					page_info=page_info,
					pixels_above=0,
					pixels_below=0,
					browser_errors=[],
					is_pdf_viewer=False,
					recent_events=self._get_recent_events_str() if event.include_recent_events else None,
					pending_network_requests=[],  # Empty page has no pending requests
					pagination_buttons=[],  # Empty page has no pagination
					closed_popup_messages=self.browser_session._closed_popup_messages.copy(),
				)

			# Execute DOM building and screenshot capture in parallel
			dom_task = None
			screenshot_task = None

			# Start DOM building task if requested
			if event.include_dom:
				self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: 🌳 Starting DOM tree build task...')

				previous_state = (
					self.browser_session._cached_browser_state_summary.dom_state
					if self.browser_session._cached_browser_state_summary
					else None
				)

				dom_task = create_task_with_error_handling(
					self._build_dom_tree_without_highlights(previous_state, event.include_all_form_fields),
					name='build_dom_tree',
					logger_instance=self.logger,
					suppress_exceptions=True,
				)

			# Start clean screenshot task if requested (without JS highlights)
			if event.include_screenshot:
				self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: 📸 Starting clean screenshot task...')
				screenshot_task = create_task_with_error_handling(
					self._capture_clean_screenshot(),
					name='capture_screenshot',
					logger_instance=self.logger,
					suppress_exceptions=True,
				)

			# Wait for both tasks to complete
			content = None
			screenshot_b64 = None

			if dom_task:
				try:
					content = await dom_task
					self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: ✅ DOM tree build completed')
				except Exception as e:
					self.logger.warning(f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: DOM build failed: {e}, using minimal state')
					content = SerializedDOMState(_root=None, selector_map={})
			else:
				content = SerializedDOMState(_root=None, selector_map={})

			if screenshot_task:
				try:
					screenshot_b64 = await screenshot_task
					self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: ✅ Clean screenshot captured')
				except Exception as e:
					self.logger.warning(f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Clean screenshot failed: {e}')
					screenshot_b64 = None

			# Add browser-side highlights for user visibility
			if content and content.selector_map and self.browser_session.browser_profile.dom_highlight_elements:
				try:
					self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: 🎨 Adding browser-side highlights...')
					await self.browser_session.add_highlights(content.selector_map)
					self.logger.debug(
						f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: ✅ Added browser highlights for {len(content.selector_map)} elements'
					)
				except Exception as e:
					self.logger.warning(f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Browser highlighting failed: {e}')

			# Ensure we have valid content
			if not content:
				content = SerializedDOMState(_root=None, selector_map={})

			# Tabs info already fetched at the beginning

			# Get target title safely
			try:
				self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: Getting page title...')
				title = await asyncio.wait_for(self.browser_session.get_current_page_title(), timeout=1.0)
				self.logger.debug(f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Got title: {title}')
			except Exception as e:
				self.logger.debug(f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Failed to get title: {e}')
				title = 'Page'

			# Get comprehensive page info from CDP with timeout
			try:
				self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: Getting page info from CDP...')
				page_info = await asyncio.wait_for(self._get_page_info(), timeout=1.0)
				self.logger.debug(f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Got page info from CDP: {page_info}')
			except Exception as e:
				self.logger.debug(
					f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: Failed to get page info from CDP: {e}, using fallback'
				)
				# Fallback to default viewport dimensions
				viewport = self.browser_session.browser_profile.viewport or {'width': 1280, 'height': 720}
				page_info = PageInfo(
					viewport_width=viewport['width'],
					viewport_height=viewport['height'],
					page_width=viewport['width'],
					page_height=viewport['height'],
					scroll_x=0,
					scroll_y=0,
					pixels_above=0,
					pixels_below=0,
					pixels_left=0,
					pixels_right=0,
				)

			# Check for PDF viewer
			is_pdf_viewer = page_url.endswith('.pdf') or '/pdf/' in page_url

			# Detect pagination buttons from the DOM
			pagination_buttons_data = []
			if content and content.selector_map:
				pagination_buttons_data = self._detect_pagination_buttons(content.selector_map)

			# Build and cache the browser state summary
			if screenshot_b64:
				self.logger.debug(
					f'🔍 DOMWatchdog.on_BrowserStateRequestEvent: 📸 Creating BrowserStateSummary with screenshot, length: {len(screenshot_b64)}'
				)
			else:
				self.logger.debug(
					'🔍 DOMWatchdog.on_BrowserStateRequestEvent: 📸 Creating BrowserStateSummary WITHOUT screenshot'
				)

			browser_state = BrowserStateSummary(
				dom_state=content,
				url=page_url,
				title=title,
				tabs=tabs_info,
				screenshot=screenshot_b64,
				page_info=page_info,
				pixels_above=0,
				pixels_below=0,
				browser_errors=[],
				is_pdf_viewer=is_pdf_viewer,
				recent_events=self._get_recent_events_str() if event.include_recent_events else None,
				pending_network_requests=pending_requests,
				pagination_buttons=pagination_buttons_data,
				closed_popup_messages=self.browser_session._closed_popup_messages.copy(),
			)

			# Cache the state
			self.browser_session._cached_browser_state_summary = browser_state

			# Cache viewport size for coordinate conversion (if llm_screenshot_size is enabled)
			if page_info:
				self.browser_session._original_viewport_size = (page_info.viewport_width, page_info.viewport_height)

			self.logger.debug('🔍 DOMWatchdog.on_BrowserStateRequestEvent: ✅ COMPLETED - Returning browser state')
			return browser_state

		except Exception as e:
			self.logger.error(f'Failed to get browser state: {e}')

			# Return minimal recovery state
			return BrowserStateSummary(
				dom_state=SerializedDOMState(_root=None, selector_map={}),
				url=page_url if 'page_url' in locals() else '',
				title='Error',
				tabs=[],
				screenshot=None,
				page_info=PageInfo(
					viewport_width=1280,
					viewport_height=720,
					page_width=1280,
					page_height=720,
					scroll_x=0,
					scroll_y=0,
					pixels_above=0,
					pixels_below=0,
					pixels_left=0,
					pixels_right=0,
				),
				pixels_above=0,
				pixels_below=0,
				browser_errors=[str(e)],
				is_pdf_viewer=False,
				recent_events=None,
				pending_network_requests=[],  # Error state has no pending requests
				pagination_buttons=[],  # Error state has no pagination
				closed_popup_messages=self.browser_session._closed_popup_messages.copy()
				if hasattr(self, 'browser_session') and self.browser_session is not None
				else [],
			)

	@time_execution_async('build_dom_tree_without_highlights')
	@observe_debug(ignore_input=True, ignore_output=True, name='build_dom_tree_without_highlights')
	async def _build_dom_tree_without_highlights(
		self, 
		previous_state: SerializedDOMState | None = None,
		include_all_form_fields: bool = False,
	) -> SerializedDOMState:
		"""Build DOM tree without injecting JavaScript highlights (for parallel execution)."""
		try:
			self.logger.debug('🔍 DOMWatchdog._build_dom_tree_without_highlights: STARTING DOM tree build')

			# Create or reuse DOM service
			if self._dom_service is None:
				self._dom_service = DomService(
					browser_session=self.browser_session,
					logger=self.logger,
					cross_origin_iframes=self.browser_session.browser_profile.cross_origin_iframes,
					paint_order_filtering=self.browser_session.browser_profile.paint_order_filtering,
					max_iframes=self.browser_session.browser_profile.max_iframes,
					max_iframe_depth=self.browser_session.browser_profile.max_iframe_depth,
				)

			# Get serialized DOM tree using the service
			self.logger.debug('🔍 DOMWatchdog._build_dom_tree_without_highlights: Calling DomService.get_serialized_dom_tree...')
			start = time.time()
			self.current_dom_state, self.enhanced_dom_tree, timing_info = await self._dom_service.get_serialized_dom_tree(
				previous_cached_state=previous_state,
				include_all_form_fields=include_all_form_fields,
			)
			end = time.time()
			total_time_ms = (end - start) * 1000
			self.logger.debug(
				'🔍 DOMWatchdog._build_dom_tree_without_highlights: ✅ DomService.get_serialized_dom_tree completed'
			)

			# Build hierarchical timing breakdown as single multi-line string
			timing_lines = [f'⏱️ Total DOM tree time: {total_time_ms:.2f}ms', '📊 Timing breakdown:']

			# get_all_trees breakdown
			get_all_trees_ms = timing_info.get('get_all_trees_total_ms', 0)
			if get_all_trees_ms > 0:
				timing_lines.append(f'  ├─ get_all_trees: {get_all_trees_ms:.2f}ms')
				iframe_scroll_ms = timing_info.get('iframe_scroll_detection_ms', 0)
				cdp_parallel_ms = timing_info.get('cdp_parallel_calls_ms', 0)
				snapshot_proc_ms = timing_info.get('snapshot_processing_ms', 0)
				if iframe_scroll_ms > 0.01:
					timing_lines.append(f'  │  ├─ iframe_scroll_detection: {iframe_scroll_ms:.2f}ms')
				if cdp_parallel_ms > 0.01:
					timing_lines.append(f'  │  ├─ cdp_parallel_calls: {cdp_parallel_ms:.2f}ms')
				if snapshot_proc_ms > 0.01:
					timing_lines.append(f'  │  └─ snapshot_processing: {snapshot_proc_ms:.2f}ms')

			# build_ax_lookup
			build_ax_ms = timing_info.get('build_ax_lookup_ms', 0)
			if build_ax_ms > 0.01:
				timing_lines.append(f'  ├─ build_ax_lookup: {build_ax_ms:.2f}ms')

			# build_snapshot_lookup
			build_snapshot_ms = timing_info.get('build_snapshot_lookup_ms', 0)
			if build_snapshot_ms > 0.01:
				timing_lines.append(f'  ├─ build_snapshot_lookup: {build_snapshot_ms:.2f}ms')

			# construct_enhanced_tree
			construct_tree_ms = timing_info.get('construct_enhanced_tree_ms', 0)
			if construct_tree_ms > 0.01:
				timing_lines.append(f'  ├─ construct_enhanced_tree: {construct_tree_ms:.2f}ms')

			# serialize_accessible_elements breakdown
			serialize_total_ms = timing_info.get('serialize_accessible_elements_total_ms', 0)
			if serialize_total_ms > 0.01:
				timing_lines.append(f'  ├─ serialize_accessible_elements: {serialize_total_ms:.2f}ms')
				create_simp_ms = timing_info.get('create_simplified_tree_ms', 0)
				paint_order_ms = timing_info.get('calculate_paint_order_ms', 0)
				optimize_ms = timing_info.get('optimize_tree_ms', 0)
				bbox_ms = timing_info.get('bbox_filtering_ms', 0)
				assign_idx_ms = timing_info.get('assign_interactive_indices_ms', 0)
				clickable_ms = timing_info.get('clickable_detection_time_ms', 0)

				if create_simp_ms > 0.01:
					timing_lines.append(f'  │  ├─ create_simplified_tree: {create_simp_ms:.2f}ms')
					if clickable_ms > 0.01:
						timing_lines.append(f'  │  │  └─ clickable_detection: {clickable_ms:.2f}ms')
				if paint_order_ms > 0.01:
					timing_lines.append(f'  │  ├─ calculate_paint_order: {paint_order_ms:.2f}ms')
				if optimize_ms > 0.01:
					timing_lines.append(f'  │  ├─ optimize_tree: {optimize_ms:.2f}ms')
				if bbox_ms > 0.01:
					timing_lines.append(f'  │  ├─ bbox_filtering: {bbox_ms:.2f}ms')
				if assign_idx_ms > 0.01:
					timing_lines.append(f'  │  └─ assign_interactive_indices: {assign_idx_ms:.2f}ms')

			# Overheads
			get_dom_overhead_ms = timing_info.get('get_dom_tree_overhead_ms', 0)
			serialize_overhead_ms = timing_info.get('serialization_overhead_ms', 0)
			get_serialized_overhead_ms = timing_info.get('get_serialized_dom_tree_overhead_ms', 0)

			if get_dom_overhead_ms > 0.1:
				timing_lines.append(f'  ├─ get_dom_tree_overhead: {get_dom_overhead_ms:.2f}ms')
			if serialize_overhead_ms > 0.1:
				timing_lines.append(f'  ├─ serialization_overhead: {serialize_overhead_ms:.2f}ms')
			if get_serialized_overhead_ms > 0.1:
				timing_lines.append(f'  └─ get_serialized_dom_tree_overhead: {get_serialized_overhead_ms:.2f}ms')

			# Calculate total tracked time for validation
			main_operations_ms = (
				get_all_trees_ms
				+ build_ax_ms
				+ build_snapshot_ms
				+ construct_tree_ms
				+ serialize_total_ms
				+ get_dom_overhead_ms
				+ serialize_overhead_ms
				+ get_serialized_overhead_ms
			)
			untracked_time_ms = total_time_ms - main_operations_ms

			if untracked_time_ms > 1.0:  # Only log if significant
				timing_lines.append(f'  ⚠️  untracked_time: {untracked_time_ms:.2f}ms')

			# Single log call with all timing info
			self.logger.debug('\n'.join(timing_lines))

			# Update selector map for other watchdogs
			self.logger.debug('🔍 DOMWatchdog._build_dom_tree_without_highlights: Updating selector maps...')
			self.selector_map = self.current_dom_state.selector_map
			# Update BrowserSession's cached selector map
			if self.browser_session:
				self.browser_session.update_cached_selector_map(self.selector_map)
			self.logger.debug(
				f'🔍 DOMWatchdog._build_dom_tree_without_highlights: ✅ Selector maps updated, {len(self.selector_map)} elements'
			)

			# Skip JavaScript highlighting injection - Python highlighting will be applied later
			self.logger.debug('🔍 DOMWatchdog._build_dom_tree_without_highlights: ✅ COMPLETED DOM tree build (no JS highlights)')
			return self.current_dom_state

		except Exception as e:
			self.logger.error(f'Failed to build DOM tree without highlights: {e}')
			self.event_bus.dispatch(
				BrowserErrorEvent(
					error_type='DOMBuildFailed',
					message=str(e),
				)
			)
			raise

	@time_execution_async('capture_clean_screenshot')
	@observe_debug(ignore_input=True, ignore_output=True, name='capture_clean_screenshot')
	async def _capture_clean_screenshot(self) -> str:
		"""Capture a clean screenshot without JavaScript highlights."""
		try:
			self.logger.debug('🔍 DOMWatchdog._capture_clean_screenshot: Capturing clean screenshot...')

			await self.browser_session.get_or_create_cdp_session(target_id=self.browser_session.agent_focus_target_id, focus=True)

			# Check if handler is registered
			handlers = self.event_bus.handlers.get('ScreenshotEvent', [])
			handler_names = [getattr(h, '__name__', str(h)) for h in handlers]
			self.logger.debug(f'📸 ScreenshotEvent handlers registered: {len(handlers)} - {handler_names}')

			screenshot_event = self.event_bus.dispatch(ScreenshotEvent(full_page=False))
			self.logger.debug('📸 Dispatched ScreenshotEvent, waiting for event to complete...')

			# Wait for the event itself to complete (this waits for all handlers)
			await screenshot_event

			# Get the single handler result
			screenshot_b64 = await screenshot_event.event_result(raise_if_any=True, raise_if_none=True)
			if screenshot_b64 is None:
				raise RuntimeError('Screenshot handler returned None')
			self.logger.debug('🔍 DOMWatchdog._capture_clean_screenshot: ✅ Clean screenshot captured successfully')
			return str(screenshot_b64)

		except TimeoutError:
			self.logger.warning('📸 Clean screenshot timed out after 6 seconds - no handler registered or slow page?')
			raise
		except Exception as e:
			self.logger.warning(f'📸 Clean screenshot failed: {type(e).__name__}: {e}')
			raise

	def _detect_pagination_buttons(self, selector_map: dict[int, EnhancedDOMTreeNode]) -> list['PaginationButton']:
		"""Detect pagination buttons from the DOM selector map.

		Args:
			selector_map: Dictionary mapping element indices to DOM tree nodes

		Returns:
			List of PaginationButton instances found in the DOM
		"""
		from browser_use.browser.views import PaginationButton

		pagination_buttons_data = []
		try:
			self.logger.debug('🔍 DOMWatchdog._detect_pagination_buttons: Detecting pagination buttons...')
			pagination_buttons_raw = DomService.detect_pagination_buttons(selector_map)
			# Convert to PaginationButton instances
			pagination_buttons_data = [
				PaginationButton(
					button_type=btn['button_type'],  # type: ignore
					backend_node_id=btn['backend_node_id'],  # type: ignore
					text=btn['text'],  # type: ignore
					selector=btn['selector'],  # type: ignore
					is_disabled=btn['is_disabled'],  # type: ignore
				)
				for btn in pagination_buttons_raw
			]
			if pagination_buttons_data:
				self.logger.debug(
					f'🔍 DOMWatchdog._detect_pagination_buttons: Found {len(pagination_buttons_data)} pagination buttons'
				)
		except Exception as e:
			self.logger.warning(f'🔍 DOMWatchdog._detect_pagination_buttons: Pagination detection failed: {e}')

		return pagination_buttons_data

	async def _get_page_info(self) -> 'PageInfo':
		"""Get comprehensive page information using a single CDP call.

		TODO: should we make this an event as well?

		Returns:
			PageInfo with all viewport, page dimensions, and scroll information
		"""

		from browser_use.browser.views import PageInfo

		# get_or_create_cdp_session() handles focus validation automatically
		cdp_session = await self.browser_session.get_or_create_cdp_session(
			target_id=self.browser_session.agent_focus_target_id, focus=True
		)

		# Get layout metrics which includes all the information we need
		metrics = await asyncio.wait_for(
			cdp_session.cdp_client.send.Page.getLayoutMetrics(session_id=cdp_session.session_id), timeout=10.0
		)

		# Extract different viewport types
		layout_viewport = metrics.get('layoutViewport', {})
		visual_viewport = metrics.get('visualViewport', {})
		css_visual_viewport = metrics.get('cssVisualViewport', {})
		css_layout_viewport = metrics.get('cssLayoutViewport', {})
		content_size = metrics.get('contentSize', {})

		# Calculate device pixel ratio to convert between device pixels and CSS pixels
		# This matches the approach in dom/service.py _get_viewport_ratio method
		css_width = css_visual_viewport.get('clientWidth', css_layout_viewport.get('clientWidth', 1280.0))
		device_width = visual_viewport.get('clientWidth', css_width)
		device_pixel_ratio = device_width / css_width if css_width > 0 else 1.0

		# For viewport dimensions, use CSS pixels (what JavaScript sees)
		# Prioritize CSS layout viewport, then fall back to layout viewport
		viewport_width = int(css_layout_viewport.get('clientWidth') or layout_viewport.get('clientWidth', 1280))
		viewport_height = int(css_layout_viewport.get('clientHeight') or layout_viewport.get('clientHeight', 720))

		# For total page dimensions, content size is typically in device pixels, so convert to CSS pixels
		# by dividing by device pixel ratio
		raw_page_width = content_size.get('width', viewport_width * device_pixel_ratio)
		raw_page_height = content_size.get('height', viewport_height * device_pixel_ratio)
		page_width = int(raw_page_width / device_pixel_ratio)
		page_height = int(raw_page_height / device_pixel_ratio)

		# For scroll position, use CSS visual viewport if available, otherwise CSS layout viewport
		# These should already be in CSS pixels
		scroll_x = int(css_visual_viewport.get('pageX') or css_layout_viewport.get('pageX', 0))
		scroll_y = int(css_visual_viewport.get('pageY') or css_layout_viewport.get('pageY', 0))

		# Calculate scroll information - pixels that are above/below/left/right of current viewport
		pixels_above = scroll_y
		pixels_below = max(0, page_height - viewport_height - scroll_y)
		pixels_left = scroll_x
		pixels_right = max(0, page_width - viewport_width - scroll_x)

		page_info = PageInfo(
			viewport_width=viewport_width,
			viewport_height=viewport_height,
			page_width=page_width,
			page_height=page_height,
			scroll_x=scroll_x,
			scroll_y=scroll_y,
			pixels_above=pixels_above,
			pixels_below=pixels_below,
			pixels_left=pixels_left,
			pixels_right=pixels_right,
		)

		return page_info

	# ========== Public Helper Methods ==========

	async def get_element_by_index(self, index: int) -> EnhancedDOMTreeNode | None:
		"""Get DOM element by index from cached selector map.

		Builds DOM if not cached.

		Returns:
			EnhancedDOMTreeNode or None if index not found
		"""
		if not self.selector_map:
			# Build DOM if not cached
			await self._build_dom_tree_without_highlights(include_all_form_fields=False)

		return self.selector_map.get(index) if self.selector_map else None

	def clear_cache(self) -> None:
		"""Clear cached DOM state to force rebuild on next access."""
		self.selector_map = None
		self.current_dom_state = None
		self.enhanced_dom_tree = None
		# Keep the DOM service instance to reuse its CDP client connection

	def is_file_input(self, element: EnhancedDOMTreeNode) -> bool:
		"""Check if element is a file input."""
		return element.node_name.upper() == 'INPUT' and element.attributes.get('type', '').lower() == 'file'

	@staticmethod
	def is_element_visible_according_to_all_parents(node: EnhancedDOMTreeNode, html_frames: list[EnhancedDOMTreeNode]) -> bool:
		"""Check if the element is visible according to all its parent HTML frames.

		Delegates to the DomService static method.
		"""
		return DomService.is_element_visible_according_to_all_parents(node, html_frames)

	async def __aexit__(self, exc_type, exc_value, traceback):
		"""Clean up DOM service on exit."""
		if self._dom_service:
			await self._dom_service.__aexit__(exc_type, exc_value, traceback)
			self._dom_service = None

	def __del__(self):
		"""Clean up DOM service on deletion."""
		super().__del__()
		# DOM service will clean up its own CDP client
		self._dom_service = None
