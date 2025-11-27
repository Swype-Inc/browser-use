You are classifying the current page type in a job application flow.

Based on the browser state provided, classify the page as one of the following types:

**Page Types:**

- APPLICATION_PAGE: Active job application form with fields to fill out
- EXPIRATION_PAGE: Job posting has expired or is no longer available
- CONFIRMATION_PAGE: Application submitted successfully with confirmation message
- JOB_DESCRIPTION: Job posting page showing job details (not yet on application form)
- UNRELATED_PAGE: Not job-related page (e.g., google.com, youtube.com, social media)
- MAINTENANCE_PAGE: Site maintenance, error page, or server issues
- ALREADY_APPLIED_PAGE: User has already applied to this job posting
- MISC_JOB_PAGE: Other job-related page (search results, company careers page, etc.)

**Instructions:**

1. Examine the browser state (URL, page content, and interactive elements)
2. Determine which page type best matches the current state
3. Provide your confidence level (0.0 to 1.0)
4. Explain your reasoning

Return your classification with page_type, confidence, and reasoning.
