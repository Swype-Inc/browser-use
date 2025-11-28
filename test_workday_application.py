"""
Test script to fill out a Workday job application using browser-use.

Usage:
    python test_workday_application.py

Make sure you have OpenAI env vars set:
    OPENAI_API_KEY (required)
    OPENAI_MODEL (optional, defaults to gpt-4o-mini)
    RESUME_API_KEY (optional, for downloading resume from API)
"""
import asyncio
import os
import sys
import json
from pathlib import Path

# Add browser-use to path
browser_use_dir = Path(__file__).parent
sys.path.insert(0, str(browser_use_dir))

from dotenv import load_dotenv
load_dotenv()

from browser_use import Agent, Browser, Tools
from browser_use.llm import ChatOpenAI
from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from pydantic import BaseModel, Field
import httpx


# User data - will be loaded from JSON file or set here
USER_DATA = None  # Will be set from JSON file or you can paste it here

# Job application URL
# JOB_URL = "https://terminix.wd1.myworkdayjobs.com/WesternExterminator/job/RNA-Anaheim-151/Manager-Operations_R-060331-2"

JOB_URL = "https://job-boards.greenhouse.io/genevatrading/jobs/4853820007"

# Resume download endpoint base URL
RESUME_ENDPOINT_BASE = "https://sought-really-pony.ngrok-free.app/api/files/internal"

# Email proxy service endpoint
PROXY_EMAIL_SERVICE_URL = "https://oneclickbackend-proxyservice.vercel.app"
PROXY_SERVICE_HEADERS = {
    'Content-Type': 'application/json',
    'auth': 'ireallydonotknowwhattosayhere1999'
}


# Parameter models for email tools
class GetSecurityCodesParams(BaseModel):
    proxy_email: str = Field(description="The proxy email address to check for security codes")
    btn_click_time: str = Field(description="Timestamp when the button was clicked (ISO format or Unix timestamp)")
    company_name: str = Field(description="Name of the company (for Workday, can be extracted from URL)")
    ats: str = Field(default="workday", description="ATS type, typically 'workday' for Workday applications")


class FindConfirmationLinkParams(BaseModel):
    proxy_email: str = Field(description="The proxy email address to check for confirmation links")
    btn_click_time: str = Field(description="Timestamp when the button was clicked (ISO format or Unix timestamp)")
    workday_app_url: str = Field(description="The Workday application URL to match against")


class FindPasswordResetLinkParams(BaseModel):
    proxy_email: str = Field(description="The proxy email address to check for password reset links")
    btn_click_time: str = Field(description="Timestamp when the button was clicked (ISO format or Unix timestamp)")
    workday_app_url: str = Field(description="The Workday application URL to match against")


def extract_user_info(user_data: dict) -> dict:
    """Extract user information from nested structure"""
    user = user_data.get('user', {})
    personal = user.get('personal', {})
    identity = personal.get('identity', {})
    demographics = personal.get('demographics', {})
    professional = user.get('professional', {})
    resume = professional.get('resume', {})
    
    # Extract name
    first_name = identity.get('FIRST_NAME', '')
    last_name = identity.get('LAST_NAME', '')
    middle_name = identity.get('MIDDLE_NAME', '')
    preferred_name = identity.get('PREFERRED_NAME', '')
    full_name = f"{first_name} {middle_name} {last_name}".strip() if middle_name else f"{first_name} {last_name}".strip()
    display_name = preferred_name or full_name
    
    # Extract location
    location = identity.get('USER_LOCATION', {})
    
    # Extract work experience
    work_experiences = resume.get('WORK_EXPERIENCES', [])
    
    # Extract education
    educations = resume.get('EDUCATIONS', [])
    
    # Extract skills
    skills = resume.get('SKILLS', [])
    
    return {
        'first_name': first_name,
        'last_name': last_name,
        'middle_name': middle_name,
        'preferred_name': preferred_name,
        'full_name': full_name,
        'display_name': display_name,
        'email': identity.get('EMAIL', ''),
        'phone': identity.get('PHONE_NUMBER', ''),
        'city': location.get('USER_LOCATION_CITY', ''),
        'state': location.get('USER_LOCATION_STATE', ''),
        'zip': location.get('USER_LOCATION_ZIP_CODE', ''),
        'country': location.get('USER_LOCATION_COUNTRY', ''),
        'address': location.get('USER_LOCATION_STREET_ADDRESS', ''),
        'date_of_birth': identity.get('DATE_OF_BIRTH', {}),
        'gender': demographics.get('GENDER', ''),
        'age_bracket': demographics.get('AGE_BRACKET', ''),
        'veteran': demographics.get('VETERAN', ''),
        'disability': demographics.get('DISABILITY', ''),
        'races': demographics.get('RACES', {}),
        'work_experiences': work_experiences,
        'educations': educations,
        'skills': skills,
        'linkedin': resume.get('LINKEDIN_URL', ''),
        'github': resume.get('GITHUB_URL', ''),
        'portfolio': resume.get('PORTFOLIO_URL', ''),
        'work_authorizations': professional.get('workAuthorizations', []),
        'resume_file': user_data.get('documents', {}).get('primary', {}).get('RESUME', {}).get('name', ''),
        'resume_id': user_data.get('documents', {}).get('primary', {}).get('RESUME', {}).get('id', ''),
    }


