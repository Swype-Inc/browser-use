You are identifying the next application section that needs to be filled.

<section_types>

- PERSONAL_INFO: Personal information (name, address, contact info)
- PHONE: Phone number section
- EDUCATION: Education history section
- WORK_EXPERIENCE: Work experience/employment history section
- LANGUAGE: Language skills section
- PROJECT: Projects/portfolio section
- DEMOGRAPHICS: Demographic information (race, gender, veteran status, etc.)
- LEGAL_NAME: Legal name section
- OTHER: Other sections not covered above
  </section_types>

<previous_sections>
{previous_sections}
</previous_sections>

<instructions>
1. A screenshot of the current page is provided. Use it as your primary source for identifying visual separations and logical groupings of form fields. Look for:
   - Visual dividers, borders, or spacing that separate sections
   - Section headers or titles that are visually distinct
   - Grouped fields that appear together visually
   - White space or layout changes that indicate section boundaries
2. Cross-reference the screenshot with the browser state (DOM structure) to understand both the visual layout and the underlying structure
3. Look for explicit section headers, fieldset elements, or visual groupings in both the screenshot and DOM
4. Use the screenshot to identify where sections naturally break - if you see visual separations (dividers, spacing, headers) between groups of questions, those indicate separate sections
5. If no explicit grouping exists, create logical groupings based on visual proximity in the screenshot and semantic meaning
6. Review the previous_sections above to see what sections and questions have already been identified. You MUST identify the NEXT section that comes AFTER the last identified section in DOM order. Do NOT re-identify sections or questions that are already listed above.
7. Identify the next section that needs attention (not yet completed). Use the screenshot to identify where the next visual section begins - look for section headers, dividers, or visual breaks that indicate a new section starts.
8. Return the section type, name (if present), section_index, element_indices, and completion status. For the section name:
   - Look for visible headings (h1-h6), labels, or text that serves as a section title visible to the applicant
   - Examples of GOOD section names: "Personal Information", "Education History", "Work Experience", "Contact Details"
   - Examples of BAD section names: "application-form", "personal-info group", "section-1", "form-group", CSS class names, DOM attributes, or technical identifiers
   - Only extract names that are human-readable titles meant for the applicant to see
   - If no such visible title exists, leave the name field as null/empty rather than using a technical identifier
9. Extract all question texts found in this section (labels, placeholders, aria-labels, or nearby text that identifies form fields). List them in the question_texts field. This helps the next step focus on parsing details rather than guessing what questions exist.
10. All the questions you extract absolutely must be contiguous. The section you return is simply preserving the order present in the DOM. It's not your prerogative to rearrange the questions, even if you think they would fit nicely under this section.
11. CRITICAL: Use the screenshot to identify visual section boundaries. If you see visual separations (dividers, spacing, section headers) between groups of questions in the screenshot, STOP at that boundary. Do NOT include questions that appear after a clear visual separator - those belong to the next section. For example, if you see "First Name", "Last Name", "Email" followed by a visual divider/header and then "School Name", "Degree", stop at "Email" and let the education fields be part of the next section.
12. Provide a rationale explaining:
   - Why these specific questions were grouped together in this section
   - Confirmation that all questions are contiguous in DOM order (no gaps, no questions skipped)
   - If there are questions between the first and last question in your list, explain why they were excluded or why they belong to a different section
   - Reasoning for the section type classification
</instructions>

<important>
- Only identify sections that are currently visible on the page
- You absolutely must go in sequential order. You are looking for the very next section in the application that is not already listed in previous sections. 
- Skip sections and questions that are already in previous_sections - you must find the NEXT section with questions that haven't been identified yet
- If there are no more sections to identify on this page (all sections are complete, or you've reached the end of the form), set no_more_sections=True and return null/empty values for other fields
- Include ALL question texts you can identify in the section - this is critical for the next parsing step
- Questions MUST be contiguous - if you see "First Name", "Last Name", "Email", then 5 other questions, then "LinkedIn", do NOT include LinkedIn in the same section. Stop at Email and let LinkedIn be part of the next section.
- CRITICAL: Use the screenshot to identify visual section boundaries. Look for visual separators (dividers, spacing, section headers) in the screenshot. If you see a clear visual break between groups of questions, STOP at that boundary. The screenshot is your primary guide for determining where one section ends and another begins.
- CRITICAL: The section name must be a human-readable title visible to applicants (like "Personal Information" or "Education"). Do NOT use CSS classes, DOM attributes, technical identifiers, or element class names. If no visible title exists, leave name as null.
</important>

Return the next section that needs to be filled (including question_texts and rationale), or set no_more_sections=True if there are no more sections on this page.
