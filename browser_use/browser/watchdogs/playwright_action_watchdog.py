"""Default browser action handlers using Playwright for DOM interactions."""

import asyncio
import json
import threading
import time
from typing import TYPE_CHECKING

from cdp_use.cdp.input.commands import DispatchKeyEventParameters

from browser_use.actor.utils import get_key_info
from browser_use.browser.events import (
	BrowserConnectedEvent,
	ClickCoordinateEvent,
	ClickElementEvent,
	GetDropdownOptionsEvent,
	GoBackEvent,
	GoForwardEvent,
	RefreshEvent,
	ScrollEvent,
	ScrollToTextEvent,
	SelectDropdownOptionEvent,
	SendKeysEvent,
	TabClosedEvent,
	TypeTextEvent,
	UploadFileEvent,
	WaitEvent,
)
from browser_use.browser.views import BrowserError, URLNotAllowedError
from browser_use.browser.watchdog_base import BaseWatchdog
from browser_use.dom.service import EnhancedDOMTreeNode
from browser_use.observability import observe_debug

if TYPE_CHECKING:
	from playwright.async_api import Page as PlaywrightPage

# Import EnhancedDOMTreeNode and rebuild event models that have forward references to it
# This must be done after all imports are complete
ClickCoordinateEvent.model_rebuild()
ClickElementEvent.model_rebuild()
GetDropdownOptionsEvent.model_rebuild()
SelectDropdownOptionEvent.model_rebuild()
TypeTextEvent.model_rebuild()
ScrollEvent.model_rebuild()
UploadFileEvent.model_rebuild()


class PlaywrightThread:
	"""Dedicated thread for Playwright operations with its own event loop.
	
	Playwright requires all operations to run in the same thread/event loop.
	This class ensures Playwright initialization and all subsequent operations
	run in a dedicated thread, isolated from bubus's event loop.
	"""
	
	def __init__(self):
		self.loop: asyncio.AbstractEventLoop | None = None
		self.thread: threading.Thread | None = None
		self._playwright_instance = None
		self._playwright_browser = None
		self._target_id_to_page: dict[str, 'PlaywrightPage'] = {}
		self._initialized = False
		self._lock = threading.Lock()
		self._shutdown_event = threading.Event()
	
	def start(self):
		"""Start the Playwright thread with its own event loop."""
		with self._lock:
			if self.thread and self.thread.is_alive():
				return
			
			def run_loop():
				"""Run the event loop in this thread."""
				# Create new event loop for this thread
				self.loop = asyncio.new_event_loop()
				asyncio.set_event_loop(self.loop)
				# Run forever until stopped
				self.loop.run_forever()
			
			self.thread = threading.Thread(target=run_loop, daemon=True, name='PlaywrightThread')
			self.thread.start()
			
			# Wait for loop to be ready
			timeout = 5.0
			start_time = time.time()
			while self.loop is None and (time.time() - start_time) < timeout:
				time.sleep(0.01)
			
			if self.loop is None:
				raise RuntimeError('Failed to start Playwright thread event loop')
	
	def stop(self):
		"""Stop the Playwright thread."""
		with self._lock:
			if self.loop and self.thread and self.thread.is_alive():
				# Schedule stop in the thread's event loop
				self.loop.call_soon_threadsafe(self.loop.stop)
				self.thread.join(timeout=5.0)
				if self.thread.is_alive():
					# Force stop if thread didn't stop gracefully
					self.loop = None
	
	async def run_coro(self, coro, timeout: float = 60.0):
		"""Run a coroutine in the Playwright thread and await the result (non-blocking for event loop).
		
		This yields control to the event loop while waiting, preventing blocking of the bubus event loop.
		
		Args:
			coro: Coroutine to run
			timeout: Maximum time to wait in seconds (default: 60s)
		"""
		if not self.loop:
			raise RuntimeError("Playwright thread not started")
		if not self.thread or not self.thread.is_alive():
			raise RuntimeError("Playwright thread is dead")
		
		future = asyncio.run_coroutine_threadsafe(coro, self.loop)
		try:
			# Use wrap_future to await the Future in the current event loop
			# This yields control and doesn't block the event loop
			return await asyncio.wait_for(asyncio.wrap_future(future), timeout=timeout)
		except asyncio.TimeoutError:
			future.cancel()
			raise RuntimeError(f"Playwright operation timed out after {timeout}s")
	
	def run_coro_async(self, coro):
		"""Schedule a coroutine in the Playwright thread and return a Future.
		
		This does NOT block - returns immediately with a Future.
		"""
		if not self.loop:
			raise RuntimeError("Playwright thread not started")
		if not self.thread or not self.thread.is_alive():
			raise RuntimeError("Playwright thread is dead")
		
		return asyncio.run_coroutine_threadsafe(coro, self.loop)


# Module-level singleton for Playwright thread
_playwright_thread_singleton: PlaywrightThread | None = None


def _get_playwright_thread() -> PlaywrightThread:
	"""Get or create the singleton Playwright thread."""
	global _playwright_thread_singleton
	if _playwright_thread_singleton is None:
		_playwright_thread_singleton = PlaywrightThread()
		_playwright_thread_singleton.start()
	return _playwright_thread_singleton


