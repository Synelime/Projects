import os
from typing import List
import pandas as pd
from chunk import chunk_docx_hierarchical
from utils import  find_file_in_subfolders, ingest_to_hana_graph_db, ingest_to_hana_graph_db_batch, slugify
from tqdm import tqdm
import logging
from sap_ai_client import SAPAIClient

logging.basicConfig(level=logging.INFO)

# base_folder = r'C:\Users\CA958UT\Downloads\Project\TSP-Hana GraphDB\BPD 1'

resource_group = 'innovation-POC-AI'
client_id= "sb-ec189626-272a-4d13-afe1-053f11d084af!b127909|aicore!b540"
client_secret= "8c30cb20-8cc7-4d79-bbda-49b5d0184f31$HTk42OzXt99J1KVHJ3p1KSoJrDZ1oCQv7OlDfbTQCvc="
auth_url = "https://gdseypoc.authentication.eu10.hana.ondemand.com/oauth/token/"
base_url= 'https://api.ai.prod.eu-central-1.aws.ml.hana.ondemand.com'

# 1. Initialize your SAPAIClient with credentials
client = SAPAIClient(resource_group, client_id, client_secret, auth_url, base_url)

def embed_doc_chunks(client: SAPAIClient, chunks: List[str]) -> List[List[float]]:
    return [client.get_embedding(chunk) for chunk in chunks]
logging.basicConfig(level=logging.INFO)

base_folder = r'SIGNAVIO_DATA'

# def main():
#     df = pd.read_excel(r"SIGNAVIO_DATA.xlsx")
#     logging.info("Successfully fetched data from .xlsx")

#     for i in tqdm(range(len(df)), desc="Processing documents"):
#         doc_info = dict(df.iloc[i])
#         doc_name = doc_info['File Name'] + '.docx'
#         region = doc_info['Region']
#         process_id = doc_info['Process ID']
#         document_type = doc_info['Document Type']
#         business_process = doc_info['Business Process']

#         try:
#             doc_path = find_file_in_subfolders(base_folder=base_folder, target_filename=doc_name)
#             chunks = chunk_docx_hierarchical(doc_path, max_chars=5000, overlap=500)
#             doc_id = doc_name
#             embedding = embed_doc_chunks(client= client,chunks=chunks)
#             for idx, text in tqdm(enumerate(chunks)):
#                 chunk_id = slugify(f"{doc_id}:{idx}")
#                     # print(chunk_id,doc_id)
                    
#                 ingest_to_hana_graph_db(region, process_id, document_type, business_process,
#                             chunk_id, doc_id, doc_name, text, embedding[idx])
#                     # print(chunk_id)
#                     # print(idx)

#             logging.info(f"Ingestion Successful for {doc_name}")

#         except Exception as e:
#             logging.error(f"Error processing {doc_name}: {e}")



# if __name__ == "__main__":
#     main()

def main():
    df = pd.read_excel(r"SIGNAVIO_DATA.xlsx")
    logging.info("Successfully fetched data from .xlsx")

    for i in tqdm(range(len(df)), desc="Processing documents"):
        doc_info = dict(df.iloc[i])
        doc_name = doc_info['File Name'] + '.docx'
        region = doc_info['Region']
        process_id = doc_info['Process ID']
        document_type = doc_info['Document Type']
        business_process = doc_info['Business Process']

        try:
            doc_path = find_file_in_subfolders(base_folder=base_folder, target_filename=doc_name)
            chunks = chunk_docx_hierarchical(doc_path, max_chars=5000, overlap=500)
            doc_id = doc_name
            embedding = embed_doc_chunks(client=client, chunks=chunks)

            chunks_data = []
            for idx, text in enumerate(chunks):
                chunk_id = slugify(f"{doc_id}:{idx}")
                chunks_data.append({
                    'region': region,
                    'process_id': process_id,
                    'document_type': document_type,
                    'business_process': business_process,
                    'chunk_id': chunk_id,
                    'doc_id': doc_id,
                    'doc_name': doc_name,
                    'chunk_text': text,
                    'embedding': embedding[idx]
                })

            ingest_to_hana_graph_db_batch(chunks_data)
            logging.info(f"Ingestion Successful for {doc_name}")

        except Exception as e:
            logging.error(f"Error processing {doc_name}: {e}")

if __name__ == "__main__":
    main()

