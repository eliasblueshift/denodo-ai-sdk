"""
 Copyright (c) 2024. DENODO Technologies.
 http://www.denodo.com
 All rights reserved.

 This software is the confidential and proprietary information of DENODO
 Technologies ("Confidential Information"). You shall not disclose such
 Confidential Information and shall use it only in accordance with the terms
 of the license agreement you entered into with DENODO.
"""

import os
import traceback

from pydantic import BaseModel, Field
from typing import Dict, Annotated, List, Literal

from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials, HTTPAuthorizationCredentials, HTTPBearer

from api.utils.sdk_utils import timing_context
from api.utils import sdk_ai_tools
from api.utils import sdk_answer_question

router = APIRouter()
security_basic = HTTPBasic()
security_bearer = HTTPBearer()

# Get the authentication type from environment
AUTH_TYPE = os.getenv("DATA_CATALOG_AUTH_TYPE", "http_basic")

if AUTH_TYPE.lower() == "http_basic":
    def authenticate(credentials: Annotated[HTTPBasicCredentials, Depends(security_basic)]):
        return (credentials.username, credentials.password)
else:
    def authenticate(credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_bearer)]):
        return credentials.credentials

class answerQuestionRequest(BaseModel):
    question: str
    plot: bool = False
    plot_details: str = ''
    embeddings_provider: str = os.getenv('EMBEDDINGS_PROVIDER')
    embeddings_model: str = os.getenv('EMBEDDINGS_MODEL')
    vector_store_provider: str = os.getenv('VECTOR_STORE')
    sql_gen_provider: str = os.getenv('SQL_GENERATION_PROVIDER')
    sql_gen_model: str = os.getenv('SQL_GENERATION_MODEL')
    chat_provider: str = os.getenv('CHAT_PROVIDER')
    chat_model: str = os.getenv('CHAT_MODEL')
    vdp_database_names: str = os.getenv('VDB_NAMES')
    use_views: str = ''
    expand_set_views: bool = True
    custom_instructions: str = os.getenv('CUSTOM_INSTRUCTIONS', '')
    markdown_response: bool = True
    vector_search_k: int = 5
    mode: Literal["default", "data", "metadata"] = Field(default = "default")
    disclaimer: bool = True
    verbose: bool = True

class answerQuestionResponse(BaseModel):
    answer: str
    sql_query: str
    query_explanation: str
    tokens: Dict
    execution_result: Dict
    related_questions: List[str]
    tables_used: List[str]
    raw_graph: str
    sql_execution_time: float
    vector_store_search_time: float
    llm_time: float
    total_execution_time: float

@router.get('/answerQuestion', response_class = JSONResponse, response_model = answerQuestionResponse)
def answerQuestion(
    endpoint_request: answerQuestionRequest = Depends(), 
    auth: str = Depends(authenticate)
):
    """
    This endpoint processes a natural language question and:

    - Searches for relevant tables using vector search
    - Determines whether the question should be answered using a SQL query or a metadata search
    - Generates a VQL query using an LLM if the question should be answered using a SQL query
    - Executes the VQL query and gets the data
    - Generates an answer to the question using the data and the VQL query

    This endpoint will also automatically look for the the following values in the environment variables for convenience:

    - EMBEDDINGS_PROVIDER
    - EMBEDDINGS_MODEL
    - VECTOR_STORE
    - SQL_GENERATION_PROVIDER
    - SQL_GENERATION_MODEL
    - CHAT_PROVIDER
    - CHAT_MODEL
    - VDB_NAMES

    As you can see, you can specify a different provider for SQL generation and chat generation. This is because generating a correct SQL query
    is a complex task that should be handled with a powerful LLM."""

    try:
        # Right now, not all Denodo instances have permissions implemented. This should be deleted in the future.
        USER_PERMISSIONS = int(os.getenv("USER_PERMISSIONS", 0))

        vector_search_tables, timings = sdk_ai_tools.get_relevant_tables(
            query=endpoint_request.question,
            embeddings_provider=endpoint_request.embeddings_provider,
            embeddings_model=endpoint_request.embeddings_model,
            vector_store_provider=endpoint_request.vector_store_provider,
            vdb_list=endpoint_request.vdp_database_names,
            auth=auth,
            k=endpoint_request.vector_search_k,
            user_permissions=USER_PERMISSIONS,
            use_views=endpoint_request.use_views,
            expand_set_views=endpoint_request.expand_set_views
        )

        with timing_context("llm_time", timings):
            category, category_response, category_related_questions, sql_category_tokens = sdk_ai_tools.sql_category(
                query=endpoint_request.question, 
                vector_search_tables=vector_search_tables, 
                llm_provider=endpoint_request.chat_provider,
                llm_model=endpoint_request.chat_model,
                mode=endpoint_request.mode,
                custom_instructions=endpoint_request.custom_instructions
            )

        if category == "SQL":
            response = sdk_answer_question.process_sql_category(
                request=endpoint_request, 
                vector_search_tables=vector_search_tables, 
                category_response=category_response,
                auth=auth, 
                timings=timings,
            )
        elif category == "METADATA":
            response = sdk_answer_question.process_metadata_category(
                category_response=category_response, 
                category_related_questions=category_related_questions, 
                vector_search_tables=vector_search_tables, 
                disclaimer=endpoint_request.disclaimer,
                timings=timings
            )
        else:
            response = sdk_answer_question.process_unknown_category(timings=timings)

        return JSONResponse(content=jsonable_encoder(response), media_type='application/json')
    except Exception as e:

        error_details = {
            'error': str(e),
            'traceback': traceback.format_exc()
        }

        raise HTTPException(status_code=500, detail=error_details)