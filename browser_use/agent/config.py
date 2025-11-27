"""Fail-fast validation for agent configuration and dependencies."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from browser_use.agent.service import Agent


def check(agent: 'Agent') -> None:
	"""Run all fail-fast validations before agent execution.
	
	This function should be called at the start of agent.run() to catch
	configuration issues early before any browser operations begin.
	
	Args:
		agent: The Agent instance to validate
		
	Raises:
		RuntimeError: If any validation fails
	"""
	_check_playwright_installed(agent)


def _check_playwright_installed(agent: 'Agent') -> None:
	"""Check if Playwright is installed when using PlaywrightActionWatchdog."""
	if not agent.browser_session:
		return  # No browser session, skip validation
	
	# Check if the watchdog is PlaywrightActionWatchdog
	watchdog = getattr(agent.browser_session, '_default_action_watchdog', None)
	if watchdog is None:
		return  # Watchdog not initialized yet, will be checked later
	
	watchdog_class_name = watchdog.__class__.__name__
	if watchdog_class_name == 'PlaywrightActionWatchdog':
		# Validate Playwright is installed
		try:
			from playwright.async_api import async_playwright
		except ImportError:
			raise RuntimeError(
				'PlaywrightActionWatchdog requires Playwright to be installed.\n'
				'Install with: pip install playwright && playwright install chromium\n'
				'Or switch back to DefaultActionWatchdog in browser_use/browser/session.py'
			)

