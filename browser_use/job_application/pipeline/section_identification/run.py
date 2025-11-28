"""Section identification step implementation."""

import importlib.resources
import logging
from typing import TYPE_CHECKING, Optional

from browser_use.browser import BrowserSession
from browser_use.browser.views import BrowserStateSummary
from browser_use.job_application.pipeline.section_identification.schema import SectionIdentificationOutput
from browser_use.job_application.pipeline.shared.enums import SectionType
from browser_use.job_application.pipeline.shared.schemas import ApplicationSection
from browser_use.job_application.pipeline.shared.utils import format_browser_state_message
from browser_use.job_application.pipeline.state import PipelineState
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import UserMessage
from browser_use.observability import observe_debug

if TYPE_CHECKING:
	pass

logger = logging.getLogger(__name__)


def _load_prompt() -> str:
	"""Load the section identification prompt template."""
	try:
		with importlib.resources.files('browser_use.job_application.pipeline.section_identification').joinpath(
			'prompt.md'
		).open('r', encoding='utf-8') as f:
			return f.read()
	except Exception as e:
		raise RuntimeError(f'Failed to load section identification prompt: {e}')


def _build_prompt(pipeline_state: PipelineState) -> str:
	"""Build the section identification prompt with formatted previous sections.
	
	Args:
		pipeline_state: The pipeline state containing previous sections
		
	Returns:
		Formatted prompt string
	"""
	template = _load_prompt()

	# Format previous sections with their questions nested
	previous_sections_lines = []
	for section in pipeline_state.sections:
		section_name = section.name or section.type.value
		status = 'COMPLETE' if section.is_complete else 'IN PROGRESS'
		previous_sections_lines.append(
			f"Section {section.section_index}: {section_name} ({section.type.value}) - {status}"
		)
		
		# Add questions nested under the section
		if section.questions:
			for question in section.questions:
				previous_sections_lines.append(f"  - {question.question_text}")
		else:
			previous_sections_lines.append("  - (no questions identified yet)")
	
	previous_sections_str = '\n'.join(previous_sections_lines) if previous_sections_lines else 'None (no sections identified yet)'

	return template.format(previous_sections=previous_sections_str)


@observe_debug(ignore_input=True, name='identify_next_section')
async def identify_next_section(
	browser_session: BrowserSession,
	llm: BaseChatModel,
	pipeline_state: PipelineState,
) -> tuple[Optional[ApplicationSection], list[str]]:
	"""Identify the next section that needs to be filled, including question texts.
	
	Args:
		browser_session: Browser session for getting page state
		llm: LLM for section identification
		pipeline_state: Current pipeline state with previous sections
		
	Returns:
		Tuple of (the next section to fill or None if no more sections, list of question texts)
	"""
	browser_state = await browser_session.get_browser_state_summary(include_all_form_fields=True)

	# Build prompt with formatted previous sections
	prompt_text = _build_prompt(pipeline_state)
	
	# Format browser state using shared utility
	browser_state_text = format_browser_state_message(browser_state)
	
	# Combine into ONE message
	combined_content = f"{prompt_text}\n\n<browser_state>\n{browser_state_text}\n</browser_state>"
	messages = [UserMessage(content=combined_content)]

	# Call LLM with structured output
	try:
		response = await llm.ainvoke(messages, output_format=SectionIdentificationOutput)
		section_output = response.completion
		
		# Check if LLM indicates no more sections
		if section_output.no_more_sections:
			logger.info('No more sections to identify on this page')
			return None, []
		
		# Validate that section_type is provided when no_more_sections is False
		if section_output.section_type is None:
			logger.warning('Section identification returned no section_type but no_more_sections is False')
			return None, []
		
		# Convert to ApplicationSection (without question_texts) for return type
		section = ApplicationSection(
			section_type=section_output.section_type,
			name=section_output.name,
			section_index=section_output.section_index,
			is_complete=section_output.is_complete,
			has_errors=section_output.has_errors,
			element_indices=section_output.element_indices,
		)
		
		input(f'[DEBUG] Press Enter to continue after section identification: {section.name or section.section_type.value}...')
		return section, section_output.question_texts
	except Exception as e:
		logger.error(f'Failed to identify section: {e}')
		# Return None if all sections are complete or error occurred
		return None, []

