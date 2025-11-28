"""Account creation step implementation."""

import asyncio
import importlib.resources
import logging
from typing import TYPE_CHECKING, List, Optional

from browser_use.browser import BrowserSession
from browser_use.browser.views import BrowserStateSummary
from browser_use.job_application.pipeline.account_creation.schema import *  # noqa: F403, F401
from browser_use.job_application.pipeline.navigation.run import (
	check_navigation_complete,
	execute_navigation_actions,
	get_navigation_actions,
	plan_navigation,
	prepare_navigation_context,
)
from browser_use.job_application.pipeline.page_classification.run import run as classify_page
from browser_use.job_application.pipeline.shared.enums import PageType
from browser_use.job_application.pipeline.shared.utils import debug_input, format_browser_state_message
from browser_use.job_application.pipeline.state import PipelineState
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import UserMessage
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.service import Tools
from browser_use.agent.views import AgentOutput, PlanOutput

if TYPE_CHECKING:
	pass

logger = logging.getLogger(__name__)


def _load_prompt() -> str:
	"""Load the account creation prompt template."""
	try:
		with importlib.resources.files('browser_use.job_application.pipeline.account_creation').joinpath(
			'prompt.md'
		).open('r', encoding='utf-8') as f:
			return f.read()
	except Exception as e:
		raise RuntimeError(f'Failed to load account creation prompt: {e}')


def _build_prompt(email: Optional[str] = None, password: Optional[str] = None) -> str:
	"""Build the account creation prompt.
	
	Args:
		email: User email for account creation/sign-in
		password: User password for account creation/sign-in
		
	Returns:
		Formatted prompt string
	"""
	template = _load_prompt()
	
	# Default values if not provided
	email = email or "[EMAIL_NOT_PROVIDED]"
	password = password or "[PASSWORD_NOT_PROVIDED]"
	
	return template.format(email=email, password=password)


async def check_account_creation_complete(
	browser_session: BrowserSession,
	llm: BaseChatModel,
) -> PageType:
	"""Check if account creation is complete by re-classifying the page.
	
	Args:
		browser_session: Browser session
		llm: LLM for page classification
		
	Returns:
		The classified page type
	"""
	logger.debug('🔍 Checking if account creation is complete...')
	page_type = await classify_page(browser_session, llm)
	# Account creation is complete if we're no longer on account creation page
	return page_type


async def plan_account_creation(
	browser_session: BrowserSession,
	llm: BaseChatModel,
	browser_state: BrowserStateSummary,
	email: Optional[str] = None,
	password: Optional[str] = None,
) -> Optional[str]:
	"""Plan account creation/sign-in steps using LLM.
	
	Args:
		browser_session: Browser session
		llm: LLM for planning
		browser_state: Current browser state
		email: User email
		password: User password
		
	Returns:
		Account creation plan or None if planning failed
	"""
	logger.debug('📋 Planning account creation steps...')

	# Build planning prompt (instructions only) with user credentials
	prompt_text = _build_prompt(email, password)
	
	# Add planning instructions
	planning_instructions = f"""{prompt_text}

You are in the PLANNING phase for account creation/sign-in. Your task is to create a focused plan for completing the account creation or sign-in process.

**Your Plan Should:**
1. Identify what type of page you're on (sign-in, account creation, email verification)
2. Determine the immediate next step(s) to complete the process
3. Be specific about which elements need interaction (include element indices)
4. Keep it concise - 3-5 steps maximum, focused on the current page

**Common Navigation Scenarios:**
- If on sign-in page: Fill credentials and click sign-in button
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
		logger.info(f'📋 Account Creation Plan: {plan_output.plan}')
		debug_input('[DEBUG] Press Enter to continue after account creation planning...')
		return plan_output.plan
	except Exception as e:
		logger.warning(f'Planning failed: {e}. Continuing without plan.')
		return None


async def get_account_creation_actions(
	browser_session: BrowserSession,
	llm: BaseChatModel,
	tools: Tools,
	browser_state: BrowserStateSummary,
	plan: Optional[str],
	email: Optional[str] = None,
	password: Optional[str] = None,
) -> List[ActionModel]:
	"""Get account creation actions from LLM based on plan.
	
	Args:
		browser_session: Browser session
		llm: LLM for action selection
		tools: Tools registry
		browser_state: Current browser state
		plan: Optional plan
		email: User email
		password: User password
		
	Returns:
		List of actions to execute
	"""
	logger.debug('🤖 Getting account creation actions from LLM...')

	# Get available actions for this page
	page_filtered_actions = tools.registry.get_prompt_description(browser_state.url)
	actions_description = page_filtered_actions if page_filtered_actions else 'Available actions: click, input, navigate, search, etc.'

	# Build account creation prompt with user credentials
	account_creation_prompt = _build_prompt(email, password)

	# Build action selection prompt
	plan_text = plan if plan else "No plan available - determine actions based on current state"
	action_prompt_content = f"""{account_creation_prompt}

