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

<completed_sections>
{completed_sections}
</completed_sections>

<instructions>
1. Examine the browser state (DOM structure and interactive elements) to identify logical groupings of form fields
2. Look for explicit section headers, fieldset elements, or visual groupings
3. If no explicit grouping exists, create logical groupings based on field proximity and semantic meaning
4. Identify the next section that needs attention (not yet completed)
5. Return the section type, name (if present), section_index, element_indices, and completion status
6. Extract all question texts found in this section (labels, placeholders, aria-labels, or nearby text that identifies form fields). List them in the question_texts field. This helps the next step focus on parsing details rather than guessing what questions exist.
7. All the questions you extract absolutely must be contiguous. The section you return is simply preserving the order present in the DOM. It's not your prerogative to rearrange the questions, even if you think they would fit nicely under this section.
8. Provide a rationale explaining:
   - Why these specific questions were grouped together in this section
   - Confirmation that all questions are contiguous in DOM order (no gaps, no questions skipped)
   - If there are questions between the first and last question in your list, explain why they were excluded or why they belong to a different section
   - Reasoning for the section type classification
</instructions>

<important>
- Only identify sections that are currently visible on the page
- Skip sections that are already completed (check completed_sections list)
- If all sections are complete, return null
- Include ALL question texts you can identify in the section - this is critical for the next parsing step
- Questions MUST be contiguous - if you see "First Name", "Last Name", "Email", then 5 other questions, then "LinkedIn", do NOT include LinkedIn in the same section. Stop at Email and let LinkedIn be part of the next section.
</important>

Return the next section that needs to be filled (including question_texts and rationale), or null if all sections are complete.
