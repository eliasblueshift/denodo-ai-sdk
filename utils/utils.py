"""
 Copyright (c) 2024. DENODO Technologies.
 http://www.denodo.com
 All rights reserved.

 This software is the confidential and proprietary information of DENODO
 Technologies ("Confidential Information"). You shall not disclose such
 Confidential Information and shall use it only in accordance with the terms
 of the license agreement you entered into with DENODO.
"""

import re
import os
import pytz
import json
import logging
import tiktoken
import functools
import asyncio

from time import time
from uuid import uuid4
from boto3 import Session
from functools import wraps, lru_cache
from datetime import datetime
from botocore.session import get_session
from langchain_core.documents.base import Document
from botocore.credentials import RefreshableCredentials
from langchain.callbacks.base import BaseCallbackHandler

def log_params(func):
    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
        func_name = func.__name__
        
        # Log entry
        def format_param(key, value):
            if key == "auth":
                return f"{key}=<redacted>"
            str_value = str(value)
            return f"{key}={str_value[:500] + '...' if len(str_value) > 500 else str_value}"
        
        params = ", ".join([format_param(f"arg{i}", arg) for i, arg in enumerate(args)] +
                           [format_param(k, v) for k, v in kwargs.items()])
        logging.info(f"{func_name} - Entry: Parameters({params})")
        
        # Call the original function
        result = await func(*args, **kwargs)
        
        # Log exit
        str_result = str(result)
        truncated_result = str_result[:500] + '...' if len(str_result) > 500 else str_result
        logging.info(f"{func_name} - Exit: Returned({truncated_result})")
        
        return result
    
    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        func_name = func.__name__
        
        # Log entry
        def format_param(key, value):
            if key == "auth":
                return f"{key}=<redacted>"
            str_value = str(value)
            return f"{key}={str_value[:500] + '...' if len(str_value) > 500 else str_value}"
        
        params = ", ".join([format_param(f"arg{i}", arg) for i, arg in enumerate(args)] +
                           [format_param(k, v) for k, v in kwargs.items()])
        logging.info(f"{func_name} - Entry: Parameters({params})")
        
        # Call the original function
        result = func(*args, **kwargs)
        
        # Log exit
        str_result = str(result)
        truncated_result = str_result[:500] + '...' if len(str_result) > 500 else str_result
        logging.info(f"{func_name} - Exit: Returned({truncated_result})")
        
        return result
    
    # Check if the function is a coroutine function
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper

@lru_cache(maxsize=None)
def get_langfuse_callback(model_id, session_id = None):
    if os.getenv('LANGFUSE_PUBLIC_KEY') and os.getenv('LANGFUSE_USER'):
        from langfuse.callback import CallbackHandler
        params = {
            "user_id": os.getenv('LANGFUSE_USER'),
            "release": os.getenv('AI_SDK_VER', 'Not set'),
            "metadata": {
                "model_id": model_id
            }
        }
        if session_id is not None:
            params["session_id"] = session_id
        return CallbackHandler(**params)
    return None

def generate_langfuse_session_id():
    """Generate a session ID in format: timestamp_user_shortUUID"""
    user = os.getenv('LANGFUSE_USER')
    if user:
        current_time = datetime.now().strftime("%Y_%m_%d_%H_%M")
        session_uuid = uuid4().hex[:4]
        return f"{current_time}_{user}_{session_uuid}"
    else:
        return None

def add_langfuse_callback(base_callback, model_id, session_id = None):
    callbacks = [base_callback]
    langfuse_callback = get_langfuse_callback(model_id, session_id)
    if langfuse_callback:
        callbacks.append(langfuse_callback)
    return callbacks

