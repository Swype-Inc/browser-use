"""Question filling step implementation."""

import asyncio
import importlib.resources
import logging
from typing import TYPE_CHECKING, List, Optional

from browser_use.browser import BrowserSession
from browser_use.browser.views import BrowserStateSummary
from browser_use.job_application.pipeline.question_extraction.schema import ApplicationQuestion
from browser_use.job_application.pipeline.question_filling.schema import FillResult, QuestionFillAssessment
from browser_use.job_application.pipeline.shared.schemas import QuestionAnswer
from browser_use.job_application.pipeline.shared.utils import format_browser_state_message
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import UserMessage
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.service import Tools
from browser_use.agent.views import AgentOutput, ActionResult

if TYPE_CHECKING:
	pass

logger = logging.getLogger(__name__)


def _load_filling_prompt() -> str:
	"""Load the question filling prompt template."""
	try:
		with importlib.resources.files('browser_use.job_application.pipeline.question_filling').joinpath(
			'prompt.md'
		).open('r', encoding='utf-8') as f:
			return f.read()
	except Exception as e:
		raise RuntimeError(f'Failed to load question filling prompt: {e}')


def _load_assessment_prompt() -> str:
	"""Load the question fill assessment prompt template."""
	try:
		with importlib.resources.files('browser_use.job_application.pipeline.question_filling').joinpath(
			'assessment_prompt.md'
		).open('r', encoding='utf-8') as f:
			return f.read()
	except Exception as e:
		raise RuntimeError(f'Failed to load question fill assessment prompt: {e}')


def _build_filling_prompt(question: ApplicationQuestion, answer: QuestionAnswer) -> str:
	"""Build the question filling prompt.
	
	Args:
		question: The question to fill
		answer: The answer to fill with
		
	Returns:
		Formatted prompt string
	"""
	template = _load_filling_prompt()
	
	# Format options if available
	if question.options:
		options_str = '\n'.join(f'- {opt.text}' + (f' (value: {opt.value})' if opt.value else '') for opt in question.options)
	else:
		options_str = 'None'
	
	return template.format(
		question_text=question.question_text,
		answer_value=answer.answer_value,
		question_type=question.question_type.value,
		element_index=question.element_index,
		is_required="Yes" if question.is_required else "No",
		options=options_str,
	)


def _build_assessment_prompt(question: ApplicationQuestion, answer: QuestionAnswer) -> str:
	"""Build the question fill assessment prompt.
	
	Args:
		question: The question to check
		answer: The expected answer
		
	Returns:
		Formatted prompt string
	"""
	template = _load_assessment_prompt()
	
	return template.format(
		question_text=question.question_text,
		answer_value=answer.answer_value,
		question_type=question.question_type.value,
		element_index=question.element_index,
	)


async def get_question_fill_actions(
	browser_session: BrowserSession,
	llm: BaseChatModel,
	tools: Tools,
	browser_state: BrowserStateSummary,
	question: ApplicationQuestion,
	answer: QuestionAnswer,
) -> List[ActionModel]:
	"""Get actions for filling a question using LLM.
	
	Args:
		browser_session: Browser session
		llm: LLM for action selection
		tools: Tools registry for getting available actions
		browser_state: Current browser state
		question: The question to fill
		answer: The answer to fill with
		
	Returns:
		List of actions to execute
	"""
	logger.debug(f'🤖 Getting fill actions for question: "{question.question_text}"...')

	# Get available actions for this page
	page_filtered_actions = tools.registry.get_prompt_description(browser_state.url)
	actions_description = page_filtered_actions if page_filtered_actions else 'Available actions: click, input, upload_file, select_dropdown, etc.'

	# Build action selection prompt using template
	prompt_text = _build_filling_prompt(question, answer)
	
	action_prompt_content = f"""{prompt_text}

<available_actions>
{actions_description}
</available_actions>

Return your selected actions."""

	# Format browser state using shared utility
	browser_state_text = format_browser_state_message(browser_state)
	
	# Combine into ONE message
	combined_content = f"{action_prompt_content}\n\n<browser_state>\n{browser_state_text}\n</browser_state>"
	messages = [UserMessage(content=combined_content)]

	# Create AgentOutput type with available actions
	ActionModel = tools.registry.create_action_model(page_url=browser_state.url)
	AgentOutputType = AgentOutput.type_with_custom_actions_no_thinking(ActionModel)

	try:
		response = await llm.ainvoke(messages, output_format=AgentOutputType)
		agent_output = response.completion
		actions = agent_output.action
		logger.info(f'⚡ Selected {len(actions)} action(s) for question fill')
		input(f'[DEBUG] Press Enter to continue after question fill action selection ({len(actions)} actions) for: "{question.question_text[:50]}..."...')
		return actions
	except Exception as e:
		logger.error(f'Failed to get question fill actions: {e}')
		raise


