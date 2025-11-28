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
from browser_use.llm.messages import UserMessage
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


def _build_prompt(section: ApplicationSection, question_texts: Optional[List[str]] = None) -> str:
	"""Build the question extraction prompt.
	
	Args:
		section: The section to extract questions from
		question_texts: Optional list of question texts identified in section identification step
		
	Returns:
		Formatted prompt string
	"""
	template = _load_prompt()

	section_type = section.section_type.value
	section_name = section.name or 'Unnamed'
	section_element_indices = ', '.join(map(str, section.element_indices)) if section.element_indices else 'N/A'
	
	# Format question texts if provided
	if question_texts:
		question_texts_str = '\n'.join(f'- {text}' for text in question_texts)
	else:
		question_texts_str = 'None (identify questions from the page)'

	return template.format(
		section_type=section_type,
		section_name=section_name,
		section_element_indices=section_element_indices,
		question_texts=question_texts_str,
	)


@observe_debug(ignore_input=True, name='identify_questions')
async def run(
	browser_session: BrowserSession,
	llm: BaseChatModel,
	section: ApplicationSection,
	question_texts: Optional[List[str]] = None,
) -> List[ApplicationQuestion]:
	"""Identify all questions in a section, using cached question texts from section identification.
	
	Args:
		browser_session: Browser session for getting page state
		llm: LLM for question extraction
		section: The section to extract questions from
		question_texts: Optional list of question texts identified in section identification step
		
	Returns:
		List of questions found in the section
	"""
	browser_state = await browser_session.get_browser_state_summary(include_all_form_fields=True)

	# Build prompt with section info and question texts
	prompt_text = _build_prompt(section, question_texts)
	
	# Format browser state using shared utility
	browser_state_text = format_browser_state_message(browser_state)
	
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
		response = await llm.ainvoke(messages, output_format=QuestionsListOutput)
		questions = response.completion.questions
		debug_input(f'[DEBUG] Press Enter to continue after question extraction ({len(questions)} questions found)...')
		return questions
	except Exception as e:
		logger.error(f'Failed to identify questions: {e}')
		return []

