You are filling a form question. First, check if it's already filled. If not, select actions to fill it.

<question_details>

- Question: "{question_text}"
- Answer Value: "{answer_value}"
- Question Type: {question_type}
- Element Index: {element_index}
- Required: {is_required}
- Options: {options}
  </question_details>

<instructions>
1. A screenshot of the current page is provided. Use it as your primary source for verifying if the field is filled and understanding the visual layout.

2. FIRST: Check if the question is already filled correctly:

   - Locate the form field with element index {element_index} in the browser state (DOM structure)
   - Cross-reference the DOM structure with the screenshot to find the actual visual field on the page
   - Check if the field has been filled with the expected answer value: "{answer_value}"
   - For different field types:
     - TEXT/TEXTAREA: Check if the input value matches (or contains) the expected answer. Look at the screenshot to see if text is visible in the field.
     - SINGLE_SELECT/MULTI_SELECT: Check if the selected option(s) match the expected answer. Use the screenshot to see what's actually selected.
     - FILE: Check if a file has been uploaded (file inputs typically show a filename). The screenshot will show if a file name appears.
     - BOOLEAN: Check if checkbox/toggle matches the expected answer (true/false, yes/no). The screenshot will show the visual state.
   - If the DOM structure doesn't clearly show the value (e.g., JavaScript-managed fields), rely primarily on the screenshot to determine if the field is filled.
   - Set is_filled=True if the field is correctly filled, False otherwise
   - Provide brief reasoning explaining your assessment

3. IF NOT FILLED: Select actions to fill the question:

   - Examine the element's tag name and role attribute in the browser state to determine its actual type:
     - If tag is "select": This is a native HTML dropdown - use select_dropdown action
     - If tag is "input" with role="combobox" or type="text": This is a custom combobox - use input action to type the value
     - If tag is "input" with type="file": Use upload_file action
     - If tag is "input" with type="checkbox": Use click action
     - If tag is "textarea": Use input action
   - Handle the field type appropriately:
     - TEXT/TEXTAREA: Use input action with element index and the answer text
     - SINGLE_SELECT/MULTI_SELECT:
       - For native <select> elements (tag="select"): Use select_dropdown action to select the option matching the answer value. If dropdown needs to be opened first, use click then select_dropdown
       - For custom comboboxes (tag="input" with role="combobox"): Use input action to type the answer value. If the dropdown needs to be opened first, use click then input
     - FILE: Use upload_file action with element index and file path from answer_value
     - BOOLEAN: Use click action to check/uncheck based on answer value
   - If the field needs to be cleared first, use input with clear=True
   - Select 1-3 actions as needed to complete the fill

4. IF ALREADY FILLED: Return an empty actions list (no actions needed)
   </instructions>

<important>
- The screenshot is your most reliable source of truth, especially for JavaScript-managed form fields
- Some form fields may have values in JavaScript state that aren't reflected in the DOM attributes - always verify visually using the screenshot
- Use the exact element index: {element_index}
- Use the exact answer value: "{answer_value}"
- CRITICAL: Check the element's tag name in the browser state before choosing actions
- For native <select> elements (tag="select"): Use select_dropdown action
- For custom comboboxes (tag="input" with role="combobox"): Use input action to type the value, NOT select_dropdown
- For select dropdowns, match the answer value to one of the available options
- For file uploads, ensure the file path exists and is accessible
- If validation errors appear, read them and adjust accordingly
</important>

Return your assessment (is_filled, reasoning) and selected actions to fill this question.
