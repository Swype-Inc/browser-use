You are checking if a form question has been filled correctly.

<question_details>

- Question: "{question_text}"
- Expected Answer Value: "{answer_value}"
- Question Type: {question_type}
- Element Index: {element_index}
  </question_details>

<instructions>
1. Locate the form field with element index {element_index} in the browser state
2. Check if the field has been filled with the expected answer value: "{answer_value}"
3. For different field types:
   - TEXT/TEXTAREA: Check if the input value matches (or contains) the expected answer
   - SINGLE_SELECT/MULTI_SELECT: Check if the selected option(s) match the expected answer
   - FILE: Check if a file has been uploaded (file inputs typically show a filename)
   - BOOLEAN: Check if checkbox/toggle matches the expected answer (true/false, yes/no)
4. Return True if the field is filled correctly, False otherwise
</instructions>

Return True if the question is filled correctly, False otherwise.
