"""Page classification step for the job application pipeline."""

from browser_use.job_application.pipeline.page_classification.run import classify_page
from browser_use.job_application.pipeline.page_classification.schema import PageClassificationOutput

__all__ = ['classify_page', 'PageClassificationOutput']