# Timer Decorator
def timed(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time()
        result = func(*args, **kwargs)
        end = time()
        elapsed_time = round(end - start, 2)
        logging.info("{} ran in {}s".format(func.__name__, elapsed_time))

        wrapper.elapsed_time = elapsed_time
        return result

    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        start = time()
        result = await func(*args, **kwargs)
        end = time()
        elapsed_time = round(end - start, 2)
        logging.info("{} ran in {}s".format(func.__name__, elapsed_time))

        async_wrapper.elapsed_time = elapsed_time
        return result

    # Check if the function is a coroutine function
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return wrapper

# Get the associations for a given table
def get_table_associations(table_name, table_json):
    table_associations = []
    schema_table_name = table_json['tableName']
    if table_name == schema_table_name:
        if 'associations' in table_json:
            for association in table_json['associations']:
                table_associations.append(association['table_name'])
    return table_associations

# Summarize a schema
def schema_summary(schema):
    summary = "====="
    table_name = schema['tableName']
    if "description" in schema and schema['description'] and schema['description'].strip():
        table_description = schema['description'].replace("\n", " ").strip()
        summary += f"Table {table_name}=====\nDescription: {table_description}\nColumns:\n"
    else:
        summary += f"Table {table_name}=====\nColumns:\n"
    for column_info in schema['schema']:
        column_name = column_info['columnName']
        column_type = column_info['type']
        if "logicalName" in column_info:
            column_logical_name = column_info['logicalName']
        else:
            column_logical_name = None
        if "description" in column_info:
            column_description = column_info['description'].replace("\n", " ").strip()
        else:
            column_description = None

        examples = schema.get('exampleRow')

        example_values = []

        if examples is not None:
            for example_dict in examples:
                if example_dict['fieldName'] == column_name:
                    example_values.extend(example_dict['fieldValues'])
                    break

        if len(example_values) != 0:
            example_values = list(set(example_values))
            example_values_str = ', '.join(example_values)
            example_value = f" Example value: {example_values_str}"
        else:
            example_value = ""

        if column_logical_name is not None and column_description is not None: 
            summary += f"- {column_name} ({column_type}) -> {column_logical_name}: {column_description}.{example_value}\n"
        elif column_logical_name is None and column_description is not None: 
            summary += f"- {column_name} ({column_type}) -> {column_description}.{example_value}\n"
        elif column_logical_name is not None and column_description is None:
            summary += f"- {column_name} ({column_type}) -> {column_logical_name}.{example_value}\n"
        else:
            summary += f"- {column_name} ({column_type}).{example_value}\n"
    
    if "associations" in schema and len(schema['associations']) != 0:
        summary += "\n"
        for association in schema['associations']:
            summary += f"This table is also associated with table {association['table_name']} on {association['where']}\n"
    summary += "\n"
    return summary
            
# Calculate the tokens of a given string
def calculate_tokens(string, encoding = 'cl100k_base'):
    encoding = tiktoken.get_encoding(encoding)
    num_tokens = len(encoding.encode(string))
    return num_tokens

# Parse the XML tags in the LLM's response
def custom_tag_parser(text, tag, default=[]):
    if text is None:
        return [default] if not isinstance(default, list) else []
    
    pattern = re.compile(fr'<{tag}>(.*?)</{tag}>', re.DOTALL)
    matches = re.findall(pattern, text)
    
    if not matches:
        return [default] if not isinstance(default, list) else []
    
    return matches

def flatten_list(list_of_lists):
    flattened_list = [x for item in list_of_lists for x in (item if isinstance(item, list) else [item])]
    return flattened_list

def create_chunks(table):
    """
    This function takes a string (schema_summary) and keeps everything before the line with Columns:
    Everything before that is the header and will be kept in every chunk.
    After Columns: you get every line and distribute it evenly so that all chunks have similar token counts.
    Function returns a list of Documents
    """
    # Split into header and content
    summary = schema_summary(table)
    parts = summary.split("Columns:\n", 1)
    header = parts[0] + "Columns:\n"
    content = parts[1] if len(parts) > 1 else ""

    # Split content into individual column lines and associations
    lines = content.split("\n")
    column_lines = []
    association_lines = []
    
    # Separate column lines from association information
    for line in lines:
        if line.startswith("This table is also associated"):
            association_lines.append(line)
        elif line.strip():  # Only add non-empty lines
            column_lines.append(line)

    # Association footer that will be added to all chunks
    association_footer = "\n" + "\n".join(association_lines) if association_lines else ""

    # Calculate optimal chunk size based on 8000 token limit
    # Account for header and association footer in token calculation
    base_content = header + association_footer
    base_tokens = calculate_tokens(base_content)
    available_tokens = 7500 - base_tokens
    
    column_content = "\n".join(column_lines)
    total_tokens = calculate_tokens(column_content)
    target_chunks = (total_tokens // available_tokens) + 1
    chunk_size = max(1, len(column_lines) // target_chunks)
        
    chunks = []
    base_id = str(table['id'])
    
    for i in range(0, len(column_lines), chunk_size):
        current_lines = column_lines[i:i + chunk_size]
        chunk_content = header + "\n".join(current_lines) + association_footer + "\n"
        
        # Create metadata for the chunk
        base_metadata = {
            "view_name": table['tableName'],
            "view_json": json.dumps(table),
            "view_id": base_id,  # Same ID for all chunks of the same table
            "database_name": table['tableName'].split('.')[0]
        }
        
        chunks.append(Document(
            id=f"{base_id}_{len(chunks)}",  # Unique ID for each chunk
            page_content=chunk_content,
            metadata=base_metadata
        ))

    return chunks

@timed
def prepare_schema(schema, embeddings_token_limit = 0):

    def create_document(table, embeddings_token_limit):            
        table_summary = schema_summary(table)
        table_summary_tokens = calculate_tokens(table_summary)
        if embeddings_token_limit and table_summary_tokens > embeddings_token_limit:
            return create_chunks(table)

        base_metadata = {
            "view_name": table['tableName'],
            "view_json": json.dumps(table),
            "view_id": str(table['id']),
            "database_name": table['tableName'].split('.')[0],
            "tag_names": str([tag['name'] for tag in table.get('tagDetails', [])])
        }

        return Document(
            id=str(table['id']),
            page_content=schema_summary(table),
            metadata=base_metadata
        )
        
    return [create_document(table, embeddings_token_limit) for table in schema['databaseTables']]

class RefreshableBotoSession:
    def __init__(
        self,
        region_name: str = None,
        access_key: str = None,
        secret_key: str = None,
        profile_name: str = None,
        sts_arn: str = None,
        session_name: str = None,
        session_ttl: int = 3000
    ):
        self.region_name = region_name
        self.access_key = access_key
        self.secret_key = secret_key
        self.profile_name = profile_name
        self.sts_arn = sts_arn
        self.session_name = session_name or uuid4().hex
        self.session_ttl = session_ttl

    def __get_session_credentials(self):
        if self.access_key and self.secret_key:
            session = Session(
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region_name
            )
        else:
            session = Session(
                region_name = self.region_name,
                profile_name = self.profile_name
            )

        if self.sts_arn:
            sts_client = session.client(service_name = "sts", region_name = self.region_name)
            response = sts_client.assume_role(
                RoleArn = self.sts_arn,
                RoleSessionName = self.session_name,
                DurationSeconds = self.session_ttl,
            ).get("Credentials")

            credentials = {
                "access_key": response.get("AccessKeyId"),
                "secret_key": response.get("SecretAccessKey"),
                "token": response.get("SessionToken"),
                "expiry_time": response.get("Expiration").isoformat(),
            }
        else:
            session_credentials = session.get_credentials().get_frozen_credentials()
            credentials = {
                "access_key": session_credentials.access_key,
                "secret_key": session_credentials.secret_key,
                "token": session_credentials.token,
                "expiry_time": datetime.fromtimestamp(time() + self.session_ttl).replace(tzinfo = pytz.utc).isoformat(),
            }

        return credentials

    def refreshable_session(self) -> Session:
        refreshable_credentials = RefreshableCredentials.create_from_metadata(
            metadata = self.__get_session_credentials(),
            refresh_using = self.__get_session_credentials,
            method = "sts-assume-role",
        )

        session = get_session()
        session._credentials = refreshable_credentials
        session.set_config_variable("region", self.region_name)
        autorefresh_session = Session(botocore_session = session)

        return autorefresh_session
    
# Token Counter for LLMs
class TokenCounter(BaseCallbackHandler):
    def __init__(self, llm):
        self.llm = llm.llm
        self.tokens = llm.tokens

    def on_llm_start(self, serialized, prompts, **kwargs):
        for p in prompts:
            self.tokens['input_tokens'] += self.llm.get_num_tokens(p)

    def on_llm_end(self, response, **kwargs):
        results = response.flatten()
        for r in results:
            self.tokens['output_tokens'] = self.llm.get_num_tokens(r.generations[0][0].text)
        self.tokens['total_tokens'] = self.tokens['input_tokens'] + self.tokens['output_tokens']

    def reset_tokens(self):
        self.tokens['input_tokens'] = 0
        self.tokens['output_tokens'] = 0
        self.tokens['total_tokens'] = 0