"""Question filling step implementation."""

import asyncio
import importlib.resources
import logging
from typing import TYPE_CHECKING, List, Optional

from browser_use.browser import BrowserSession
from browser_use.browser.views import BrowserStateSummary
from browser_use.job_application.pipeline.question_extraction.schema import ApplicationQuestion
from browser_use.job_application.pipeline.question_filling.schema import FillResult
from browser_use.job_application.pipeline.shared.schemas import QuestionAnswer
from browser_use.job_application.pipeline.shared.utils import debug_input, format_browser_state_message
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import ContentPartImageParam, ContentPartTextParam, ImageURL, UserMessage
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.service import Tools
from browser_use.agent.views import AgentOutput, ActionResult
from pydantic import Field, create_model

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


def _format_action_history(action_history: List[dict]) -> str:
	"""Format action history for the prompt.
	
	Args:
		action_history: List of dicts with 'step', 'actions', 'results', 'reasoning', 'is_filled'
		
	Returns:
		Formatted history string
	"""
	if not action_history:
		return ""
	
	lines = ["<action_history>"]
	for entry in action_history:
		step = entry.get('step', 0)
		actions = entry.get('actions', [])
		results = entry.get('results', [])
		reasoning = entry.get('reasoning')
		is_filled = entry.get('is_filled', False)
		
		lines.append(f"<step_{step}>:")
		lines.append(f"  State: Question is {'filled' if is_filled else 'not filled yet'}")
		if reasoning:
			lines.append(f"  Reasoning: {reasoning}")
		
		if actions:
			lines.append(f"  Actions:")
			for i, action in enumerate(actions):
				# Format action nicely
				action_dict = action.model_dump(exclude_unset=True) if hasattr(action, 'model_dump') else {}
				action_type = list(action_dict.keys())[0] if action_dict else "unknown"
				action_params = action_dict.get(action_type, {})
				
				# Get corresponding result and group it with the action
				result_text = ""
				if i < len(results):
					result = results[i]
					if hasattr(result, 'error') and result.error:
						result_text = f" → FAILED: {result.error}"
					elif hasattr(result, 'extracted_content') and result.extracted_content:
						content_preview = result.extracted_content[:100].replace('\n', ' ')
						result_text = f" → SUCCESS: {content_preview}..."
					else:
						result_text = " → EXECUTED"
				
				lines.append(f"    - {action_type}({action_params}){result_text}")
		
		lines.append(f"</step_{step}>")
		lines.append("")
	
	lines.append("</action_history>")
	return "\n".join(lines)


async def get_question_fill_output(
	browser_session: BrowserSession,
	llm: BaseChatModel,
	tools: Tools,
	browser_state: BrowserStateSummary,
	question: ApplicationQuestion,
	answer: QuestionAnswer,
	action_history: Optional[List[dict]] = None,
) -> tuple[bool, List[ActionModel], Optional[str]]:
	"""Get assessment and actions for filling a question using LLM in a single call.
	
	Args:
		browser_session: Browser session
		llm: LLM for assessment and action selection
		tools: Tools registry for getting available actions
		browser_state: Current browser state
		question: The question to fill
		answer: The answer to fill with
		action_history: Optional list of previous attempts with actions and results
		
	Returns:
		Tuple of (is_filled, actions, reasoning)
	"""
	logger.debug(f'🤖 Getting fill assessment and actions for question: "{question.question_text}"...')

	# Get available actions for this page
	page_filtered_actions = tools.registry.get_prompt_description(browser_state.url)
	actions_description = page_filtered_actions if page_filtered_actions else 'Available actions: click, input, upload_file, select_dropdown, etc.'

	# Build combined prompt using template
	prompt_text = _build_filling_prompt(question, answer)
	
	# Format action history if provided
	history_text = ""
	if action_history:
		history_text = f"\n\n{_format_action_history(action_history)}\n"
	
	action_prompt_content = f"""{prompt_text}{history_text}

<available_actions>
{actions_description}
</available_actions>

Return your assessment (is_filled, reasoning) and selected actions."""

	# Format browser state using shared utility
	browser_state_text = format_browser_state_message(browser_state)
	
	# Combine into ONE message with screenshot
	combined_content = f"{action_prompt_content}\n\n<browser_state>\n{browser_state_text}\n</browser_state>"
	
	# Create message with screenshot if available
	if browser_state.screenshot:
		messages = [UserMessage(
			content=[
				ContentPartTextParam(type="text", text=combined_content),
				ContentPartImageParam(
					type="image_url",
					image_url=ImageURL(url=f'data:image/png;base64,{browser_state.screenshot}')
				)
			]
		)]
	else:
		messages = [UserMessage(content=combined_content)]

	# Create combined output model
	ActionModel = tools.registry.create_action_model(page_url=browser_state.url)
	
	# Create a model that extends AgentOutput with is_filled and reasoning
	
	class QuestionFillAgentOutput(AgentOutput):
		is_filled: bool = Field(description="Whether the question is already filled correctly. Check the screenshot and DOM to verify.")
		reasoning: Optional[str] = Field(None, description="Brief explanation of why the question is or isn't filled (if not filled, explain what's missing)")
		
		@classmethod
		def model_json_schema(cls, **kwargs):
			schema = super().model_json_schema(**kwargs)
			# Remove thinking field
			if 'thinking' in schema.get('properties', {}):
				del schema['properties']['thinking']
			# Make action optional (can be empty if already filled)
			if 'required' in schema:
				schema['required'] = [f for f in schema['required'] if f != 'action']
			return schema
	
	CombinedOutputType = create_model(
		'QuestionFillAgentOutput',
		__base__=QuestionFillAgentOutput,
		action=(
			list[ActionModel],
			Field(
				default_factory=list,
				description='List of actions to execute (empty if already filled)',
				json_schema_extra={'min_items': 0}
			),
		),
		__module__=QuestionFillAgentOutput.__module__,
	)

	try:
		response = await llm.ainvoke(messages, output_format=CombinedOutputType)
		output = response.completion
		is_filled = output.is_filled
		actions = output.action if output.action else []
		reasoning = output.reasoning
		
		logger.info(f'📊 Assessment: is_filled={is_filled}, actions={len(actions)}')
		if reasoning:
			logger.debug(f'💭 Reasoning: {reasoning}')
		
		debug_input(f'[DEBUG] Press Enter to continue after question fill assessment and action selection (filled={is_filled}, {len(actions)} actions) for: "{question.question_text[:50]}..."...')
		return is_filled, actions, reasoning
	except Exception as e:
		logger.error(f'Failed to get question fill output: {e}')
		raise


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
	logger.info(f'⚡ Executing {len(actions)} action(s)...')

	results = []
	for i, action in enumerate(actions):
		try:
			logger.info(f'Executing action {i + 1}/{len(actions)}: {action.model_dump(exclude_unset=True)}')
			
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