def build_task_from_user_data(user_data: dict) -> str:
    """Build a task description with only user information (no workflow instructions)"""
    
    info = extract_user_info(user_data)
    
    task = f"""Job Application URL: {JOB_URL}

User Information:

Personal Information:
- First Name: {info['first_name']}
- Last Name: {info['last_name']}
- Full Name: {info['full_name']}
- Email: {info['email']}
- Phone: {info['phone']}
- City: {info['city']}
- State: {info['state']}
- ZIP Code: {info['zip']}
- Country: {info['country']}

password to use: ObaMa!2025
account exists: True
"""
    
    if info['address']:
        task += f"- Street Address: {info['address']}\n"
    
    # Date of birth
    dob = info['date_of_birth']
    if dob.get('day') and dob.get('month') and dob.get('year'):
        task += f"- Date of Birth: {dob['month']}/{dob['day']}/{dob['year']}\n"
    
    # Demographics
    task += f"\nDemographics:\n"
    task += f"- Gender: {info['gender']}\n"
    if info['age_bracket']:
        task += f"- Age Bracket: {info['age_bracket']}\n"
    task += f"- Veteran Status: {info['veteran']}\n"
    task += f"- Disability Status: {info['disability']}\n"
    
    # Race/Ethnicity
    races = info['races']
    if races:
        selected_races = [k for k, v in races.items() if v]
        if selected_races:
            task += f"- Race/Ethnicity: {', '.join(selected_races)}\n"
    
    # Work Experience
    if info['work_experiences']:
        task += "\nWork Experience:\n"
        for idx, exp in enumerate(info['work_experiences'][:5], 1):
            title = exp.get('TITLE', '')
            company = exp.get('COMPANY', '')
            location = exp.get('LOCATION', '')
            start = exp.get('START_DATE', {})
            end = exp.get('END_DATE', {})
            currently_employed = exp.get('CURRENTLY_EMPLOYED', False)
            
            start_str = f"{start.get('month', '')}/{start.get('year', '')}" if start.get('month') else ""
            end_str = "Present" if currently_employed else (f"{end.get('month', '')}/{end.get('year', '')}" if end.get('month') else "")
            
            task += f"{idx}. {title} at {company}"
            if location:
                task += f" ({location})"
            if start_str:
                task += f" - {start_str} to {end_str}"
            task += "\n"
            
            # Add responsibilities
            responsibilities = exp.get('RESPONSIBILITIES', [])
            if responsibilities:
                for resp in responsibilities[:2]:  # Limit to 2 per job
                    task += f"   • {resp}\n"
    
    # Education
    if info['educations']:
        task += "\nEducation:\n"
        for edu in info['educations'][:3]:
            institution = edu.get('INSTITUTION', '')
            degree = edu.get('DEGREE', '').replace('_', ' ').title()
            majors = edu.get('MAJORS', [])
            completion = edu.get('COMPLETION_DATE', {})
            location = edu.get('LOCATION', '')
            
            task += f"- {degree}"
            if majors:
                task += f" in {', '.join(majors)}"
            task += f" from {institution}"
            if location:
                task += f" ({location})"
            if completion.get('year'):
                task += f" - Graduated {completion['year']}"
            task += "\n"
    
    # Skills
    if info['skills']:
        skills_str = ', '.join(info['skills'][:15])
        task += f"\nSkills: {skills_str}\n"
    
    # Links
    if info['linkedin']:
        task += f"- LinkedIn: {info['linkedin']}\n"
    if info['github']:
        task += f"- GitHub: {info['github']}\n"
    if info['portfolio']:
        task += f"- Portfolio: {info['portfolio']}\n"
    
    # Work Authorization
    work_auths = info['work_authorizations']
    us_auth = None
    if work_auths:
        task += "\nWork Authorization:\n"
        for auth in work_auths:
            country = auth.get('COUNTRY', '')
            status = auth.get('STATUS', {})
            if country == 'United States':
                us_auth = status
            if status.get('CITIZEN'):
                task += f"- Citizen of {country}\n"
            elif status.get('AUTHORIZED_WORKER'):
                task += f"- Authorized to work in {country}\n"
            if status.get('NEEDS_EMPLOYER_SPONSORSHIP'):
                task += f"- Needs sponsorship: Yes\n"
            else:
                task += f"- Needs sponsorship: No\n"
    
    # Special notes specific to this user's data
    task += "\nSpecial Notes:\n"
    task += "- For \"Currently Employed\" questions, mark the Operations Manager position as current (Present)\n"
    task += "- For previous employment, mark Business Analyst as ended in 02/2021\n"
    
    return task


