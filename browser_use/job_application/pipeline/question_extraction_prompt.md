You are extracting questions from an application section.

**Question Types:**

- SINGLE_SELECT: Dropdown or radio button group (select one option)
- MULTI_SELECT: Checkbox group or multi-select dropdown (select multiple options)
- TEXT: Single-line text input
- TEXTAREA: Multi-line text input
- BOOLEAN: Yes/No checkbox or toggle

**Section Information:**
Type: {section_type}
Name: {section_name}
Element Indices: {section_element_indices}

**Questions to Extract:**
{question_texts}

**Instructions:**

1. Focus on extracting details for the questions listed above
2. For each question text listed, find the corresponding form field in the browser state
3. For each question, extract:
   - Question text (label, placeholder, aria-label, or nearby text)
   - Whether it's required (asterisk, "required" attribute, validation)
   - Question type (TEXT, TEXTAREA, SINGLE_SELECT, MULTI_SELECT, BOOLEAN)
   - Element index (backend_node_id)
   - Options (if select type) - list all available options
   - Validation pattern (if visible in DOM)
   - Dependencies (if question only appears conditionally)
4. Group related fields that form a single logical question (e.g., "First Name" + "Last Name" = "Full Name")
5. You must extract the questions sequentially. Don't jump around. Go in order, from top of the application to the bottom.
6. Be very thorough. Find all the questions in this section.
7. All the questions in this section should be contiguous

**Important:**

- Extract ALL questions in the section, not just required ones
- For select types, list all available options if visible
- If options are truncated or hidden, set options_complete=False
- Include element indices for all interactive elements in the question

Return a list of all questions found in this section.
