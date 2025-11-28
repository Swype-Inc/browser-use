You are extracting questions from an application section.

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

<questions_to_extract>
{question_texts}
</questions_to_extract>

<instructions>
1. A screenshot of the current page is provided. Use it as your primary source for detecting question types and understanding the visual layout of form fields.
2. You must only extract details for the questions listed above
3. For each question text listed, find the corresponding form field in the browser state (DOM structure)
4. Cross-reference the DOM structure with the screenshot to visually identify the field type:
   - Look at the screenshot to see what the field actually looks like (dropdown arrow, checkbox, text input, file upload button, etc.)
   - Use the visual appearance from the screenshot to determine the question type, especially for custom-styled form fields
   - The DOM may show generic input types, but the screenshot reveals the actual UI component
5. For each question, extract:
   - Question text (label, placeholder, aria-label, or nearby text)
   - Whether it's required (asterisk visible in screenshot, "required" attribute, validation)
   - Question type (TEXT, TEXTAREA, SINGLE_SELECT, MULTI_SELECT, BOOLEAN, FILE) - use screenshot to verify the visual appearance matches the type
   - Element index (backend_node_id)
   - Options (if select type) - list all available options visible in screenshot or DOM
   - Validation pattern (if visible in DOM)
   - Dependencies (if question only appears conditionally)
6. Group related fields that form a single logical question (e.g., "First Name" + "Last Name" = "Full Name")
7. You must extract the questions sequentially. Don't jump around. Go in order, from top of the application to the bottom.
8. Be very thorough. Find all the questions in this section.
9. All the questions in this section should be contiguous
</instructions>

<important>
- The screenshot is your most reliable source for detecting question types, especially for custom-styled form fields
- Some form fields may appear as generic inputs in DOM but are visually styled as dropdowns, comboboxes, or other components - use the screenshot to identify the actual type
- Extract ALL questions in the section, not just required ones
- Do not combine any questions into one. each of these questions is a standalone directly from the DOM.
- For select types, list all available options if visible in screenshot or DOM
- If options are truncated or hidden, set options_complete=False
- Include element indices for all interactive elements in the question
- When in doubt about question type, rely on the visual appearance in the screenshot rather than just DOM attributes
</important>

Return a list of all questions found in this section.
