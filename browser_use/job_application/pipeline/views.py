"""Schema definitions for job application pipeline."""

from enum import Enum
from typing import TYPE_CHECKING, Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
	from browser_use.job_application.pipeline.state import SectionWithQuestions


class PageType(str, Enum):
	"""Types of pages encountered during job application flow."""

	APPLICATION_PAGE = "application_page"
	EXPIRATION_PAGE = "expiration_page"
	CONFIRMATION_PAGE = "confirmation_page"
	JOB_DESCRIPTION = "job_description"
	UNRELATED_PAGE = "unrelated_page"
	MAINTENANCE_PAGE = "maintenance_page"
	ALREADY_APPLIED_PAGE = "already_applied_page"
	MISC_JOB_PAGE = "misc_job_page"
	ACCOUNT_CREATION = "account_creation"

	@classmethod
	def get_descriptions(cls) -> dict[str, str]:
		"""Get descriptions for each page type."""
		return {
			cls.APPLICATION_PAGE.value: "Active job application form with fields to fill out",
			cls.EXPIRATION_PAGE.value: "Job posting has expired or is no longer available",
			cls.CONFIRMATION_PAGE.value: "Application submitted successfully with confirmation message",
			cls.JOB_DESCRIPTION.value: "Job posting page showing job details (not yet on application form)",
			cls.UNRELATED_PAGE.value: "Not job-related page (e.g., google.com, youtube.com, social media)",
			cls.MAINTENANCE_PAGE.value: "Site maintenance, error page, or server issues",
			cls.ALREADY_APPLIED_PAGE.value: "User has already applied to this job posting",
			cls.MISC_JOB_PAGE.value: "Other job-related page (search results, company careers page, etc.)",
			cls.ACCOUNT_CREATION.value: "Account creation or sign-in page that must be completed before applying",
		}


class SectionType(str, Enum):
	"""Types of application sections."""

	EDUCATION = "EDUCATION"
	WORK_EXPERIENCE = "WORK_EXPERIENCE"
	PERSONAL_INFO = "PERSONAL_INFO"
	DEMOGRAPHICS = "DEMOGRAPHICS"
	LANGUAGE = "LANGUAGE"
	PROJECT = "PROJECT"
	OTHER = "OTHER"
	PHONE = "PHONE"
	LEGAL_NAME = "LEGAL_NAME"


class QuestionType(str, Enum):
	"""Types of form questions."""

	SINGLE_SELECT = "SINGLE_SELECT"
	MULTI_SELECT = "MULTI_SELECT"
	TEXT = "TEXT"
	TEXTAREA = "TEXTAREA"
	BOOLEAN = "BOOLEAN"


class PageClassificationOutput(BaseModel):
	"""Output from page classification step."""

	model_config = ConfigDict(arbitrary_types_allowed=True, extra='forbid')

	page_type: PageType = Field(description="The type of page currently displayed")
	confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0-1")
	reasoning: str = Field(description="Brief explanation of classification")


class ApplicationSection(BaseModel):
	"""Represents a section of the application form."""

	model_config = ConfigDict(arbitrary_types_allowed=True, extra='forbid')

	section_type: SectionType = Field(description="Type of section")
	name: Optional[str] = Field(None, description="Name of section if present in DOM")
	section_index: int = Field(description="Order of section on page (0-indexed)")
	is_complete: bool = Field(default=False, description="Whether all required fields are filled")
	has_errors: bool = Field(default=False, description="Whether section has validation errors")
	element_indices: List[int] = Field(default_factory=list, description="Backend node IDs of elements in this section")


class SectionIdentificationOutput(BaseModel):
	"""Output from section identification step, including section info and question texts."""

	model_config = ConfigDict(arbitrary_types_allowed=True, extra='forbid')

	section_type: SectionType = Field(description="Type of section")
	name: Optional[str] = Field(None, description="Name of section if present in DOM")
	section_index: int = Field(description="Order of section on page (0-indexed)")
	is_complete: bool = Field(default=False, description="Whether all required fields are filled")
	has_errors: bool = Field(default=False, description="Whether section has validation errors")
	element_indices: List[int] = Field(default_factory=list, description="Backend node IDs of elements in this section")
	question_texts: List[str] = Field(default_factory=list, description="List of question texts found in this section")


