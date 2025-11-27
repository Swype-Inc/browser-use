"""Prompt loader for job application pipeline."""

import importlib.resources
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from browser_use.browser.views import BrowserStateSummary
	from browser_use.job_application.pipeline.state import PipelineState
	from browser_use.job_application.pipeline.views import ApplicationSection

logger = logging.getLogger(__name__)


class PipelinePromptLoader:
	"""Loader for pipeline prompt templates."""

	def __init__(self):
		"""Initialize prompt loader."""
		self._templates: dict[str, str] = {}

	def _load_template(self, template_name: str) -> str:
		"""Load a prompt template from markdown file."""
		if template_name in self._templates:
			return self._templates[template_name]

		try:
			with importlib.resources.files('browser_use.job_application.pipeline').joinpath(
				f'{template_name}.md'
			).open('r', encoding='utf-8') as f:
				template = f.read()
				self._templates[template_name] = template
				return template
		except Exception as e:
			raise RuntimeError(f'Failed to load prompt template {template_name}: {e}')

	def build_page_classification_prompt(self) -> str:
		"""Build page classification prompt (instructions only, no browser state)."""
		return self._load_template('page_classification_prompt')

	def build_navigate_to_application_prompt(self) -> str:
		"""Build navigation to application prompt (instructions only)."""
		return self._load_template('navigate_to_application_prompt')

	def build_section_identification_prompt(self, pipeline_state: 'PipelineState') -> str:
		"""Build section identification prompt (instructions only)."""
		template = self._load_template('section_identification_prompt')

		# Format completed sections
		completed_sections = pipeline_state.get_completed_sections()
		completed_sections_str = ', '.join(completed_sections) if completed_sections else 'None'

		return template.format(completed_sections=completed_sections_str)

	def build_question_extraction_prompt(self, section: 'ApplicationSection') -> str:
		"""Build question extraction prompt (instructions only)."""
		template = self._load_template('question_extraction_prompt')

		section_type = section.type.value
		section_name = section.name or 'Unnamed'
		section_element_indices = ', '.join(map(str, section.element_indices)) if section.element_indices else 'N/A'

		return template.format(
			section_type=section_type,
			section_name=section_name,
			section_element_indices=section_element_indices,
		)

