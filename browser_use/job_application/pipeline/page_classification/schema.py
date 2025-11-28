"""Schema for page classification step."""

from pydantic import BaseModel, ConfigDict, Field

from browser_use.job_application.pipeline.shared.enums import PageType


class PageClassificationOutput(BaseModel):
	"""Output from page classification step."""

	model_config = ConfigDict(arbitrary_types_allowed=True, extra='forbid')

	page_type: PageType = Field(description="The type of page currently displayed")
	confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0-1")
	reasoning: str = Field(description="Brief explanation of classification")

