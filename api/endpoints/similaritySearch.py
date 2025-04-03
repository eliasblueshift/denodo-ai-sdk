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
import json
import traceback

from pydantic import BaseModel
from typing import List, Annotated

from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials, HTTPAuthorizationCredentials, HTTPBearer

from utils.data_catalog import get_allowed_view_ids
from utils.uniformVectorStore import UniformVectorStore
from api.utils.sdk_utils import filter_non_allowed_associations

router = APIRouter()
security_basic = HTTPBasic(auto_error = False)
security_bearer = HTTPBearer(auto_error = False)
    
def authenticate(
        basic_credentials: Annotated[HTTPBasicCredentials, Depends(security_basic)],
        bearer_credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_bearer)]
        ):
    if bearer_credentials is not None:
        return bearer_credentials.credentials
    elif basic_credentials is not None:
        return (basic_credentials.username, basic_credentials.password)
    else:
        raise HTTPException(status_code=401, detail="Authentication required")

class similaritySearchRequest(BaseModel):
    query: str
    vdp_database_names: str = os.getenv('VDB_NAMES', '')
    vdp_tag_names: str = os.getenv('VDB_TAGS', '')
    embeddings_provider: str = os.getenv('EMBEDDINGS_PROVIDER')
    embeddings_model: str = os.getenv('EMBEDDINGS_MODEL')
    vector_store_provider: str = os.getenv('VECTOR_STORE')
    n_results: int = 5
    scores: bool = False

class similaritySearchResponse(BaseModel):
    views: List[str]

@router.get(
        '/similaritySearch',
        response_class = JSONResponse,
        response_model = similaritySearchResponse,
        tags = ['Vector Store'])
async def similaritySearch(endpoint_request: similaritySearchRequest = Depends(), auth: str = Depends(authenticate)):
    """
    This endpoint performs a similarity search on the vector database specified in the request.
    The vector store MUST have been previously populated with the metadata of the views in the vector database
    using getMetadata endpoint.
    """
    try:
        vdp_database_names = [db.strip() for db in endpoint_request.vdp_database_names.split(',')] if endpoint_request.vdp_database_names else []
        vdp_tag_names = [tag.strip() for tag in endpoint_request.vdp_tag_names.split(',')] if endpoint_request.vdp_tag_names else []

        vector_store = UniformVectorStore(
            provider=endpoint_request.vector_store_provider,
            embeddings_provider=endpoint_request.embeddings_provider,
            embeddings_model=endpoint_request.embeddings_model,
        )

        if not vdp_database_names and not vdp_tag_names:
            vdp_database_names = vector_store.get_database_names()
            vdp_tag_names = vector_store.get_tag_names()

        search_params = {
            "query": endpoint_request.query,
            "k": endpoint_request.n_results,
            "scores": endpoint_request.scores,
            "database_names": vdp_database_names,
            "tag_names": vdp_tag_names
        }

        valid_view_ids = await get_allowed_view_ids(auth = auth, database_names = vdp_database_names, tag_names = vdp_tag_names)
        valid_view_ids = [str(view_id) for view_id in valid_view_ids]
        search_params["view_ids"] = valid_view_ids

        search_results = vector_store.search(**search_params)

        output = {
            "views": [
                {
                    "view_name": (result[0] if endpoint_request.scores else result).metadata["view_name"],
                    "view_json": (
                        filter_non_allowed_associations(
                            json.loads((result[0] if endpoint_request.scores else result).metadata["view_json"]),
                            valid_view_ids
                        )
                    ),
                    "view_text": (result[0] if endpoint_request.scores else result).page_content,
                    "database_name": (result[0] if endpoint_request.scores else result).metadata["database_name"],
                    "tag_names": (result[0] if endpoint_request.scores else result).metadata["tag_names"],
                    **({"scores": result[1]} if endpoint_request.scores else {})
                } for result in search_results
            ]
        }

        return JSONResponse(content = jsonable_encoder(output), media_type = "application/json")
    except Exception as e:

        error_details = {
            'error': str(e),
            'traceback': traceback.format_exc()
        }

        raise HTTPException(status_code=500, detail=error_details)
