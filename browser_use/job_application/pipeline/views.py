"""Schema definitions for job application pipeline.

This module re-exports schemas from shared and step directories for backwards compatibility.
"""

# Re-export shared enums
from browser_use.job_application.pipeline.shared.enums import PageType, QuestionType, SectionType

# Re-export shared schemas
from browser_use.job_application.pipeline.shared.schemas import (
	ApplicationQuestion,
	ApplicationResult,
	ApplicationSection,
	QuestionAnswer,
	QuestionOption,
)

# Re-export step-specific schemas
from browser_use.job_application.pipeline.answer_generation.schema import AnswerGenerationOutput
from browser_use.job_application.pipeline.page_classification.schema import PageClassificationOutput
from browser_use.job_application.pipeline.question_filling.schema import FillResult, QuestionFillAssessment
from browser_use.job_application.pipeline.navigation.schema import NavigationResult
from browser_use.job_application.pipeline.section_identification.schema import SectionIdentificationOutput

# Note: ApplicationQuestion and QuestionOption are re-exported from shared.schemas
# They are also defined in question_extraction.schema but we use the shared versions for consistency
__all__ = [
	'PageType',
	'SectionType',
	'QuestionType',
	'ApplicationSection',
	'ApplicationQuestion',
	'QuestionAnswer',
	'QuestionOption',
	'ApplicationResult',
	'PageClassificationOutput',
	'SectionIdentificationOutput',
	'AnswerGenerationOutput',
	'FillResult',
	'NavigationResult',
	'QuestionFillAssessment',
]
