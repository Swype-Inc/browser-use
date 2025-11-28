"""Main pipeline service for job application automation."""

import logging
from typing import TYPE_CHECKING, List, Optional

from browser_use.browser import BrowserSession
from browser_use.job_application.pipeline.account_creation.run import handle_account_creation
from browser_use.job_application.pipeline.answer_generation.run import generate_answer
from browser_use.job_application.pipeline.navigation.run import navigate_to_application, navigate_to_next_page
from browser_use.job_application.pipeline.page_classification.run import classify_page
from browser_use.job_application.pipeline.question_extraction.run import identify_questions_in_section
from browser_use.job_application.pipeline.question_filling.run import fill_answer
from browser_use.job_application.pipeline.section_identification.run import identify_next_section
from browser_use.job_application.pipeline.shared.enums import PageType
from browser_use.job_application.pipeline.shared.schemas import (
	ApplicationQuestion,
	ApplicationResult,
	ApplicationSection,
	QuestionAnswer,
)
from browser_use.job_application.pipeline.state import PipelineState, QuestionWithAnswer, SectionWithQuestions
from browser_use.job_application.websocket.client import AnswerGeneratorClient
from browser_use.llm.base import BaseChatModel
from browser_use.observability import observe
from browser_use.utils import time_execution_async
from browser_use.tools.service import Tools

if TYPE_CHECKING:
	pass

logger = logging.getLogger(__name__)


