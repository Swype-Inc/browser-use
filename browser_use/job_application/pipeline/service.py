"""Main pipeline service for job application automation."""

import asyncio
import logging
from typing import TYPE_CHECKING, List, Optional

from browser_use.browser import BrowserSession
from browser_use.browser.events import ClickElementEvent, TypeTextEvent
from browser_use.browser.views import BrowserStateSummary
from browser_use.job_application.pipeline.prompts import PipelinePromptLoader
from browser_use.job_application.pipeline.state import PipelineState, SectionWithQuestions
from browser_use.job_application.pipeline.views import (
	ApplicationQuestion,
	ApplicationResult,
	ApplicationSection,
	FillResult,
	NavigationResult,
	PageClassificationOutput,
	PageType,
	QuestionAnswer,
)
from browser_use.job_application.websocket.client import AnswerGeneratorClient
from pydantic import BaseModel, ConfigDict, Field
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import UserMessage
from browser_use.observability import observe, observe_debug
from browser_use.utils import time_execution_async
from browser_use.tools.service import Tools
from browser_use.tools.registry.views import ActionModel
from browser_use.agent.views import AgentOutput, ActionResult, PlanOutput

if TYPE_CHECKING:
	pass

logger = logging.getLogger(__name__)


class JobApplicationPipeline:
	"""Multi-step pipeline for filling out job applications."""

	def __init__(
		self,
		browser_session: BrowserSession,
		llm: BaseChatModel,
		answer_generator_client: Optional[AnswerGeneratorClient] = None,
	):
		"""Initialize pipeline.

		Args:
			browser_session: Browser session for interacting with the page
			llm: LLM for classification and identification tasks
			answer_generator_client: Optional websocket client for answer generation
		"""
		self.browser_session = browser_session
		self.llm = llm
		self.answer_generator_client = answer_generator_client
		self.state = PipelineState()
		self.prompt_loader = PipelinePromptLoader()
		self.logger = logging.getLogger(__name__)
		# Initialize Tools for navigation actions
		self.tools = Tools()

	def _format_browser_state_message(self, browser_state: BrowserStateSummary) -> str:
		"""Format browser state using the same logic as AgentMessagePrompt.
		
		This ensures consistent browser state formatting across all pipeline steps.
		"""
		from browser_use.agent.prompts import AgentMessagePrompt
		from browser_use.filesystem.file_system import FileSystem
		
		# Create a minimal AgentMessagePrompt just to use its browser state formatting
		# FileSystem is required but not used for browser state formatting
		file_system = FileSystem("./tmp")
		prompt_helper = AgentMessagePrompt(
			browser_state_summary=browser_state,
			file_system=file_system,
			include_attributes=None,  # Use defaults
		)
		
		return prompt_helper._get_browser_state_description()

	@observe(name='pipeline.run', ignore_input=True, ignore_output=True)
	async def run(self) -> ApplicationResult:
		"""Main pipeline execution loop."""
		try:
			# Step 1: Classify current page
			page_type = await self.classify_page()
			self.state.current_page_type = page_type
			self.state.page_classification_history.append(page_type)

			# Step 2: Route based on page type
			if page_type == PageType.JOB_DESCRIPTION or page_type == PageType.MISC_JOB_PAGE:
				await self.navigate_to_application()
				# Re-classify after navigation
				page_type = await self.classify_page()
				self.state.current_page_type = page_type

			if page_type == PageType.APPLICATION_PAGE:
				return await self.fill_application()
			elif page_type == PageType.CONFIRMATION_PAGE:
				return ApplicationResult(
					success=True,
					completed=True,
					sections=self.state.sections,
					questions_answered=len(self.state.get_all_question_answers()),
					sections_completed=len(self.state.get_completed_sections()),
				)
			elif page_type == PageType.ALREADY_APPLIED_PAGE:
				return ApplicationResult(
					success=True,
					already_applied=True,
					sections=self.state.sections,
					questions_answered=len(self.state.get_all_question_answers()),
					sections_completed=len(self.state.get_completed_sections()),
				)
			elif page_type == PageType.EXPIRATION_PAGE:
				return ApplicationResult(
					success=False,
					error='Job posting has expired',
					sections=self.state.sections,
				)
			elif page_type == PageType.UNRELATED_PAGE:
				return ApplicationResult(
					success=False,
					error='Navigated to unrelated page',
					sections=self.state.sections,
				)
			elif page_type == PageType.MAINTENANCE_PAGE:
				return ApplicationResult(
					success=False,
					error='Site is under maintenance',
					sections=self.state.sections,
				)
			else:
				return ApplicationResult(
					success=False,
					error=f'Unexpected page type: {page_type}',
					sections=self.state.sections,
				)

		except Exception as e:
			self.logger.error(f'Pipeline error: {e}', exc_info=True)
			return ApplicationResult(
				success=False,
				error=str(e),
				sections=self.state.sections,
			)

	@observe_debug(ignore_input=True, name='classify_page')
	async def classify_page(self) -> PageType:
		"""Classify the current page type using LLM."""
		browser_state = await self.browser_session.get_browser_state_summary()

		# Build classification prompt (instructions only)
		prompt_text = self.prompt_loader.build_page_classification_prompt()
		
		# Format browser state using centralized method
		browser_state_text = self._format_browser_state_message(browser_state)
		
		# Combine into ONE message
		combined_content = f"{prompt_text}\n\n<browser_state>\n{browser_state_text}\n</browser_state>"
		messages = [UserMessage(content=combined_content)]

		# Call LLM with structured output
		response = await self.llm.ainvoke(messages, output_format=PageClassificationOutput)
		classification = response.completion

		self.logger.info(
			f'Page classified as: {classification.page_type.value} (confidence: {classification.confidence:.2f})'
		)
		return classification.page_type

	@observe_debug(ignore_input=True, name='navigate_to_application')
	async def navigate_to_application(self) -> None:
		"""Navigate from job description to application page using full agent loop."""
		max_navigation_steps = 20
		consecutive_failures = 0
		max_failures = 3

		self.logger.info('🚀 Starting navigation to application page...')

		for step in range(max_navigation_steps):
			self.state.navigation_attempts += 1
			self.logger.info(f'📍 Navigation step {step + 1}/{max_navigation_steps}')

			try:
				# Phase 1: Read DOM - Get browser state
				browser_state = await self._prepare_navigation_context()

				# Phase 2: Check if we've reached the application page
				page_type = await self._check_navigation_complete()
				if page_type == PageType.APPLICATION_PAGE:
					self.logger.info('✅ Successfully navigated to application page!')
					return

				# Phase 3: Plan navigation
				plan = await self._plan_navigation(browser_state)

				# Phase 4: Get navigation actions
				actions = await self._get_navigation_actions(browser_state, plan)

				# Phase 5: Execute actions
				results = await self._execute_navigation_actions(actions)

				# Check for errors
				if results and any(r.error for r in results):
					consecutive_failures += 1
					self.logger.warning(f'⚠️ Navigation step failed. Consecutive failures: {consecutive_failures}')
					if consecutive_failures >= max_failures:
						self.logger.error(f'❌ Navigation failed after {max_failures} consecutive failures')
						raise RuntimeError('Navigation failed: too many consecutive failures')
				else:
					consecutive_failures = 0

				# Wait for page to stabilize after actions
				await asyncio.sleep(1.0)

			except Exception as e:
				self.logger.error(f'❌ Navigation step {step + 1} failed: {e}')
				consecutive_failures += 1
				if consecutive_failures >= max_failures:
					raise RuntimeError(f'Navigation failed after {max_failures} consecutive failures: {e}')

		# If we get here, we didn't reach the application page
		raise RuntimeError(f'Failed to navigate to application page after {max_navigation_steps} steps')

	@time_execution_async('--fill_application')
	async def fill_application(self) -> ApplicationResult:
		"""Main application filling loop."""
		max_iterations = 50  # Safety limit
		iteration = 0

		while iteration < max_iterations:
			iteration += 1

			# 1. Identify next section
			section = await self.identify_next_section()
			if section is None:
				self.logger.info('All sections complete!')
				break

			self.state.current_section = section
			section_name = section.name or section.type.value
			self.logger.info(f'Working on section: {section_name}')

			# Add section to tracking if not already present
			section_with_questions = None
			for existing_section in self.state.sections:
				if (
					existing_section.name == section.name
					and existing_section.type == section.type
					and existing_section.section_index == section.section_index
				):
					section_with_questions = existing_section
					break

			if section_with_questions is None:
				section_with_questions = self.state.add_section(section)

			# 2. Identify questions in section
			questions = await self.identify_questions_in_section(section)

			# Add questions to section tracking
			from browser_use.job_application.pipeline.state import QuestionWithAnswer

			for question in questions:
				# Check if question already exists
				question_exists = any(
					q.question_text == question.question_text for q in section_with_questions.questions
				)
				if not question_exists:
					section_with_questions.questions.append(QuestionWithAnswer.from_question(question))

			# 3. Generate and fill answers
			for question in questions:
				# Check if already answered
				question_with_answer = None
				for qwa in section_with_questions.questions:
					if qwa.question_text == question.question_text:
						question_with_answer = qwa
						break

				if question_with_answer and question_with_answer.answer and question_with_answer.answer.filled_successfully:
					continue  # Already filled successfully

				# Generate answer (via websocket to browser extension)
				answer = await self.generate_answer(question)

				# Fill answer
				fill_result = await self.fill_answer(question, answer)

				# Update answer with fill result
				answer.filled_successfully = fill_result.success
				if not fill_result.success:
					answer.error_message = fill_result.error

				# Update question with answer
				if question_with_answer:
					question_with_answer.answer = answer
				else:
					# Shouldn't happen, but handle gracefully
					self.state.update_question_answer(section_name, question.question_text, answer)

				# Handle errors
				if not fill_result.success:
					await self.handle_fill_error(question, answer, fill_result.error)

			# 4. Attempt to move to next page
			navigation_result = await self.navigate_to_next_page()

			# 5. Resolve errors if navigation failed
			if not navigation_result.success:
				await self.resolve_navigation_errors(navigation_result.errors)
			elif navigation_result.page_changed:
				# Page changed, break to re-classify
				break

		return ApplicationResult(
			success=True,
			completed=True,
			sections=self.state.sections,
			questions_answered=len(self.state.get_all_question_answers()),
			sections_completed=len(self.state.get_completed_sections()),
		)

	@observe_debug(ignore_input=True, name='identify_next_section')
	async def identify_next_section(self) -> Optional[ApplicationSection]:
		"""Identify the next section that needs to be filled."""
		browser_state = await self.browser_session.get_browser_state_summary()

		# Build prompt (instructions only)
		prompt_text = self.prompt_loader.build_section_identification_prompt(self.state)
		
		# Format browser state using centralized method
		browser_state_text = self._format_browser_state_message(browser_state)
		
		# Combine into ONE message
		combined_content = f"{prompt_text}\n\n<browser_state>\n{browser_state_text}\n</browser_state>"
		messages = [UserMessage(content=combined_content)]

		# Call LLM with structured output
		# TODO: Define output format for section identification (could be Optional[ApplicationSection] or List[ApplicationSection])
		# For now, using ApplicationSection directly
		try:
			response = await self.llm.ainvoke(messages, output_format=ApplicationSection)
			section = response.completion
			return section
		except Exception as e:
			self.logger.error(f'Failed to identify section: {e}')
			# Return None if all sections are complete or error occurred
			return None

	@observe_debug(ignore_input=True, name='identify_questions')
	async def identify_questions_in_section(self, section: ApplicationSection) -> List[ApplicationQuestion]:
		"""Identify all questions in a section."""
		browser_state = await self.browser_session.get_browser_state_summary()

		# Build prompt (instructions only)
		prompt_text = self.prompt_loader.build_question_extraction_prompt(section)
		
		# Format browser state using centralized method
		browser_state_text = self._format_browser_state_message(browser_state)
		
		# Combine into ONE message
		combined_content = f"{prompt_text}\n\n<browser_state>\n{browser_state_text}\n</browser_state>"
		messages = [UserMessage(content=combined_content)]

		# Call LLM with structured output
		# Create a model for list of questions
		class QuestionsListOutput(BaseModel):
			"""Output model for question extraction."""

			model_config = ConfigDict(arbitrary_types_allowed=True, extra='forbid')

			questions: List[ApplicationQuestion] = Field(
				default_factory=list, description='List of questions found in the section'
			)

		try:
			response = await self.llm.ainvoke(messages, output_format=QuestionsListOutput)
			questions = response.completion.questions
			return questions
		except Exception as e:
			self.logger.error(f'Failed to identify questions: {e}')
			return []

	async def generate_answer(self, question: ApplicationQuestion) -> QuestionAnswer:
		"""Generate answer via websocket to browser extension."""
		if self.answer_generator_client:
			try:
				return await self.answer_generator_client.generate_answer(question)
			except NotImplementedError:
				self.logger.warning('Websocket answer generation not available, using placeholder')
			except Exception as e:
				self.logger.error(f'Failed to generate answer via websocket: {e}')

		# Fallback: return placeholder answer
		# TODO: Remove this once websocket is implemented
		return QuestionAnswer(
			question_text=question.question_text,
			answer_value='PLACEHOLDER_ANSWER',
			answer_type=question.question_type,
			element_index=question.element_index,
			filled_successfully=False,
			error_message='Answer generation not implemented',
		)

	async def fill_answer(
		self, question: ApplicationQuestion, answer: QuestionAnswer
	) -> FillResult:
		"""Fill the answer into the form."""
		try:
			# Get element node
			element_node = await self.browser_session.get_dom_element_by_index(question.element_index)
			if not element_node:
				return FillResult(
					success=False,
					error=f'Element with index {question.element_index} not found',
					element_index=question.element_index,
				)

			# Use appropriate event based on question type
			if question.question_type.value in ['SINGLE_SELECT', 'MULTI_SELECT']:
				# For selects, use click event to open dropdown, then select option
				# TODO: Implement select dropdown handling
				event = self.browser_session.event_bus.dispatch(ClickElementEvent(node=element_node))
				await event
				await event.event_result(raise_if_any=True, raise_if_none=False)
			else:
				# For text inputs, use TypeTextEvent
				event = self.browser_session.event_bus.dispatch(
					TypeTextEvent(node=element_node, text=answer.answer_value)
				)
				await event
				await event.event_result(raise_if_any=True, raise_if_none=False)

			return FillResult(success=True, element_index=question.element_index)
		except Exception as e:
			self.logger.error(f'Failed to fill answer: {e}')
			return FillResult(
				success=False,
				error=str(e),
				element_index=question.element_index,
			)

	async def navigate_to_next_page(self) -> NavigationResult:
		"""Attempt to navigate to next page."""
		try:
			# Look for "Save and Continue", "Next", "Continue" buttons
			browser_state = await self.browser_session.get_browser_state_summary()
			current_url = browser_state.url

			# Find navigation button
			# TODO: Use LLM or heuristics to find the button
			# For now, stub implementation
			self.logger.info('Attempting to navigate to next page (stub)')

			# Wait a bit to see if page changes
			await asyncio.sleep(1.0)
			new_browser_state = await self.browser_session.get_browser_state_summary()
			page_changed = new_browser_state.url != current_url

			return NavigationResult(success=True, page_changed=page_changed)
		except Exception as e:
			self.logger.error(f'Failed to navigate to next page: {e}')
			return NavigationResult(success=False, errors=[str(e)])

	async def resolve_navigation_errors(self, errors: List[str]) -> None:
		"""Resolve errors preventing navigation."""
		self.logger.warning(f'Navigation errors detected: {errors}')
		# TODO: Implement error resolution logic
		# - Check for validation errors
		# - Identify missing required fields
		# - Fill missing fields
		# - Retry navigation

	async def handle_fill_error(
		self, question: ApplicationQuestion, answer: QuestionAnswer, error: str
	) -> None:
		"""Handle fill error with retry logic."""
		retry_count = self.state.increment_failed_question(question.question_text)

		if retry_count > 3:
			self.logger.error(
				f'Question "{question.question_text}" failed {retry_count} times, giving up'
			)
			return

		self.logger.warning(
			f'Fill error for question "{question.question_text}": {error}. Retry count: {retry_count}'
		)

		# TODO: Implement retry logic
		# - Refresh DOM
		# - Re-identify question
		# - Retry fill

	# ========== Navigation Helper Methods ==========

	async def _prepare_navigation_context(self) -> BrowserStateSummary:
		"""Prepare context for navigation: get browser state and wait for stability."""
		self.logger.debug('🌐 Getting browser state for navigation...')
		
		# Get browser state
		browser_state = await self.browser_session.get_browser_state_summary(
			include_screenshot=True,
		)

		# Wait for page stability
		if self.browser_session._dom_watchdog:
			self.logger.debug('🔍 Waiting for page stability...')
			await self.browser_session._dom_watchdog.wait_for_page_stability()

		return browser_state

	async def _plan_navigation(self, browser_state: BrowserStateSummary) -> Optional[str]:
		"""Plan navigation steps using LLM."""
		self.logger.debug('📋 Planning navigation steps...')

		# Build planning prompt (instructions only)
		prompt_text = self.prompt_loader.build_navigate_to_application_prompt()
		
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
		
		# Format browser state using centralized method
		browser_state_text = self._format_browser_state_message(browser_state)
		
		# Combine into ONE message
		combined_content = f"{planning_instructions}\n\n<browser_state>\n{browser_state_text}\n</browser_state>"
		messages = [UserMessage(content=combined_content)]

		try:
			response = await self.llm.ainvoke(messages, output_format=PlanOutput)
			plan_output = response.completion
			self.logger.info(f'📋 Navigation Plan: {plan_output.plan}')
			return plan_output.plan
		except Exception as e:
			self.logger.warning(f'Planning failed: {e}. Continuing without plan.')
			return None

	async def _get_navigation_actions(
		self, browser_state: BrowserStateSummary, plan: Optional[str]
	) -> List[ActionModel]:
		"""Get navigation actions from LLM based on plan."""
		self.logger.debug('🤖 Getting navigation actions from LLM...')

		# Get available actions for this page
		page_filtered_actions = self.tools.registry.get_prompt_description(browser_state.url)
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

		# Format browser state using centralized method
		browser_state_text = self._format_browser_state_message(browser_state)
		
		# Combine into ONE message
		combined_content = f"{action_prompt_content}\n\n<browser_state>\n{browser_state_text}\n</browser_state>"
		messages = [UserMessage(content=combined_content)]

		# Create AgentOutput type with available actions
		# Get the action model for the current page (filters actions by URL)
		ActionModel = self.tools.registry.create_action_model(page_url=browser_state.url)
		AgentOutputType = AgentOutput.type_with_custom_actions_no_thinking(ActionModel)

		try:
			response = await self.llm.ainvoke(messages, output_format=AgentOutputType)
			agent_output = response.completion
			actions = agent_output.action
			self.logger.info(f'⚡ Selected {len(actions)} navigation action(s)')
			return actions
		except Exception as e:
			self.logger.error(f'Failed to get navigation actions: {e}')
			raise

	async def _execute_navigation_actions(self, actions: List[ActionModel]) -> List[ActionResult]:
		"""Execute navigation actions."""
		self.logger.debug(f'⚡ Executing {len(actions)} navigation action(s)...')

		results = []
		for i, action in enumerate(actions):
			try:
				self.logger.debug(f'Executing action {i + 1}/{len(actions)}: {action.model_dump(exclude_unset=True)}')
				
				result = await self.tools.act(
					action=action,
					browser_session=self.browser_session,
					page_extraction_llm=None,
					sensitive_data=None,
					available_file_paths=None,
					file_system=None,
				)

				results.append(result)

				if result.error:
					self.logger.warning(f'⚠️ Action {i + 1} failed: {result.error}')
				elif result.is_done:
					self.logger.info(f'✅ Action {i + 1} completed task')
					break

				# Wait between actions
				if i < len(actions) - 1:
					await asyncio.sleep(0.5)

			except Exception as e:
				self.logger.error(f'❌ Action {i + 1} raised exception: {e}')
				results.append(ActionResult(error=str(e)))

		return results

	async def _check_navigation_complete(self) -> PageType:
		"""Check if navigation is complete by re-classifying the page."""
		self.logger.debug('🔍 Checking if navigation to application page is complete...')
		return await self.classify_page()