class PlaywrightActionWatchdog(BaseWatchdog):
	"""Handles default browser actions like click, type, and scroll using Playwright for DOM interactions."""

	_playwright_initialized: bool = False

	async def on_BrowserConnectedEvent(self, event: BrowserConnectedEvent) -> None:
		"""Initialize Playwright when browser connects (ensures same event loop context).
		
		This is critical: Playwright must be initialized in the same event loop/thread
		where actions will be executed, otherwise operations will hang/timeout.
		"""
		if not self._playwright_initialized:
			await self._initialize_playwright()

	async def _initialize_playwright(self) -> None:
		"""Initialize Playwright connection to browser in the dedicated thread.
		
		This method dispatches initialization to the Playwright thread to ensure
		all Playwright operations run in the same thread/event loop.
		"""
		if self._playwright_initialized:
			return
		
		thread = _get_playwright_thread()
		
		# Capture values we need BEFORE dispatching to Playwright thread (avoid deadlock)
		cdp_url = self.browser_session.cdp_url
		if not cdp_url:
			self.logger.debug('Playwright initialization deferred: no CDP URL yet')
			return
		
		# Define initialization coroutine (runs in Playwright thread)
		async def init_coro():
			from playwright.async_api import async_playwright
			
			try:
				# Connect Playwright to the same Chrome instance (in Playwright thread)
				if thread._playwright_instance is None:
					self.logger.debug('Starting Playwright instance...')
					thread._playwright_instance = await async_playwright().start()
					self.logger.debug('Playwright instance started')
				
				if thread._playwright_browser is None:
					self.logger.debug(f'Connecting Playwright to CDP: {cdp_url}')
					thread._playwright_browser = await thread._playwright_instance.chromium.connect_over_cdp(cdp_url)
					self.logger.debug('Playwright connected to CDP')
				
				# Verify connection succeeded
				if not thread._playwright_browser or not thread._playwright_browser.contexts:
					raise RuntimeError('Failed to connect Playwright to browser')
				
				# Note: We don't map pages here because that requires browser_session access
				# which can cause deadlocks. Mapping will happen lazily when pages are accessed.
				context = thread._playwright_browser.contexts[0]
				if context.pages:
					self.logger.debug(f'Found {len(context.pages)} existing pages (will map on demand)')
				else:
					self.logger.debug('No existing pages found when initializing Playwright')
				
				thread._initialized = True
				self.logger.debug('✅ Connected Playwright to browser session in dedicated thread')
			except Exception as e:
				self.logger.error(f'\033[91mError in Playwright initialization coroutine: {e}\033[0m', exc_info=True)
				raise
		
		# Dispatch initialization to Playwright thread
		try:
			await thread.run_coro(init_coro())
			self._playwright_initialized = True
		except ImportError:
			raise RuntimeError('Playwright not installed. Install with: pip install playwright && playwright install chromium')
		except Exception as e:
			self.logger.error(f'\033[91mFailed to connect Playwright: {e}\033[0m')
			raise
	
	async def _map_existing_pages_in_thread(
		self, pages: list['PlaywrightPage'], thread: PlaywrightThread, cdp_client_root=None
	) -> None:
		"""Map existing Playwright pages to their CDP target IDs (runs in Playwright thread).
		
		Args:
			pages: List of Playwright pages to map
			thread: PlaywrightThread instance
			cdp_client_root: CDP client root (captured before dispatching to avoid deadlock)
		"""
		if not cdp_client_root:
			# If no CDP client provided, skip mapping - will be done lazily
			return
		
		try:
			targets_result = await cdp_client_root.send.Target.getTargets()
			targets = targets_result.get('targetInfos', [])
			
			self.logger.debug(
				f'🗺️ Mapping {len(pages)} Playwright pages to {len(targets)} CDP targets'
			)
			
			# Match each Playwright page to a CDP target by URL
			for page in pages:
				page_url = page.url
				for target_info in targets:
					if target_info.get('type') == 'page' and target_info.get('url') == page_url:
						target_id = target_info['targetId']
						thread._target_id_to_page[target_id] = page
						self.logger.debug(
							f'✅ Mapped existing Playwright page to target_id={target_id[-8:]}: '
							f'page={page}, url={page_url[:50]}, closed={page.is_closed()}'
						)
						break
		except Exception as e:
			self.logger.warning(f'Failed to map existing pages: {e}')

	async def _get_playwright_page(self) -> 'PlaywrightPage':
		"""Get Playwright Page instance for the current agent_focus_target_id (dispatches to Playwright thread).
		
		Uses the target_id -> page mapping to ensure we always get the correct page.
		"""
		# If not initialized yet, try to initialize now (fallback for edge cases)
		if not self._playwright_initialized:
			await self._initialize_playwright()
		
		thread = _get_playwright_thread()
		current_target_id = self.browser_session.agent_focus_target_id
		if not current_target_id:
			raise RuntimeError('Cannot get Playwright page: agent_focus_target_id is None')
		
		# Do CDP mapping in bubus thread (before dispatching to Playwright thread)
		# This avoids deadlock from accessing CDP from Playwright thread
		if current_target_id not in thread._target_id_to_page:
			await self._map_pages_from_bubus_thread(thread)
		
		# Define coroutine to get page (runs in Playwright thread)
		async def get_page_coro():
			# Log the mapping state
			mapped_ids = [tid[-8:] for tid in thread._target_id_to_page.keys()]
			mapped_pages_info = [
				(f'target_id={tid[-8:]}', f'page={str(page)[:80]}', f'url={page.url[:50]}', f'closed={page.is_closed()}')
				for tid, page in thread._target_id_to_page.items()
			]
			self.logger.debug(
				f'🔍 Looking up Playwright page for target_id={current_target_id[-8:]}. '
				f'Mapped target_ids: {mapped_ids}. '
				f'Mapped pages: {mapped_pages_info}'
			)
			
			# Look up the page in our mapping
			if current_target_id in thread._target_id_to_page:
				page = thread._target_id_to_page[current_target_id]
				self.logger.debug(
					f'✅ Found mapped page for target_id={current_target_id[-8:]}: '
					f'page={page}, url={page.url}, closed={page.is_closed()}'
				)
				
				# Verify the page is still valid (not closed)
				if page.is_closed():
					# Page was closed, remove from mapping
					del thread._target_id_to_page[current_target_id]
					self.logger.warning(
						f'⚠️ Playwright page for target_id={current_target_id[-8:]} was closed, removed from mapping'
					)
					raise RuntimeError(f'Playwright page for target_id {current_target_id[-8:]} was closed')
				return page
			
			# Fallback: if we still can't find it, raise an error
			available_ids = [tid[-8:] for tid in thread._target_id_to_page.keys()]
			self.logger.error(
				f'\033[91m❌ Playwright page not found for target_id={current_target_id[-8:]}. '
				f'Available mapped pages: {available_ids}\033[0m'
			)
			raise RuntimeError(
				f'Playwright page not found for target_id {current_target_id[-8:]}. '
				f'Available mapped pages: {available_ids}'
			)
		
		# Dispatch to Playwright thread
		return await thread.run_coro(get_page_coro())
	
	async def _map_pages_from_bubus_thread(self, thread: PlaywrightThread) -> None:
		"""Map Playwright pages to CDP target IDs (runs in bubus thread to avoid deadlock).
		
		This function:
		1. Gets Playwright pages from the Playwright thread (non-blocking)
		2. Gets CDP targets from bubus thread (where CDP client lives)
		3. Matches them by URL
		4. Stores the mapping in the Playwright thread
		"""
		if not self.browser_session._cdp_client_root:
			return
		
		try:
			# Get CDP targets (in bubus thread)
			targets_result = await self.browser_session._cdp_client_root.send.Target.getTargets()
			targets = targets_result.get('targetInfos', [])
			
			# Get Playwright pages (dispatch to Playwright thread, but get list synchronously)
			async def get_pages_coro():
				if not thread._playwright_browser or not thread._playwright_browser.contexts:
					return []
				context = thread._playwright_browser.contexts[0]
				return context.pages
			
			# Get pages from Playwright thread
			pages = await thread.run_coro(get_pages_coro())
			
			if not pages:
				self.logger.debug('No Playwright pages found to map')
				return
			
			self.logger.debug(
				f'🗺️ Mapping {len(pages)} Playwright pages to {len(targets)} CDP targets'
			)
			
			# Match each Playwright page to a CDP target by URL
			# Store mapping in Playwright thread
			async def store_mapping_coro():
				for page in pages:
					page_url = page.url
					for target_info in targets:
						if target_info.get('type') == 'page' and target_info.get('url') == page_url:
							target_id = target_info['targetId']
							thread._target_id_to_page[target_id] = page
							self.logger.debug(
								f'✅ Mapped Playwright page to target_id={target_id[-8:]}: '
								f'page={page}, url={page_url[:50]}, closed={page.is_closed()}'
							)
							break
			
			# Store mapping in Playwright thread
			await thread.run_coro(store_mapping_coro())
			
		except Exception as e:
			self.logger.warning(f'Failed to map pages: {e}')

	async def create_page_via_playwright(self, url: str = 'about:blank') -> str:
		"""Create a new page/tab using Playwright and return the CDP target ID (dispatches to Playwright thread).
		
		This ensures Playwright is aware of all pages created, avoiding stale references.
		
		Args:
			url: URL to navigate to (default: 'about:blank')
			
		Returns:
			CDP target ID of the newly created page
		"""
		if not self._playwright_initialized:
			await self._initialize_playwright()
		
		thread = _get_playwright_thread()
		
		# Define create page coroutine (runs in Playwright thread)
		async def create_page_coro():
			if not thread._playwright_browser or not thread._playwright_browser.contexts:
				raise RuntimeError('Playwright browser not connected')
			
			context = thread._playwright_browser.contexts[0]
			
			# Get current page count before creating new page
			page_count_before = len(context.pages)
			
			# Create new page via Playwright
			new_page = await context.new_page()
			
			# Navigate to the URL if provided
			if url != 'about:blank':
				await new_page.goto(url)
			
			# Get the CDP target ID from the page
			# When Playwright connects over CDP, we can get the target ID via CDP session
			# Create a CDP session for the new page
			cdp_session = await new_page.context.new_cdp_session(new_page)
			
			# Query all targets to find the one matching our newly created page
			# We'll match by finding targets that weren't there before
			if self.browser_session._cdp_client_root:
				# Wait a brief moment for the target to be registered
				import asyncio
				await asyncio.sleep(0.1)
				
				targets_result = await self.browser_session._cdp_client_root.send.Target.getTargets()
				targets = targets_result.get('targetInfos', [])
				
				# Get the page URL to match against
				page_url = new_page.url
				
				# Find targets matching our page URL
				# For 'about:blank', we need to match by the fact that it's a new page
				matching_targets = []
				for target_info in targets:
					target_url = target_info.get('url', '')
					# Match by URL, or if it's about:blank, we'll use other heuristics
					if target_url == page_url:
						matching_targets.append(target_info)
				
				if matching_targets:
					# If multiple matches, prefer page types over other types
					page_targets = [t for t in matching_targets if t.get('type') == 'page']
					if page_targets:
						target_id = page_targets[0]['targetId']
						# Store the mapping
						thread._target_id_to_page[target_id] = new_page
						self.logger.debug(
							f'✅ Mapped new Playwright page to target_id={target_id[-8:]}: '
							f'page={new_page}, url={new_page.url[:50]}, closed={new_page.is_closed()}'
						)
						return target_id
					# Otherwise use the first match
					target_id = matching_targets[0]['targetId']
					# Store the mapping
					thread._target_id_to_page[target_id] = new_page
					self.logger.debug(
						f'✅ Mapped new Playwright page to target_id={target_id[-8:]} (non-page type): '
						f'page={new_page}, url={new_page.url[:50]}'
					)
					return target_id
				
				# Fallback: if URL matching fails (e.g., for about:blank), 
				# find the most recently created page target
				page_targets = [t for t in targets if t.get('type') == 'page']
				if page_targets:
					# Use the last page target (most recently created)
					# Since we just created a page, it should be among the most recent
					target_id = page_targets[-1]['targetId']
					# Store the mapping
					thread._target_id_to_page[target_id] = new_page
					self.logger.debug(
						f'✅ Mapped new Playwright page to most recent target_id={target_id[-8:]}: '
						f'page={new_page}, url={new_page.url[:50]}, closed={new_page.is_closed()}'
					)
					return target_id
			
			# If we can't get target ID via CDP query, raise an error
			raise RuntimeError('Failed to get CDP target ID for Playwright-created page')
		
		# Dispatch to Playwright thread
		return await thread.run_coro(create_page_coro())

	def _element_node_to_playwright_selector(self, element_node: EnhancedDOMTreeNode) -> str:
		"""Convert element_node to a Playwright selector (prefer structural selector over other methods)."""
		attrs = element_node.attributes or {}
		
		# FIRST: Use pre-computed structural selector if available (most reliable!)
		# This was generated during DOM serialization when we had full tree structure
		if element_node.structural_selector:
			return element_node.structural_selector
		
		# Fallback: Prioritize most specific selectors (ID, data-automation-id, etc.)
		# Prefer ID selector (most specific)
		if attrs.get('id'):
			return f'#{attrs["id"]}'
		
		# Use data-automation-id (common in Workday and similar apps)
		if attrs.get('data-automation-id'):
			return f'[data-automation-id="{attrs["data-automation-id"]}"]'
		
		# Use name attribute
		if attrs.get('name'):
			return f'[name="{attrs["name"]}"]'
		
		# Use data-testid or similar
		for attr in ['data-testid', 'data-test', 'data-cy']:
			if attrs.get(attr):
				return f'[{attr}="{attrs[attr]}"]'
		
		# Try to generate structural selector on-the-fly (fallback if not pre-computed)
		try:
			structural_selector = element_node.get_structural_selector()
			if structural_selector:
				return structural_selector
		except Exception:
			pass  # Fall through to other methods
		
		# Use XPath only if it's specific enough (not just a tag name)
		if hasattr(element_node, 'xpath') and element_node.xpath:
			xpath = element_node.xpath
			# If xpath is just a tag name (like "a" or "input"), it's too generic
			# Only use it if it has path segments (contains "/") or indices (contains "[")
			if '/' in xpath or '[' in xpath:
				return f'xpath={xpath}'
		
		# Fallback to tag + role
		tag = element_node.tag_name or 'div'
		if attrs.get('role'):
			return f'{tag}[role="{attrs["role"]}"]'
		
		# Last resort: use backend_node_id with JavaScript evaluation
		# This will require a different approach - use CDP to resolve to element handle
		raise ValueError(f'Cannot create selector for element with backend_node_id={element_node.backend_node_id}')

	def _is_print_related_element(self, element_node: EnhancedDOMTreeNode) -> bool:
		"""Check if an element is related to printing (print buttons, print dialogs, etc.).

		Primary check: onclick attribute (most reliable for print detection)
		Fallback: button text/value (for cases without onclick)
		"""
		# Primary: Check onclick attribute for print-related functions (most reliable)
		onclick = element_node.attributes.get('onclick', '').lower() if element_node.attributes else ''
		if onclick and 'print' in onclick:
			# Matches: window.print(), PrintElem(), print(), etc.
			return True

		return False

	async def _handle_print_button_click(self, element_node: EnhancedDOMTreeNode) -> dict | None:
		"""Handle print button by directly generating PDF via CDP instead of opening dialog.

		Returns:
			Metadata dict with download path if successful, None otherwise
		"""
		try:
			import base64
			import os
			from pathlib import Path

			# Get CDP session
			cdp_session = await self.browser_session.get_or_create_cdp_session(focus=True)

			# Generate PDF using CDP Page.printToPDF
			result = await asyncio.wait_for(
				cdp_session.cdp_client.send.Page.printToPDF(
					params={
						'printBackground': True,
						'preferCSSPageSize': True,
					},
					session_id=cdp_session.session_id,
				),
				timeout=15.0,  # 15 second timeout for PDF generation
			)

			pdf_data = result.get('data')
			if not pdf_data:
				self.logger.warning('⚠️ PDF generation returned no data')
				return None

			# Decode base64 PDF data
			pdf_bytes = base64.b64decode(pdf_data)

			# Get downloads path
			downloads_path = self.browser_session.browser_profile.downloads_path
			if not downloads_path:
				self.logger.warning('⚠️ No downloads path configured, cannot save PDF')
				return None

			# Generate filename from page title or URL
			try:
				page_title = await asyncio.wait_for(self.browser_session.get_current_page_title(), timeout=2.0)
				# Sanitize title for filename
				import re

				safe_title = re.sub(r'[^\w\s-]', '', page_title)[:50]  # Max 50 chars
				filename = f'{safe_title}.pdf' if safe_title else 'print.pdf'
			except Exception:
				filename = 'print.pdf'

			# Ensure downloads directory exists
			downloads_dir = Path(downloads_path).expanduser().resolve()
			downloads_dir.mkdir(parents=True, exist_ok=True)

			# Generate unique filename if file exists
			final_path = downloads_dir / filename
			if final_path.exists():
				base, ext = os.path.splitext(filename)
				counter = 1
				while (downloads_dir / f'{base} ({counter}){ext}').exists():
					counter += 1
				final_path = downloads_dir / f'{base} ({counter}){ext}'

			# Write PDF to file
			import anyio

			async with await anyio.open_file(final_path, 'wb') as f:
				await f.write(pdf_bytes)

			file_size = final_path.stat().st_size
			self.logger.info(f'✅ Generated PDF via CDP: {final_path} ({file_size:,} bytes)')

			# Dispatch FileDownloadedEvent
			from browser_use.browser.events import FileDownloadedEvent

			page_url = await self.browser_session.get_current_page_url()
			self.browser_session.event_bus.dispatch(
				FileDownloadedEvent(
					url=page_url,
					path=str(final_path),
					file_name=final_path.name,
					file_size=file_size,
					file_type='pdf',
					mime_type='application/pdf',
					auto_download=False,  # This was intentional (user clicked print)
				)
			)

			return {'pdf_generated': True, 'path': str(final_path)}

		except TimeoutError:
			self.logger.warning('⏱️ PDF generation timed out')
			return None
		except Exception as e:
			self.logger.warning(f'⚠️ Failed to generate PDF via CDP: {type(e).__name__}: {e}')
			return None

	@observe_debug(ignore_input=True, ignore_output=True, name='click_element_event')
	async def on_ClickElementEvent(self, event: ClickElementEvent) -> dict | None:
		"""Handle click request with Playwright."""
		self.logger.debug(f'🖱️ ClickElementEvent: {event}')

		try:
			# Check if session is alive before attempting any operations
			if not self.browser_session.agent_focus_target_id:
				error_msg = 'Cannot execute click: browser session is corrupted (target_id=None). Session may have crashed.'
				self.logger.error(f'\033[91m{error_msg}\033[0m')
				raise BrowserError(error_msg)

			# Use the provided node
			element_node = event.node
			index_for_logging = element_node.backend_node_id or 'unknown'
			starting_target_id = self.browser_session.agent_focus_target_id

			# Check if element is a file input (should not be clicked)
			if self.browser_session.is_file_input(element_node):
				msg = f'Index {index_for_logging} - has an element which opens file upload dialog. To upload files please use a specific function to upload files'
				self.logger.info(f'{msg}')
				# Return validation error instead of raising to avoid ERROR logs
				return {'validation_error': msg}

			# Detect print-related elements and handle them specially
			is_print_element = self._is_print_related_element(element_node)
			if is_print_element:
				self.logger.info(
					f'🖨️ Detected print button (index {index_for_logging}), generating PDF directly instead of opening dialog...'
				)

				# Instead of clicking, directly generate PDF via CDP
				click_metadata = await self._handle_print_button_click(element_node)

				if click_metadata and click_metadata.get('pdf_generated'):
					msg = f'Generated PDF: {click_metadata.get("path")}'
					self.logger.info(f'💾 {msg}')
					return click_metadata
				else:
					# Fallback to regular click if PDF generation failed
					self.logger.warning('⚠️ PDF generation failed, falling back to regular click')

			# Perform the actual click using Playwright
			self.logger.debug(f'🎯 Performing actual click using Playwright...')
			click_metadata = await self._click_element_node_impl(element_node)
			download_path = None  # moved to downloads_watchdog.py

			# Check for validation errors - return them without raising to avoid ERROR logs
			if isinstance(click_metadata, dict) and 'validation_error' in click_metadata:
				self.logger.info(f'{click_metadata["validation_error"]}')
				return click_metadata

			# Build success message
			if download_path:
				msg = f'Downloaded file to {download_path}'
				self.logger.info(f'💾 {msg}')
			else:
				msg = f'Clicked button {element_node.node_name}: {element_node.get_all_children_text(max_depth=2)}'
				self.logger.debug(f'🖱️ {msg}')
			self.logger.debug(f'Element xpath: {element_node.xpath}')

			return click_metadata if isinstance(click_metadata, dict) else None
		except Exception as e:
			raise

	async def on_ClickCoordinateEvent(self, event: ClickCoordinateEvent) -> dict | None:
		"""Handle click at coordinates with Playwright."""
		try:
			# Check if session is alive before attempting any operations
			if not self.browser_session.agent_focus_target_id:
				error_msg = 'Cannot execute click: browser session is corrupted (target_id=None). Session may have crashed.'
				self.logger.error(f'\033[91m{error_msg}\033[0m')
				raise BrowserError(error_msg)

			# If force=True, skip safety checks and click directly
			if event.force:
				self.logger.debug(f'Force clicking at coordinates ({event.coordinate_x}, {event.coordinate_y})')
				return await self._click_on_coordinate(event.coordinate_x, event.coordinate_y, force=True)

			# Get element at coordinates for safety checks
			element_node = await self.browser_session.get_dom_element_at_coordinates(event.coordinate_x, event.coordinate_y)
			if element_node is None:
				# No element found, click directly
				self.logger.debug(
					f'No element found at coordinates ({event.coordinate_x}, {event.coordinate_y}), proceeding with click anyway'
				)
				return await self._click_on_coordinate(event.coordinate_x, event.coordinate_y, force=False)

			# Safety check: file input
			if self.browser_session.is_file_input(element_node):
				msg = f'Cannot click at ({event.coordinate_x}, {event.coordinate_y}) - element is a file input. To upload files please use upload_file action'
				self.logger.info(f'{msg}')
				return {'validation_error': msg}

			# Safety check: select element
			tag_name = element_node.tag_name.lower() if element_node.tag_name else ''
			if tag_name == 'select':
				msg = f'Cannot click at ({event.coordinate_x}, {event.coordinate_y}) - element is a <select>. Use dropdown_options action instead.'
				self.logger.info(f'{msg}')
				return {'validation_error': msg}

			# Safety check: print-related elements
			is_print_element = self._is_print_related_element(element_node)
			if is_print_element:
				self.logger.info(
					f'🖨️ Detected print button at ({event.coordinate_x}, {event.coordinate_y}), generating PDF directly instead of opening dialog...'
				)
				click_metadata = await self._handle_print_button_click(element_node)
				if click_metadata and click_metadata.get('pdf_generated'):
					msg = f'Generated PDF: {click_metadata.get("path")}'
					self.logger.info(f'💾 {msg}')
					return click_metadata
				else:
					self.logger.warning('⚠️ PDF generation failed, falling back to regular click')

			# All safety checks passed, click at coordinates
			return await self._click_on_coordinate(event.coordinate_x, event.coordinate_y, force=False)

		except Exception:
			raise

	async def on_TypeTextEvent(self, event: TypeTextEvent) -> dict | None:
		"""Handle text input request with Playwright."""
		try:
			# Use the provided node
			element_node = event.node
			index_for_logging = element_node.backend_node_id or 'unknown'

			# Check if this is index 0 or a falsy index - type to the page (whatever has focus)
			if not element_node.backend_node_id or element_node.backend_node_id == 0:
				# Type to the page without focusing any specific element (dispatch to Playwright thread)
				page = await self._get_playwright_page()
				thread = _get_playwright_thread()
				
				async def type_page_coro():
					await page.keyboard.type(event.text, delay=18)
				
				await thread.run_coro(type_page_coro())
				# Log with sensitive data protection
				if event.is_sensitive:
					if event.sensitive_key_name:
						self.logger.info(f'⌨️ Typed <{event.sensitive_key_name}> to the page (current focus)')
					else:
						self.logger.info('⌨️ Typed <sensitive> to the page (current focus)')
				else:
					self.logger.info(f'⌨️ Typed "{event.text}" to the page (current focus)')
				return None  # No coordinates available for page typing
			else:
				try:
					# Try to type to the specific element using Playwright
					input_metadata = await self._input_text_element_node_impl(
						element_node,
						event.text,
						clear=event.clear or (not event.text),
						is_sensitive=event.is_sensitive,
					)
					# Log with sensitive data protection
					if event.is_sensitive:
						if event.sensitive_key_name:
							self.logger.info(f'⌨️ Typed <{event.sensitive_key_name}> into element with index {index_for_logging}')
						else:
							self.logger.info(f'⌨️ Typed <sensitive> into element with index {index_for_logging}')
					else:
						self.logger.info(f'⌨️ Typed "{event.text}" into element with index {index_for_logging}')
					self.logger.debug(f'Element xpath: {element_node.xpath}')
					return input_metadata  # Return coordinates if available
				except Exception as e:
					# Element not found or error - fall back to typing to the page (dispatch to Playwright thread)
					self.logger.warning(f'Failed to type to element {index_for_logging}: {e}. Falling back to page typing.')
					page = await self._get_playwright_page()
					thread = _get_playwright_thread()
					
					async def type_page_fallback_coro():
						await page.keyboard.type(event.text, delay=18)
					
					await thread.run_coro(type_page_fallback_coro())
					# Log with sensitive data protection
					if event.is_sensitive:
						if event.sensitive_key_name:
							self.logger.info(f'⌨️ Typed <{event.sensitive_key_name}> to the page as fallback')
						else:
							self.logger.info('⌨️ Typed <sensitive> to the page as fallback')
					else:
						self.logger.info(f'⌨️ Typed "{event.text}" to the page as fallback')
					return None  # No coordinates available for fallback typing

			# Note: We don't clear cached state here - let multi_act handle DOM change detection
			# by explicitly rebuilding and comparing when needed
		except Exception as e:
			raise

	async def on_ScrollEvent(self, event: ScrollEvent) -> None:
		"""Handle scroll request with Playwright."""
		# Check if we have a current target for scrolling
		if not self.browser_session.agent_focus_target_id:
			error_msg = 'No active target for scrolling'
			raise BrowserError(error_msg)

		try:
			# Convert direction and amount to pixels
			# Positive pixels = scroll down, negative = scroll up
			pixels = event.amount if event.direction == 'down' else -event.amount

			# Element-specific scrolling if node is provided
			if event.node is not None:
				element_node = event.node
				index_for_logging = element_node.backend_node_id or 'unknown'

				# Check if the element is an iframe
				is_iframe = element_node.tag_name and element_node.tag_name.upper() == 'IFRAME'

				# Try to scroll the element's container using Playwright (dispatch to Playwright thread)
				try:
					page = await self._get_playwright_page()
					thread = _get_playwright_thread()
					selector = self._element_node_to_playwright_selector(element_node)
					
					async def scroll_element_coro():
						locator = page.locator(selector).first
						
						# Scroll the element into view
						await locator.scroll_into_view_if_needed()
						
						# Scroll the element's container
						await locator.evaluate(f'element => element.scrollBy(0, {pixels})')
					
					await thread.run_coro(scroll_element_coro())
					
					self.logger.debug(
						f'📜 Scrolled element {index_for_logging} container {event.direction} by {event.amount} pixels'
					)

					if is_iframe:
						self.logger.debug('🔄 Forcing DOM refresh after iframe scroll')
						await asyncio.sleep(0.2)

					return None
				except Exception as e:
					self.logger.debug(f'Playwright scroll failed: {e}, falling back to CDP')
					# Fallback to CDP scrolling
					success = await self._scroll_element_container_cdp(element_node, pixels)
					if success:
						self.logger.debug(
							f'📜 Scrolled element {index_for_logging} container {event.direction} by {event.amount} pixels'
						)
						return None

			# Perform page-level scroll using Playwright (dispatch to Playwright thread)
			page = await self._get_playwright_page()
			thread = _get_playwright_thread()
			
			async def scroll_page_coro():
				await page.evaluate(f'window.scrollBy(0, {pixels})')
			
			await thread.run_coro(scroll_page_coro())
			
			self.logger.debug(f'📜 Scrolled {event.direction} by {event.amount} pixels')
			return None
		except Exception as e:
			raise

	# ========== Implementation Methods ==========

	async def _click_element_node_impl(self, element_node) -> dict | None:
		"""
		Click an element using Playwright.

		Args:
			element_node: The DOM element to click
		"""
		try:
			# Check if element is a file input or select dropdown - these should not be clicked
			tag_name = element_node.tag_name.lower() if element_node.tag_name else ''
			element_type = element_node.attributes.get('type', '').lower() if element_node.attributes else ''

			if tag_name == 'select':
				msg = f'Cannot click on <select> elements. Use dropdown_options(index={element_node.backend_node_id}) action instead.'
				return {'validation_error': msg}

			if tag_name == 'input' and element_type == 'file':
				msg = f'Cannot click on file input element (index={element_node.backend_node_id}). File uploads must be handled using upload_file_to_element action.'
				return {'validation_error': msg}

			# Get Playwright page
			self.logger.debug(f'🔍 Getting Playwright page for element_node: {element_node}')
			page = await self._get_playwright_page()
			
			# Convert element_node to selector
			try:
				self.logger.debug(f'🔍 Converting element_node to selector...')
				selector = self._element_node_to_playwright_selector(element_node)
			except ValueError:
				# Fallback: use JavaScript to click via backend_node_id using CDP
				self.logger.debug('Using CDP JavaScript fallback for click (no selector available)')
				cdp_session = await self.browser_session.cdp_client_for_node(element_node)
				result = await cdp_session.cdp_client.send.DOM.resolveNode(
					params={'backendNodeId': element_node.backend_node_id},
					session_id=cdp_session.session_id,
				)
				if 'object' in result and 'objectId' in result['object']:
					object_id = result['object']['objectId']
					await cdp_session.cdp_client.send.Runtime.callFunctionOn(
						params={
							'functionDeclaration': 'function() { this.click(); }',
							'objectId': object_id,
						},
						session_id=cdp_session.session_id,
					)
					await asyncio.sleep(0.05)
					return None
				else:
					raise Exception('Failed to resolve node for JavaScript click fallback')

			# Use Playwright to click (dispatch to Playwright thread)
			try:
				thread = _get_playwright_thread()
				
				# Define click coroutine (runs in Playwright thread)
				async def click_coro():
					self.logger.debug(f'🎯 Creating Playwright locator for selector: {selector}')
					locator = page.locator(selector).first
					
					self.logger.debug(f'📜 Scrolling element into view...')
					# Scroll into view and wait for element to be visible
					await locator.scroll_into_view_if_needed()
					self.logger.debug(f'✅ Element scrolled into view')
					
					self.logger.debug(f'⏳ Waiting for element to be visible (timeout=5000ms)...')
					await locator.wait_for(state='visible', timeout=5000)
					self.logger.debug(f'✅ Element is visible')
					
					self.logger.debug(f'📦 Getting bounding box...')
					# Get bounding box for metadata
					box = await locator.bounding_box()
					self.logger.debug(f'✅ Got bounding box: {box}')
					
					self.logger.debug(f'🖱️ Clicking element (timeout=10000ms)...')
					# Click using Playwright
					await locator.click(timeout=10000)
					
					self.logger.debug(f'🖱️ Clicked element using Playwright: {selector}')
					
					return box
				
				# Dispatch click operation to Playwright thread
				box = await thread.run_coro(click_coro())
				
				# Return coordinates as metadata
				if box:
					return {'click_x': box['x'] + box['width'] / 2, 'click_y': box['y'] + box['height'] / 2}
				return None
			except Exception as e:
				self.logger.warning(f'Playwright click failed: {e}, falling back to JavaScript')
				# Fallback to JavaScript click via CDP
				cdp_session = await self.browser_session.cdp_client_for_node(element_node)
				result = await cdp_session.cdp_client.send.DOM.resolveNode(
					params={'backendNodeId': element_node.backend_node_id},
					session_id=cdp_session.session_id,
				)
				if 'object' in result and 'objectId' in result['object']:
					object_id = result['object']['objectId']
					await cdp_session.cdp_client.send.Runtime.callFunctionOn(
						params={
							'functionDeclaration': 'function() { this.click(); }',
							'objectId': object_id,
						},
						session_id=cdp_session.session_id,
					)
					await asyncio.sleep(0.05)
					return None
				else:
					raise Exception(f'Failed to click element: {e}')

		except URLNotAllowedError as e:
			raise e
		except BrowserError as e:
			raise e
		except Exception as e:
			# Extract key element info for error message
			element_info = f'<{element_node.tag_name or "unknown"}'
			if element_node.backend_node_id:
				element_info += f' index={element_node.backend_node_id}'
			element_info += '>'

			# Create helpful error message based on context
			error_detail = f'Failed to click element {element_info}. The element may not be interactable or visible.'

			# Add hint if element has index (common in code-use mode)
			if element_node.backend_node_id:
				error_detail += f' If the page changed after navigation/interaction, the index [{element_node.backend_node_id}] may be stale. Get fresh browser state before retrying.'

			raise BrowserError(
				message=f'Failed to click element: {str(e)}',
				long_term_memory=error_detail,
			)

	async def _click_on_coordinate(self, coordinate_x: int, coordinate_y: int, force: bool = False) -> dict | None:
		"""
		Click directly at coordinates using Playwright (dispatches to Playwright thread).

		Args:
			coordinate_x: X coordinate in viewport
			coordinate_y: Y coordinate in viewport
			force: If True, skip all safety checks (used when force=True in event)

		Returns:
			Dict with click coordinates or None
		"""
		try:
			page = await self._get_playwright_page()
			thread = _get_playwright_thread()
			
			# Define click coroutine (runs in Playwright thread)
			async def click_coord_coro():
				self.logger.debug(f'👆 Clicking at ({coordinate_x}, {coordinate_y})...')
				
				# Click at coordinates using Playwright
				await page.mouse.click(coordinate_x, coordinate_y)
				
				self.logger.debug(f'🖱️ Clicked successfully at ({coordinate_x}, {coordinate_y})')
			
			# Dispatch to Playwright thread
			await thread.run_coro(click_coord_coro())
			
			# Return coordinates as metadata
			return {'click_x': coordinate_x, 'click_y': coordinate_y}

		except Exception as e:
			self.logger.error(f'\033[91mFailed to click at coordinates ({coordinate_x}, {coordinate_y}): {type(e).__name__}: {e}\033[0m')
			raise BrowserError(
				message=f'Failed to click at coordinates: {e}',
				long_term_memory=f'Failed to click at coordinates ({coordinate_x}, {coordinate_y}). The coordinates may be outside viewport or the page may have changed.',
			)

	async def _input_text_element_node_impl(
		self, element_node: EnhancedDOMTreeNode, text: str, clear: bool = True, is_sensitive: bool = False
	) -> dict | None:
		"""
		Input text into an element using Playwright.

		For date/time inputs, uses direct value assignment via Playwright.
		"""
		try:
			# Get Playwright page
			page = await self._get_playwright_page()
			
			# Convert element_node to selector
			try:
				selector = self._element_node_to_playwright_selector(element_node)
			except ValueError:
				# Fallback: use CDP for typing
				self.logger.debug('Using CDP fallback for type (no selector available)')
				return await self._input_text_element_node_impl_cdp_fallback(
					element_node, text, clear, is_sensitive
				)

			# Use Playwright to fill/type (dispatch to Playwright thread)
			thread = _get_playwright_thread()
			
			# Define type coroutine (runs in Playwright thread)
			async def type_coro():
				locator = page.locator(selector).first
				await locator.wait_for(state='visible', timeout=5000)
				
				# Check if this element requires direct value assignment (date/time inputs)
				requires_direct_assignment = self._requires_direct_value_assignment(element_node)
				
				if requires_direct_assignment:
					# Date/time inputs: use direct value assignment
					self.logger.debug(
						f'🎯 Element type={element_node.attributes.get("type")} requires direct value assignment, setting value directly'
					)
					await locator.fill(text)
				else:
					# Regular inputs: clear if requested, then fill
					if clear:
						await locator.clear()
					await locator.fill(text)
				
				# Get bounding box for metadata
				box = await locator.bounding_box()
				return box
			
			# Dispatch to Playwright thread
			box = await thread.run_coro(type_coro())
			if box:
				return {'input_x': box['x'], 'input_y': box['y']}
			return None

		except Exception as e:
			self.logger.error(f'\033[91mFailed to input text via Playwright: {type(e).__name__}: {e}\033[0m')
			raise BrowserError(f'Failed to input text into element: {repr(element_node)}')

	def _requires_direct_value_assignment(self, element_node: EnhancedDOMTreeNode) -> bool:
		"""
		Check if an element requires direct value assignment instead of character-by-character typing.

		Certain input types have compound components, custom plugins, or special requirements
		that make character-by-character typing unreliable. These need direct .value assignment:

		Native HTML5:
		- date, time, datetime-local: Have spinbutton components (ISO format required)
		- month, week: Similar compound structure
		- color: Expects hex format #RRGGBB
		- range: Needs numeric value within min/max

		jQuery/Bootstrap Datepickers:
		- Detected by class names or data attributes
		- Often expect specific date formats (MM/DD/YYYY, DD/MM/YYYY, etc.)
		"""
		if not element_node.tag_name or not element_node.attributes:
			return False

		tag_name = element_node.tag_name.lower()

		# Check for native HTML5 inputs that need direct assignment
		if tag_name == 'input':
			input_type = element_node.attributes.get('type', '').lower()

			# Native HTML5 inputs with compound components or strict formats
			if input_type in {'date', 'time', 'datetime-local', 'month', 'week', 'color', 'range'}:
				return True

			# Detect jQuery/Bootstrap datepickers (text inputs with datepicker plugins)
			if input_type in {'text', ''}:
				# Check for common datepicker indicators
				class_attr = element_node.attributes.get('class', '').lower()
				if any(
					indicator in class_attr
					for indicator in ['datepicker', 'daterangepicker', 'datetimepicker', 'bootstrap-datepicker']
				):
					return True

				# Check for data attributes indicating datepickers
				if any(attr in element_node.attributes for attr in ['data-datepicker', 'data-date-format', 'data-provide']):
					return True

		return False

	async def _input_text_element_node_impl_cdp_fallback(
		self, element_node: EnhancedDOMTreeNode, text: str, clear: bool, is_sensitive: bool
	) -> dict | None:
		"""CDP fallback for typing when selector is not available."""
		# Import the CDP implementation from default_action_watchdog
		from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog
		
		# Create a temporary instance to use its CDP implementation
		# We'll use the browser_session's existing CDP methods
		cdp_session = await self.browser_session.cdp_client_for_node(element_node)
		backend_node_id = element_node.backend_node_id
		
		# Resolve node to object ID
		result = await cdp_session.cdp_client.send.DOM.resolveNode(
			params={'backendNodeId': backend_node_id},
			session_id=cdp_session.session_id,
		)
		if 'object' not in result or 'objectId' not in result['object']:
			raise ValueError('Could not get object_id for element')
		
		object_id = result['object']['objectId']
		
		# Use CDP to set value directly (simpler fallback)
		set_value_js = f"""
		function() {{
			this.value = {json.dumps(text)};
			this.dispatchEvent(new Event('input', {{ bubbles: true }}));
			this.dispatchEvent(new Event('change', {{ bubbles: true }}));
			return this.value;
		}}
		"""
		
		await cdp_session.cdp_client.send.Runtime.callFunctionOn(
			params={
				'objectId': object_id,
				'functionDeclaration': set_value_js,
				'returnByValue': True,
			},
			session_id=cdp_session.session_id,
		)
		
		return None

	async def _scroll_element_container_cdp(self, element_node, pixels: int) -> bool:
		"""CDP fallback for scrolling element container."""
		try:
			cdp_session = await self.browser_session.cdp_client_for_node(element_node)

			# Check if this is an iframe - if so, scroll its content directly
			if element_node.tag_name and element_node.tag_name.upper() == 'IFRAME':
				backend_node_id = element_node.backend_node_id
				result = await cdp_session.cdp_client.send.DOM.resolveNode(
					params={'backendNodeId': backend_node_id},
					session_id=cdp_session.session_id,
				)
				if 'object' in result and 'objectId' in result['object']:
					object_id = result['object']['objectId']
					scroll_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
						params={
							'functionDeclaration': f"""
								function() {{
									try {{
										const doc = this.contentDocument || this.contentWindow.document;
										if (doc) {{
											const scrollElement = doc.documentElement || doc.body;
											if (scrollElement) {{
												const oldScrollTop = scrollElement.scrollTop;
												scrollElement.scrollTop += {pixels};
												const newScrollTop = scrollElement.scrollTop;
												return {{
													success: true,
													oldScrollTop: oldScrollTop,
													newScrollTop: newScrollTop,
													scrolled: newScrollTop - oldScrollTop
												}};
											}}
										}}
										return {{success: false, error: 'Could not access iframe content'}};
									}} catch (e) {{
										return {{success: false, error: e.toString()}};
									}}
								}}
							""",
							'objectId': object_id,
							'returnByValue': True,
						},
						session_id=cdp_session.session_id,
					)
					if scroll_result and 'result' in scroll_result and 'value' in scroll_result['result']:
						result_value = scroll_result['result']['value']
						if result_value.get('success'):
							return True

			# For non-iframe elements, use mouse wheel
			backend_node_id = element_node.backend_node_id
			box_model = await cdp_session.cdp_client.send.DOM.getBoxModel(
				params={'backendNodeId': backend_node_id}, session_id=cdp_session.session_id
			)
			content_quad = box_model['model']['content']
			center_x = (content_quad[0] + content_quad[2] + content_quad[4] + content_quad[6]) / 4
			center_y = (content_quad[1] + content_quad[3] + content_quad[5] + content_quad[7]) / 4

			await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
				params={
					'type': 'mouseWheel',
					'x': center_x,
					'y': center_y,
					'deltaX': 0,
					'deltaY': pixels,
				},
				session_id=cdp_session.session_id,
			)
			return True
		except Exception as e:
			self.logger.debug(f'Failed to scroll element container via CDP: {e}')
			return False

	async def on_SelectDropdownOptionEvent(self, event: SelectDropdownOptionEvent) -> dict[str, str]:
		"""Handle select dropdown option request with Playwright."""
		try:
			element_node = event.node
			index_for_logging = element_node.backend_node_id or 'unknown'
			target_text = event.text

			# Get Playwright page
			page = await self._get_playwright_page()
			
			# Convert element_node to selector
			try:
				selector = self._element_node_to_playwright_selector(element_node)
			except ValueError:
				# Fallback to CDP
				return await self._select_dropdown_cdp_fallback(element_node, target_text, index_for_logging)

			# Use Playwright to select dropdown option (dispatch to Playwright thread)
			thread = _get_playwright_thread()
			
			async def select_dropdown_coro():
				locator = page.locator(selector).first
				await locator.wait_for(state='visible', timeout=5000)
				
				# Try select_option with text
				try:
					await locator.select_option(label=target_text, timeout=5000)
				except Exception:
					# If label fails, try value
					try:
						await locator.select_option(value=target_text, timeout=5000)
					except Exception:
						# Last resort: try index if target_text is numeric
						if target_text.isdigit():
							await locator.select_option(index=int(target_text), timeout=5000)
						else:
							raise
			
			await thread.run_coro(select_dropdown_coro())

			msg = f'Selected "{target_text}" in dropdown at index {index_for_logging}'
			self.logger.debug(f'{msg}')

			# Return the result as a dict matching CDP format
			return {
				'success': 'true',
				'message': msg,
				'value': target_text,
				'backend_node_id': str(index_for_logging),
			}

		except BrowserError:
			raise
		except Exception as e:
			# Fallback to CDP if Playwright fails
			self.logger.debug(f'Playwright dropdown selection failed: {e}, falling back to CDP')
			return await self._select_dropdown_cdp_fallback(element_node, event.text, index_for_logging)

	async def _select_dropdown_cdp_fallback(
		self, element_node: EnhancedDOMTreeNode, target_text: str, index_for_logging: str
	) -> dict[str, str]:
		"""CDP fallback for dropdown selection."""
		# Import CDP implementation from default_action_watchdog
		from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog
		
		# Create temporary instance to reuse CDP logic
		temp_watchdog = DefaultActionWatchdog(
			event_bus=self.event_bus,
			browser_session=self.browser_session
		)
		
		# Create a mock event to pass to the CDP handler
		from browser_use.browser.events import SelectDropdownOptionEvent
		mock_event = SelectDropdownOptionEvent(node=element_node, text=target_text)
		
		# Call the CDP implementation
		return await temp_watchdog.on_SelectDropdownOptionEvent(mock_event)

	# ========== Keep CDP methods for reading operations ==========

	async def on_GetDropdownOptionsEvent(self, event: GetDropdownOptionsEvent) -> dict[str, str]:
		"""Handle get dropdown options request with CDP (reading operation, no DOM modification)."""
		# Import CDP implementation from default_action_watchdog
		from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog
		
		# Create temporary instance to reuse CDP logic
		temp_watchdog = DefaultActionWatchdog(
			event_bus=self.event_bus,
			browser_session=self.browser_session
		)
		
		# Call the CDP implementation (this is a read operation, so CDP is fine)
		return await temp_watchdog.on_GetDropdownOptionsEvent(event)

	async def on_GoBackEvent(self, event: GoBackEvent) -> None:
		"""Handle navigate back request with CDP."""
		from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog
		temp_watchdog = DefaultActionWatchdog(
			event_bus=self.event_bus,
			browser_session=self.browser_session
		)
		return await temp_watchdog.on_GoBackEvent(event)

	async def on_GoForwardEvent(self, event: GoForwardEvent) -> None:
		"""Handle navigate forward request with CDP."""
		from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog
		temp_watchdog = DefaultActionWatchdog(
			event_bus=self.event_bus,
			browser_session=self.browser_session
		)
		return await temp_watchdog.on_GoForwardEvent(event)

	async def on_RefreshEvent(self, event: RefreshEvent) -> None:
		"""Handle target refresh request with CDP."""
		from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog
		temp_watchdog = DefaultActionWatchdog(
			event_bus=self.event_bus,
			browser_session=self.browser_session
		)
		return await temp_watchdog.on_RefreshEvent(event)

	@observe_debug(ignore_input=True, ignore_output=True, name='wait_event_handler')
	async def on_WaitEvent(self, event: WaitEvent) -> None:
		"""Handle wait request."""
		try:
			# Cap wait time at maximum
			actual_seconds = min(max(event.seconds, 0), event.max_seconds)
			if actual_seconds != event.seconds:
				self.logger.info(f'🕒 Waiting for {actual_seconds} seconds (capped from {event.seconds}s)')
			else:
				self.logger.info(f'🕒 Waiting for {actual_seconds} seconds')

			await asyncio.sleep(actual_seconds)
		except Exception as e:
			raise

	async def on_SendKeysEvent(self, event: SendKeysEvent) -> None:
		"""Handle send keys request with Playwright (dispatches to Playwright thread)."""
		page = await self._get_playwright_page()
		thread = _get_playwright_thread()
		
		# Normalize key names from common aliases
		key_aliases = {
			'ctrl': 'Control',
			'control': 'Control',
			'alt': 'Alt',
			'option': 'Alt',
			'meta': 'Meta',
			'cmd': 'Meta',
			'command': 'Meta',
			'shift': 'Shift',
			'enter': 'Enter',
			'return': 'Enter',
			'tab': 'Tab',
			'delete': 'Delete',
			'backspace': 'Backspace',
			'escape': 'Escape',
			'esc': 'Escape',
			'space': ' ',
			'up': 'ArrowUp',
			'down': 'ArrowDown',
			'left': 'ArrowLeft',
			'right': 'ArrowRight',
			'pageup': 'PageUp',
			'pagedown': 'PageDown',
			'home': 'Home',
			'end': 'End',
		}

		# Parse and normalize the key string
		keys = event.keys
		if '+' in keys:
			# Handle key combinations like "ctrl+a"
			parts = keys.split('+')
			normalized_parts = []
			for part in parts:
				part_lower = part.strip().lower()
				normalized = key_aliases.get(part_lower, part)
				normalized_parts.append(normalized)
			normalized_keys = '+'.join(normalized_parts)
		else:
			# Single key
			keys_lower = keys.strip().lower()
			normalized_keys = key_aliases.get(keys_lower, keys)

		# Define send keys coroutine (runs in Playwright thread)
		async def send_keys_coro():
			# Handle key combinations
			if '+' in normalized_keys:
				parts = normalized_keys.split('+')
				modifiers = parts[:-1]
				main_key = parts[-1]
				
				# Press modifier keys
				for mod in modifiers:
					await page.keyboard.down(mod)
				
				# Press main key
				await page.keyboard.press(main_key)
				
				# Release modifier keys
				for mod in reversed(modifiers):
					await page.keyboard.up(mod)
			else:
				# Single key or text
				special_keys = {
					'Enter', 'Tab', 'Delete', 'Backspace', 'Escape',
					'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
					'PageUp', 'PageDown', 'Home', 'End',
					'Control', 'Alt', 'Meta', 'Shift',
					'F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12',
				}
				
				if normalized_keys in special_keys:
					await page.keyboard.press(normalized_keys)
				else:
					# It's text - type it
					await page.keyboard.type(normalized_keys, delay=18)
		
		# Dispatch to Playwright thread
		await thread.run_coro(send_keys_coro())

		self.logger.info(f'⌨️ Sent keys: {event.keys}')

		# Wait briefly for potential navigation
		if 'enter' in event.keys.lower() or 'return' in event.keys.lower():
			await asyncio.sleep(0.1)

	async def on_TabClosedEvent(self, event: TabClosedEvent) -> None:
		"""Handle tab closure - remove page from mapping."""
		thread = _get_playwright_thread()
		if event.target_id in thread._target_id_to_page:
			page = thread._target_id_to_page[event.target_id]
			del thread._target_id_to_page[event.target_id]
			self.logger.debug(
				f'🗑️ Removed Playwright page mapping for closed target_id={event.target_id[-8:]}: '
				f'page={page}, url={page.url[:50] if not page.is_closed() else "closed"}'
			)

	async def on_UploadFileEvent(self, event: UploadFileEvent) -> None:
		"""Handle file upload request with Playwright."""
		try:
			# Use the provided node
			element_node = event.node
			index_for_logging = element_node.backend_node_id or 'unknown'

			# Check if it's a file input
			if not self.browser_session.is_file_input(element_node):
				msg = f'Upload failed - element {index_for_logging} is not a file input.'
				raise BrowserError(message=msg, long_term_memory=msg)

			# Get Playwright page
			page = await self._get_playwright_page()
			
			# Convert element_node to selector
			try:
				selector = self._element_node_to_playwright_selector(element_node)
			except ValueError:
				# Fallback to CDP
				from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog
				temp_watchdog = DefaultActionWatchdog(
					event_bus=self.event_bus,
					browser_session=self.browser_session
				)
				return await temp_watchdog.on_UploadFileEvent(event)

			# Use Playwright to set file (dispatch to Playwright thread)
			thread = _get_playwright_thread()
			
			async def upload_file_coro():
				locator = page.locator(selector).first
				await locator.wait_for(state='visible', timeout=5000)
				await locator.set_input_files(event.file_path)
			
			await thread.run_coro(upload_file_coro())

			self.logger.info(f'📎 Uploaded file {event.file_path} to element {index_for_logging}')
		except Exception as e:
			raise

	async def on_ScrollToTextEvent(self, event: ScrollToTextEvent) -> None:
		"""Handle scroll to text request with Playwright (dispatches to Playwright thread)."""
		page = await self._get_playwright_page()
		thread = _get_playwright_thread()
		
		try:
			# Define scroll to text coroutine (runs in Playwright thread)
			async def scroll_to_text_coro():
				# Use Playwright's text locator
				locator = page.get_by_text(event.text, exact=False).first
				await locator.scroll_into_view_if_needed(timeout=5000)
			
			# Dispatch to Playwright thread
			await thread.run_coro(scroll_to_text_coro())
			self.logger.debug(f'📜 Scrolled to text: "{event.text}"')
		except Exception as e:
			# Fallback to CDP if Playwright fails
			self.logger.debug(f'Playwright scroll to text failed: {e}, falling back to CDP')
			from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog
			temp_watchdog = DefaultActionWatchdog(
				event_bus=self.event_bus,
				browser_session=self.browser_session
			)
			return await temp_watchdog.on_ScrollToTextEvent(event)

