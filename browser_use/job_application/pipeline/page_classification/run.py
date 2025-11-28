"""Page classification step implementation."""

import importlib.resources
import logging
from typing import TYPE_CHECKING

from browser_use.browser import BrowserSession
from browser_use.browser.views import BrowserStateSummary
from browser_use.job_application.pipeline.page_classification.schema import PageClassificationOutput
from browser_use.job_application.pipeline.shared.enums import PageType
from browser_use.job_application.pipeline.shared.utils import format_browser_state_message
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import UserMessage
from browser_use.observability import observe_debug

if TYPE_CHECKING:
	pass

logger = logging.getLogger(__name__)


def _load_prompt() -> str:
	"""Load the page classification prompt template."""
	try:
		with importlib.resources.files('browser_use.job_application.pipeline.page_classification').joinpath(
			'prompt.md'
		).open('r', encoding='utf-8') as f:
			return f.read()
	except Exception as e:
		raise RuntimeError(f'Failed to load page classification prompt: {e}')


@observe_debug(ignore_input=True, name='classify_page')
async def classify_page(
	browser_session: BrowserSession,
	llm: BaseChatModel,
) -> PageType:
	"""Classify the current page type using LLM.
	
	Args:
		browser_session: Browser session for getting page state
		llm: LLM for classification
		
	Returns:
		The classified page type
	"""
	browser_state = await browser_session.get_browser_state_summary()

	# Load prompt template
	prompt_text = _load_prompt()
	
	# Format browser state using shared utility
	browser_state_text = format_browser_state_message(browser_state)
	
	# Combine into ONE message
	combined_content = f"{prompt_text}\n\n<browser_state>\n{browser_state_text}\n</browser_state>"
	messages = [UserMessage(content=combined_content)]

	# Call LLM with structured output
	response = await llm.ainvoke(messages, output_format=PageClassificationOutput)
	classification = response.completion

	logger.info(
		f'Page classified as: {classification.page_type.value} (confidence: {classification.confidence:.2f})'
	)
	input('[DEBUG] Press Enter to continue after page classification...')
	return classification.page_type

