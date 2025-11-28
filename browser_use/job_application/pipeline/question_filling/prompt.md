You are filling a form question.

<question_details>

- Question: "{question_text}"
- Answer Value: "{answer_value}"
- Question Type: {question_type}
- Element Index: {element_index}
- Required: {is_required}
- Options: {options}
  </question_details>

<instructions>
1. Locate the form field with element index {element_index} in the browser state
2. Examine the element's tag name and role attribute in the browser state to determine its actual type:
   - If tag is "select": This is a native HTML dropdown - use select_dropdown action
   - If tag is "input" with role="combobox" or type="text": This is a custom combobox - use input action to type the value
   - If tag is "input" with type="file": Use upload_file action
   - If tag is "input" with type="checkbox": Use click action
   - If tag is "textarea": Use input action
3. Fill it with the answer value: "{answer_value}"
4. Handle the field type appropriately:
   - TEXT/TEXTAREA: Use input action with element index and the answer text
   - SINGLE_SELECT/MULTI_SELECT: 
     * For native <select> elements (tag="select"): Use select_dropdown action to select the option matching the answer value. If dropdown needs to be opened first, use click then select_dropdown
     * For custom comboboxes (tag="input" with role="combobox"): Use input action to type the answer value. If the dropdown needs to be opened first, use click then input
   - FILE: Use upload_file action with element index and file path from answer_value
   - BOOLEAN: Use click action to check/uncheck based on answer value
5. If the field needs to be cleared first, use input with clear=True
6. Select 1-3 actions as needed to complete the fill
7. Verify the field was filled correctly after actions
</instructions>

<important>
- Use the exact element index: {element_index}
- Use the exact answer value: "{answer_value}"
- CRITICAL: Check the element's tag name in the browser state before choosing actions
- For native <select> elements (tag="select"): Use select_dropdown action
- For custom comboboxes (tag="input" with role="combobox"): Use input action to type the value, NOT select_dropdown
- For select dropdowns, match the answer value to one of the available options
- For file uploads, ensure the file path exists and is accessible
- If validation errors appear, read them and adjust accordingly
</important>

Return your selected actions to fill this question.
