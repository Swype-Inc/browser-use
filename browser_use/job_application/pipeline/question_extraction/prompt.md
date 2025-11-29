You are extracting the NEXT question from an application section that needs to be filled.

<question_types>

- SINGLE_SELECT: Dropdown or radio button group (select one option)
- MULTI_SELECT: Checkbox group or multi-select dropdown (select multiple options)
- TEXT: Single-line text input
- TEXTAREA: Multi-line text input
- BOOLEAN: Yes/No checkbox or toggle
- FILE: File upload input (for resumes, cover letters, etc.)
  </question_types>

<section_information>
Type: {section_type}
Name: {section_name}
Element Indices: {section_element_indices}
</section_information>

<all_questions_in_section>
{question_texts}
</all_questions_in_section>

<already_filled_questions>
{filled_questions}
</already_filled_questions>

<instructions>
1. A screenshot of the current page is provided. Use it as your primary source for detecting question types and understanding the visual layout of form fields.

2. Review the already_filled_questions above to see which questions have already been filled in this section.

3. Find the NEXT question in DOM order from the all_questions_in_section list that has NOT been filled yet. This must be the next consecutive question in the DOM that logically belongs to this section.

4. The question you extract must:

   - Be in the all_questions_in_section list
   - NOT be in the already_filled_questions list
   - Be the next question in DOM order after the last filled question (or the first question if none are filled)
   - Logically belong to this section (use the screenshot to verify visual grouping)

5. For the question you find, extract:

   - Question text (label, placeholder, aria-label, or nearby text)
   - Whether it's required (asterisk visible in screenshot, "required" attribute, validation)
   - Question type (TEXT, TEXTAREA, SINGLE_SELECT, MULTI_SELECT, BOOLEAN, FILE) - use screenshot to verify the visual appearance matches the type
   - Element index (backend_node_id) - CRITICAL: This MUST be the backend_node_id of the actual interactive element (input, select, textarea, file input), NOT a parent container (form, div, fieldset, etc.). Look for the element with the tag name matching the question type (input for TEXT/FILE, select for SINGLE_SELECT/MULTI_SELECT, textarea for TEXTAREA). The element_index is the number in square brackets [N] before the element tag in the browser state.
   - Options (if select type) - list all available options visible in screenshot or DOM
   - Validation pattern (if visible in DOM)
   - Dependencies (if question only appears conditionally)

6. Provide a rationale explaining:

   - Why this specific question was selected (confirmation it's the next unfilled question in DOM order)
   - What element_index was chosen and why (describe the element tag, id, aria-label, or other identifying attributes)
   - How the element_index relates to the question text in the DOM (e.g., "Element index 10 corresponds to the input element with id='first_name' and aria-label='First Name', which is the actual form field for the 'First Name' question")
   - Confirmation that the element_index is the actual interactive element, not a parent container

7. Cross-reference the DOM structure with the screenshot to visually identify the field type:

   - Look at the screenshot to see what the field actually looks like (dropdown arrow, checkbox, text input, file upload button, etc.)
   - Use the visual appearance from the screenshot to determine the question type, especially for custom-styled form fields
   - The DOM may show generic input types, but the screenshot reveals the actual UI component

8. If all questions in the section have been filled, set no_more_questions=True and return null for the question field.
   </instructions>

<important>
- The screenshot is your most reliable source for detecting question types, especially for custom-styled form fields
- Some form fields may appear as generic inputs in DOM but are visually styled as dropdowns, comboboxes, or other components - use the screenshot to identify the actual type
- You must extract the NEXT question in DOM order that hasn't been filled yet
- Do NOT skip questions - go sequentially through the all_questions_in_section list
- The question must logically belong to this section (use screenshot to verify visual grouping)
- CRITICAL: The element_index MUST be the backend_node_id of the actual interactive element (input, select, textarea), NOT a parent container like form, div, fieldset, or label. Look for the element tag that matches the question type.
- For select types, list all available options if visible in screenshot or DOM
- If options are truncated or hidden, set options_complete=False
- Include element indices for all interactive elements in the question
- When in doubt about question type, rely on the visual appearance in the screenshot rather than just DOM attributes
- Always provide a detailed rationale explaining your element_index choice
</important>

Return the next question to fill in this section, or set no_more_questions=True if all questions are filled.