class JobApplicationPipeline:
	"""Multi-step pipeline for filling out job applications."""

	def __init__(
		self,
		browser_session: BrowserSession,
		llm: BaseChatModel,
		answer_generator_client: Optional[AnswerGeneratorClient] = None,
		email: Optional[str] = None,
		password: Optional[str] = None,
		user_profile: Optional[dict] = None,
	):
		"""Initialize pipeline.

		Args:
			browser_session: Browser session for interacting with the page
			llm: LLM for classification and identification tasks
			answer_generator_client: Optional websocket client for answer generation
			email: User email for account creation/sign-in
			password: User password for account creation/sign-in
			user_profile: User profile data (dict with personal/professional info)
		"""
		self.browser_session = browser_session
		self.llm = llm
		self.answer_generator_client = answer_generator_client
		self.email = email
		self.password = password
		self.user_profile = user_profile or {}
		self.state = PipelineState()
		self.logger = logging.getLogger(__name__)
		# Initialize Tools for navigation actions
		self.tools = Tools()

	@observe(name='pipeline.run', ignore_input=True, ignore_output=True)
	async def run(self) -> ApplicationResult:
		"""Main pipeline execution loop."""
		try:
			# Step 1: Classify current page
			page_type = await classify_page(self.browser_session, self.llm)
			self.state.current_page_type = page_type
			self.state.page_classification_history.append(page_type)

			# Step 2: Route based on page type
			if page_type == PageType.JOB_DESCRIPTION or page_type == PageType.MISC_JOB_PAGE:
				await navigate_to_application(self.browser_session, self.llm, self.tools, self.state)
				# Re-classify after navigation
				page_type = await classify_page(self.browser_session, self.llm)
				self.state.current_page_type = page_type

			# Handle account creation/sign-in if needed
			if page_type == PageType.ACCOUNT_CREATION:
				await handle_account_creation(
					self.browser_session, self.llm, self.tools, self.state, self.email, self.password
				)
				# Re-classify after account creation
				page_type = await classify_page(self.browser_session, self.llm)
				self.state.current_page_type = page_type

			if page_type == PageType.APPLICATION_PAGE:
				return await self.fill_application()
			elif page_type == PageType.CONFIRMATION_PAGE:
				return ApplicationResult(
					success=True,
					completed=True,
					sections=self.state.sections,
					questions_answered=len(self.state.get_all_question_answers()),
					sections_completed=len(self.state.get_completed_sections()),
				)
			elif page_type == PageType.ALREADY_APPLIED_PAGE:
				return ApplicationResult(
					success=True,
					already_applied=True,
					sections=self.state.sections,
					questions_answered=len(self.state.get_all_question_answers()),
					sections_completed=len(self.state.get_completed_sections()),
				)
			elif page_type == PageType.EXPIRATION_PAGE:
				return ApplicationResult(
					success=False,
					error='Job posting has expired',
					sections=self.state.sections,
				)
			elif page_type == PageType.UNRELATED_PAGE:
				return ApplicationResult(
					success=False,
					error='Navigated to unrelated page',
					sections=self.state.sections,
				)
			elif page_type == PageType.MAINTENANCE_PAGE:
				return ApplicationResult(
					success=False,
					error='Site is under maintenance',
					sections=self.state.sections,
				)
			else:
				return ApplicationResult(
					success=False,
					error=f'Unexpected page type: {page_type}',
					sections=self.state.sections,
				)

		except Exception as e:
			self.logger.error(f'Pipeline error: {e}', exc_info=True)
			return ApplicationResult(
				success=False,
				error=str(e),
				sections=self.state.sections,
			)

	@time_execution_async('--fill_application')
	async def fill_application(self) -> ApplicationResult:
		"""Main application filling loop."""
		max_iterations = 50  # Safety limit
		iteration = 0

		while iteration < max_iterations:
			iteration += 1

			# 1. Identify next section
			section, question_texts = await identify_next_section(
				self.browser_session, self.llm, self.state
			)
			if section is None:
				self.logger.info('No more sections to fill on this page, attempting navigation to next page')
				# Try to navigate to next page
				navigation_result = await navigate_to_next_page(self.browser_session)
				if navigation_result.page_changed:
					# Page changed, continue loop to re-classify
					continue
				else:
					# No more pages or navigation failed, we're done
					self.logger.info('All sections complete and no more pages!')
					break

			self.state.current_section = section
			section_name = section.name or section.section_type.value
			self.logger.info(f'Working on section: {section_name}')

			# Add section to tracking if not already present
			section_with_questions = None
			for existing_section in self.state.sections:
				if (
					existing_section.name == section.name
					and existing_section.type == section.section_type
					and existing_section.section_index == section.section_index
				):
					section_with_questions = existing_section
					break

			if section_with_questions is None:
				section_with_questions = self.state.add_section(section)

			# 2. Identify questions in section
			questions = await identify_questions_in_section(
				self.browser_session, self.llm, section, question_texts
			)

			# Add questions to section tracking
			for question in questions:
				# Check if question already exists
				question_exists = any(
					q.question_text == question.question_text for q in section_with_questions.questions
				)
				if not question_exists:
					section_with_questions.questions.append(QuestionWithAnswer.from_question(question))

			# 3. Generate and fill answers
			for question in questions:
				# Check if already answered
				question_with_answer = None
				for qwa in section_with_questions.questions:
					if qwa.question_text == question.question_text:
						question_with_answer = qwa
						break

				if question_with_answer and question_with_answer.answer and question_with_answer.answer.filled_successfully:
					continue  # Already filled successfully

				# Generate answer (via websocket to browser extension or LLM)
				answer = await generate_answer(
					question, self.llm, self.user_profile, self.answer_generator_client
				)

				# Fill answer
				fill_result = await fill_answer(
					self.browser_session, self.llm, self.tools, question, answer
				)

				# Update answer with fill result
				answer.filled_successfully = fill_result.success
				if not fill_result.success:
					answer.error_message = fill_result.error

				# Update question with answer
				if question_with_answer:
					question_with_answer.answer = answer
				else:
					# Shouldn't happen, but handle gracefully
					self.state.update_question_answer(section_name, question.question_text, answer)

				# Handle errors
				if not fill_result.success:
					await self.handle_fill_error(question, answer, fill_result.error)

			section_with_questions.is_complete = True
            
			# 4. Attempt to move to next page
			navigation_result = await navigate_to_next_page(self.browser_session)

			# 5. Resolve errors if navigation failed
			if not navigation_result.success:
				await self.resolve_navigation_errors(navigation_result.errors)
			elif navigation_result.page_changed:
				# Page changed, break to re-classify
				break

		return ApplicationResult(
			success=True,
			completed=True,
			sections=self.state.sections,
			questions_answered=len(self.state.get_all_question_answers()),
			sections_completed=len(self.state.get_completed_sections()),
		)

	async def resolve_navigation_errors(self, errors: List[str]) -> None:
		"""Resolve errors preventing navigation."""
		self.logger.warning(f'Navigation errors detected: {errors}')
		# TODO: Implement error resolution logic
		# - Check for validation errors
		# - Identify missing required fields
		# - Fill missing fields
		# - Retry navigation

	async def handle_fill_error(
		self, question: ApplicationQuestion, answer: QuestionAnswer, error: str
	) -> None:
		"""Handle fill error with retry logic."""
		retry_count = self.state.increment_failed_question(question.question_text)

		if retry_count > 3:
			self.logger.error(
				f'Question "{question.question_text}" failed {retry_count} times, giving up'
			)
			return

		self.logger.warning(
			f'Fill error for question "{question.question_text}": {error}. Retry count: {retry_count}'
		)

		# TODO: Implement retry logic
		# - Refresh DOM
		# - Re-identify question
		# - Retry fill
