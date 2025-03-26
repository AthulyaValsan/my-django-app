import os
import requests
import json
import base64
import google.generativeai as genai
from github import Github
from datetime import datetime

# Environment variables for configuration
SENTRY_TOKEN = os.environ.get("SENTRY_TOKEN")
SENTRY_ORG = os.environ.get("SENTRY_ORG")
SENTRY_PROJECT = os.environ.get("SENTRY_PROJECT")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Initialize clients
github_client = Github(GITHUB_TOKEN)

# Configure Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-pro-latest')

def get_recent_sentry_issues():
    """Fetch recent unresolved issues from Sentry"""
    url = f"https://sentry.io/api/0/projects/{SENTRY_ORG}/{SENTRY_PROJECT}/issues/?query=is:unresolved"
    
    headers = {
        "Authorization": f"Bearer {SENTRY_TOKEN}",
        "Content-Type": "application/json"
    }
    
    # Debug logging
    print(f"Making request to Sentry API:")
    print(f"URL: {url}")
    print(f"Organization: {SENTRY_ORG}")
    print(f"Project: {SENTRY_PROJECT}")
    print(f"Token (first 10 chars): {SENTRY_TOKEN[:10] if SENTRY_TOKEN else 'None'}...")
    
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        print(f"Error response from Sentry API: {response.status_code}")
        print(f"Response body: {response.text}")
    
    response.raise_for_status()
    
    return response.json()

def get_issue_details(issue_id):
    """Get detailed information about a specific issue"""
    url = f"https://sentry.io/api/0/issues/{issue_id}/events/latest/"
    
    headers = {
        "Authorization": f"Bearer {SENTRY_TOKEN}",
        "Content-Type": "application/json"
    }
    
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    
    return response.json()

def get_file_content(file_path):
    """Get the content of a file from GitHub"""
    repo = github_client.get_repo(GITHUB_REPO)
    
    try:
        file_content = repo.get_contents(file_path)
        return base64.b64decode(file_content.content).decode('utf-8'), file_content.sha
    except Exception as e:
        print(f"Error getting file content: {e}")
        return None, None

def extract_stack_context(event_data):
    """Extract relevant code context from the stack trace"""
    frames = event_data.get('entries', [])[0].get('data', {}).get('values', [])[0].get('stacktrace', {}).get('frames', [])
    
    if not frames:
        return None, None
    
    # Get the frame where the exception occurred (usually the last one)
    relevant_frame = frames[-1]
    file_path = relevant_frame.get('filename')
    line_number = relevant_frame.get('lineno')
    
    # Get context lines if available
    context_lines = relevant_frame.get('context_line', '')
    pre_context = relevant_frame.get('pre_context', [])
    post_context = relevant_frame.get('post_context', [])
    
    return {
        'file_path': file_path,
        'line_number': line_number,
        'context_line': context_lines,
        'pre_context': pre_context,
        'post_context': post_context,
        'function': relevant_frame.get('function', '')
    }, file_path

def create_ai_fix(error_message, file_content, context_info):
    """Use Gemini to generate a fix"""
    if not context_info or not file_content:
        return None
    
    # Pre-join the context lines
    pre_context_text = "\n".join(context_info['pre_context'])
    post_context_text = "\n".join(context_info['post_context'])
    
    prompt = f"""
    You are an expert Python developer tasked with fixing a bug in a codebase.
    
    ERROR MESSAGE:
    {error_message}
    
    FILE: {context_info['file_path']}
    FUNCTION: {context_info['function']}
    LINE NUMBER: {context_info['line_number']}
    
    Here's the context of the error:
    
    Pre-context lines:
    ```
    {pre_context_text}
    ```
    
    Line with error:
    ```
    {context_info['context_line']}
    ```
    
    Post-context lines:
    ```
    {post_context_text}
    ```
    
    Here's the full file content:
    ```python
    {file_content}
    ```
    
    Please provide a fix for this issue. Explain what's causing the error and provide the corrected code.
    Return your response in the following format:
    
    EXPLANATION:
    [Explanation of the issue and your fix]
    
    FIXED_CODE:
    [The entire fixed file with your changes]
    """
    
    try:
        response = model.generate_content(prompt)
        ai_response = response.text
        
        # Extract the explanation and fixed code from the AI response
        try:
            explanation = ai_response.split("EXPLANATION:")[1].split("FIXED_CODE:")[0].strip()
            fixed_code = ai_response.split("FIXED_CODE:")[1].strip()
            
            # Remove the code block markers if present
            if fixed_code.startswith("```python"):
                fixed_code = fixed_code[10:].strip()
            if fixed_code.startswith("```"):
                fixed_code = fixed_code[3:].strip()
            if fixed_code.endswith("```"):
                fixed_code = fixed_code[:-3].strip()
                
            return {
                "explanation": explanation,
                "fixed_code": fixed_code
            }
        except Exception as e:
            print(f"Error parsing AI response: {e}")
            print(f"Raw AI response: {ai_response}")
            return None
    except Exception as e:
        print(f"Error generating AI fix: {e}")
        return None

