"""Schema for answer generation step."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AnswerGenerationOutput(BaseModel):
	"""Output model for LLM answer generation."""

	model_config = ConfigDict(arbitrary_types_allowed=True, extra='forbid')

	answer_value: str = Field(description="The answer value to fill into the form field. For FILE questions, provide the file_id (numeric ID as string, e.g., '793667') from Available Files.")
	reasoning: Optional[str] = Field(None, description="Brief explanation of why this answer was chosen")

