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

from pydantic import BaseModel
from typing import Dict, List, Annotated
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBearer, HTTPBasicCredentials, HTTPAuthorizationCredentials
from utils.uniformEmbeddings import UniformEmbeddings
from api.utils.sdk_ai_tools import get_concepts

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

class getConceptsRequest(BaseModel):
    question: str
    chat_provider: str = os.getenv('CHAT_PROVIDER')
    chat_model: str = os.getenv('CHAT_MODEL')
    embeddings_provider: str = os.getenv('EMBEDDINGS_PROVIDER')
    embeddings_model: str = os.getenv('EMBEDDINGS_MODEL')

@router.get("/getConcepts", response_class = JSONResponse, response_model = Dict[str, List[int]], tags = ['Deprecated'])
def getConcepts(endpoint_request: getConceptsRequest = Depends(), auth: str = Depends(authenticate)):
    """
    This endpoint extracts the concepts from a question and returns the embeddings for each concept.

    This endpoint will also automatically look for the the following values in the environment variables for convenience, if not set:

    - EMBEDDINGS_PROVIDER
    - EMBEDDINGS_MODEL
    - CHAT_PROVIDER
    - CHAT_MODEL
    """
    try:
        concepts, get_concepts_tokens = get_concepts(
            query = endpoint_request.question, 
            llm_provider = endpoint_request.chat_provider, 
            llm_model = endpoint_request.chat_model
        )

        embeddings = UniformEmbeddings(
            endpoint_request.embeddings_provider,
            endpoint_request.embeddings_model,
        ).model

        concepts_with_embeddings = {concept: embeddings.embed_query(concept) for concept in concepts}

        return JSONResponse(content = jsonable_encoder(concepts_with_embeddings))
    except Exception as e:

        error_details = {
            'error': str(e),
            'traceback': traceback.format_exc()
        }
        
        raise HTTPException(status_code=500, detail=error_details)