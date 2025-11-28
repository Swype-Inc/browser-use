"""Section identification step for the job application pipeline."""

from browser_use.job_application.pipeline.section_identification.run import identify_next_section
from browser_use.job_application.pipeline.section_identification.schema import SectionIdentificationOutput

__all__ = ['identify_next_section', 'SectionIdentificationOutput']

