"""Schema for navigation step."""

from typing import List

from pydantic import BaseModel, ConfigDict, Field


class NavigationResult(BaseModel):
	"""Result of attempting to navigate to next page."""

	model_config = ConfigDict(arbitrary_types_allowed=True, extra='forbid')

	success: bool = Field(description="Whether navigation succeeded")
	errors: List[str] = Field(default_factory=list, description="List of validation errors if navigation failed")
	page_changed: bool = Field(default=False, description="Whether the page actually changed after navigation attempt")

