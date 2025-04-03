import os
import re
import sys
import random
import uvicorn
import logging
import requests

from time import time
from contextlib import contextmanager

def add_tokens(token_set1, token_set2):
    return {key: token_set1[key] + token_set2[key] for key in token_set1}

def generate_session_id(question):
    question_prefix = ''.join(c for c in question[:20] if c.isalpha() or c.isspace())
    question_prefix = question_prefix.replace(' ', '_')
    return f"{question_prefix}_{random.randint(1000,9999)}"

@contextmanager
def timing_context(name, timings):
    start_time = time()
    yield
    elapsed_time = time() - start_time
    if name in timings:
        timings[name] += elapsed_time
    else:
        timings[name] = elapsed_time
    
    for key, value in timings.items():
        timings[key] = round(value, 2)

def readable_tables(relevant_tables):
    readable_output = ""

    for table in relevant_tables:
        table_schema = table['view_json']['schema']
        table_columns = [column['columnName'] for column in table_schema]
        readable_output += f'<table>Table {table["view_name"]} with columns {", ".join(table_columns)}\n</table>\n'
    
    return readable_output

def is_data_complex(data):
    if isinstance(data, dict) and len(data) > 3:
        if len(data['Row 1']) > 1:
            return True 
    return False

def match_nested_parentheses(text):
    def find_closing_paren(s, start):
        count = 0
        for i, c in enumerate(s[start:], start):
            if c == '(':
                count += 1
            elif c == ')':
                count -= 1
                if count == 0:
                    return i
        return -1

    matches = []
    start = 0
    while True:
        start = text.find('(', start)
        if start == -1:
            break
        end = find_closing_paren(text, start)
        if end == -1:
            break
        matches.append(text[start:end+1])
        start = end + 1

    return matches

# Prepare VQL
def prepare_vql(vql):    
    error_log = ''
    error_categories = []

    # Convert VQL to single line for regex processing
    vql_single_line = vql.replace('\n', ' ')

    # Look for LLM code styling
    if '```' in vql:
        logging.info("Backward ticks detected in VQL, fixing...")
        vql = vql.replace('```vql', '').replace('```sql', '').replace('```', '')

    if '\\_' in vql:
        logging.info("Markdown underscore detected in VQL, fixing...")
        vql = vql.replace('\\_', '_')
    
    # Protected words for aliases
    protected_words = (
        'ADD|ALL|ALTER|AND|ANY|AS|ASC|BASE|BOTH|CASE|CONNECT|CONTEXT|CREATE|CROSS|'
        'CURRENT_DATE|CURRENT_TIMESTAMP|CUSTOM|DATABASE|DEFAULT|DESC|DF|DISTINCT|DROP|'
        'EXISTS|FALSE|FETCH|FLATTEN|FROM|FULL|GRANT|GROUP BY|HASH|HAVING|HTML|IF|INNER|'
        'INTERSECT|INTO|IS|JDBC|JOIN|LDAP|LEADING|LEFT|LIMIT|LOCALTIME|LOCALTIMESTAMP|'
        'MERGE|MINUS|MY|NATURAL|NESTED|NOS|NOT|NULL|OBL|ODBC|OF|OFF|OFFSET|ON|ONE|OPT|'
        'OR|ORDER BY|ORDERED|PRIVILEGES|READ|REVERSEORDER|REVOKE|RIGHT|ROW|SELECT|SWAP|'
        'TABLE|TO|TRACE|TRAILING|TRUE|UNION|USER|USING|VIEW|WHEN|WHERE|WITH|WRITE|WS|ZERO'
    )
    
    # Pattern to match protected words used as aliases
    pattern = fr'\s+AS\s+({protected_words})\s+'
    matches = re.finditer(pattern, vql_single_line, re.IGNORECASE)
    
    # Track all replacements
    replacements = {}
    for match in matches:
        protected_word = match.group(1)
        new_alias = f"{protected_word}_"
        replacements[protected_word] = new_alias
        logging.info(f"Protected word '{protected_word}' used as alias, appending underscore")
        
    # Apply replacements
    modified_vql = vql
    for old_word, new_word in replacements.items():
        # Pattern to match the exact alias after AS
        replace_pattern = fr'(\s+AS\s+){old_word}(\s+)'
        modified_vql = re.sub(replace_pattern, fr'\1{new_word}\2', modified_vql, flags=re.IGNORECASE)
    
    vql = modified_vql
    
    # Look for forbidden functions
    forbidden_functions = [
        'LENGTH',
        'CHAR_LENGTH',
        'CHARACTER_LENGTH',
        'CURRENT_TIME',
        'DIVIDE',
        'MULTIPLY',
        'DATE',
        'STRFTIME',
        'SUBSTRING',
        'DATE_SUB',
        'DATE_ADD',
        'DATE_TRUNC',
        'INTERVAL',
        'ADDDATE',
        'TO_CHAR',
        'LPAD',
        'STRING_AGG',
        'ARRAY_AGG',
    ]

    for forbidden_function in forbidden_functions:
        if f" {forbidden_function} " in vql.upper() or f" {forbidden_function} ( " in vql.upper() or f" {forbidden_function}(" in vql.upper() or f"({forbidden_function}(" in vql.upper():
            error_log += f"{forbidden_function} is not permitted in VQL.\n"
            if "FORBIDDEN_FUNCTION" not in error_categories:
                #error_categories.append('FORBIDDEN_FUNCTION')
                continue

    # Look for LIMIT in subquery
    matches = match_nested_parentheses(vql_single_line)
    
    for match in matches:
        if ' LIMIT ' in match:
            error_log += "There is a LIMIT in subquery, which is not permitted in VQL. Use ROW_NUMBER () instead.\n"
            if "LIMIT_SUBQUERY" not in error_categories:
                error_categories.append('LIMIT_SUBQUERY')
        
        if ' FETCH ' in match:
            error_log += "There is a FETCH in subquery, which is not permitted in VQL. Use ROW_NUMBER () instead.\n"
            if "LIMIT_SUBQUERY" not in error_categories:
                error_categories.append('LIMIT_SUBQUERY')

    if " OFFSET " in vql_single_line:
        error_log += "There is a LIMIT OFFSET in the main query, which is not permitted in VQL. Use ROW_NUMBER () instead.\n"
        if "LIMIT_OFFSET" not in error_categories:
            error_categories.append('LIMIT_OFFSET')

    if error_log == "":
        error_log = False
        
    logging.info(f"prepare_vql vql: {vql} error log: {error_log} and categories: {error_categories}")
    return vql.strip(), error_log, error_categories