async def is_question_filled(
	browser_session: BrowserSession,
	llm: BaseChatModel,
	browser_state: BrowserStateSummary,
	question: ApplicationQuestion,
	answer: QuestionAnswer,
) -> bool:
	"""Check if the question is filled correctly using LLM assessment.
	
	Args:
		browser_session: Browser session
		llm: LLM for assessment
		browser_state: Current browser state
		question: The question to check
		answer: The expected answer
		
	Returns:
		True if filled correctly, False otherwise
	"""
	logger.debug(f'🔍 Checking if question is filled: "{question.question_text}"...')
	
	# Build assessment prompt using template
	prompt_text = _build_assessment_prompt(question, answer)
	
	# Format browser state
	browser_state_text = format_browser_state_message(browser_state)
	
	# Combine prompt and browser state
	assessment_content = f"{prompt_text}\n\n<browser_state>\n{browser_state_text}\n</browser_state>"
	messages = [UserMessage(content=assessment_content)]
	
	try:
		response = await llm.ainvoke(messages, output_format=QuestionFillAssessment)
		assessment = response.completion
		logger.debug(f'Question fill assessment: {assessment.is_filled} - {assessment.reasoning or "No reasoning provided"}')
		return assessment.is_filled
	except Exception as e:
		logger.warning(f'Failed to assess question fill status: {e}, assuming not filled')
		return False


async def execute_actions(
	browser_session: BrowserSession,
	tools: Tools,
	actions: List[ActionModel],
) -> List[ActionResult]:
	"""Execute a list of actions.
	
	Args:
		browser_session: Browser session
		tools: Tools registry
		actions: List of actions to execute
		
	Returns:
		List of action results
	"""
	logger.debug(f'⚡ Executing {len(actions)} action(s)...')

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


async def fill_answer(
	browser_session: BrowserSession,
	llm: BaseChatModel,
	tools: Tools,
	question: ApplicationQuestion,
	answer: QuestionAnswer,
) -> FillResult:
	"""Fill the answer into the form using LLM-based action selection with retry loop.
	
	Args:
		browser_session: Browser session
		llm: LLM for action selection and assessment
		tools: Tools registry
		question: The question to fill
		answer: The answer to fill with
		
	Returns:
		Result of the fill operation
	"""
	max_attempts = 20
	attempt = 0
	
	try:
		while attempt < max_attempts:
			attempt += 1
			logger.info(f'🔄 Fill attempt {attempt}/{max_attempts} for question: "{question.question_text}"')
			
			# 1. Read browser state
			browser_state = await browser_session.get_browser_state_summary(include_all_form_fields=True)
			
			# 2. Check if already filled
			filled = await is_question_filled(browser_session, llm, browser_state, question, answer)
			if filled:
				logger.info(f'✅ Question already filled correctly: "{question.question_text}"')
				return FillResult(success=True, element_index=question.element_index)
			
			# 3. Get actions from LLM
			actions = await get_question_fill_actions(browser_session, llm, tools, browser_state, question, answer)
			
			# 4. Execute actions
			results = await execute_actions(browser_session, tools, actions)
			
			# 5. Check if any action failed
			if results and any(r.error for r in results):
				errors = [r.error for r in results if r.error]
				logger.warning(f'⚠️ Actions failed on attempt {attempt}: {", ".join(errors)}')
				if attempt >= max_attempts:
					return FillResult(
						success=False,
						error=f"Failed to fill question after {max_attempts} attempts: {', '.join(errors)}",
						element_index=question.element_index,
					)
				# Wait for DOM stability before retry
				await browser_session._dom_watchdog.wait_for_page_stability()
				continue
			
			# 6. Wait for page to stabilize after actions (network + DOM)
			await browser_session._dom_watchdog.wait_for_page_stability()
			
			# 7. Reassess if filled (read browser state again)
			browser_state = await browser_session.get_browser_state_summary(include_all_form_fields=True)
			filled = await is_question_filled(browser_session, llm, browser_state, question, answer)
			
			if filled:
				logger.info(f'✅ Question filled successfully on attempt {attempt}: "{question.question_text}"')
				return FillResult(success=True, element_index=question.element_index)
			else:
				logger.warning(f'⚠️ Question not filled correctly after attempt {attempt}, retrying...')
				if attempt < max_attempts:
					# Wait for DOM stability before next attempt
					await browser_session._dom_watchdog.wait_for_page_stability()
		
		# If we get here, we've exhausted all attempts
		return FillResult(
			success=False,
			error=f"Failed to fill question after {max_attempts} attempts",
			element_index=question.element_index,
		)
	except Exception as e:
		logger.error(f'Failed to fill answer: {e}')
		return FillResult(
			success=False,
			error=str(e),
			element_index=question.element_index,
		)

