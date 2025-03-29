import os
import re
import json
import requests
import subprocess
from datetime import datetime


################################
# Utility function to load config
################################
def load_config(path: str = "config.json") -> dict:
    """Loads configuration values from config.json."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


####################################
# Utility functions for reading files
####################################
def read_resume_file(file_path: str) -> str:
    """Reads and returns the contents of the resume file."""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()

def read_job_description_file(file_path: str) -> str:
    """Reads and returns the contents of the job description file."""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


#############################################
# Function to clean the AI's JSON-like string
#############################################
def clean_ai_json(ai_text: str) -> str:
    """
    Cleans up the AI response so that it becomes valid JSON.
    1) Strips whitespace.
    2) Removes code-fence markers (```) if present.
    3) Removes wrapping single/double quotes if the entire string is quoted.
    4) Extracts the substring from the first '{' to the last '}'.
    """
    text = ai_text.strip()

    # Remove triple backticks or code fences if present
    if text.startswith("```") and text.endswith("```"):
        text = text[3:-3].strip()

    # Remove outer single or double quotes if the entire string is quoted
    if (text.startswith("'") and text.endswith("'")) or (text.startswith('"') and text.endswith('"')):
        text = text[1:-1].strip()

    # Extract only from first '{' to last '}'
    start_idx = text.find('{')
    end_idx = text.rfind('}')
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        text = text[start_idx:end_idx+1].strip()

    return text


###############################
# LaTeX helpers
###############################
def escape_latex(s: str) -> str:
    """Escapes LaTeX special characters in a string."""
    return (
        s.replace('\\', '\\textbackslash{}')
         .replace('&', '\\&')
         .replace('%', '\\%')
         .replace('$', '\\$')
         .replace('#', '\\#')
         .replace('_', '\\_')
         .replace('{', '\\{')
         .replace('}', '\\}')
         .replace('~', '\\textasciitilde{}')
         .replace('^', '\\textasciicircum{}')
    )


def replace_bullet_points(lines, start_index, new_bullets):
    """
    Replaces the bullet points in an itemize environment starting at start_index with new_bullets.
    Expects lines[start_index] to be '\begin{itemize}'.
    """
    end_index = start_index
    # Find the matching \end{itemize}
    for i in range(start_index + 1, len(lines)):
        if '\\end{itemize}' in lines[i]:
            end_index = i
            break
    else:
        print(f"Warning: \\end{{itemize}} not found after line {start_index}")
        return lines

    new_itemize = [lines[start_index], '    \\itemsep -6pt {}']
    for bullet in new_bullets:
        escaped_bullet = escape_latex(bullet)
        new_itemize.append(f'    \\item {escaped_bullet}')
    new_itemize.append(lines[end_index])

    lines = lines[:start_index] + new_itemize + lines[end_index + 1:]
    return lines


def find_company_itemize_index(lines, company_name):
    """
    Finds the line index of \begin{itemize} for the specified company_name by searching for
    \experienceItem[...] with 'company={company_name}' and then scanning until \begin{itemize}.
    Returns None if not found.
    """
    content_str = '\n'.join(lines)
    pattern = re.compile(
        rf'\\experienceItem\[(?:(?!\\experienceItem).)*?company=\s*\{{\s*{re.escape(company_name)}\s*\}}.*?\]',
        re.IGNORECASE | re.DOTALL
    )
    match = pattern.search(content_str)
    if match:
        match_end = match.end()
        itemize_pattern = re.compile(r'\\begin\{itemize\}', re.DOTALL)
        itemize_match = itemize_pattern.search(content_str, pos=match_end)
        if itemize_match:
            itemize_pos = itemize_match.start()
            start_index = content_str.count('\n', 0, itemize_pos)
            return start_index
        else:
            print(f"\\begin{{itemize}} not found after \\experienceItem for {company_name}.")
    else:
        print(f"{company_name} section not found. Please check the company name formatting.")
    return None


def find_skills_section_index(lines):
    """
    Looks for a line containing '\begin{skillsSection}' and returns its index or None if not found.
    """
    for i, line in enumerate(lines):
        if '\\begin{skillsSection}' in line:
            return i
    return None


def replace_skills_section(lines, start_index, technical_skills):
    """
    Replaces content in the 'skillsSection' environment starting at start_index until '\end{skillsSection}'.
    Uses the data from technical_skills to build skillItem lines.
    """
    end_index = start_index
    for i in range(start_index + 1, len(lines)):
        if '\\end{skillsSection}' in lines[i]:
            end_index = i
            break
    else:
        print(f"Warning: \\end{{skillsSection}} not found after line {start_index}")
        return lines
    
    new_skills_section = [lines[start_index]]
    for idx, (category, skills) in enumerate(technical_skills.items()):
        escaped_category = escape_latex(category)
        escaped_skills = [escape_latex(skill) for skill in skills]
        skill_line = (
            f'    \\skillItem['
            f'\n        category={{{escaped_category}}},'
            f'\n        skills={{{", ".join(escaped_skills)}}}'
            f'\n    ]'
        )
        # If not the last item, let’s add a latex line break
        if idx < len(technical_skills) - 1:
            skill_line += ' \\\\'
        new_skills_section.append(skill_line)

    new_skills_section.append(lines[end_index])  # keep the \end{skillsSection} line
    lines = lines[:start_index] + new_skills_section + lines[end_index + 1:]
    return lines


###########################
# Main execution starts here
###########################
if __name__ == "__main__":
    # 1. Load config
    config = load_config("config.json")

    YOUR_API_KEY = config["api_key"]
    model_name = config["model_name"]
    job_description_file = config["job_description_file"]
    resume_file = config["resume_file"]
    url = config["api_endpoint"]

    # 2. Read resume and job description from files
    my_resume = read_resume_file(resume_file)
    job_description = read_job_description_file(job_description_file)

    # 3. Build the prompt
    prompt = f"""
You are my assistant and responsible to follow my instructions strictly. I am providing my resume content in LaTeX format in the variable "my_resume".
Specifically, you need to update the "Professional Experience" section and the "Technical Skills" section. Your goal is to enhance my resume for job applications by adding
missing keywords and improving the bullet points of my existing professional experience with the missing keywords.

Instructions:
0. You are allowed allowed to follow below instructions and return the final output only.
1. First, generate a list of missing keywords from my resume in the variable "my_resume" based on the given role's job_description from variable "job_description".
2. You are only allowed to return the list of missing keywords only in the list with variable name "missing_keywords", as given in the below example
missing_keywords = [Java, Spring Boot, Microservices, Java 8, Design Patterns, MySql, Dockers]
3. Generate bullet points to modify my work experience by reading my resume from variable "my_resume".
4. You are strictly allowed to make changes to only the existing bullet points. Do not add or remove any bullet points from either of Professional work experience's.
4.1 If any bullet point doesn't need any changes, just return as it is.
5. Ensure the updates are concise, professional, and include measurable impact
6. Finally, return all bullet points in respective lists as given in the below example.
6.1 - If you made changes to Yellow.Ai work experience, return the output in the variable "yellow_changes", below is the example
"yellow_changes" = [] #Add all bullet points made changes and non changed.
6.2 - If changes made to Cognizant work experience, return the output in the variable "cognizant_changes", below is the example
"cognizant_changes" = [] #Add all the bullet points made changes and non changed.
6.3 - If no changes were made in either of work experience or both of them, just return the existing work experience bullet points. Do not make changes in that case.
7. Now, from the step 2, classify the missing kewords from variable missing_keywords into the following categories only.
Categories - Web Technologies, Database Management, Cloud & DevOps, Software Fundamentals
8. Add missing keywords related to tools like Github/Git/Postman etc to "Web Technologies" category.
9. Return the classified categories in the list only. Below is the examples
For Web Technologies, web = [] ##Add keywords in list
For Database Management,  database = [] #Add keywords in list
For Cloud & DevOps, cloud = [] #Add keywords in list
For Software Fundamentals, fundementals = [] #Add keywords in list

10. You must strictly return the output in the following JSON structure. Do not include any additional text, explanations, or comments. Only return the output variable in the exact format specified below. Ensure the content of the fields aligns with the context of the instructions but strictly preserve the structure.
11. Content Differentiation: Ensure that the content for yellow.ai and cognizant in professional_experience is contextualized and distinct, reflecting the unique nature of the work experience in each company. Do not repeat or reuse the same sentences across both categories. Use the provided resume details to tailor the content appropriately.
12. Modify and Enhance: While retaining the meaning and context of the original experience, you must enhance the text by focusing on relevant technologies, methodologies, and accomplishments unique to each role. Avoid directly copying the text from the resume without modification.
13. You must strictly return a max of 5-6 bullet points for Yellow.Ai and 4-5 bullet points for Cognizant only. You are not allowed to give more than the limit.
14. - Do not add any additional fields, explanations, or comments in the JSON structure. Any output outside of the provided format will be considered invalid.
15. - Your output must strictly match the format provided below:

"output": {{
  "professional_experience": {{
    "yellow.ai": [
      "Developed and maintained scalable chatbot applications leveraging NodeJS, Python, and JavaScript, integrating RESTful APIs and secure third-party services (WhatsApp API, Microsoft Teams, Web Portals).",
      "",
      "",
      "",
      ""
    ],
    "cognizant": [
      "Designed and developed RESTful APIs using Java Spring Boot, ensuring efficient, secure data communication between client applications and backend services.",
      "",
      "",
      ""
    ]
  }},
  "technical_skills": {{
    "Web Technologies": ["AWS", "CDK", "Go", "Email technologies", "Notification technologies"],
    "Database Management": ["Data pipelines", "Business intelligence", "Data governance"],
    "Cloud & DevOps": ["Cloud infrastructure", "Data infrastructure"],
    "Software Fundamentals": ["Infrastructure as code", "Enterprise applications"]
  }}
}}


Below is the content of my resume in latex format, in the variable "my_resume":
my_resume = {my_resume}

Below is the job description for the role, I am looking to modify my resume in variable "job_description"
job_description = {job_description}


--END of PROMPT--
"""

    # 4. Make the API call
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "Authorization": YOUR_API_KEY
    }

    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ]
    }

    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        response_json = response.json()
        choices = response_json.get('choices', [])
        if choices:
            ai_response = choices[0].get('message', {}).get('content', '')
        else:
            print("No choices available in the response.")
            ai_response = ""
    else:
        print(f"Error: {response.status_code}")
        print(response.text)
        ai_response = ""


    # 5. Clean the AI response to ensure valid JSON
    cleaned_content = clean_ai_json(ai_response)

    # 6. Attempt to parse the cleaned content as JSON
    try:
        output_dict = json.loads(cleaned_content)
        print("Successfully parsed JSON output.")
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        output_dict = {}  # fallback if parsing fails

    if not output_dict:
        print("No valid JSON output to process, exiting.")
        exit(1)

    # 7. Read the 'my_resume' again from file for modifications
    with open(resume_file, 'r', encoding='utf-8') as file:
        resume_text = file.read()

    # 8. Extract bullet points and technical skills from output_dict
    try:
        yellow_bullets = output_dict['output']['professional_experience']['yellow.ai']
        cognizant_bullets = output_dict['output']['professional_experience']['cognizant']
        technical_skills = output_dict['output']['technical_skills']
    except KeyError as e:
        print(f"KeyError: Missing expected data in JSON - {e}")
        exit(1)

    # 9. Modify the resume LaTeX
    lines = resume_text.split('\n')

    # Replace bullet points for Yellow.Ai
    yellow_start_index = find_company_itemize_index(lines, 'Yellow.Ai')
    if yellow_start_index is not None:
        lines = replace_bullet_points(lines, yellow_start_index, yellow_bullets)

    # Replace bullet points for Cognizant
    cognizant_start_index = find_company_itemize_index(lines, 'Cognizant')
    if cognizant_start_index is not None:
        lines = replace_bullet_points(lines, cognizant_start_index, cognizant_bullets)

    # Replace the technical skills in the LaTeX
    skills_start_index = find_skills_section_index(lines)
    if skills_start_index is not None:
        lines = replace_skills_section(lines, skills_start_index, technical_skills)
    else:
        print("Technical Skills section not found in the resume.")

    # 10. Save the modified LaTeX content to a new file
    modified_resume = '\n'.join(lines)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    latex_filename = f'resume_{timestamp}.tex'

    with open(latex_filename, 'w', encoding='utf-8') as f:
        f.write(modified_resume)

    print(f"Modified LaTeX resume saved as {latex_filename}")