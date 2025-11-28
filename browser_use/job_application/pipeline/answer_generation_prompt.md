# Answer Generation Task

You are helping to fill out a job application form. Given a question and the user's profile information, generate an appropriate answer.

## Question Details

**Question:** {question_text}
**Type:** {question_type}
**Required:** {is_required}
**Validation Pattern:** {validation_pattern}

## Available Options (if applicable)

{options}

## User Profile

```json
{user_profile}
```

## Instructions

1. Generate an answer that matches the question type:
   - **TEXT**: Provide a text answer based on user profile
   - **EMAIL**: Use the user's email address
   - **PHONE**: Use the user's phone number
   - **DATE**: Provide a date in the appropriate format
   - **NUMBER**: Provide a numeric value
   - **SINGLE_SELECT**: Choose one option from the available options
   - **MULTI_SELECT**: Choose one or more options from the available options
   - **YES_NO**: Answer "Yes" or "No" based on user profile
   - **FILE**: This will be handled separately, return a placeholder

2. For select-type questions, choose the option that best matches the user's profile information.

3. If the question asks for information not in the user profile, make a reasonable inference based on available data.

4. For required questions, always provide an answer. For optional questions, you may leave blank if truly not applicable.

5. Ensure the answer matches any validation patterns specified.

6. For demographic questions (race, gender, veteran status, disability), use the information from the user profile.

7. For work authorization questions, use the work_authorizations from the user profile.

8. For address-related questions, use the location information from the user profile.

9. For name fields, use the appropriate name from the user profile (first_name, last_name, preferred_name, etc.).

10. For work experience questions, reference the work_experiences array from the user profile.

11. For education questions, reference the educations array from the user profile.

12. For skills questions, reference the skills array from the user profile.

Return your answer in the specified format.

