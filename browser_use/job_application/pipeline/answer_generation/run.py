"""Answer generation step implementation."""

import importlib.resources
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import httpx

from browser_use.job_application.pipeline.answer_generation.schema import AnswerGenerationOutput
from browser_use.job_application.pipeline.question_extraction.schema import ApplicationQuestion
from browser_use.job_application.pipeline.shared.schemas import QuestionAnswer
from browser_use.job_application.pipeline.shared.utils import debug_input
from browser_use.job_application.websocket.client import AnswerGeneratorClient
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import UserMessage

if TYPE_CHECKING:
	pass

logger = logging.getLogger(__name__)


def _load_prompt() -> str:
	"""Load the answer generation prompt template."""
	try:
		with importlib.resources.files('browser_use.job_application.pipeline.answer_generation').joinpath(
			'prompt.md'
		).open('r', encoding='utf-8') as f:
			return f.read()
	except Exception as e:
		raise RuntimeError(f'Failed to load answer generation prompt: {e}')


def _build_prompt(question: ApplicationQuestion, user_profile: dict) -> str:
	"""Build the answer generation prompt.
	
	Args:
		question: The question to generate an answer for
		user_profile: User profile data dictionary
		
	Returns:
		Formatted prompt string
	"""
	template = _load_prompt()
	
	# Format user profile information
	user_profile_str = json.dumps(user_profile, indent=2) if user_profile else "{}"
	
	# Extract available files with filename and file_id from user_profile
	available_files = []
	if user_profile and 'documents' in user_profile:
		docs = user_profile.get('documents', {})
		primary = docs.get('primary', {})
		additional = docs.get('additional', [])
		
		# Add primary document files
		for doc_type, doc_info in primary.items():
			if doc_info and isinstance(doc_info, dict) and 'name' in doc_info and 'id' in doc_info:
				available_files.append(f"- {doc_info['name']} (file_id: {doc_info['id']})")
		
		# Add additional document files
		for doc in additional:
			if isinstance(doc, dict) and 'name' in doc and 'id' in doc:
				available_files.append(f"- {doc['name']} (file_id: {doc['id']})")
	
	files_str = '\n'.join(available_files) if available_files else 'None'
	
	# Format question details
	question_type = question.question_type.value
	is_required = "Yes" if question.is_required else "No"
	
	# Format options if available
	if question.options:
		options_str = '\n'.join(f'- {opt.text}' + (f' (value: {opt.value})' if opt.value else '') for opt in question.options)
	else:
		options_str = 'None'
	
	# Format validation pattern if available
	validation_pattern = question.validation_pattern or 'None'
	
	return template.format(
		question_text=question.question_text,
		question_type=question_type,
		is_required=is_required,
		options=options_str,
		validation_pattern=validation_pattern,
		user_profile=user_profile_str,
		available_files=files_str,
	)


def _get_filename_from_file_id(file_id: int, user_profile: dict) -> Optional[str]:
	"""Get filename from user_profile using file_id.
	
	Args:
		file_id: File ID to look up
		user_profile: User profile data dictionary
		
	Returns:
		Filename if found, None otherwise
	"""
	if not user_profile or 'documents' not in user_profile:
		return None
	
	docs = user_profile.get('documents', {})
	primary = docs.get('primary', {})
	additional = docs.get('additional', [])
	
	# Check primary documents
	for doc_type, doc_info in primary.items():
		if doc_info and isinstance(doc_info, dict) and doc_info.get('id') == file_id:
			return doc_info.get('name')
	
	# Check additional documents
	for doc in additional:
		if isinstance(doc, dict) and doc.get('id') == file_id:
			return doc.get('name')
	
	return None


