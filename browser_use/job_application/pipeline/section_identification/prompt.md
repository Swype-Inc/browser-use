You are identifying the next application section that needs to be filled.

<section_types>

- EDUCATION: Education history section
- WORK_EXPERIENCE: Work experience/employment history section
- PERSONAL_INFO: Personal information (name, address, contact info)
- DEMOGRAPHICS: Demographic information (race, gender, veteran status, etc.)
- LANGUAGE: Language skills section
- PROJECT: Projects/portfolio section
- PHONE: Phone number section
- LEGAL_NAME: Legal name section
- OTHER: Other sections not covered above
  </section_types>

<previous_sections>
{previous_sections}
</previous_sections>

<instructions>
1. Examine the browser state (DOM structure and interactive elements) to identify logical groupings of form fields
2. Look for explicit section headers, fieldset elements, or visual groupings
3. If no explicit grouping exists, create logical groupings based on field proximity and semantic meaning
4. Review the previous_sections above to see what sections and questions have already been identified. You MUST identify the NEXT section that comes AFTER the last identified section in DOM order. Do NOT re-identify sections or questions that are already listed above.
5. Identify the next section that needs attention (not yet completed)
6. Return the section type, name (if present), section_index, element_indices, and completion status
7. Extract all question texts found in this section (labels, placeholders, aria-labels, or nearby text that identifies form fields). List them in the question_texts field. This helps the next step focus on parsing details rather than guessing what questions exist.
8. All the questions you extract absolutely must be contiguous. The section you return is simply preserving the order present in the DOM. It's not your prerogative to rearrange the questions, even if you think they would fit nicely under this section.
9. Provide a rationale explaining:
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
</important>

Return the next section that needs to be filled (including question_texts and rationale), or set no_more_sections=True if there are no more sections on this page.