def generate_vql_restrictions(prompt_parts, vql_rules_prompt, groupby_vql_prompt, having_vql_prompt, dates_vql_prompt, arithmetic_vql_prompt):
    if prompt_parts is None:
        return vql_rules_prompt.replace("{EXTRA_RESTRICTIONS}", "")

    vql_prompt_parts = {
        "groupby": groupby_vql_prompt if prompt_parts.get("groupby") else "",
        "having": having_vql_prompt if prompt_parts.get("having") else "",
        "dates": dates_vql_prompt if prompt_parts.get("dates") else "",
        "arithmetic": arithmetic_vql_prompt if prompt_parts.get("arithmetic") else ""
    }

    extra_restrictions = '\n'.join(vql_prompt_parts[key] for key in vql_prompt_parts if prompt_parts.get(key))
    return vql_rules_prompt.replace("{EXTRA_RESTRICTIONS}", extra_restrictions)

def get_response_format(markdown_response):
    if markdown_response:
        response_format = """
        - Use bold, italics and tables in markdown when appropiate to better illustrate the response.
        - You cannot use markdown headings, instead use titles in bold to separate sections, if needed.
        """
        response_example = "**Cristiano Ronaldo** was the player who scored the most goals last year, with a total of **23 goals**."
    else:
        response_format = "- Use plain text to answer, don't use markdown or any other formatting."
        response_example = "Cristiano Ronaldo was the player who scored the most goals last year, with a total of 23 goals."
    return response_format, response_example

def check_env_variables(required_vars):
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        print("ERROR. The following required environment variables are missing:")
        for var in missing_vars:
            print(f"- {var}")
        print("Please set these variables before starting the application.")
        sys.exit(1)

def test_data_catalog_connection(data_catalog_url, verify_ssl):
    try:
        response = requests.get(data_catalog_url, verify=verify_ssl, timeout=10)
        response.raise_for_status()
        return True
    except Exception:
        return False
    
def filter_non_allowed_associations(view_json, valid_view_ids):
    # If valid_view_ids is None, return the original view_json unchanged
    if valid_view_ids is None:
        return view_json
    
    # Create a new view_json with filtered associations
    filtered_view_json = view_json.copy()
    filtered_view_json['associations'] = [
        assoc for assoc in view_json['associations']
        if str(assoc['table_id']) in valid_view_ids
    ]
    
    return filtered_view_json

def configure_uvicorn_logging():
    """Configure Uvicorn's logging to use our format."""
    log_config = uvicorn.config.LOGGING_CONFIG
    timestamp_fmt = "%(asctime)s [Worker %(process)d] %(levelname)-8s %(message)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"

    # Update all formatters
    for formatter in log_config["formatters"].values():
        formatter["fmt"] = timestamp_fmt
        formatter["datefmt"] = date_fmt

    # The access formatter needs special handling to preserve request information
    log_config["formatters"]["access"]["fmt"] = "%(asctime)s [Worker %(process)d] %(levelname)-8s %(client_addr)s - \"%(request_line)s\" %(status_code)s"
    
    # Set up a custom filter to only allow INFO level logs
    class InfoOnlyFilter(logging.Filter):
        def filter(self, record):
            return record.levelno == logging.INFO

    # Apply the filter to all handlers
    for handler in log_config["handlers"].values():
        handler["filters"] = ["info_only"]
    
    # Add the filter to the filters section
    log_config["filters"] = {
        "info_only": {
            "()": InfoOnlyFilter,
        }
    }

    return log_config