"""Shared enums for the job application pipeline."""

from enum import Enum


class PageType(str, Enum):
	"""Types of pages encountered during job application flow."""

	APPLICATION_PAGE = "application_page"
	EXPIRATION_PAGE = "expiration_page"
	CONFIRMATION_PAGE = "confirmation_page"
	JOB_DESCRIPTION = "job_description"
	UNRELATED_PAGE = "unrelated_page"
	MAINTENANCE_PAGE = "maintenance_page"
	ALREADY_APPLIED_PAGE = "already_applied_page"
	MISC_JOB_PAGE = "misc_job_page"
	ACCOUNT_CREATION = "account_creation"

	@classmethod
	def get_descriptions(cls) -> dict[str, str]:
		"""Get descriptions for each page type."""
		return {
			cls.APPLICATION_PAGE.value: "Active job application form with fields to fill out",
			cls.EXPIRATION_PAGE.value: "Job posting has expired or is no longer available",
			cls.CONFIRMATION_PAGE.value: "Application submitted successfully with confirmation message",
			cls.JOB_DESCRIPTION.value: "Job posting page showing job details (not yet on application form)",
			cls.UNRELATED_PAGE.value: "Not job-related page (e.g., google.com, youtube.com, social media)",
			cls.MAINTENANCE_PAGE.value: "Site maintenance, error page, or server issues",
			cls.ALREADY_APPLIED_PAGE.value: "User has already applied to this job posting",
			cls.MISC_JOB_PAGE.value: "Other job-related page (search results, company careers page, etc.)",
			cls.ACCOUNT_CREATION.value: "Account creation or sign-in page that must be completed before applying",
		}


class SectionType(str, Enum):
	"""Types of application sections."""

	EDUCATION = "EDUCATION"
	WORK_EXPERIENCE = "WORK_EXPERIENCE"
	PERSONAL_INFO = "PERSONAL_INFO"
	DEMOGRAPHICS = "DEMOGRAPHICS"
	LANGUAGE = "LANGUAGE"
	PROJECT = "PROJECT"
	OTHER = "OTHER"
	PHONE = "PHONE"
	LEGAL_NAME = "LEGAL_NAME"


class QuestionType(str, Enum):
	"""Types of form questions."""

	SINGLE_SELECT = "SINGLE_SELECT"
	MULTI_SELECT = "MULTI_SELECT"
	TEXT = "TEXT"
	TEXTAREA = "TEXTAREA"
	BOOLEAN = "BOOLEAN"
	FILE = "FILE"

