import json
import logging
import os
from typing import List
import uuid
from sap_ai_client import SAPAIClient
from hdbcli import dbapi

logging.basicConfig(level=logging.INFO)

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

def ingest_to_hana_graph_db(region, process_id, document_type, business_process,
                            chunk_id, doc_id, doc_name, chunk_text, embedding):
    conn = dbapi.connect(
        address=HANA_CONFIG["address"],
        port=HANA_CONFIG["port"],
        user=HANA_CONFIG["user"],
        password=HANA_CONFIG["password"]
    )
    cursor = conn.cursor()
    schema = HANA_CONFIG["schema"]

    try:
        # === 1. Insert into SIGNAVIO_TEST_CASE_DATA===
        cursor.execute(f"""
            UPSERT {schema}.SIGNAVIO_TEST_CASE_DATA
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            WITH PRIMARY KEY
        """, (
            doc_name,          # PK
            region,
            document_type,
            process_id,
            business_process,
            doc_id,
            chunk_id,
            chunk_text,
            json.dumps(embedding)
        ))

        # === 2. Upsert Vertices ===
        for vid, label in [
            (region, "Region"),
            (document_type, "DocumentType"),
            (process_id, "ProcessId"),
            (business_process, "BusinessProcess"),
            (doc_name, "Document")
        ]:
            cursor.execute(f"""
                UPSERT {schema}.SIGNAVIO_VERTICES
                VALUES (?, ?)
                WITH PRIMARY KEY
            """, (vid, label))

        # === 3. Upsert Edges (composite IDs) ===
        edges = [
            (f"{region}_{document_type}", region, document_type, "belongs_to"),
            (f"{document_type}_{process_id}", document_type, process_id, "belongs_to"),
            (f"{process_id}_{business_process}", process_id, business_process, "belongs_to"),
            (f"{business_process}_{doc_name}", business_process, doc_name, "belongs_to"),
        ]
        for eid, src, tgt, lbl in edges:
            cursor.execute(f"""
                UPSERT {schema}.SIGNAVIO_EDGES
                VALUES (?, ?, ?, ?)
                WITH PRIMARY KEY
            """, (eid, src, tgt, lbl))

        conn.commit()
        logging.info(f"✅ Ingested chunk {chunk_id} for document {doc_id} successfully.")

    except Exception as e:
        logging.error(f"❌ Error ingesting data for chunk {chunk_id}: {e}")
        conn.rollback()

    finally:
        cursor.close()
        conn.close()


def ingest_to_hana_graph_db_batch(chunks_data):
    conn = dbapi.connect(
        address=HANA_CONFIG["address"],
        port=HANA_CONFIG["port"],
        user=HANA_CONFIG["user"],
        password=HANA_CONFIG["password"]
    )
    cursor = conn.cursor()
    schema = HANA_CONFIG["schema"]

    try:
        test_case_rows = []
        vertices_set = set()
        edges_set = set()

        for data in chunks_data:
            test_case_rows.append((
                data['doc_name'],
                data['region'],
                data['document_type'],
                data['process_id'],
                data['business_process'],
                data['doc_id'],
                data['chunk_id'],
                data['chunk_text'],
                json.dumps(data['embedding'])
            ))

            vertices_set.update([
                (data['region'], "Region"),
                (data['document_type'], "DocumentType"),
                (data['process_id'], "ProcessId"),
                (data['business_process'], "BusinessProcess"),
                (data['doc_name'], "Document")
            ])

            edges_set.update([
                (f"{data['region']}_{data['document_type']}", data['region'], data['document_type'], "belongs_to"),
                (f"{data['document_type']}_{data['process_id']}", data['document_type'], data['process_id'], "belongs_to"),
                (f"{data['process_id']}_{data['business_process']}", data['process_id'], data['business_process'], "belongs_to"),
                (f"{data['business_process']}_{data['doc_name']}", data['business_process'], data['doc_name'], "belongs_to"),
            ])

        cursor.executemany(f"""
            UPSERT {schema}.SIGNAVIO_TEST_CASE_DATA
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            WITH PRIMARY KEY
        """, test_case_rows)

        cursor.executemany(f"""
            UPSERT {schema}.SIGNAVIO_VERTICES
            VALUES (?, ?)
            WITH PRIMARY KEY
        """, list(vertices_set))

        cursor.executemany(f"""
            UPSERT {schema}.SIGNAVIO_EDGES
            VALUES (?, ?, ?, ?)
            WITH PRIMARY KEY
        """, list(edges_set))

        conn.commit()
        logging.info(f"✅ Batch ingestion successful for {len(chunks_data)} chunks.")

    except Exception as e:
        logging.error(f"❌ Batch ingestion error: {e}")
        conn.rollback()

    finally:
        cursor.close()
        conn.close()


def find_file_in_subfolders(base_folder, target_filename):
    # Traverse the directory tree
    for root, dirs, files in os.walk(base_folder):
        if target_filename in files:
            # Return the full path of the file
            return os.path.join(root, target_filename)
    return None

def slugify(s: str) -> str:
    out, prev_dash = [], False
    for ch in s:
        if ch.isalnum():
            out.append(ch.lower()); prev_dash = False
        else:
            if not prev_dash:
                out.append("-"); prev_dash = True
    slug = "".join(out).strip("-")
    return slug if slug else str(uuid.uuid4())
