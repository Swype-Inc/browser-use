"""Navigation step implementation."""

import asyncio
import importlib.resources
import logging
from typing import TYPE_CHECKING, Callable, List, Optional

from browser_use.browser import BrowserSession
from browser_use.browser.views import BrowserStateSummary
from browser_use.job_application.pipeline.navigation.schema import NavigationResult
from browser_use.job_application.pipeline.page_classification.run import run as classify_page
from browser_use.job_application.pipeline.shared.enums import PageType
from browser_use.job_application.pipeline.shared.utils import debug_input, format_browser_state_message
from browser_use.job_application.pipeline.state import PipelineState
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import UserMessage
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.service import Tools
from browser_use.agent.views import AgentOutput, ActionResult, PlanOutput

if TYPE_CHECKING:
	pass

logger = logging.getLogger(__name__)


def _load_prompt() -> str:
	"""Load the navigation prompt template."""
	try:
		with importlib.resources.files('browser_use.job_application.pipeline.navigation').joinpath(
			'prompt.md'
		).open('r', encoding='utf-8') as f:
			return f.read()
	except Exception as e:
		raise RuntimeError(f'Failed to load navigation prompt: {e}')


async def prepare_navigation_context(
	browser_session: BrowserSession,
	include_all_form_fields: bool = False,
) -> BrowserStateSummary:
	"""Prepare context for navigation: get browser state and wait for stability.
	
	Args:
		browser_session: Browser session
		include_all_form_fields: Whether to include all form fields
		
	Returns:
		Browser state summary
	"""
	logger.debug('🌐 Getting browser state for navigation...')
	
	# Get browser state
	browser_state = await browser_session.get_browser_state_summary(
		include_screenshot=True,
		include_all_form_fields=include_all_form_fields,
	)

	# Wait for page stability
	if browser_session._dom_watchdog:
		logger.debug('🔍 Waiting for page stability...')
		await browser_session._dom_watchdog.wait_for_page_stability()

	return browser_state


async def plan_navigation(
	browser_session: BrowserSession,
	llm: BaseChatModel,
	browser_state: BrowserStateSummary,
) -> Optional[str]:
	"""Plan navigation steps using LLM.
	
	Args:
		browser_session: Browser session
		llm: LLM for planning
		browser_state: Current browser state
		
	Returns:
		Navigation plan or None if planning failed
	"""
	logger.debug('📋 Planning navigation steps...')

	# Load prompt template
	prompt_text = _load_prompt()
	
	# Add planning instructions
	planning_instructions = f"""{prompt_text}

You are in the PLANNING phase for navigation. Your task is to create a focused plan for navigating from the current page to the job application page.

**Your Plan Should:**
1. Identify what page you're currently on (job description, login, account creation, etc.)
2. Determine the immediate next step(s) to progress toward the application page
3. Be specific about which elements need interaction (include element indices)
4. Keep it concise - 3-5 steps maximum, focused on the current page

**Common Navigation Scenarios:**
- If on job description page: Find and click "Apply" or "Apply Now" button
- If on login page: Fill credentials and click sign-in button
- If on account creation: Fill registration form and submit
- If on email verification: Handle verification flow

Return your plan with rationale explaining your reasoning."""
	
	# Format browser state using shared utility
	browser_state_text = format_browser_state_message(browser_state)
	
	# Combine into ONE message
	combined_content = f"{planning_instructions}\n\n<browser_state>\n{browser_state_text}\n</browser_state>"
	messages = [UserMessage(content=combined_content)]

	try:
		response = await llm.ainvoke(messages, output_format=PlanOutput)
		plan_output = response.completion
		logger.info(f'📋 Navigation Plan: {plan_output.plan}')
		debug_input('[DEBUG] Press Enter to continue after navigation planning...')
		return plan_output.plan
	except Exception as e:
		logger.warning(f'Planning failed: {e}. Continuing without plan.')
		return None


async def get_navigation_actions(
	browser_session: BrowserSession,
	llm: BaseChatModel,
	tools: Tools,
	browser_state: BrowserStateSummary,
	plan: Optional[str],
) -> List[ActionModel]:
	"""Get navigation actions from LLM based on plan.
	
	Args:
		browser_session: Browser session
		llm: LLM for action selection
		tools: Tools registry
		browser_state: Current browser state
		plan: Navigation plan
		
	Returns:
		List of actions to execute
	"""
	logger.debug('🤖 Getting navigation actions from LLM...')

	# Get available actions for this page
	page_filtered_actions = tools.registry.get_prompt_description(browser_state.url)
	actions_description = page_filtered_actions if page_filtered_actions else 'Available actions: click, input, navigate, search, etc.'

	# Build action selection prompt
	plan_text = plan if plan else "No plan available - determine actions based on current state"
	action_prompt_content = f"""You are in the ACTION SELECTION phase for navigation.

**Available Actions:**
{actions_description}

**Navigation Plan:**
{plan_text}

**Your Task:**
Select the specific actions needed to progress toward the application page. Use the plan to guide your action selection.

**Action Selection Guidelines:**
- If plan says "click Apply button", use click action with the element index
- If plan says "fill login form", use input actions for each field
- If plan says "navigate to URL", use navigate action
- Select 1-3 actions per step to make progress

Return your selected actions."""

	# Format browser state using shared utility
	browser_state_text = format_browser_state_message(browser_state)
	
	# Combine into ONE message
	combined_content = f"{action_prompt_content}\n\n<browser_state>\n{browser_state_text}\n</browser_state>"
	messages = [UserMessage(content=combined_content)]

	# Create AgentOutput type with available actions
	# Get the action model for the current page (filters actions by URL)
	ActionModel = tools.registry.create_action_model(page_url=browser_state.url)
	AgentOutputType = AgentOutput.type_with_custom_actions_no_thinking(ActionModel)

	try:
		response = await llm.ainvoke(messages, output_format=AgentOutputType)
		agent_output = response.completion
		actions = agent_output.action
		logger.info(f'⚡ Selected {len(actions)} navigation action(s)')
		debug_input(f'[DEBUG] Press Enter to continue after navigation action selection ({len(actions)} actions)...')
		return actions
	except Exception as e:
		logger.error(f'Failed to get navigation actions: {e}')
		raise