class QuestionOption(BaseModel):
	"""An option available for a select-type question."""

	model_config = ConfigDict(arbitrary_types_allowed=True, extra='forbid')

	text: str = Field(description="Display text of the option")
	value: Optional[str] = Field(None, description="Value attribute if different from text")
	element_index: int = Field(description="Backend node ID of the option element")


class ApplicationQuestion(BaseModel):
	"""Represents a single question in the application."""

	model_config = ConfigDict(arbitrary_types_allowed=True, extra='forbid')

	question_text: str = Field(description="The question text as displayed")
	is_required: bool = Field(description="Whether this question is required")
	question_type: QuestionType = Field(description="Type of question input")
	element_index: int = Field(description="Backend node ID of the question element")
	options: List[QuestionOption] = Field(default_factory=list, description="Available options for select types")
	options_complete: bool = Field(default=True, description="Whether all options are listed (false if truncated)")
	section_type: SectionType = Field(description="Type of section this question belongs to")
	validation_pattern: Optional[str] = Field(None, description="Validation pattern if visible in DOM")
	depends_on: Optional[str] = Field(None, description="Question this depends on (for conditional questions)")


class QuestionAnswer(BaseModel):
	"""Answer for a question (generated by browser extension)."""

	model_config = ConfigDict(arbitrary_types_allowed=True, extra='forbid')

	question_text: str = Field(description="Question this answers")
	answer_value: str = Field(description="The answer value")
	answer_type: QuestionType = Field(description="Type of answer")
	element_index: int = Field(description="Backend node ID of the question element")
	filled_successfully: bool = Field(default=False, description="Whether answer was successfully filled")
	error_message: Optional[str] = Field(None, description="Error message if filling failed")


class AnswerGenerationOutput(BaseModel):
	"""Output model for LLM answer generation."""

	model_config = ConfigDict(arbitrary_types_allowed=True, extra='forbid')

	answer_value: str = Field(description="The answer value to fill into the form field")
	reasoning: Optional[str] = Field(None, description="Brief explanation of why this answer was chosen")


class FillResult(BaseModel):
	"""Result of filling an answer into a form field."""

	model_config = ConfigDict(arbitrary_types_allowed=True, extra='forbid')

	success: bool = Field(description="Whether the fill operation succeeded")
	error: Optional[str] = Field(None, description="Error message if fill failed")
	element_index: Optional[int] = Field(None, description="Element index that was filled")


class NavigationResult(BaseModel):
	"""Result of attempting to navigate to next page."""

	model_config = ConfigDict(arbitrary_types_allowed=True, extra='forbid')

	success: bool = Field(description="Whether navigation succeeded")
	errors: List[str] = Field(default_factory=list, description="List of validation errors if navigation failed")
	page_changed: bool = Field(default=False, description="Whether the page actually changed after navigation attempt")


class ApplicationResult(BaseModel):
	"""Result of pipeline execution."""

	model_config = ConfigDict(arbitrary_types_allowed=True, extra='forbid')

	success: bool = Field(description="Whether the pipeline completed successfully")
	completed: bool = Field(default=False, description="Whether the application was fully completed")
	already_applied: bool = Field(default=False, description="Whether user has already applied")
	error: Optional[str] = Field(None, description="Error message if pipeline failed")
	questions_answered: int = Field(default=0, description="Number of questions answered")
	sections_completed: int = Field(default=0, description="Number of sections completed")
	# sections included for user display (hierarchical structure)
	# Note: SectionWithQuestions is defined in state.py to avoid circular imports
	sections: List[Any] = Field(
		default_factory=list, description="All sections with questions and answers (SectionWithQuestions objects)"
	)