async def main(user_data: dict):
    print("🤖 Starting browser-use agent for Workday job application...")
    print(f"📍 Job URL: {JOB_URL}")
    
    # Extract user name for display
    info = extract_user_info(user_data)
    print(f"👤 User: {info['full_name']} ({info['email']})")
    print()
    
    # Initialize OpenAI LLM
    # Debug: Print environment variables to verify they're loaded
    print("🔍 Debug - Environment Variables:")
    print(f"  API Key: {'SET' if os.getenv('OPENAI_API_KEY') else 'NOT SET'}")
    print()

    # Initialize OpenAI LLM
    llm = ChatOpenAI(
        model=os.getenv('OPENAI_MODEL', 'gpt-4o-mini'),
        api_key=os.getenv('OPENAI_API_KEY'),
    )
    
    # Initialize tools and add custom resume download tool
    tools = Tools()
    resume_id = info.get('resume_id', '793667')
    resume_filename = info.get('resume_file', 'Obama_Osama_resume.pdf')
    
    @tools.action('Download resume file from the API endpoint. Use this when you need to upload the resume.')
    async def download_resume(browser_session: BrowserSession):
        """Download resume from API endpoint"""
        resume_url = f"{RESUME_ENDPOINT_BASE}/{resume_id}"
        
        # Get API key from environment if available
        api_key = os.getenv('RESUME_API_KEY')
        print(f"🔍 Debug - Resume API Key: {api_key}")
        headers = {}
        if api_key:
            headers['X-Api-Key'] = api_key
        
        try:
            # Download the file
            async with httpx.AsyncClient() as client:
                response = await client.get(resume_url, headers=headers)
                response.raise_for_status()
                
                # Save to a temporary location
                temp_dir = Path('/tmp')
                temp_dir.mkdir(exist_ok=True)
                file_path = temp_dir / resume_filename
                
                with open(file_path, 'wb') as f:
                    f.write(response.content)
                
                # Add to browser session's downloaded files
                browser_session.downloaded_files.append(str(file_path))
                
                return ActionResult(
                    extracted_content=f"Resume downloaded successfully to {file_path}. Use upload_file action with path: {file_path}",
                    include_in_memory=True
                )
        except Exception as e:
            return ActionResult(error=f"Failed to download resume: {str(e)}")
    
    @tools.action(
        'Get security codes from email for Workday verification. Use this when Workday asks for a security code sent to your email.',
        param_model=GetSecurityCodesParams,
    )
    async def get_security_codes(params: GetSecurityCodesParams):
        """Get security codes from email proxy service"""
        try:
            url = f"{PROXY_EMAIL_SERVICE_URL}/find_security_codes"
            payload = {
                "ats_type": params.ats,
                "company_name": params.company_name,
                "proxy_email": params.proxy_email,
                "search_start_time": params.btn_click_time
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=PROXY_SERVICE_HEADERS, timeout=30.0)
                response.raise_for_status()
                result = response.json()
            
            if result.get('error'):
                return ActionResult(error=f"Failed to get security codes: {result.get('error')}")
            
            security_codes = result.get('security_codes', [])
            if not security_codes:
                return ActionResult(
                    extracted_content="No security codes found in email yet. Wait a moment and try again.",
                    long_term_memory="Attempted to get security codes but none found"
                )
            
            codes_str = ", ".join(security_codes)
            return ActionResult(
                extracted_content=f"Found security codes: {codes_str}. Use the most recent code.",
                long_term_memory=f"Retrieved security codes: {codes_str}"
            )
        except Exception as e:
            return ActionResult(error=f"Failed to get security codes: {str(e)}")
    
    @tools.action(
        'Find Workday confirmation link from email. Use this when Workday sends a confirmation email that needs to be clicked.',
        param_model=FindConfirmationLinkParams,
    )
    async def find_confirmation_link(params: FindConfirmationLinkParams):
        """Find Workday confirmation link from email"""
        try:
            url = f"{PROXY_EMAIL_SERVICE_URL}/find_workday_confirmation_link"
            payload = {
                "proxy_email": params.proxy_email,
                "search_start_time": params.btn_click_time,
                "workday_app_url": params.workday_app_url
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=PROXY_SERVICE_HEADERS, timeout=30.0)
                response.raise_for_status()
                result = response.json()
            
            if result.get('error'):
                return ActionResult(error=f"Failed to find confirmation link: {result.get('error')}")
            
            links = result.get('links', [])
            if not links:
                return ActionResult(
                    extracted_content="No confirmation link found in email yet. Wait a moment and try again.",
                    long_term_memory="Attempted to find confirmation link but none found"
                )
            
            # Return the first/most recent link
            confirmation_link = links[0] if isinstance(links, list) else links
            return ActionResult(
                extracted_content=f"Found confirmation link: {confirmation_link}. Use navigate action to open this URL.",
                long_term_memory=f"Found Workday confirmation link: {confirmation_link}"
            )
        except Exception as e:
            return ActionResult(error=f"Failed to find confirmation link: {str(e)}")
    
    @tools.action(
        'Find Workday password reset link from email. Use this when Workday sends a password reset email that needs to be clicked.',
        param_model=FindPasswordResetLinkParams,
    )
    async def find_password_reset_link(params: FindPasswordResetLinkParams):
        """Find Workday password reset link from email"""
        try:
            url = f"{PROXY_EMAIL_SERVICE_URL}/find_workday_reset_password_link"
            payload = {
                "proxy_email": params.proxy_email,
                "search_start_time": params.btn_click_time,
                "workday_app_url": params.workday_app_url
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=PROXY_SERVICE_HEADERS, timeout=30.0)
                response.raise_for_status()
                result = response.json()
            
            if result.get('error'):
                return ActionResult(error=f"Failed to find password reset link: {result.get('error')}")
            
            links = result.get('links', [])
            if not links:
                return ActionResult(
                    extracted_content="No password reset link found in email yet. Wait a moment and try again.",
                    long_term_memory="Attempted to find password reset link but none found"
                )
            
            # Return the first/most recent link
            reset_link = links[0] if isinstance(links, list) else links
            return ActionResult(
                extracted_content=f"Found password reset link: {reset_link}. Use navigate action to open this URL.",
                long_term_memory=f"Found Workday password reset link: {reset_link}"
            )
        except Exception as e:
            return ActionResult(error=f"Failed to find password reset link: {str(e)}")
    
    # Build task from user data
    task = build_task_from_user_data(user_data)
    
    # Extract email and password for account creation
    # Email is already extracted in info
    user_email = info.get('email', '')
    # Password is currently hardcoded in build_task_from_user_data
    # TODO: Extract password from user_data if it becomes available
    user_password = "ObaMa!2025"
    
    print("📋 Task:")
    print(task)
    print()
    
    # Create browser instance
    browser = Browser()
    
    # Create agent (system prompt is now self-contained in system_prompt.md)
    agent = Agent(
        task=task,
        llm=llm,
        browser=browser,
        tools=tools,
        max_steps=50,  # Allow more steps for complex forms
        email=user_email,
        password=user_password,
        user_profile=info,  # Pass extracted user profile data
    )
    
    # Run agent
    print("🚀 Running agent...")
    history = await agent.run()
    
    print("\n✅ Agent completed!")
    print(f"\n📊 Final Result:")
    if hasattr(history, 'extracted_content') and history.extracted_content:
        print(history.extracted_content)
    else:
        print("Check agent history for details")
    
    # Print summary
    if hasattr(history, 'history'):
        print(f"\n📈 Steps taken: {len(history.history)}")
        print("\nLast few steps:")
        for step in history.history[-5:]:
            if hasattr(step, 'model_output') and step.model_output:
                actions = step.model_output.action
                if actions:
                    for action in actions:
                        action_dict = action.model_dump(exclude_unset=True)
                        for action_name, params in action_dict.items():
                            if params:
                                print(f"  - {action_name}: {params}")


def load_user_data(json_path: str | None = None) -> dict | None:
    """Load user data from JSON file or use inline data"""
    if json_path and os.path.exists(json_path):
        with open(json_path, 'r') as f:
            return json.load(f)
    return USER_DATA


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Fill out Workday job application')
    parser.add_argument('--user-data', type=str, help='Path to JSON file with user data')
    parser.add_argument('--user-json', type=str, help='Inline JSON string with user data')
    args = parser.parse_args()
    
    # Load user data
    user_data = None
    if args.user_data:
        user_data = load_user_data(args.user_data)
    elif args.user_json:
        user_data = json.loads(args.user_json)
    elif USER_DATA is not None:
        user_data = USER_DATA
    
    if user_data is None:
        print("⚠️  No user data provided!")
        print("   Usage options:")
        print("   1. python test_workday_application.py --user-data path/to/user.json")
        print("   2. python test_workday_application.py --user-json '{\"name\": \"...\", ...}'")
        print("   3. Update USER_DATA in the script directly")
        print()
        print("Ready for your user JSON! Provide it via --user-data or --user-json flag.")
        sys.exit(1)
    
    asyncio.run(main(user_data))

