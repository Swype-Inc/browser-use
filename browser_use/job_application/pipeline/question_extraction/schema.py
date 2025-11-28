"""Schema for question extraction step."""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from browser_use.job_application.pipeline.shared.enums import QuestionType, SectionType


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

