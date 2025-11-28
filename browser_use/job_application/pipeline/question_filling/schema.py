"""Schema for question filling step."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class FillResult(BaseModel):
	"""Result of filling an answer into a form field."""

	model_config = ConfigDict(arbitrary_types_allowed=True, extra='forbid')

	success: bool = Field(description="Whether the fill operation succeeded")
	error: Optional[str] = Field(None, description="Error message if fill failed")
	element_index: Optional[int] = Field(None, description="Element index that was filled")


class QuestionFillAssessment(BaseModel):
	"""Assessment of whether a question has been filled correctly."""

	model_config = ConfigDict(arbitrary_types_allowed=True, extra='forbid')

	is_filled: bool = Field(description="Whether the question is filled correctly")
	reasoning: Optional[str] = Field(None, description="Brief explanation of the assessment")

