"""State tracking for job application pipeline."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from browser_use.job_application.pipeline.views import (
	ApplicationQuestion,
	ApplicationSection,
	PageType,
	QuestionAnswer,
	QuestionType,
	SectionType,
)


@dataclass
class QuestionWithAnswer:
	"""Combines question info and answer."""

	# All fields from ApplicationQuestion
	question_text: str
	is_required: bool
	question_type: QuestionType
	element_index: int
	options: List[Any] = field(default_factory=list)
	options_complete: bool = True
	section_type: SectionType = SectionType.OTHER
	validation_pattern: Optional[str] = None
	depends_on: Optional[str] = None

	# Answer (if filled)
	answer: Optional[QuestionAnswer] = None

	@classmethod
	def from_question(cls, question: ApplicationQuestion) -> 'QuestionWithAnswer':
		"""Create QuestionWithAnswer from ApplicationQuestion."""
		return cls(
			question_text=question.question_text,
			is_required=question.is_required,
			question_type=question.question_type,
			element_index=question.element_index,
			options=question.options,
			options_complete=question.options_complete,
			section_type=question.section_type,
			validation_pattern=question.validation_pattern,
			depends_on=question.depends_on,
			answer=None,
		)


@dataclass
class SectionWithQuestions:
	"""Section with its questions and answers."""

	# All fields from ApplicationSection
	type: SectionType
	name: Optional[str] = None
	section_index: int = 0
	is_complete: bool = False
	has_errors: bool = False
	element_indices: List[int] = field(default_factory=list)

	# Questions in this section
	questions: List[QuestionWithAnswer] = field(default_factory=list)

	@classmethod
	def from_section(cls, section: ApplicationSection) -> 'SectionWithQuestions':
		"""Create SectionWithQuestions from ApplicationSection."""
		return cls(
			type=section.section_type,
			name=section.name,
			section_index=section.section_index,
			is_complete=section.is_complete,
			has_errors=section.has_errors,
			element_indices=section.element_indices,
			questions=[],
		)


@dataclass
class PipelineState:
	"""Tracks state throughout the job application pipeline.

	State tracking serves three purposes:
	1. Primary: User display - Show user what was filled (sections -> questions -> answers) when application is submitted
	2. Secondary: LLM context - Include in prompts so LLM knows what has been completed (can flatten for prompts)
	3. Tertiary: Internal logic - Track progress and make decisions (avoid re-filling, detect loops)
	"""

	# Page classification
	current_page_type: Optional[PageType] = None
	page_classification_history: List[PageType] = field(default_factory=list)

	# Navigation
	navigation_attempts: int = 0
	requires_login: bool = False
	requires_account_creation: bool = False
	requires_email_verification: bool = False

	# Application filling - hierarchical structure: sections -> questions -> answers
	# Primary purpose: user display when application is submitted
	sections: List[SectionWithQuestions] = field(default_factory=list)
	current_section: Optional[ApplicationSection] = None  # Current section being worked on (for internal logic)

	# Error tracking
	failed_questions: Dict[str, int] = field(default_factory=dict)  # question_text -> retry_count
	validation_errors: List[str] = field(default_factory=list)

	def add_section(self, section: ApplicationSection) -> SectionWithQuestions:
		"""Add new section to tracking."""
		section_with_questions = SectionWithQuestions.from_section(section)
		self.sections.append(section_with_questions)
		return section_with_questions

	def add_question_to_section(self, section_name: str, question: ApplicationQuestion) -> None:
		"""Add question to existing section."""
		# Find section by name or type
		for section in self.sections:
			if section.name == section_name or (section.name is None and section.type.value == section_name):
				section.questions.append(QuestionWithAnswer.from_question(question))
				return
		# If section not found, create it
		# This shouldn't happen in normal flow, but handle gracefully
		raise ValueError(f"Section '{section_name}' not found in pipeline state")

	def update_question_answer(self, section_name: str, question_text: str, answer: QuestionAnswer) -> None:
		"""Update answer for a question."""
		for section in self.sections:
			if section.name == section_name or (section.name is None and section.type.value == section_name):
				for question in section.questions:
					if question.question_text == question_text:
						question.answer = answer
						return
		raise ValueError(f"Question '{question_text}' not found in section '{section_name}'")

	def mark_section_complete(self, section_name: str) -> None:
		"""Mark section as complete."""
		for section in self.sections:
			if section.name == section_name or (section.name is None and section.type.value == section_name):
				section.is_complete = True
				return

	def increment_failed_question(self, question_text: str) -> int:
		"""Increment retry count for a failed question."""
		self.failed_questions[question_text] = self.failed_questions.get(question_text, 0) + 1
		return self.failed_questions[question_text]

	def get_all_question_answers(self) -> List[QuestionAnswer]:
		"""Flatten structure for LLM context or display."""
		answers = []
		for section in self.sections:
			for question in section.questions:
				if question.answer:
					answers.append(question.answer)
		return answers

	def get_completed_sections(self) -> List[str]:
		"""Get list of completed section names/types."""
		completed = []
		for section in self.sections:
			if section.is_complete:
				completed.append(section.name or section.type.value)
		return completed

