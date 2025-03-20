import os
import ast
import time
import sqlite3
import logging
import concurrent.futures

from utils.utils import log_params
from utils.uniformEmbeddings import UniformEmbeddings

class UniformVectorStore:
    def __init__(self, provider, embeddings_provider, embeddings_model, index_name = "ai_sdk_vector_store", manager_db = "ai_sdk_manager.db", rate_limit_rpm = None):
        self.provider = provider.lower()
        self.embeddings = UniformEmbeddings(embeddings_provider, embeddings_model).model
        self.index_name = index_name
        self.rate_limit_rpm = rate_limit_rpm
        self.manager_db = os.path.join(index_name, manager_db)
        self.client = None
        self.dimensions = self._get_dimensions()
        self._connect_manager()
        self._connect()
        
    def _connect(self):
        if self.provider == "chroma":
            import platform
            if platform.system() == "Linux":
                __import__('pysqlite3')
                import sys
                sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
            from chromadb.config import Settings
            from langchain_chroma import Chroma
            self.client = Chroma(
                collection_name=self.index_name,
                embedding_function=self.embeddings,
                persist_directory=self.index_name,
                collection_metadata={
                    "hnsw:space": "cosine",
                    "hnsw:construction_ef": 128,
                    "hnsw:search_ef": 128,
                    "hnsw:M": 128
                },
                client_settings = Settings(
                    anonymized_telemetry=False,
                    is_persistent=True
                )
            )
        elif self.provider == "pgvector":
            from langchain_postgres import PGVector

            PGVECTOR_CONNECTION_STRING = os.getenv("PGVECTOR_CONNECTION_STRING", "postgresql+psycopg://langchain:langchain@localhost:6024/langchain")

            self.client = PGVector(
                embeddings=self.embeddings,
                collection_name=self.index_name,
                connection=PGVECTOR_CONNECTION_STRING,
                use_jsonb=True,
            )
        elif self.provider == "opensearch":
            from langchain_community.vectorstores import OpenSearchVectorSearch

            OPENSEARCH_URL = os.getenv("OPENSEARCH_URL", "http://localhost:9200")
            OPENSEARCH_USERNAME = os.getenv("OPENSEARCH_USERNAME", "admin")
            OPENSEARCH_PASSWORD = os.getenv("OPENSEARCH_PASSWORD", "admin")

            self.client = OpenSearchVectorSearch(
                opensearch_url = OPENSEARCH_URL,
                http_auth = (OPENSEARCH_USERNAME, OPENSEARCH_PASSWORD),
                embedding_function = self.embeddings,
                index_name = self.index_name,
                use_ssl = True,
                verify_certs = False,
                ssl_assert_hostname = False,
                ssl_show_warn = False,
            )
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")
        
    def _get_dimensions(self):
        return len(self.embeddings.embed_query("test"))

    def _connect_manager(self):
        if not os.path.exists(self.index_name):
            os.makedirs(self.index_name)
        self.manager_conn = sqlite3.connect(self.manager_db, check_same_thread=False)
        self.manager_cursor = self.manager_conn.cursor()
        
        # Create views table
        self.manager_cursor.execute('''
            CREATE TABLE IF NOT EXISTS views (
                view_id TEXT PRIMARY KEY,
                view_name TEXT,
                database_id INTEGER
            )
        ''')
        
        # Create databases table
        self.manager_cursor.execute('''
            CREATE TABLE IF NOT EXISTS databases (
                database_id INTEGER PRIMARY KEY AUTOINCREMENT,
                database_name TEXT UNIQUE
            )
        ''')
        
        # Create tags table
        self.manager_cursor.execute('''
            CREATE TABLE IF NOT EXISTS tags (
                tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag_name TEXT UNIQUE
            )
        ''')
        
        # Create view_tags linking table
        self.manager_cursor.execute('''
            CREATE TABLE IF NOT EXISTS view_tags (
                view_id TEXT,
                tag_id INTEGER,
                PRIMARY KEY (view_id, tag_id),
                FOREIGN KEY (view_id) REFERENCES views (view_id),
                FOREIGN KEY (tag_id) REFERENCES tags (tag_id)
            )
        ''')
        
        self.manager_conn.commit()
        
    def _add_views_to_manager(self, views):
        for view in views:
            # Get database_id or create new database entry
            database_name = view.metadata['database_name']
            self.manager_cursor.execute(
                "INSERT OR IGNORE INTO databases (database_name) VALUES (?)", 
                (database_name,)
            )
            self.manager_cursor.execute(
                "SELECT database_id FROM databases WHERE database_name = ?", 
                (database_name,)
            )
            database_id = self.manager_cursor.fetchone()[0]
            
            # Insert or update view
            self.manager_cursor.execute(
                "INSERT OR REPLACE INTO views (view_id, view_name, database_id) VALUES (?, ?, ?)",
                (view.id, view.metadata['view_name'], database_id)
            )
            
            # Process tags if they exist in metadata
            if 'tag_names' in view.metadata and view.metadata['tag_names']:
                try:
                    tag_names = ast.literal_eval(view.metadata['tag_names'])
                                        
                    # Add new tag associations
                    for tag_name in tag_names:
                        # Insert tag if not exists
                        self.manager_cursor.execute(
                            "INSERT OR IGNORE INTO tags (tag_name) VALUES (?)", 
                            (tag_name,)
                        )
                        # Get tag_id
                        self.manager_cursor.execute(
                            "SELECT tag_id FROM tags WHERE tag_name = ?", 
                            (tag_name,)
                        )
                        tag_id = self.manager_cursor.fetchone()[0]
                        
                        # Link view to tag
                        self.manager_cursor.execute(
                            "INSERT OR IGNORE INTO view_tags (view_id, tag_id) VALUES (?, ?)",
                            (view.id, tag_id)
                        )
                except Exception as e:
                    logging.error(f"Error parsing tag_names for view {view.id}: {e}")
        
        self.manager_conn.commit()

    def _delete_views_from_manager(self, view_ids):
        placeholders = ','.join(['?' for _ in view_ids])
        
        # Delete from view_tags first (foreign key constraint)
        self.manager_cursor.execute(f"DELETE FROM view_tags WHERE view_id IN ({placeholders})", view_ids)
        
        # Delete from views
        self.manager_cursor.execute(f"DELETE FROM views WHERE view_id IN ({placeholders})", view_ids)
        
        self.manager_conn.commit()
        
        # Clean up orphaned tags
        self.manager_cursor.execute("""
            DELETE FROM tags 
            WHERE tag_id NOT IN (SELECT DISTINCT tag_id FROM view_tags)
        """)
        self.manager_conn.commit()

    @log_params
    def _get_existing_view_ids(self):
        self.manager_cursor.execute("SELECT view_id FROM views")
        return [row[0] for row in self.manager_cursor.fetchall()]

    @log_params
    def get_view_ids(self, view_names):
        # Make sure the view names don't contain quotes
        view_names = [view_name.replace('"', '') for view_name in view_names]
        placeholders = ','.join(['?' for _ in view_names])
        self.manager_cursor.execute(f"SELECT view_id FROM views WHERE view_name IN ({placeholders})", view_names)
        return [row[0] for row in self.manager_cursor.fetchall()]
    
    @log_params
    def _get_view_ids_by_database(self, database_name):
        self.manager_cursor.execute("""
            SELECT v.view_id 
            FROM views v
            JOIN databases d ON v.database_id = d.database_id
            WHERE d.database_name = ?
        """, (database_name,))
        return [str(row[0]) for row in self.manager_cursor.fetchall()]

    @log_params
    def _get_view_ids_by_tag(self, tag_name):
        """
        Returns all view_ids associated with a specific tag.
        """
        self.manager_cursor.execute("""
            SELECT v.view_id 
            FROM views v
            JOIN view_tags vt ON v.view_id = vt.view_id
            JOIN tags t ON vt.tag_id = t.tag_id
            WHERE t.tag_name = ?
        """, (tag_name,))
        return [row[0] for row in self.manager_cursor.fetchall()]

    @log_params
    def search(self, query, k=3, view_ids=None, scores=False, database_names=None, tag_names=None):
        # Get view_ids based on database_names and tag_names if provided
        filtered_view_ids = self._filter_view_ids(view_ids, database_names, tag_names)
        
        if filtered_view_ids is not None and len(filtered_view_ids) == 0:
            return []

        search_filter = self._build_search_filter(filtered_view_ids)
        
        if scores:
            if self.provider == "opensearch":
                return self.client.similarity_search_with_score(query, k=k, search_type="script_scoring", pre_filter=search_filter)
            elif self.provider in ["chroma", "pgvector"]:
                return self.client.similarity_search_with_score(query, k=k, filter=search_filter)
        else:
            if self.provider == "opensearch":
                return self.client.similarity_search(query, k=k, search_type="script_scoring", pre_filter=search_filter)
            elif self.provider in ["chroma", "pgvector"]:
                return self.client.similarity_search(query, k=k, filter=search_filter)

    @log_params
    def search_by_vector(self, vector, k=3, view_ids=None, scores=False, database_names=None, tag_names=None):
        # Get view_ids based on database_names and tag_names if provided
        filtered_view_ids = self._filter_view_ids(view_ids, database_names, tag_names)
        
        if filtered_view_ids is not None and len(filtered_view_ids) == 0:
            return []
        
        search_filter = self._build_search_filter(filtered_view_ids)

        # PGVector does not support scores
        if self.provider == "pgvector":
            scores = False
        
        if scores:
            if self.provider == "opensearch":
                return self.client.similarity_search_by_vector_with_relevance_scores(vector, k=k, search_type="script_scoring", pre_filter=search_filter)
            elif self.provider in ["chroma"]:
                return self.client.similarity_search_by_vector_with_relevance_scores(vector, k=k, filter=search_filter)
        else:
            if self.provider == "opensearch":
                return self.client.similarity_search_by_vector(vector, k=k, search_type="script_scoring", pre_filter=search_filter)
            elif self.provider in ["chroma"]:
                return self.client.similarity_search_by_vector(vector, k=k, filter=search_filter)

    @log_params
    def _filter_view_ids(self, view_ids=None, database_names=None, tag_names=None):
        if view_ids is None and not database_names and not tag_names:
            return None
        
        if len(view_ids) == 0:
            return view_ids
        
        db_view_ids = []
        tag_view_ids = []

        # Filter by database_names
        if database_names:
            for db_name in database_names:
                db_view_ids.extend(self._get_view_ids_by_database(db_name))
                            
        # Filter by tag_names
        if tag_names:
            for tag_name in tag_names:
                tag_view_ids.extend(self._get_view_ids_by_tag(tag_name))
        
        if view_ids:
            view_ids = [view_id for view_id in view_ids if view_id in db_view_ids or view_id in tag_view_ids]
        else:
            view_ids = db_view_ids + tag_view_ids

        return view_ids

    @log_params
    def _build_search_filter(self, view_ids):
        # Convert empty lists to None
        view_ids = None if not view_ids else view_ids
        if not view_ids:
            return None
        
        if self.provider == "opensearch":
            return {"terms": {"metadata.view_id": view_ids}}
        elif self.provider in ['chroma', 'pgvector']:
            return {"view_id": {"$in": view_ids}}
        else:
            return None

    def add_views(self, views, overwrite = False, parallel = True):
        views = list({view.id: view for view in views}.values())
        view_ids = [view.id for view in views]

        if overwrite:
            self.client.delete(ids = view_ids)
            self._delete_views_from_manager(view_ids)

        existing_view_ids = self._get_existing_view_ids()
        new_views = [view for view in views if view.id not in existing_view_ids]
        ids = [view.id for view in new_views]
        
        if not new_views:
            return
            
        # If rate limiting is enabled, process views in batches
        if self.rate_limit_rpm and len(new_views) > self.rate_limit_rpm:
            logging.info(f"Rate limiting enabled: {self.rate_limit_rpm} views per minute. Total views: {len(new_views)}")
            
            # Process views in batches based on rate limit
            for i in range(0, len(new_views), self.rate_limit_rpm):
                batch_end = min(i + self.rate_limit_rpm, len(new_views))
                batch_views = new_views[i:batch_end]
                batch_ids = ids[i:batch_end]
                
                logging.info(f"Processing batch {i//self.rate_limit_rpm + 1}: {len(batch_views)} views")
                
                # Process this batch using existing methods
                if parallel:
                    try:
                        self._add_views_parallel(batch_views, batch_ids)
                    except Exception as e:
                        logging.warning(f"Parallel processing failed: {str(e)}. Falling back to sequential processing.")
                        self.client.add_documents(batch_views, ids=batch_ids)
                        self._add_views_to_manager(batch_views)
                else:
                    self.client.add_documents(batch_views, ids=batch_ids)
                    self._add_views_to_manager(batch_views)
                
                # If there are more batches to process, wait for the next minute
                if batch_end < len(new_views):
                    wait_time = 60  # Wait 1 minute
                    logging.info(f"Waiting {wait_time} seconds before processing next batch...")
                    time.sleep(wait_time)
        else:
            # Process all views at once (original behavior)
            if parallel:
                try:
                    self._add_views_parallel(new_views, ids)
                except Exception as e:
                    logging.warning(f"Parallel processing failed: {str(e)}. Falling back to sequential processing.")
                    self.client.add_documents(new_views, ids=ids)
                    self._add_views_to_manager(new_views)
            else:
                self.client.add_documents(new_views, ids=ids)
                self._add_views_to_manager(new_views)

    def _add_views_parallel(self, views, ids, batch_size=5, max_retries=3):
        """Add views in parallel with batching and error handling."""
        
        def process_batch(batch_views, batch_ids, attempt=1):
            try:
                self.client.add_documents(batch_views, ids=batch_ids)
                self._add_views_to_manager(batch_views)
                return True, None
            except Exception as e:
                if attempt < max_retries:
                    logging.warning(f"Attempt {attempt} failed: {str(e)}. Retrying...")
                    time.sleep(5**attempt)
                    return process_batch(batch_views, batch_ids, attempt + 1)
                return False, (batch_views, batch_ids, str(e))

        # Create batches
        batches = [
            (views[i:i + batch_size], ids[i:i + batch_size])
            for i in range(0, len(views), batch_size)
        ]

        failed_batches = []
        
        # Process batches in parallel
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = [
                executor.submit(process_batch, batch_views, batch_ids)
                for batch_views, batch_ids in batches
            ]
            
            # Collect results and handle failures
            for future in concurrent.futures.as_completed(futures):
                success, result = future.result()
                if not success:
                    failed_batch_views, failed_batch_ids, error = result
                    failed_batches.append((failed_batch_views, failed_batch_ids))
                    logging.error(f"Batch processing failed: {error}")

        # Handle any failed batches sequentially
        if failed_batches:
            logging.warning(f"Processing {len(failed_batches)} failed batches sequentially")
            for failed_views, failed_ids in failed_batches:
                try:
                    self.client.add_documents(failed_views, ids=failed_ids)
                    self._add_views_to_manager(failed_views)
                except Exception as e:
                    logging.error(f"Fatal error processing batch: {str(e)}")
                    raise RuntimeError(f"Failed to process views after all retries: {str(e)}")

    @log_params
    def get_views(self, view_names, valid_view_ids = None):
        view_ids = self.get_view_ids(view_names)
        if valid_view_ids is not None:
            view_ids = [view_id for view_id in view_ids if view_id in valid_view_ids]
        if len(view_ids) == 0:
            view_ids = None
            return []
        chunk_factor = 5
        views = self.search_by_vector([0]*self.dimensions, k=len(view_names) * chunk_factor, view_ids=view_ids, scores=False)
        
        # Create a dictionary to keep only unique views based on view_name
        # Necessary because now there might be chunks of the same view
        unique_views = {}
        for view in views:
            view_name = view.metadata['view_name']
            if view_name not in unique_views:
                unique_views[view_name] = view
        
        return list(unique_views.values())
    
    @log_params
    def delete_views(self, view_names):
        view_ids = [str(id) for id in self.get_view_ids(view_names)]
        if len(view_ids) != 0:
            self.client.delete(view_ids)
            self._delete_views_from_manager(view_ids)

    @log_params
    def delete_database(self, database_name):
        view_ids = []
        while True:
            ids = self.search_by_vector([0]*self.dimensions, k=1000, database_names=[database_name])
            if len(ids) == 0:
                break
            view_ids.extend(ids)
        self.client.delete(view_ids)
        self._delete_views_from_manager(view_ids)

    @log_params
    def get_database_names(self):
        """
        Returns a list of all database names in the manager.
        """
        self.manager_cursor.execute("SELECT database_name FROM databases ORDER BY database_name")
        return [row[0] for row in self.manager_cursor.fetchall()]

    @log_params
    def get_tag_names(self):
        """
        Returns a list of all tag names in the manager.
        """
        self.manager_cursor.execute("SELECT tag_name FROM tags ORDER BY tag_name")
        return [row[0] for row in self.manager_cursor.fetchall()]

    def __del__(self):
        try:
            if hasattr(self, 'manager_conn'):
                self.manager_conn.close()
        except Exception:
            pass