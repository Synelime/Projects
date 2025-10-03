import json
from typing import List
import numpy as np
from sap_ai_client import SAPAIClient
from hdbcli import dbapi
from langchain.schema import SystemMessage, HumanMessage
# import mdpd


HANA_CONFIG = {
    "address": "fa397c64-114e-4362-9703-7269afd867ef.hana.prod-eu10.hanacloud.ondemand.com",
    "port": 443,
    "user": "GAURAV",
    "password": "Pune@123",
    "schema": "GAURAV"
}

resource_group = 'innovation-POC-AI'
client_id= "sb-ec189626-272a-4d13-afe1-053f11d084af!b127909|aicore!b540"
client_secret= "8c30cb20-8cc7-4d79-bbda-49b5d0184f31$HTk42OzXt99J1KVHJ3p1KSoJrDZ1oCQv7OlDfbTQCvc="
auth_url = "https://gdseypoc.authentication.eu10.hana.ondemand.com/oauth/token/"
base_url= 'https://api.ai.prod.eu-central-1.aws.ml.hana.ondemand.com'

# 1. Initialize your SAPAIClient with credentials
from typing import List, Tuple
import json
import numpy as np
from langchain.schema import SystemMessage, HumanMessage

# --- Fetch embeddings and chunks from HANA ---
def fetch_embeddings_by_filters(region: str, document_type: str, process_id: str, business_process: str) -> Tuple[List[List[float]], List[str]]:
    conn = dbapi.connect(
        address=HANA_CONFIG["address"],
        port=HANA_CONFIG["port"],
        user=HANA_CONFIG["user"],
        password=HANA_CONFIG["password"]
    )
    cursor = conn.cursor()
    schema = HANA_CONFIG["schema"]

    query = f"""
        SELECT CHUNK, EMBEDDINGS
        FROM {schema}.SIGNAVIO_TEST_CASE_DATA
        WHERE REGION = ? AND DOCUMENT_TYPE = ? AND PROCESS_ID = ? AND BUSINESS_PROCESS = ?
    """
    cursor.execute(query, (region, document_type, process_id, business_process))
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    chunks = []
    embeddings = []

    for chunk_text, embedding_blob in rows:
        embedding = json.loads(embedding_blob.tobytes().decode('utf-8'))
        chunks.append(chunk_text)
        embeddings.append(embedding)

    return embeddings, chunks

from hana_ml import dataframe as hd
import json

def fetch_embeddings_by_hanaml(region, document_type, process_id, business_process):
    conn = hd.ConnectionContext(
        address=HANA_CONFIG["address"],
        port=HANA_CONFIG["port"],
        user=HANA_CONFIG["user"],
        password=HANA_CONFIG["password"]
    )

    query = f"""
        SELECT d.CHUNK, d.EMBEDDINGS
        FROM SIGNAVIO_TEST_CASE_DATA d
        JOIN SIGNAVIO_VERTICES vdoc
          ON d.DOC_NAME = vdoc.VERTEX_ID
        JOIN SIGNAVIO_EDGES e3
          ON e3.TARGET = vdoc.VERTEX_ID
        JOIN SIGNAVIO_VERTICES vbp
          ON e3.SOURCE = vbp.VERTEX_ID
        JOIN SIGNAVIO_EDGES e2
          ON e2.TARGET = vbp.VERTEX_ID
        JOIN SIGNAVIO_VERTICES vpid
          ON e2.SOURCE = vpid.VERTEX_ID
        JOIN SIGNAVIO_EDGES e1
          ON e1.TARGET = vpid.VERTEX_ID
        JOIN SIGNAVIO_VERTICES vdt
          ON e1.SOURCE = vdt.VERTEX_ID
        JOIN SIGNAVIO_EDGES e0
          ON e0.TARGET = vdt.VERTEX_ID
        JOIN SIGNAVIO_VERTICES vr
          ON e0.SOURCE = vr.VERTEX_ID
        WHERE vr.VERTEX_ID = '{region}'
          AND vdt.VERTEX_ID = '{document_type}'
          AND vpid.VERTEX_ID = '{process_id}'
          AND vbp.VERTEX_ID = '{business_process}'
    """

    df = conn.sql(query)
    pdf = df.collect()

    chunks, embeddings = [], []
    for _, row in pdf.iterrows():
        emb = json.loads(row['EMBEDDINGS'].tobytes().decode('utf-8'))
        chunks.append(row['CHUNK'])
        embeddings.append(emb)

    conn.close()
    return embeddings, chunks



# from typing import List, Tuple
# import json
# import hana_ml.dataframe as dataframe
# from hana_ml.graph import GraphWorkspace

# def fetch_embeddings_by_filters(region: str, document_type: str, process_id: str, business_process: str) -> Tuple[List[List[float]], List[str]]:
#     conn = dbapi.connect(
#         address=HANA_CONFIG["address"],
#         port=HANA_CONFIG["port"],
#         user=HANA_CONFIG["user"],
#         password=HANA_CONFIG["password"]
#     )
#     schema = HANA_CONFIG["schema"]

