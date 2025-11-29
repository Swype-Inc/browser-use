"""Schema for section identification step."""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from browser_use.job_application.pipeline.shared.enums import SectionType


class SectionIdentificationOutput(BaseModel):
	"""Output from section identification step, including section info and question texts."""

	model_config = ConfigDict(arbitrary_types_allowed=True, extra='forbid')

	no_more_sections: bool = Field(default=False, description="Set to True if there are no more sections to identify on this page")
	section_type: Optional[SectionType] = Field(None, description="Type of section (required if no_more_sections is False)")
	name: Optional[str] = Field(None, description="Human-readable section title visible to applicants (e.g., 'Personal Information', 'Education History'). Do NOT use CSS classes, DOM attributes, or technical identifiers. Leave null if no visible title exists.")
	section_index: int = Field(default=0, description="Order of section on page (0-indexed)")
	is_complete: bool = Field(default=False, description="Whether all required fields are filled")
	has_errors: bool = Field(default=False, description="Whether section has validation errors")
	element_indices: List[int] = Field(default_factory=list, description="Backend node IDs of elements in this section")
	question_texts: List[str] = Field(default_factory=list, description="List of question texts found in this section")
	rationale: Optional[str] = Field(None, description="Explanation of why these questions were grouped together, confirmation that they are contiguous in the DOM order, and reasoning for the section type classification")

