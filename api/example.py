import requests
import json
import time

# API_HOST for demo purposes
API_HOST = 'http://localhost:8008'
API_VDB = 'bank'
DATA_CATALOG_USER = 'admin'
DATA_CATALOG_PWD = 'admin'

def get_metadata(database_name, insert_in_vector_db = True, overwrite_vector_db = True):
    """Get metadata from VDP and optionally insert it into the database."""
    request_params = {
        'vdp_database_name': database_name,
        'insert_in_vector_db': insert_in_vector_db,
        'overwrite_vector_db': overwrite_vector_db
    }
    response = requests.get(f'{API_HOST}/getMetadata', params=request_params, auth = (DATA_CATALOG_USER, DATA_CATALOG_PWD))
    
    if response.status_code == 200:
        return response.json()
    else:
        response.raise_for_status()

def stream_answer_question(question):
    """Stream the answer to a question from the LLM."""
    request_params = {'question': question}
    response = requests.get(f'{API_HOST}/streamAnswerQuestion', params=request_params, stream=True, auth = (DATA_CATALOG_USER, DATA_CATALOG_PWD))
        
    for chunk in response.iter_lines(decode_unicode = True):
        print(chunk, end='', flush=True)
    
def answer_question(question, mode="default"):
    """Get the answer to a question from the LLM."""
    request_params = {'question': question, "mode": mode}
    response = requests.get(f'{API_HOST}/answerQuestion', params=request_params, auth = (DATA_CATALOG_USER, DATA_CATALOG_PWD))
    if response.status_code == 200:
        try:
            response_data = response.json()
            print(f"Mode: {mode}")
            print("Answer:", response_data.get('answer', 'No answer found.'))
            print("SQL Query:", response_data.get('sql_query', 'No SQL query found.'))
            print("Tokens:", response_data.get('tokens', 'No tokens found.'))
            print("CSV data:", response_data.get('execution_result', 'No CSV data returned.'))
            print("Tables used:", response_data.get('tables_used', 'No tables used data returned.'))
            print("Denodo execution time:", response_data.get('denodo_execution_time', 'No denodo execution time data returned.'))
            print()
        except json.JSONDecodeError:
            print("Error decoding JSON response")
    else:
        response.raise_for_status()

if __name__ == "__main__":
    # Get metadata and insert it into the vector store
    start_time = time.time()
    metadata = get_metadata(API_VDB)
    print("Metadata retrieved and inserted into the vector store.")
    print(f"Time taken: {time.time() - start_time:.2f} seconds\n")

    question = "How many approved loans do we have?"
    
    # Using streamAnswerQuestion
    print(f"\nQuestion: {question}")
    print("Streaming answer:")
    start_time = time.time()
    stream_answer_question(question)
    print(f"Time taken: {time.time() - start_time:.2f} seconds\n")

    # Using answerQuestion
    print(f"\nQuestion: {question}")
    print("Direct Answer:")
    start_time = time.time()
    answer_question(question)
    print(f"Time taken: {time.time() - start_time:.2f} seconds\n")

    modes = ["data", "metadata"]

    for mode in modes:
        print(f"Testing {mode.upper()} mode in answerQuestion:")
        start_time = time.time()
        answer_question(question, mode)
        print(f"Time taken: {time.time() - start_time:.2f} seconds\n")