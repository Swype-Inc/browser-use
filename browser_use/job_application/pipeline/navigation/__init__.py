"""Navigation step for the job application pipeline."""

from browser_use.job_application.pipeline.navigation.run import (
	check_navigation_complete,
	execute_navigation_actions,
	get_navigation_actions,
	navigate_to_application,
	navigate_to_next_page,
	plan_navigation,
	prepare_navigation_context,
)
from browser_use.job_application.pipeline.navigation.schema import NavigationResult

__all__ = [
	'navigate_to_application',
	'plan_navigation',
	'get_navigation_actions',
	'execute_navigation_actions',
	'check_navigation_complete',
	'navigate_to_next_page',
	'prepare_navigation_context',
	'NavigationResult',
]