You are in the ACTION SELECTION phase for account creation/sign-in.

**Available Actions:**
{actions_description}

**Account Creation Plan:**
{plan_text}

**Your Task:**
Select the specific actions needed to complete account creation or sign-in. Use the plan to guide your action selection.

**Action Selection Guidelines:**
- If plan says "fill email/password", use input actions with email="{email or '[EMAIL_NOT_PROVIDED]'}" and password="{password or '[PASSWORD_NOT_PROVIDED]'}"
- If plan says "click Sign In", use click action with the element index
- If plan says "click Create Account", use click action
- If plan says "enter verification code", use input action
- Select 1-3 actions per step to make progress

**Important:** When filling email or password fields, use the exact values provided above.

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
		logger.info(f'⚡ Selected {len(actions)} account creation action(s)')
		debug_input(f'[DEBUG] Press Enter to continue after account creation action selection ({len(actions)} actions)...')
		return actions
	except Exception as e:
		logger.error(f'Failed to get account creation actions: {e}')
		raise


async def run(
	browser_session: BrowserSession,
	llm: BaseChatModel,
	tools: Tools,
	pipeline_state: PipelineState,
	email: Optional[str] = None,
	password: Optional[str] = None,
) -> None:
	"""Handle account creation or sign-in flow using full agent loop.
	
	Args:
		browser_session: Browser session
		llm: LLM for account creation
		tools: Tools registry
		pipeline_state: Pipeline state for tracking attempts
		email: User email
		password: User password
		
	Raises:
		RuntimeError: If account creation fails after max attempts
	"""
	max_steps = 20
	consecutive_failures = 0
	max_failures = 3

	logger.info('🔐 Starting account creation/sign-in flow...')

	for step in range(max_steps):
		pipeline_state.navigation_attempts += 1
		logger.info(f'📍 Account creation step {step + 1}/{max_steps}')

		try:
			# Phase 1: Read DOM - Get browser state
			browser_state = await prepare_navigation_context(browser_session, include_all_form_fields=True)

			# Phase 2: Check if we've completed account creation (reached application or job description)
			page_type = await check_account_creation_complete(browser_session, llm)
			if page_type in [PageType.APPLICATION_PAGE, PageType.JOB_DESCRIPTION]:
				logger.info('✅ Successfully completed account creation/sign-in!')
				return

			# Phase 3: Plan account creation steps
			plan = await plan_account_creation(browser_session, llm, browser_state, email, password)

			# Phase 4: Get account creation actions
			actions = await get_account_creation_actions(browser_session, llm, tools, browser_state, plan, email, password)

			# Phase 5: Execute actions
			results = await execute_navigation_actions(browser_session, tools, actions)

			# Check for errors
			if results and any(r.error for r in results):
				consecutive_failures += 1
				logger.warning(f'⚠️ Account creation step failed. Consecutive failures: {consecutive_failures}')
				if consecutive_failures >= max_failures:
					logger.error(f'❌ Account creation failed after {max_failures} consecutive failures')
					raise RuntimeError('Account creation failed: too many consecutive failures')
			else:
				consecutive_failures = 0

			# Wait for page to stabilize after actions
			if browser_session._dom_watchdog:
				await browser_session._dom_watchdog.wait_for_page_stability()
			else:
				await asyncio.sleep(1.0)

		except Exception as e:
			logger.error(f'❌ Account creation step {step + 1} failed: {e}')
			consecutive_failures += 1
			if consecutive_failures >= max_failures:
				raise RuntimeError(f'Account creation failed after {max_failures} consecutive failures: {e}')

	# If we get here, we didn't complete account creation
	raise RuntimeError(f'Failed to complete account creation after {max_steps} steps')

