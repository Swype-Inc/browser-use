"""Prompt loader for job application pipeline."""

import importlib.resources
import logging
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
	from browser_use.browser.views import BrowserStateSummary
	from browser_use.job_application.pipeline.state import PipelineState
	from browser_use.job_application.pipeline.views import ApplicationSection, ApplicationQuestion

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

	def build_question_extraction_prompt(self, section: 'ApplicationSection', question_texts: Optional[List[str]] = None) -> str:
		"""Build question extraction prompt (instructions only).
		
		Args:
			section: The section to extract questions from
			question_texts: Optional list of question texts identified in section identification step
		"""
		template = self._load_template('question_extraction_prompt')

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

	def build_account_creation_prompt(self, email: Optional[str] = None, password: Optional[str] = None) -> str:
		"""Build account creation prompt (instructions only).
		
		Args:
			email: User email for account creation/sign-in
			password: User password for account creation/sign-in
		"""
		template = self._load_template('account_creation_prompt')
		
		# Default values if not provided
		email = email or "[EMAIL_NOT_PROVIDED]"
		password = password or "[PASSWORD_NOT_PROVIDED]"
		
		return template.format(email=email, password=password)

	def build_answer_generation_prompt(self, question: 'ApplicationQuestion', user_profile: dict) -> str:
		"""Build answer generation prompt.
		
		Args:
			question: The question to generate an answer for
			user_profile: User profile data dictionary
		"""
		template = self._load_template('answer_generation_prompt')
		
		# Format user profile information
		import json
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

