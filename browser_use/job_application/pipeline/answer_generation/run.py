"""Answer generation step implementation."""

import importlib.resources
import json
import logging
from typing import TYPE_CHECKING, Optional

from browser_use.job_application.pipeline.answer_generation.schema import AnswerGenerationOutput
from browser_use.job_application.pipeline.question_extraction.schema import ApplicationQuestion
from browser_use.job_application.pipeline.shared.schemas import QuestionAnswer
from browser_use.job_application.pipeline.shared.utils import debug_input
from browser_use.job_application.websocket.client import AnswerGeneratorClient
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import UserMessage

if TYPE_CHECKING:
	pass

logger = logging.getLogger(__name__)


def _load_prompt() -> str:
	"""Load the answer generation prompt template."""
	try:
		with importlib.resources.files('browser_use.job_application.pipeline.answer_generation').joinpath(
			'prompt.md'
		).open('r', encoding='utf-8') as f:
			return f.read()
	except Exception as e:
		raise RuntimeError(f'Failed to load answer generation prompt: {e}')


def _build_prompt(question: ApplicationQuestion, user_profile: dict) -> str:
	"""Build the answer generation prompt.
	
	Args:
		question: The question to generate an answer for
		user_profile: User profile data dictionary
		
	Returns:
		Formatted prompt string
	"""
	template = _load_prompt()
	
	# Format user profile information
	user_profile_str = json.dumps(user_profile, indent=2) if user_profile else "{}"
	
	# Format question details
	question_type = question.question_type.value
	is_required = "Yes" if question.is_required else "No"
	
	# Format options if available
	if question.options:
		options_str = '\n'.join(f'- {opt.text}' + (f' (value: {opt.value})' if opt.value else '') for opt in question.options)
	else:
		options_str = 'None'
	
	# Format validation pattern if available
	validation_pattern = question.validation_pattern or 'None'
	
	return template.format(
		question_text=question.question_text,
		question_type=question_type,
		is_required=is_required,
		options=options_str,
		validation_pattern=validation_pattern,
		user_profile=user_profile_str,
	)


async def run(
	question: ApplicationQuestion,
	llm: BaseChatModel,
	user_profile: dict,
	answer_generator_client: Optional[AnswerGeneratorClient] = None,
) -> QuestionAnswer:
	"""Generate answer using LLM based on user profile and question.
	
	Args:
		question: The question to generate an answer for
		llm: LLM for answer generation
		user_profile: User profile data dictionary
		answer_generator_client: Optional websocket client for answer generation
		
	Returns:
		Generated answer
	"""
	# Try websocket first if available
	if answer_generator_client:
		try:
			return await answer_generator_client.generate_answer(question)
		except NotImplementedError:
			logger.warning('Websocket answer generation not available, using LLM')
		except Exception as e:
			logger.error(f'Failed to generate answer via websocket: {e}')

	# Use LLM to generate answer
	try:
		# Build prompt with user profile and question
		prompt_text = _build_prompt(question, user_profile)
		
		messages = [UserMessage(content=prompt_text)]
		
		# Use structured output for answer generation
		response = await llm.ainvoke(messages, output_format=AnswerGenerationOutput)
		answer_output = response.completion
		
		debug_input(f'[DEBUG] Press Enter to continue after answer generation for: "{question.question_text[:50]}..."...')
		
		# Convert to QuestionAnswer
		return QuestionAnswer(
			question_text=question.question_text,
			answer_value=answer_output.answer_value,
			answer_type=question.question_type,
			element_index=question.element_index,
			filled_successfully=True,
		)
	except Exception as e:
		logger.error(f'Failed to generate answer via LLM: {e}')
		# Fallback: return placeholder answer
		return QuestionAnswer(
			question_text=question.question_text,
			answer_value='PLACEHOLDER_ANSWER',
			answer_type=question.question_type,
			element_index=question.element_index,
			filled_successfully=False,
			error_message=f'Answer generation failed: {str(e)}',
		)