async def _download_file(file_id: int, file_base_url: str, backend_api_key: str, filename: Optional[str] = None) -> str:
	"""Download a file using file_id and return the local file path.
	
	Args:
		file_id: File ID from user profile
		file_base_url: Base URL for file API
		backend_api_key: API key for authentication
		filename: Optional filename to preserve extension
		
	Returns:
		Local file path where the file was saved
	"""
	logger.info(f'Downloading file {file_id}...')
	
	try:
		async with httpx.AsyncClient(timeout=30.0) as client:
			response = await client.get(
				f'{file_base_url}/internal/{file_id}',
				headers={'x-api-key': backend_api_key}
			)
			response.raise_for_status()
			
			# Create temp directory to save the downloaded content
			temp_dir = Path(tempfile.gettempdir()) / 'browser_use_downloads'
			temp_dir.mkdir(parents=True, exist_ok=True)
			
			# Use filename if provided, otherwise use file_id
			if filename:
				# Preserve the extension from filename
				temp_file = temp_dir / filename
			else:
				temp_file = temp_dir / f'file_{file_id}'
			
			temp_file.write_bytes(response.content)
			
			logger.info(f'File downloaded to {temp_file}')
			return str(temp_file)
	except Exception as err:
		logger.error(f"An error occurred during file download: {err}")
		raise Exception(f"Failed to download file: {err}") from err


async def run(
	question: ApplicationQuestion,
	llm: BaseChatModel,
	user_profile: dict,
	answer_generator_client: Optional[AnswerGeneratorClient] = None,
) -> QuestionAnswer:
	"""Generate answer using LLM based on user profile and question.
	
	Args:
		question: The question to generate an answer for
		llm: LLM for answer generation
		user_profile: User profile data dictionary
		answer_generator_client: Optional websocket client for answer generation
		
	Returns:
		Generated answer
	"""
	# Try websocket first if available
	if answer_generator_client:
		try:
			return await answer_generator_client.generate_answer(question)
		except NotImplementedError:
			logger.warning('Websocket answer generation not available, using LLM')
		except Exception as e:
			logger.error(f'Failed to generate answer via websocket: {e}')

	# Use LLM to generate answer
	try:
		# Build prompt with user profile and question
		prompt_text = _build_prompt(question, user_profile)
		
		messages = [UserMessage(content=prompt_text)]
		
		# Use structured output for answer generation
		response = await llm.ainvoke(messages, output_format=AnswerGenerationOutput)
		answer_output = response.completion
		
		answer_value = answer_output.answer_value
		
		# If it's a FILE question, answer_value should be a file_id - download the file
		if question.question_type.value == 'FILE' and answer_value:
			try:
				# Parse file_id from answer_value
				file_id = int(answer_value)
				
				# Get file_base_url and backend_api_key from environment
				file_base_url = os.getenv('FILE_BASE_URL')
				backend_api_key = os.getenv('BACKEND_API_KEY')
				
				if not file_base_url:
					raise ValueError('FILE_BASE_URL environment variable not set')
				if not backend_api_key:
					raise ValueError('BACKEND_API_KEY environment variable not set')
				
				# Get filename from user_profile to preserve extension
				filename = _get_filename_from_file_id(file_id, user_profile)
				
				# Download the file
				file_path = await _download_file(file_id, file_base_url, backend_api_key, filename)
				
				# Update answer_value to the downloaded file path
				answer_value = file_path
				logger.info(f'Downloaded file {file_id} to {file_path}')
			except ValueError as e:
				logger.warning(f'Invalid file_id format in answer_value "{answer_value}": {e}')
				# Keep answer_value as-is if parsing fails
			except Exception as e:
				logger.error(f'Failed to download file from answer_value "{answer_value}": {e}')
				# Keep answer_value as-is if download fails
		
		debug_input(f'[DEBUG] Press Enter to continue after answer generation for: "{question.question_text[:50]}..."...')
		
		# Convert to QuestionAnswer
		return QuestionAnswer(
			question_text=question.question_text,
			answer_value=answer_value,
			answer_type=question.question_type,
			element_index=question.element_index,
			filled_successfully=True,
		)
	except Exception as e:
		logger.error(f'Failed to generate answer via LLM: {e}')
		# Fallback: return placeholder answer
		return QuestionAnswer(
			question_text=question.question_text,
			answer_value='PLACEHOLDER_ANSWER',
			answer_type=question.question_type,
			element_index=question.element_index,
			filled_successfully=False,
			error_message=f'Answer generation failed: {str(e)}',
		)