async def execute_navigation_actions(
	browser_session: BrowserSession,
	tools: Tools,
	actions: List[ActionModel],
) -> List[ActionResult]:
	"""Execute navigation actions.
	
	Args:
		browser_session: Browser session
		tools: Tools registry
		actions: List of actions to execute
		
	Returns:
		List of action results
	"""
	logger.debug(f'⚡ Executing {len(actions)} navigation action(s)...')

	results = []
	for i, action in enumerate(actions):
		try:
			logger.debug(f'Executing action {i + 1}/{len(actions)}: {action.model_dump(exclude_unset=True)}')
			
			result = await tools.act(
				action=action,
				browser_session=browser_session,
				page_extraction_llm=None,
				sensitive_data=None,
				available_file_paths=None,
				file_system=None,
			)

			results.append(result)

			if result.error:
				logger.warning(f'⚠️ Action {i + 1} failed: {result.error}')
			elif result.is_done:
				logger.info(f'✅ Action {i + 1} completed task')
				break

			# Wait between actions
			if i < len(actions) - 1:
				await asyncio.sleep(0.5)

		except Exception as e:
			logger.error(f'❌ Action {i + 1} raised exception: {e}')
			results.append(ActionResult(error=str(e)))

	return results


async def check_navigation_complete(
	browser_session: BrowserSession,
	llm: BaseChatModel,
) -> PageType:
	"""Check if navigation is complete by re-classifying the page.
	
	Args:
		browser_session: Browser session
		llm: LLM for page classification
		
	Returns:
		The classified page type
	"""
	logger.debug('🔍 Checking if navigation to application page is complete...')
	return await classify_page(browser_session, llm)


async def run(
	browser_session: BrowserSession,
	llm: BaseChatModel,
	tools: Tools,
	pipeline_state: PipelineState,
) -> None:
	"""Navigate from job description to application page using full agent loop.
	
	Args:
		browser_session: Browser session
		llm: LLM for navigation
		tools: Tools registry
		pipeline_state: Pipeline state for tracking attempts
		
	Raises:
		RuntimeError: If navigation fails after max attempts
	"""
	max_navigation_steps = 20
	consecutive_failures = 0
	max_failures = 3

	logger.info('🚀 Starting navigation to application page...')

	for step in range(max_navigation_steps):
		pipeline_state.navigation_attempts += 1
		logger.info(f'📍 Navigation step {step + 1}/{max_navigation_steps}')

		try:
			# Phase 1: Read DOM - Get browser state
			browser_state = await prepare_navigation_context(browser_session)

			# Phase 2: Check if we've reached the application page
			page_type = await check_navigation_complete(browser_session, llm)
			if page_type == PageType.APPLICATION_PAGE:
				logger.info('✅ Successfully navigated to application page!')
				return

			# Phase 3: Plan navigation
			plan = await plan_navigation(browser_session, llm, browser_state)

			# Phase 4: Get navigation actions
			actions = await get_navigation_actions(browser_session, llm, tools, browser_state, plan)

			# Phase 5: Execute actions
			results = await execute_navigation_actions(browser_session, tools, actions)

			# Check for errors
			if results and any(r.error for r in results):
				consecutive_failures += 1
				logger.warning(f'⚠️ Navigation step failed. Consecutive failures: {consecutive_failures}')
				if consecutive_failures >= max_failures:
					logger.error(f'❌ Navigation failed after {max_failures} consecutive failures')
					raise RuntimeError('Navigation failed: too many consecutive failures')
			else:
				consecutive_failures = 0

			# Wait for page to stabilize after actions
			if browser_session._dom_watchdog:
				await browser_session._dom_watchdog.wait_for_page_stability()
			else:
				await asyncio.sleep(1.0)

		except Exception as e:
			logger.error(f'❌ Navigation step {step + 1} failed: {e}')
			consecutive_failures += 1
			if consecutive_failures >= max_failures:
				raise RuntimeError(f'Navigation failed after {max_failures} consecutive failures: {e}')

	# If we get here, we didn't reach the application page
	raise RuntimeError(f'Failed to navigate to application page after {max_navigation_steps} steps')


async def navigate_to_next_page(
	browser_session: BrowserSession,
) -> NavigationResult:
	"""Attempt to navigate to next page.
	
	Args:
		browser_session: Browser session
		
	Returns:
		Navigation result
	"""
	try:
		# Look for "Save and Continue", "Next", "Continue" buttons
		browser_state = await browser_session.get_browser_state_summary(include_all_form_fields=True)
		current_url = browser_state.url

		# Find navigation button
		# TODO: Use LLM or heuristics to find the button
		# For now, stub implementation
		logger.info('Attempting to navigate to next page (stub)')

		# Wait a bit to see if page changes
		await asyncio.sleep(1.0)
		new_browser_state = await browser_session.get_browser_state_summary(include_all_form_fields=True)
		page_changed = new_browser_state.url != current_url

		return NavigationResult(success=True, page_changed=page_changed)
	except Exception as e:
		logger.error(f'Failed to navigate to next page: {e}')
		return NavigationResult(success=False, errors=[str(e)])

