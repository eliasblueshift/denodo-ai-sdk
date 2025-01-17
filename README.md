![Denodo Logo](api/static/denodo-logo.png)

**Denodo AI SDK**
==============

The user manual for the Denodo AI SDK is available [in the Denodo Connects documentation section](https://community.denodo.com/docs/html/browse/9.0/en/denodoconnects/index).

The Denodo AI SDK includes all the necessary artifacts required to serve a RAG client user-interface application.   

The goals of this project are:
* To enable AI via the RAG pattern to leverage an entire data ecosystem through accessing a governed single layer. A single security model that enforces data access constaints or rules through the users interacting with the SDK. 
* Simplify model functions by removing the need to build JOINS and other relational operations that can be encoded into Denodo.
* Enable LLM models to have access to real time data
* Leverage virtualization through AI by providing a single view of metadata where changes to the data sources and implementation logic will not change interface views.

### Recommended LLM and Embeddings Models

| Provider    | LLM Recommended      | LLM Alternative                     | Embeddings            |
|------------:|---------------------:|------------------------------------:|----------------------:|
| OpenAI      | gpt-4o               | gpt-4o-mini                         | text-embedding-3-large|
| Bedrock     | anthropic.claude-3-5-sonnet-20240620-v1:0    | anthropic.claude-3-haiku-20240307-v1:0                   | amazon.titan-embed-text-v2:0   |
| Google      | gemini-1.5-pro       | gemini-1.5-flash                    | gecko                 |
| Mistral      | mistral-large-latest       | mistral-large-latest                    | mistral-embed                 |

# Licensing
Please see the file called LICENSE.