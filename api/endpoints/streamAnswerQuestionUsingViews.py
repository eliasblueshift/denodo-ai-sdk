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
from typing import Annotated, List, Literal

from fastapi.responses import StreamingResponse
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

class streamAnswerQuestionUsingViewsRequest(BaseModel):
    question: str
    vector_search_tables: List[str]
    plot: bool = False
    plot_details: str = ''
    embeddings_provider: str = os.getenv('EMBEDDINGS_PROVIDER')
    embeddings_model: str = os.getenv('EMBEDDINGS_MODEL')
    vector_store_provider: str = os.getenv('VECTOR_STORE')
    sql_gen_provider: str = os.getenv('SQL_GENERATION_PROVIDER')
    sql_gen_model: str = os.getenv('SQL_GENERATION_MODEL')
    chat_provider: str = os.getenv('CHAT_PROVIDER')
    chat_model: str = os.getenv('CHAT_MODEL')
    custom_instructions: str = os.getenv('CUSTOM_INSTRUCTIONS', '')
    markdown_response: bool = True
    vector_search_k: int = 5
    mode: Literal["default", "data", "metadata"] = Field(default = "default")
    disclaimer: bool = True
    verbose: bool = True

@router.get('/streamAnswerQuestionUsingViews', response_class = StreamingResponse)
def streamAnswerQuestionUsingViews(endpoint_request: streamAnswerQuestionUsingViewsRequest = Depends(), auth: str = Depends(authenticate)):
    """
    The only difference between this endpoint and `streamAnswerQuestion` is that this endpoint 
    expects the result of the vector search to be passed in as a parameter.

    To simply limit or force the LLM to use a specific set of views, please use answerQuestion.

    This is useful for implementations with custom vector stores.

    This endpoint will also automatically look for the the following values in the environment variables for convenience:

    - EMBEDDINGS_PROVIDER
    - EMBEDDINGS_MODEL
    - VECTOR_STORE
    - SQL_GENERATION_PROVIDER
    - SQL_GENERATION_MODEL
    - CHAT_PROVIDER
    - CHAT_MODEL

    As you can see, you can specify a different provider for SQL generation and chat generation. This is because generating a correct SQL query
    is a complex task that should be handled with a powerful LLM."""

    try:
        timings = {}
        with timing_context("llm_time", timings):
            category, category_response, category_related_questions, sql_category_tokens = sdk_ai_tools.sql_category(
                query=endpoint_request.question, 
                vector_search_tables=endpoint_request.vector_search_tables, 
                llm_provider=endpoint_request.chat_provider,
                llm_model=endpoint_request.chat_model,
                mode=endpoint_request.mode,
                custom_instructions=endpoint_request.custom_instructions
            )

        if category == "SQL":
            response = sdk_answer_question.process_sql_category(
                request=endpoint_request, 
                vector_search_tables=endpoint_request.vector_search_tables, 
                category_response=category_response,
                auth=auth, 
                timings=timings,
            )
        elif category == "METADATA":
            response = sdk_answer_question.process_metadata_category(
                category_response=category_response, 
                category_related_questions=category_related_questions, 
                vector_search_tables=endpoint_request.vector_search_tables, 
                timings=timings,
            )
        else:
            response = sdk_answer_question.process_unknown_category(timings=timings)

        def generator():
            yield from response.get('answer', 'Error processing the question.')
        return StreamingResponse(generator(), media_type = 'text/plain')
    
    except Exception as e:

        error_details = {
            'error': str(e),
            'traceback': traceback.format_exc()
        }

        raise HTTPException(status_code=500, detail=error_details)