async def run(
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
	step = 0
	action_history: List[dict] = []  # Track history of steps
	
	try:
		while step < max_attempts:
			step += 1
			logger.info(f'🔄 Fill step {step}/{max_attempts} for question: "{question.question_text}"')
			
			# 1. Read browser state
			browser_state = await browser_session.get_browser_state_summary(
				include_all_form_fields=True,
				include_screenshot=True
			)
			
			# 2. Get assessment and actions in one LLM call (with history)
			is_filled, actions, reasoning = await get_question_fill_output(
				browser_session, llm, tools, browser_state, question, answer, action_history
			)
			
			# 3. If already filled AND no actions needed, return success
			# Note: If actions are provided even when is_filled=True (e.g., closing dropdown), we must execute them and reassess
			if is_filled and not actions:
				logger.info(f'✅ Question already filled correctly: "{question.question_text}"')
				if reasoning:
					logger.debug(f'💭 Assessment reasoning: {reasoning}')
				return FillResult(success=True, element_index=question.element_index)
			
			# 4. If no actions provided but not filled, log warning and retry
			if not actions:
				logger.warning(f'⚠️ No actions provided but question not filled. Reasoning: {reasoning or "None provided"}. Retrying...')
				# Add to history
				action_history.append({
					'step': step,
					'actions': [],
					'results': [],
					'reasoning': reasoning,
					'is_filled': False,
				})
				if step < max_attempts:
					await browser_session._dom_watchdog.wait_for_page_stability()
					continue
				else:
					return FillResult(
						success=False,
						error=f"Failed to fill question: No actions provided after {max_attempts} attempts",
						element_index=question.element_index,
					)
			
			# 5. Execute actions
			results = await execute_actions(browser_session, tools, actions)
			
			# 6. Check if any action failed
			if results and any(r.error for r in results):
				errors = [r.error for r in results if r.error]
				logger.warning(f'⚠️ Actions failed on step {step}: {", ".join(errors)}')
				# Add to history
				action_history.append({
					'step': step,
					'actions': actions,
					'results': results,
					'reasoning': reasoning,
					'is_filled': False,
				})
				if step >= max_attempts:
					return FillResult(
						success=False,
						error=f"Failed to fill question after {max_attempts} attempts: {', '.join(errors)}",
						element_index=question.element_index,
					)
				# Wait for DOM stability before retry
				await browser_session._dom_watchdog.wait_for_page_stability()
				continue
			
			# 7. Wait for page to stabilize after actions (network + DOM)
			await browser_session._dom_watchdog.wait_for_page_stability()
			
			# 8. Reassess if filled (read browser state again and check)
			browser_state = await browser_session.get_browser_state_summary(
				include_all_form_fields=True,
				include_screenshot=True
			)
			is_filled, _, reasoning = await get_question_fill_output(
				browser_session, llm, tools, browser_state, question, answer, action_history
			)
			
			# Add this step to history
			action_history.append({
				'step': step,
				'actions': actions,
				'results': results,
				'reasoning': reasoning,
				'is_filled': is_filled,
			})
			
			if is_filled:
				logger.info(f'✅ Question filled successfully on step {step}: "{question.question_text}"')
				if reasoning:
					logger.debug(f'💭 Assessment reasoning: {reasoning}')
				return FillResult(success=True, element_index=question.element_index)
			else:
				logger.warning(f'⚠️ Question not filled correctly after step {step}, retrying...')
				if reasoning:
					logger.debug(f'💭 Assessment reasoning: {reasoning}')
				if step < max_attempts:
					# Wait for DOM stability before next step
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

