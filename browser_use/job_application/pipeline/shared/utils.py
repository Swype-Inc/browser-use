"""Shared utilities for the job application pipeline."""

from browser_use.browser.views import BrowserStateSummary

# ANSI color codes
GREEN = '\033[92m'
RESET = '\033[0m'


def debug_input(prompt: str) -> str:
	"""Print a colored debug prompt and wait for user input.
	
	Args:
		prompt: The debug message to display
		
	Returns:
		User input string
	"""
	return input(f'{GREEN}{prompt}{RESET}')


def format_browser_state_message(browser_state: BrowserStateSummary) -> str:
	"""Format browser state using the same logic as AgentMessagePrompt.
	
	This ensures consistent browser state formatting across all pipeline steps.
	
	Args:
		browser_state: The browser state summary to format
		
	Returns:
		Formatted browser state as a string
	"""
	from browser_use.agent.prompts import AgentMessagePrompt
	from browser_use.filesystem.file_system import FileSystem
	
	# Create a minimal AgentMessagePrompt just to use its browser state formatting
	# FileSystem is required but not used for browser state formatting
	file_system = FileSystem("./tmp")
	prompt_helper = AgentMessagePrompt(
		browser_state_summary=browser_state,
		file_system=file_system,
		include_attributes=None,  # Use defaults
	)
	
	return prompt_helper._get_browser_state_description()

