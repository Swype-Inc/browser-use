"""Question extraction step implementation."""

import importlib.resources
import logging
from typing import TYPE_CHECKING, List, Optional

from browser_use.browser import BrowserSession
from browser_use.browser.views import BrowserStateSummary
from browser_use.job_application.pipeline.question_extraction.schema import ApplicationQuestion
from browser_use.job_application.pipeline.shared.schemas import ApplicationSection
from browser_use.job_application.pipeline.shared.utils import debug_input, format_browser_state_message
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import ContentPartImageParam, ContentPartTextParam, ImageURL, UserMessage
from browser_use.observability import observe_debug
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
	pass

logger = logging.getLogger(__name__)


def _load_prompt() -> str:
	"""Load the question extraction prompt template."""
	try:
		with importlib.resources.files('browser_use.job_application.pipeline.question_extraction').joinpath(
			'prompt.md'
		).open('r', encoding='utf-8') as f:
			return f.read()
	except Exception as e:
		raise RuntimeError(f'Failed to load question extraction prompt: {e}')


def _format_filled_questions(filled_questions: List[str]) -> str:
	"""Format list of already filled questions for the prompt.
	
	Args:
		filled_questions: List of question texts that have already been filled
		
	Returns:
		Formatted string
	"""
	if not filled_questions:
		return "None (no questions filled yet in this section)"
	
	return '\n'.join(f'- {text}' for text in filled_questions)


def _build_prompt(
	section: ApplicationSection, 
	question_texts: List[str],
	filled_questions: List[str],
) -> str:
	"""Build the question extraction prompt.
	
	Args:
		section: The section to extract questions from
		question_texts: List of all question texts identified in section identification step
		filled_questions: List of question texts that have already been filled
		
	Returns:
		Formatted prompt string
	"""
	template = _load_prompt()

	section_type = section.section_type.value
	section_name = section.name or 'Unnamed'
	section_element_indices = ', '.join(map(str, section.element_indices)) if section.element_indices else 'N/A'
	
	# Format question texts
	question_texts_str = '\n'.join(f'- {text}' for text in question_texts)
	
	# Format filled questions
	filled_questions_str = _format_filled_questions(filled_questions)

	return template.format(
		section_type=section_type,
		section_name=section_name,
		section_element_indices=section_element_indices,
		question_texts=question_texts_str,
		filled_questions=filled_questions_str,
	)


@observe_debug(ignore_input=True, name='identify_next_question')
async def run(
	browser_session: BrowserSession,
	llm: BaseChatModel,
	section: ApplicationSection,
	question_texts: List[str],
	filled_questions: List[str],
) -> Optional[ApplicationQuestion]:
	"""Identify the next question in a section that hasn't been filled yet.
	
	Args:
		browser_session: Browser session for getting page state
		llm: LLM for question extraction
		section: The section to extract questions from
		question_texts: List of all question texts identified in section identification step
		filled_questions: List of question texts that have already been filled in this section
		
	Returns:
		The next question to fill, or None if all questions in the section are filled
	"""
	browser_state = await browser_session.get_browser_state_summary(include_all_form_fields=True, include_screenshot=True)

	# Build prompt with section info, question texts, and filled questions
	prompt_text = _build_prompt(section, question_texts, filled_questions)
	
	# Format browser state using shared utility
	browser_state_text = format_browser_state_message(browser_state)
	
	# Combine into ONE message
	combined_content = f"{prompt_text}\n\n<browser_state>\n{browser_state_text}\n</browser_state>"
	
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

	# Call LLM with structured output - return single question or None
	class QuestionOutput(BaseModel):
		"""Output model for question extraction."""

		model_config = ConfigDict(arbitrary_types_allowed=True, extra='forbid')

		question: Optional[ApplicationQuestion] = Field(
			None, description='The next question to fill in this section, or None if all questions are filled'
		)
		no_more_questions: bool = Field(
			default=False, description='Set to True if there are no more questions to fill in this section'
		)
		rationale: str = Field(
			description='Explanation of why this question was selected, what element_index was chosen and why, and how it relates to the question text in the DOM. Required even when no_more_questions=True to explain why no question was selected.'
		)

	try:
		response = await llm.ainvoke(messages, output_format=QuestionOutput)
		output = response.completion
		
		if output.no_more_questions or output.question is None:
			logger.info('No more questions to extract in this section')
			return None
		
		debug_input(f'[DEBUG] Press Enter to continue after question extraction: "{output.question.question_text}" (element_index: {output.question.element_index})...')
		return output.question
	except Exception as e:
		logger.error(f'Failed to identify next question: {e}')
		return None