#     # Step 1: Use GRAPH_MATCH to find connected documents
#     graph_query = f"""
#         CREATE PROCEDURE GET_DOCUMENTS_BY_GRAPH_PATH (
#         IN {region} NVARCHAR(100),
#         IN {document_type} NVARCHAR(100),
#         IN {process_id} NVARCHAR(100),
#         IN {business_process} NVARCHAR(255)
#         )
#         LANGUAGE SQLSCRIPT
#         AS
#         BEGIN
#             RETURN
#             SELECT v_doc.VERTEX_ID AS DOC_NAME
#             FROM GRAPH_MATCH (
#                 GRAPH "SIGNAVIO_TEST_CASE_GRAPH"
#                 START VERTEX v_region
#                 MATCH v_region -> v_doc_type -> v_process -> v_bp -> v_doc
#                 WHERE v_region.VERTEX_ID = :{region}
#                 AND v_doc_type.VERTEX_ID = :{document_type}
#                 AND v_process.VERTEX_ID = :{process_id}
#                 AND v_bp.VERTEX_ID = :{business_process}
#             );
#         END;
#     """

#     cursor = conn.cursor()
#     cursor.execute(graph_query)
#     graph_rows = cursor.fetchall()

#     # Extract document names from graph traversal
#     doc_names = list(set(row[-1] for row in graph_rows))  # Assuming v_doc.VERTEX_ID is last

#     if not doc_names:
#         cursor.close()
#         conn.close()
#         return [], []

#     # Step 2: Query base table using document names
#     placeholders = ','.join(['?'] * len(doc_names))
#     data_query = f"""
#         SELECT CHUNK, EMBEDDINGS
#         FROM {schema}.SIGNAVIO_TEST_CASE_DATA
#         WHERE DOC_NAME IN ({placeholders})
#     """
#     cursor.execute(data_query, doc_names)
#     rows = cursor.fetchall()

#     cursor.close()
#     conn.close()

#     chunks = []
#     embeddings = []

#     for chunk_text, embedding_blob in rows:
#         embedding = json.loads(embedding_blob.tobytes().decode('utf-8'))
#         chunks.append(chunk_text)
#         embeddings.append(embedding)

#     return embeddings, chunks

# def fetch_embeddings_by_filters(region: str, document_type: str, process_id: str, business_process: str) -> Tuple[List[List[float]], List[str]]:
#     conn = dbapi.connect(
#         address=HANA_CONFIG["address"],
#         port=HANA_CONFIG["port"],
#         user=HANA_CONFIG["user"],
#         password=HANA_CONFIG["password"]
#     )
#     schema = HANA_CONFIG["schema"]
#     cursor = conn.cursor()

#     # Call the stored procedure
#     cursor.callproc(f"{schema}.GET_DOCUMENTS_BY_GRAPH_PATH", [region, document_type, process_id, business_process])
#     graph_rows = cursor.fetchall()

#     doc_names = list(set(row[0] for row in graph_rows))  # Assuming DOC_NAME is in first column

#     if not doc_names:
#         cursor.close()
#         conn.close()
#         return [], []

#     # Query base table using document names
#     placeholders = ','.join(['?'] * len(doc_names))
#     data_query = f"""
#         SELECT CHUNK, EMBEDDINGS
#         FROM {schema}.SIGNAVIO_TEST_CASE_DATA
#         WHERE DOC_NAME IN ({placeholders})
#     """
#     cursor.execute(data_query, doc_names)
#     rows = cursor.fetchall()

#     cursor.close()
#     conn.close()

#     chunks = []
#     embeddings = []

#     for chunk_text, embedding_blob in rows:
#         embedding = json.loads(embedding_blob.tobytes().decode('utf-8'))
#         chunks.append(chunk_text)
#         embeddings.append(embedding)

#     return embeddings, chunks



# --- Cosine similarity ---
def cosine_similarity(a: List[float], b: List[float]) -> float:
    a = np.array(a)
    b = np.array(b)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

# --- Find top-k relevant chunks ---
def find_top_k_relevant_chunks(
    query: str,
    client: SAPAIClient,
    chunks: List[str],
    chunk_embeddings: List[List[float]],
    k: int = 8
) -> List[Tuple[str, float]]:
    query_embedding = client.get_embedding(query)
    similarities = [cosine_similarity(query_embedding, emb) for emb in chunk_embeddings]
    top_k_indices = np.argsort(similarities)[-k:][::-1]
    return [(chunks[i], similarities[i]) for i in top_k_indices]

# --- Main execution ---
client = SAPAIClient(resource_group, client_id, client_secret, auth_url, base_url)

query = """
From the context extracted out, find the section **Test Procedures**.
Provide full content including sub-sections with table and text.
"""

# Fetch data
chunk_embeddings, chunks = fetch_embeddings_by_hanaml(
    region='US',
    document_type= 'Test Script',
    process_id= '21R',
    business_process="Service Contract "
)

# Get top 3 relevant chunks
top_chunks = find_top_k_relevant_chunks(query, client, chunks, chunk_embeddings, k=3)

# Format chunks for LLM input
formatted_chunks = "\n\n".join([f"Chunk {i+1} (score={score:.4f}):\n{chunk}" for i, (chunk, score) in enumerate(top_chunks)])

# Prepare messages
messages = [
    SystemMessage(content="""
You are an experienced SAP functional consultant tasked with generating detailed and high-quality content for Business Process Design (BPD) documents.
The BPD documents are to be created for a client in the Retail Industry for an SAP ERP implementation. As is the standard process, this BPD is to be created following the workshops with the client,
detailing their requirements in this implementation.
"""),
    HumanMessage(content=f"Based on the query:\n{query}\n\nHere are the top relevant chunks:\n{formatted_chunks}\n\nPlease generate the most suitable answer.")
]

# Invoke LLM
response = client.llm.invoke(messages)
print(response.content)
