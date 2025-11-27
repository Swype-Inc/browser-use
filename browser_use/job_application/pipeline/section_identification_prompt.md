You are identifying the next application section that needs to be filled.

**Section Types:**

- EDUCATION: Education history section
- WORK_EXPERIENCE: Work experience/employment history section
- PERSONAL_INFO: Personal information (name, address, contact info)
- DEMOGRAPHICS: Demographic information (race, gender, veteran status, etc.)
- LANGUAGE: Language skills section
- PROJECT: Projects/portfolio section
- PHONE: Phone number section
- LEGAL_NAME: Legal name section
- OTHER: Other sections not covered above

**Completed Sections:**
{completed_sections}

**Instructions:**

1. Examine the browser state (DOM structure and interactive elements) to identify logical groupings of form fields
2. Look for explicit section headers, fieldset elements, or visual groupings
3. If no explicit grouping exists, create logical groupings based on field proximity and semantic meaning
4. Identify the next section that needs attention (not yet completed)
5. Return the section type, name (if present), section_index, element_indices, and completion status

**Important:**

- Only identify sections that are currently visible on the page
- Skip sections that are already completed (check completed_sections list)
- If all sections are complete, return null

Return the next section that needs to be filled, or null if all sections are complete.