def create_github_pr(file_path, original_content_sha, fixed_code, issue_details, explanation):
    """Create a GitHub PR with the fix"""
    repo = github_client.get_repo(GITHUB_REPO)
    
    # Create a new branch
    base_branch = repo.default_branch
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    new_branch_name = f"fix/sentry-{issue_details['id']}-{timestamp}"
    
    # Get the reference to the default branch
    ref = repo.get_git_ref(f"heads/{base_branch}")
    
    # Create new branch
    repo.create_git_ref(f"refs/heads/{new_branch_name}", ref.object.sha)
    
    # Update file in the new branch
    commit_message = f"Fix: {issue_details['title']} (Sentry ID: {issue_details['id']})"
    repo.update_file(
        path=file_path,
        message=commit_message,
        content=fixed_code,
        sha=original_content_sha,
        branch=new_branch_name
    )
    
    # Create pull request
    pr_title = f"🤖 [AI Fix] {issue_details['title']}"
    pr_body = f"""
## Automated fix for Sentry issue #{issue_details['id']}

### Issue Details
- **Error:** {issue_details['title']}
- **Sentry Link:** {issue_details['permalink']}
- **File:** {file_path}

### AI Explanation
{explanation}

---
*This PR was automatically generated by the Sentry Gemini Fix Agent*
    """
    
    pr = repo.create_pull(
        title=pr_title,
        body=pr_body,
        head=new_branch_name,
        base=base_branch
    )
    
    return pr.html_url

def process_issues():
    """Main function to process Sentry issues and create PRs"""
    # Get recent unresolved issues
    issues = get_recent_sentry_issues()
    
    for issue in issues:
        issue_id = issue['id']
        issue_title = issue['title']
        
        # Skip already processed issues (you might want to store these in a database)
        # For simplicity, we're not implementing this check here
        
        # Get detailed information about the issue
        issue_details = get_issue_details(issue_id)
        
        # Extract context information from the stack trace
        context_info, file_path = extract_stack_context(issue_details)
        
        if not context_info or not file_path:
            print(f"Could not extract context for issue {issue_id}")
            continue
        
        # Get the file content from GitHub
        file_content, content_sha = get_file_content(file_path)
        
        if not file_content:
            print(f"Could not get file content for {file_path}")
            continue
        
        # Generate a fix using AI
        fix_result = create_ai_fix(issue_title, file_content, context_info)
        
        if not fix_result:
            print(f"Could not generate fix for issue {issue_id}")
            continue
        
        # Create a PR with the fix
        try:
            pr_url = create_github_pr(
                file_path, 
                content_sha, 
                fix_result["fixed_code"], 
                {
                    "id": issue_id,
                    "title": issue_title,
                    "permalink": issue['permalink']
                }, 
                fix_result["explanation"]
            )
            
            print(f"Created PR for issue {issue_id}: {pr_url}")
            
            # Mark the issue as being worked on in Sentry
            # This part depends on your workflow, but you might want to add a comment
            # or change the status of the issue
            
        except Exception as e:
            print(f"Error creating PR for issue {issue_id}: {e}")

if __name__ == "__main__":
    process_issues()