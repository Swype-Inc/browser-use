"""Answer generation step for the job application pipeline."""

from browser_use.job_application.pipeline.answer_generation.run import generate_answer
from browser_use.job_application.pipeline.answer_generation.schema import AnswerGenerationOutput

__all__ = ['generate_answer', 'AnswerGenerationOutput']

