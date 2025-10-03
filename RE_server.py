import threading
import eventlet
eventlet.monkey_patch()
from flask_socketio import SocketIO, emit

from flask import Flask, request, jsonify,  send_file, make_response,abort
import zipfile
import json
from flask_cors import CORS
import time
import json
import base64
import os
import io
import traceback
from docx import Document
import logging
import tempfile
import json
import pyzipper
from flask import Response
from sap import xssec
from cfenv import AppEnv
from codetodescription import CodetoDescription
from common import upload_json_common, download_results_common,  update_status_common, set_business_prompt_and_tables, set_technical_prompt_and_tables
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from utils import *
from Document_Gen import *
import pandas as pd
from credentials import uaa_service
from add_title import *
from dotenv import load_dotenv
import shutil
from io import BytesIO
from pathlib import Path
from azure.storage.blob import BlobServiceClient, BlobClient
import boto3
import urllib3
from document_count import get_template_flag_count
import pandas as pd
from db_wrapper import get_jobrun_data, update_inprogress_status_to_error,update_jobrun_status, update_jobrun_status_by_ids
from tsp_utilities.db_call import DBcon
from tsp_utilities.core import *
import Chunking_process
import base64
from google.cloud import storage
from google.oauth2 import service_account
# Suppress only the single InsecureRequestWarning from urllib3 needed for this example
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# Load environment variables from .env file
load_dotenv()

objectstore_env = os.getenv('objectstore')
# Parse it as JSON
if objectstore_env:
    objectstore = json.loads(objectstore_env)
    endpoint_url =   objectstore.get('uri',None)
    if endpoint_url is not None:
        endpoint_url = endpoint_url.replace("s3", "https", 1)
    access_key =   objectstore.get('access_key_id',None)
    secret_key = objectstore.get('secret_access_key',None)
    bucket_name = objectstore.get('bucket',None)
    region_name = objectstore.get('region',None)

    AZURE_STORAGE_ACCOUNT_NAME = objectstore.get('account_name',None)
    AZURE_STORAGE_ACCOUNT_KEY = objectstore.get('sas_token',None)
    CONTAINER_NAME = objectstore.get('container_name',None)
    CONTAINER_URI = objectstore.get('container_uri',None)
    gcp_private_key = objectstore.get('base64EncodedPrivateKeyData',None)
    print("CONTAINER_URI", CONTAINER_URI)


else:
   logging.info("Environment variable 'objectstore' not found.")

try:
    dest = next(d for d in json.loads(os.getenv('destinations', '[]')) if d.get("name") == "TSP-srv")
    cap_url = f"{dest['url']}/odata/v4/datamanager"
    logging.info(f"Service URL: {dest['url']}")
except StopIteration:
    logging.warning("Destination 'TSP-srv' not found.")

# Initialize a session using boto3
session = boto3.session.Session()
# Create S3 client
s3_client = session.client(
    service_name='s3',
    endpoint_url=endpoint_url,
    aws_access_key_id=access_key,
    aws_secret_access_key=secret_key,
    region_name=region_name,
    verify=False
)

env = AppEnv()
hana_service= env.get_service(name='tsp-db').credentials
aicore_service = env.get_service(name='tsp-aicore').credentials

hanadbhost = hana_service["host"]
hanadbport = hana_service["port"]
hanadbuser = hana_service["user"]
hanadbpassword = hana_service["password"]
hanadbschema = hana_service["schema"]

HANADB_ADDRESS=hanadbhost

HANADB_PASSWORD=hanadbpassword
HANADB_USER=hanadbuser

HANADB_PORT=hanadbport	
hanadbschema = hanadbschema


app = Flask(__name__)
# CORS(app)

socketio = SocketIO(app, async_mode='threading',cors_allowed_origins="*", max_http_buffer_size=100*1024*1024) 

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["500/minute"]
)

@app.before_request
def hide_server_header():
    import werkzeug.serving
    werkzeug.serving.WSGIRequestHandler.server_version = "MySecureServer"
    werkzeug.serving.WSGIRequestHandler.sys_version = ""
main_app = CodetoDescription()

@app.route('/', methods=['GET'])
def root():
    #logging.debug("Health check endpoint accessed.")
    return 'Fit to standard app: Health Check Successful.', 200

#this for business just + functional spec
@app.route('/upload_json_business', methods=['POST'])
def upload_json_business():

    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)

    try:
        access_token = request.headers.get('authorization')[7:]
    except:
        access_token = request.headers.get('Authorization')[7:]


    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')


            if not isAuthorized:
                abort(403)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    set_business_prompt_and_tables(main_app)
    return upload_json_common(main_app,cap_url,headers,"ReverseFSD")


#business just + tech spec
@app.route('/upload_json_technical', methods=['POST'])
def upload_json_technical():

    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)

    try:
        access_token = request.headers.get('authorization')[7:]
    except:
        access_token = request.headers.get('Authorization')[7:]


    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')


            if not isAuthorized:
                abort(403)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    set_technical_prompt_and_tables(main_app)
    return upload_json_common(main_app)

@app.route('/upload_text_business', methods=['POST'])
def upload_text_business():
    #logging.debug("Received request at /upload_text_business")
    set_business_prompt_and_tables(main_app)

    return process_uploaded_text_file(request, main_app)

@app.route('/upload_text_technical', methods=['POST'])
def upload_text_technical():
    #logging.debug("Received request at /upload_text_technical")
    set_technical_prompt_and_tables(main_app)

    return process_uploaded_text_file(request, main_app)
    
def process_uploaded_text_file(request, main_app):
    if 'file' not in request.files:
        logging.error("No file part in the request")
        return jsonify({"error": "No file part in the request"}), 400
 
    file = request.files['file']
    if file.filename == '':
        logging.error("No file selected for uploading")
        return jsonify({"error": "No file selected for uploading"}), 400
 
    # Extract user_id from request
    user_id = request.form.get('user_id')
    if not user_id:
        logging.error("User ID not provided in the request")
        return jsonify({"error": "User ID not provided"}), 400
 
    # Extract add_info from request (can be optional)
    add_info_from_ui = request.form.get('add_info', '')  # Default to empty string if not provided
    language = request.form.get('language', 'English')  # Default to 'English' if not provided
    add_info = add_info_from_ui.split('$')[0]
    pattern = r'\$(.*?)\$'
 
    # Find the match
    match = re.search(pattern, add_info_from_ui)
 
    # Extract the text if a match is found
    if match:
        system = match.group(1)
    else:
        system = ""  
 
    try:
        with tempfile.TemporaryDirectory() as extract_dir:
            zip_path = os.path.join(extract_dir, 'uploaded_zip.zip')
            file.save(zip_path)
 
            if not pyzipper.is_zipfile(zip_path):
                logging.error("The saved file is not recognized as a valid ZIP file after saving.")
                return jsonify({"error": "File corruption detected. The uploaded file is not a valid ZIP file."}), 400
 
            try:
                with pyzipper.AESZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)
            except pyzipper.BadZipFile as e:
                logging.error(f"Error extracting ZIP file: {str(e)}", exc_info=True)
                return jsonify({"error": "Error extracting ZIP file. The file may be corrupted.", "message": str(e)}), 400
            except Exception as e:
                logging.error(f"Unexpected error while extracting ZIP file: {str(e)}", exc_info=True)
                return jsonify({"error": "Unexpected error while extracting ZIP file.", "message": str(e)}), 500
 
            # Prepare the JSON data to send to process_json
            documents = []
            for root, dirs, files in os.walk(extract_dir):
                for file_name in files:
                    if file_name.endswith('.txt'):
                        source_path = os.path.join(root, file_name)
                        try:
                            # Try reading with utf-8 first
                            with open(source_path, 'r', encoding='utf-8') as txt_file:
                                source_code = txt_file.read()  # Read entire file content as a single string
                        except UnicodeDecodeError as e:
                            logging.warning(f"UnicodeDecodeError for file {file_name} with utf-8: {str(e)}. Trying ISO-8859-1.")
                            try:
                                # Fallback to ISO-8859-1 if utf-8 fails
                                with open(source_path, 'r', encoding='ISO-8859-1') as txt_file:
                                    source_code = txt_file.read()
                            except Exception as e:
                                logging.error(f"Error reading file {file_name} with ISO-8859-1: {str(e)}", exc_info=True)
                                return jsonify({"error": "Error reading file due to encoding issue.", "message": str(e)}), 400
                        except Exception as e:
                            logging.error(f"Error reading file {file_name}: {str(e)}", exc_info=True)
                            return jsonify({"error": "Error reading file.", "message": str(e)}), 500
                       
                        # Serialize the source code using json.dumps
                        serialized_source_code = json.dumps(source_code)

 
                        # Form the JSON object for each text file
                        document = {
                            'OBJECT_NAME': file_name.replace('.txt', ''),  # Removing '.txt' extension for OBJECT_NAME
                            'SOURCE_CODE':serialized_source_code ,  # The content inside the text file as source code
                            # Add additional keys with default or empty values as needed
                            'USER_ID': user_id,  # Replace with appropriate user id logic
                            'OBJECT_TYPE': '',  # Set or determine as needed
                            'MODULENAME':'',
                            'ADD_INFO': add_info,
                            'LANGUAGE': language,
                            'SYSTEM': system,
                            'TABLE': [],
                            'FUNCTION': [],
                            'FUNCTIONGROUP': [],
                            'CLASS_LIST': [],
                            'PROGRAM': [],
                            'TCODE': [],
                            'CLONE': '',
                            'S4HANAREADINESS': '',
                            'UNUSED': ''  
                        }
                        documents.append(document)
 
            # If no documents were formed, return an error
            if not documents:
                logging.warning("No text files found in the uploaded zip file.")
                return jsonify({"error": "No text files found in the uploaded zip file."}), 400
            flag = 'X'
            # Send the JSON data to the process_json method
            response = main_app.process_json(documents, flag=flag)  # Passing the list of documents directly
 
            # return jsonify({'result': response}), 200
            return {"result": response}, 200
 
    except Exception as e:
        logging.error(f"Error processing text files: {str(e)}", exc_info=True)
        return jsonify({"error": str(e), "message": "Error processing text files"}), 500
@app.route('/download_results_business', methods=['POST'])
def download_results_business():
    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)

    try:
        access_token = request.headers.get('authorization')[7:]
    except:
        access_token = request.headers.get('Authorization')[7:]


    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')


            if not isAuthorized:
                abort(403)
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    download_name = "Functional Code Documentation"
    word_suffix = "FCD"
    return download_results_common("ReverseFSD",download_name, word_suffix,headers)

@app.route('/download_results_technical', methods=['POST'])
def download_results_technical():
    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)

    try:
        access_token = request.headers.get('authorization')[7:]
    except:
        access_token = request.headers.get('Authorization')[7:]


    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')


            if not isAuthorized:
                abort(403)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    download_name = "Technical Code Documentation"
    word_suffix = "TCD"
    return download_results_common("ReverseTSD",download_name, word_suffix,headers)

@app.route('/update_status_business', methods=['POST'])
def update_status_business():
    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)

    try:
        access_token = request.headers.get('authorization')[7:]
    except:
        access_token = request.headers.get('Authorization')[7:]


    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')


            if not isAuthorized:
                abort(403)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    return update_status_common("ReverseFSD",headers)

@app.route('/update_status_technical', methods=['POST'])
def update_status_technical():
    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)

    try:
        access_token = request.headers.get('authorization')[7:]
    except:
        access_token = request.headers.get('Authorization')[7:]


    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')


            if not isAuthorized:
                abort(403)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    return update_status_common("ReverseTSD",headers)

@app.route('/delete_fetched_entries_business', methods=['POST'])
def delete_fetched_entries_business():
    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)

    try:
        access_token = request.headers.get('authorization')[7:]
    except:
        access_token = request.headers.get('Authorization')[7:]


    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')


            if not isAuthorized:
                abort(403)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    try:

        if not request.is_json:
            logging.error("No JSON data in request")
            return jsonify({"error": "No JSON data provided"}), 400

        json_data = request.get_json()
        user_id = json_data.get('USER_ID')
        object_names = json_data.get('OBJECT_NAMES')
        
        if not user_id or not object_names:
            logging.error("USER_ID or OBJECT_NAMES missing in JSON data")
            return jsonify({"error": "USER_ID or OBJECT_NAMES missing in JSON data"}), 400

        # Ensure object_names is a list of individual names
        if len(object_names) == 1 and isinstance(object_names[0], str):
            object_names = [name.strip() for name in object_names[0].split(',')]    
        
        cap_client = CapServiceClient(cap_url,"ReverseFSD")
        return cap_client.delete_fetched_entries(user_id, object_names,headers)
    except Exception as e:
        logging.error(f"Error deleting fetched entries: {str(e)}", exc_info=True)
        return jsonify({"error": str(e), "message": "Failed to delete fetched entries"}), 500

@app.route('/delete_fetched_entries_technical', methods=['POST'])
def delete_fetched_entries_technical():
    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)

    try:
        access_token = request.headers.get('authorization')[7:]
    except:
        access_token = request.headers.get('Authorization')[7:]


    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')


            if not isAuthorized:
                abort(403)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    try:
        if not request.is_json:
            logging.error("No JSON data in request")
            return jsonify({"error": "No JSON data provided"}), 400

        json_data = request.get_json()
        user_id = json_data.get('USER_ID')
        object_names = json_data.get('OBJECT_NAMES')
        
        if not user_id or not object_names:
            logging.error("USER_ID or OBJECT_NAMES missing in JSON data")
            return jsonify({"error": "USER_ID or OBJECT_NAMES missing in JSON data"}), 400
        
        # Ensure object_names is a list of individual names
        if len(object_names) == 1 and isinstance(object_names[0], str):
            object_names = [name.strip() for name in object_names[0].split(',')]
            
        cap_client = CapServiceClient(cap_url,"ReverseTSD")
        return cap_client.delete_fetched_entries(user_id, object_names,headers)
    except Exception as e:
        logging.error(f"Error deleting fetched entries: {str(e)}", exc_info=True)
        return jsonify({"error": str(e), "message": "Failed to delete fetched entries"}), 500



@app.route('/fcdtcd_json', methods=['POST'])
def fcdtcd_json():
    """
    Executes upload_json_business followed by upload_json_technical sequentially,
    using upload_json_common for both.
    """
    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)

    try:
        access_token = request.headers.get('authorization')[7:]
    except:
        access_token = request.headers.get('Authorization')[7:]


    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')


            if not isAuthorized:
                abort(403)
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    try:
        # Step 1: Process Business JSON
        logging.info("Starting Business JSON upload process.")
        set_business_prompt_and_tables(main_app)
        business_response, business_status = upload_json_common(main_app, cap_url, headers, "ReverseFSD")
        
        if business_status != 200:
            logging.error("Business JSON upload failed.")
            return jsonify({"error": "Business JSON upload failed.", "details": business_response}), 400
        
        # Step 2: Process Technical JSON
        logging.info("Starting Technical JSON upload process.")
        set_technical_prompt_and_tables(main_app)
        technical_response, technical_status = upload_json_common(main_app, cap_url, headers, "ReverseTSD")
        
        if technical_status != 200:
            logging.error("Technical JSON upload failed.")
            return jsonify({"error": "Technical JSON upload failed.", "details": technical_response}), 400
        
        # Both processes succeeded
        logging.info("Business and Technical JSON uploads completed successfully.")
        return jsonify({"message": "Both Business and Technical JSON uploads completed successfully."}), 200

    except Exception as e:
        logging.error(f"Error in FCD and TCD JSON processing: {str(e)}", exc_info=True)
        return jsonify({"error": "An error occurred during FCD and TCD JSON processing.", "details": str(e)}), 500


@app.route('/fcdtcd_download', methods=['POST'])
def fcdtcd_download():
    """
    Combines the functional and technical zip files into a single zip file
    and returns it to the user.
    """
    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)

    try:
        access_token = request.headers.get('authorization')[7:]
    except:
        access_token = request.headers.get('Authorization')[7:]


    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')


            if not isAuthorized:
                abort(403)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    try:
        # Ensure the request has the correct Content-Type
        if not request.is_json:
            logging.error("Content-Type must be application/json")
            return jsonify({"error": "Content-Type must be application/json"}), 415

        # Extract JSON data from the request
        json_data = request.get_json()
        if not json_data:
            logging.error("No JSON data in request")
            return jsonify({"error": "No JSON data provided"}), 400

        # Validate JSON payload
        user_id = json_data.get('USER_ID')
        object_names = json_data.get('OBJECT_NAMES')
        if not user_id or not object_names:
            logging.error("USER_ID or OBJECT_NAMES missing in JSON data")
            return jsonify({"error": "USER_ID or OBJECT_NAMES missing in JSON data"}), 400

        # Fetch Functional Code Documentation
        logging.info("Fetching Functional Code Documentation zip.")
        functional_zip_response = download_results_common("ReverseFSD","Functional Code Documentation", "FCD",headers)

        # Handle tuple response
        if isinstance(functional_zip_response, tuple):
            return functional_zip_response

        if functional_zip_response.status_code != 200:
            logging.error("Failed to fetch Functional Code Documentation zip.")
            return functional_zip_response

        # Save functional zip content to memory
        functional_zip_buffer = io.BytesIO()
        for chunk in functional_zip_response.response:  # Read the streamed response
            functional_zip_buffer.write(chunk)
        functional_zip_buffer.seek(0)

        # Fetch Technical Code Documentation
        logging.info("Fetching Technical Code Documentation zip.")

        technical_zip_response = download_results_common("ReverseTSD","Technical Code Documentation", "TCD",headers)

        # Handle tuple response
        if isinstance(technical_zip_response, tuple):
            return technical_zip_response

        if technical_zip_response.status_code != 200:
            logging.error("Failed to fetch Technical Code Documentation zip.")
            return technical_zip_response

        # Save technical zip content to memory
        technical_zip_buffer = io.BytesIO()
        for chunk in technical_zip_response.response:  # Read the streamed response
            technical_zip_buffer.write(chunk)
        technical_zip_buffer.seek(0)

        # Combine both zip files into a single zip
        combined_zip_stream = io.BytesIO()
        with zipfile.ZipFile(combined_zip_stream, 'w', zipfile.ZIP_DEFLATED) as combined_zip:
            # Add the functional zip
            combined_zip.writestr("Functional_Code_Documentation.zip", functional_zip_buffer.getvalue())
            # Add the technical zip
            combined_zip.writestr("Technical_Code_Documentation.zip", technical_zip_buffer.getvalue())

        combined_zip_stream.seek(0)

        # Return the combined zip file
        response = make_response(send_file(
            combined_zip_stream,
            mimetype='application/zip',
            as_attachment=True,
            download_name="Combined_Code_Documentation.zip"
        ))

        response.headers["Content-Disposition"] = "attachment; filename=Combined_Code_Documentation.zip"
        response.headers["Access-Control-Expose-Headers"] = "Content-Disposition"
        logging.info("Combined zip file successfully created and sent to the user.")
        return response

    except Exception as e:
        logging.error(f"Error in FCD and TCD zip download: {str(e)}", exc_info=True)
        return jsonify({"error": "An error occurred while combining zip files.", "details": str(e)}), 500


@app.route('/fcdtcd_delete', methods=['POST'])
def fcdtcd_delete():
    """
    Sequentially deletes entries from both Functional and Technical results tables.
    """
    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)

    try:
        access_token = request.headers.get('authorization')[7:]
    except:
        access_token = request.headers.get('Authorization')[7:]


    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')


            if not isAuthorized:
                abort(403)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    try:
        if not request.is_json:
            logging.error("No JSON data in request")
            return jsonify({"error": "No JSON data provided"}), 400

        json_data = request.get_json()
        user_id = json_data.get('USER_ID')
        object_names = json_data.get('OBJECT_NAMES')

        if not user_id or object_names is None:
            logging.error("USER_ID or OBJECT_NAMES missing in JSON data")
            return jsonify({"error": "USER_ID or OBJECT_NAMES missing"}), 400

        # Normalize object_names into a list
        if isinstance(object_names, list) and len(object_names) == 1 and isinstance(object_names[0], str):
            object_names = [name.strip() for name in object_names[0].split(',')]

        def delete_entries(justification, label):
            logging.info(f"Deleting {label} entries.")
            cap_client = CapServiceClient(cap_url, justification)
            response, status_code = cap_client.delete_fetched_entries(user_id, object_names, headers)
            if status_code != 200:
                logging.error(f"Failed to delete {label} entries.")
                return False, {
                    "error": f"Failed to delete {label} entries.",
                    "details": response
                }, status_code
            return True, None, 200

        # Delete Functional Entries
        success, error_response, status_code = delete_entries("ReverseFSD", "Functional")
        if not success:
            return jsonify(error_response), status_code

        # Delete Technical Entries
        success, error_response, status_code = delete_entries("ReverseTSD", "Technical")
        if not success:
            return jsonify(error_response), status_code

        # Both deletions succeeded
        logging.info("Both Functional and Technical entries deleted successfully.")
        return jsonify({"message": "Both Functional and Technical entries deleted successfully."}), 200

    except Exception as e:
        logging.error(f"Error in FCD and TCD delete processing: {str(e)}", exc_info=True)
        return jsonify({"error": "An error occurred during FCD and TCD deletion.", "details": str(e)}), 500



@app.route('/fcdtcd_update_status', methods=['POST'])
def fcdtcd_update_status():
    """
    Sequentially updates the status for both Functional and Technical results tables.
    """
    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)

    try:
        access_token = request.headers.get('authorization')[7:]
    except:
        access_token = request.headers.get('Authorization')[7:]


    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')


            if not isAuthorized:
                abort(403)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    try:
        if not request.is_json:
            logging.error("No JSON data in request")
            return jsonify({"error": "No JSON data provided"}), 400

        json_data = request.get_json()

        # Step 1: Update Status for Functional Results
        logging.info("Updating status for Functional results.")
        business_response, business_status = update_status_common("ReverseFSD",headers)

        if business_status != 200:
            logging.error("Failed to update status for Functional results.")
            return jsonify({
                "error": "Failed to update status for Functional results.",
                "details": business_response
            }), business_status

        # Step 2: Update Status for Technical Results
        logging.info("Updating status for Technical results.")
        technical_response, technical_status = update_status_common("ReverseTSD",headers)

        if technical_status != 200:
            logging.error("Failed to update status for Technical results.")
            return jsonify({
                "error": "Failed to update status for Technical results.",
                "details": technical_response
            }), technical_status

        # Both updates succeeded
        logging.info("Status updated for both Functional and Technical results successfully.")
        return jsonify({"message": "Status updated for both Functional and Technical results successfully."}), 200

    except Exception as e:
        logging.error(f"Error in FCD and TCD status update processing: {str(e)}", exc_info=True)
        return jsonify({
            "error": "An error occurred during FCD and TCD status update.",
            "details": str(e)
        }), 500

@app.route('/detailedspecfunctional', methods=['POST'])
def detailedspecfunctional():
    """
    Extracts source_code from JSON data and passes it to FS_document_generation function.
    """
    try:
        if not request.is_json:
            logging.error("No JSON data in request")
            return jsonify({"error": "No JSON data provided"}), 400

        # Parse JSON data
        json_data = request.get_json()

        # Extract source_code
        source_code = json_data.get('source_code')
        if not source_code:
            logging.error("source_code key is missing or empty in the JSON data")
            return jsonify({"error": "source_code key is missing or empty in the JSON data"}), 400
        
        source_code = str(source_code)  # Ensure source_code is a string

        # Pass source_code to FS_document_generation
        logging.info("Passing source_code to FS_document_generation function.")
        response = FS_document_generation(source_code)

        # Return the response from FS_document_generation
        return response

    except Exception as e:
        logging.error(f"Error in detailedspecfunctional processing: {str(e)}", exc_info=True)
        return jsonify({
            "error": "An error occurred while processing the detailed spec for functional data.",
            "details": str(e)
        }), 500

@app.route('/detailedspectechnical', methods=['POST'])
def detailedspectechnical():
    """
    Extracts source_code from JSON data and passes it to TS_document_generation function.
    """
    try:
        if not request.is_json:
            logging.error("No JSON data in request")
            return jsonify({"error": "No JSON data provided"}), 400

        # Parse JSON data
        json_data = request.get_json()

        # Extract source_code
        source_code = json_data.get('source_code')
        if not source_code:
            logging.error("source_code key is missing or empty in the JSON data")
            return jsonify({"error": "source_code key is missing or empty in the JSON data"}), 400
        
        source_code = str(source_code)  # Ensure source_code is a string

        # Pass source_code to TS_document_generation
        logging.info("Passing source_code to TS_document_generation function.")
        response = TS_document_generation(source_code)

        # Return the response from TS_document_generation
        return response

    except Exception as e:
        logging.error(f"Error in detailedspectechnical processing: {str(e)}", exc_info=True)
        return jsonify({
            "error": "An error occurred while processing the detailed spec for technical data.",
            "details": str(e)
        }), 500
    
@app.route('/detailedspeccombined', methods=['POST'])
def detailedspeccombined():
    """
    Extracts source_code from JSON data, ensures it is a string,
    and sequentially calls FS_document_generation and TS_document_generation functions.
    """
    try:
        if not request.is_json:
            logging.error("No JSON data in request")
            return jsonify({"error": "No JSON data provided"}), 400

        # Parse JSON data
        json_data = request.get_json()

        # Extract source_code and ensure it's a string
        source_code = json_data.get('source_code')
        if not source_code:
            logging.error("source_code key is missing or empty in the JSON data")
            return jsonify({"error": "source_code key is missing or empty in the JSON data"}), 400

        source_code = str(source_code)  # Ensure source_code is a string

        # Step 1: Call FS_document_generation
        logging.info("Calling FS_document_generation function.")
        fs_response = FS_document_generation(source_code)

        # Step 2: Call TS_document_generation
        logging.info("Calling TS_document_generation function.")
        ts_response = TS_document_generation(source_code)

        # Combine responses from both functions
        combined_response = {
            "functional_specification": fs_response,
            "technical_specification": ts_response
        }

        # Return combined response
        return jsonify(combined_response), 200

    except Exception as e:
        logging.error(f"Error in detailedspeccombined processing: {str(e)}", exc_info=True)
        return jsonify({
            "error": "An error occurred while processing the combined detailed spec.",
            "details": str(e)
        }), 500

#downloading combine fs+ts
@app.route('/combinedfsts', methods=['GET'])
def combinedfsts():
    """
    Combines functional and technical specification word documents into a zip file with two folders.
    """
    try:
        # Define file paths
        functional_doc_name = 'SAP_Functional_Specification_Document.docx'
        technical_doc_name = 'SAP_Technical_Specification_Document.docx'

        # Define folder names
        functional_folder = 'Functional_Specification'
        technical_folder = 'Technical_Specification'

        # Create an in-memory zip file
        zip_stream = io.BytesIO()

        with zipfile.ZipFile(zip_stream, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Add Functional Specification Word Document to its folder
            if os.path.exists(functional_doc_name):
                with open(functional_doc_name, 'rb') as functional_file:
                    zf.writestr(f'{functional_folder}/{functional_doc_name}', functional_file.read())
            else:
                logging.error(f"{functional_doc_name} does not exist.")

            # Add Technical Specification Word Document to its folder
            if os.path.exists(technical_doc_name):
                with open(technical_doc_name, 'rb') as technical_file:
                    zf.writestr(f'{technical_folder}/{technical_doc_name}', technical_file.read())
            else:
                logging.error(f"{technical_doc_name} does not exist.")

        # Finalize the zip file
        zip_stream.seek(0)

        # Send the zip file to the user
        return send_file(
            zip_stream,
            mimetype='application/zip',
            as_attachment=True,
            download_name='Combined_FSTSSpecifications.zip'
        )

    except Exception as e:
        logging.error(f"Error creating combined specifications zip: {str(e)}", exc_info=True)
        return jsonify({
            "error": "An error occurred while creating the combined specifications zip file.",
            "details": str(e)
        }), 500


    
def convert_image_to_base64(image_filename):
    # Get the current working directory
    current_directory = os.getcwd()

    # Join the current directory with the image filename
    image_path = os.path.join(current_directory, image_filename)

    with open(image_path, "rb") as image_file:
        # Read the image file in binary mode
        image_binary = image_file.read()
        # Encode the binary data as base64
        image_base64 = base64.b64encode(image_binary).decode("utf-8")
    return image_base64


def create_object_uuid_dict(results,project_id,user_id, headers):

    cap_client = CapServiceClient(cap_url)

    object_uuid_dict = {}

    # Iterate through the results fetched from the HANA database
    for i, result in results.iterrows():
        # Extract the object_name from the result
        object_name = result['OBJECTNAME']

        # Generate a unique UUID for each object_name if not already generated
        if object_name not in object_uuid_dict:
            object_uuid = str(uuid.uuid4())
            object_uuid_dict[object_name] = object_uuid


    cap_client.insert_doccount_records(project_id, object_uuid_dict,user_id,headers)
    cap_client.update_documents_generated(project_id, len(object_uuid_dict),headers)

    return jsonify(object_uuid_dict)

def list_s3_objects(bucket_name):
    s3_client = boto3.client('s3', verify=False)

    try:
        # List objects in the specified bucket
        response = s3_client.list_objects_v2(Bucket=bucket_name)
        
        if 'Contents' in response:
            logging.info(f"Objects in bucket '{bucket_name}':")
            for obj in response['Contents']:
                logging.info(obj['Key'])
        else:
            logging.info(f"No objects found in bucket '{bucket_name}'.")
    except Exception as e:
        logging.error(f"Error listing objects in bucket '{bucket_name}': {e}")


@app.route('/get_word_document', methods=['POST'])
def get_word_document():
    #list_s3_objects(bucket_name)
    if 'authorization' not in request.headers and 'Authorization' not in request.headers:
        abort(403)

    try:
        access_token = request.headers.get('authorization', request.headers.get('Authorization'))[7:]
    except:
        abort(403)

    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')
            if not isAuthorized:
                abort(403)
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    user_id = request.form.get('user_id')
    project_id = request.form.get('project_id')
    document_type = request.form.get("document_type")
    mode = request.form.get('Mode')
    if document_type == 'M':
        file = request.files['file']
    else:
        file = request.form.get('file')

    user_id = encrypt_string(user_id.split('@')[0])


    try:
        cap_client = CapServiceClient(cap_url)
        if document_type == 'M':
            folderName = f"Documents_{user_id}"
            excel_name = f"{document_type}_tracker_{user_id}.xlsx"
            #logging.debug(excel_name)

            if not check_folder(folderName):
                return jsonify(
                    {"error": "Please generate the document first.", "details": f"{folderName} does not exist"}), 502

            if not check_excel_exists(excel_name):
                return jsonify({"error": "Background run is in progress, please wait.",
                                "details": "Files are not generated completely"}), 502

            document_name_with_UUIDs = generate_uuids_for_documents(folderName)
            if document_name_with_UUIDs:
                Flag = cap_client.insert_doccount_records(project_id, document_name_with_UUIDs, user_id, headers)
                if Flag:
                    cap_client.update_documents_generated(project_id, len(document_name_with_UUIDs.keys()),headers)
           
            document_count = count_documents(folderName)
            #logging.debug(f"Total number of documents {document_count}")

            zip_filename = create_zip(user_id, mode)

            # # Upload the ZIP file to S3
            s3_key = f'{folderName}/{zip_filename}'
            try:
                s3_client.upload_file(zip_filename, bucket_name, s3_key)

            except Exception as e:
                return jsonify({"error": "Error while uploading to S3.", "details": str(e)}), 500

            # Download the ZIP file from S3
            try:
                local_zip_path = os.path.join(os.path.dirname(file.filename), zip_filename)
                s3_client.download_file(bucket_name, s3_key, local_zip_path)

            except Exception as e:
                return jsonify({"error": "Error while downloading from S3.", "details": str(e)}), 500

            with open(local_zip_path, 'rb') as f:
                data = f.readlines()

            delete_path(local_zip_path, folderName)
            delete_excel(excel_name)

            return Response(data, headers={
                'Content-Type': 'application/zip',
                'Content-Disposition': f'attachment; filename={zip_filename};'
            })
        else:
            #logging.debug("for auto upload")
            folderName = f"Documents_{user_id}"
            excel_name = f"{document_type}_tracker_{user_id}.xlsx"
            #logging.debug(excel_name)

            if not check_folder(folderName):
                return jsonify(
                    {"error": "Please generate the document first.", "details": f"{folderName} does not exist"}), 502

            if not check_excel_exists(excel_name):
                return jsonify({"error": "Background run is in progress, please wait.",
                                "details": "Files are not generated completely"}), 502

            document_name_with_UUIDs = generate_uuids_for_documents(folderName)
            if document_name_with_UUIDs:
                Flag = cap_client.insert_doccount_records(project_id, document_name_with_UUIDs, user_id, headers)
                if Flag:
                    cap_client.update_documents_generated(project_id, len(document_name_with_UUIDs.keys()),headers)


            document_count = count_documents(folderName)

            zip_filename = create_zip(user_id, mode)

            # # Upload the ZIP file to S3
            s3_key = f'{folderName}/{zip_filename}'
            try:
                s3_client.upload_file(zip_filename, bucket_name, s3_key)

            except Exception as e:
                return jsonify({"error": "Error while uploading to S3.", "details": str(e)}), 500

            # Download the ZIP file from S3
            try:
                local_zip_path = os.path.join(os.path.dirname(file), zip_filename)
                s3_client.download_file(bucket_name, s3_key, local_zip_path)

            except Exception as e:
                return jsonify({"error": "Error while downloading from S3.", "details": str(e)}), 500

            with open(local_zip_path, 'rb') as f:
                data = f.readlines()

            delete_path(local_zip_path, folderName)
            delete_excel(excel_name)

            return Response(data, headers={
                'Content-Type': 'application/zip',
                'Content-Disposition': f'attachment; filename={zip_filename};'
            })


    except Exception as e:
        return jsonify({"error": "An error occurred while processing your request.", "details": str(e)}), 502


def create_zip(user_id, mode):
    folderName = f"Documents_{user_id}"
    zip_filename = f"{mode}_Documents_{user_id}.zip"
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(folderName):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, folderName)
                zipf.write(file_path, arcname)
    return zip_filename


@app.route('/autoUploadTechnical', methods=['POST'])
def autoTechnical():
    """
    Extracts source_code from JSON data, ensures it is a string,
    and sequentially calls FS_document_generation and TS_document_generation functions.
    """
    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)

    try:
      access_token = request.headers.get('authorization')[7:]
    except:
      access_token = request.headers.get('Authorization')[7:]


    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')


            if not isAuthorized:
                abort(403)

    try:
        DOC_OBJ = DOCGEN()
        if not request.is_json:
            logging.error("No JSON data in request")
            return jsonify({"error": "No JSON data provided"}), 400

        # Parse JSON data
        json_data_combined = request.get_json()

        total_document = len(json_data_combined)

        # Extract source_code and ensure it's a string
        combined_list = []
        add_info_list = json_data_combined[0].get('ADD_INFO', []) # Consider one list of ADD_INFO

        # Create a mapping for each OBJECT_NAME to its corresponding ADD_INFO value
        add_info_mapping = {}

        if len(add_info_list) == 0:
            logging.error("ADD_INFO list is empty. Using default value for all mappings.")
            # Use a default value (e.g., "") for all mappings
            for json_data in json_data_combined:
                add_info_mapping[json_data['OBJECT_NAME']] = ""
        else:
            for i, json_data in enumerate(json_data_combined):
                add_info_mapping[json_data['OBJECT_NAME']] = add_info_list[i % len(add_info_list)]



        for json_data in json_data_combined:
            source_code = json_data.get('SOURCE_CODE')
            obj_type = json_data.get('OBJECT_TYPE')
            nameOfFile = json_data.get('OBJECT_NAME')
            user_id = json_data.get('USER_ID')
            user_id = encrypt_string(user_id.split("@")[0])
            context,system = extract_context_and_system(add_info_mapping.get(nameOfFile, ""))
            language = json_data.get('LANGUAGE')
            execution_summary_ts = json_data.get('ST03_TEXT'," ")

            obj_flag = False
            if obj_type == "PROG" or obj_type=="REPORT":
                obj_flag = True
            logging.info("Obj_flag : ", obj_flag)

            if not source_code:
                logging.error("source_code key is missing or empty in the JSON data")
                return jsonify({"error": "source_code key is missing or empty in the JSON data"}), 400
            if not nameOfFile:
                logging.error("object_name key is missing or empty in the JSON data")
                return jsonify({"error": "object_name key is missing or empty in the JSON data"}), 400

            combined_list.append((str(source_code), user_id, nameOfFile, context, language, system,execution_summary_ts,obj_flag,'single'))

        with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
            results = list(executor.map(lambda args:DOC_OBJ.TS_document_generationLat(*args), combined_list))
        outputJson, Flag = check_status(results)
        if not Flag:
            folderName = f"Documents_{user_id}"
            delete_folder(folderName)
            return json.dumps({"error": "Error Processing uploaded files post generation"}), 500
        combined_response = outputJson

        if combined_response == '':
            return jsonify({"error": "Error While generating TS document"}), 400
        else:
            document_dict = {
                "user_id": user_id,
                "type": "Technical document",
                "Count": total_document
            }

            df = pd.DataFrame([document_dict])
            df.to_excel(f'TS_tracker_{user_id}.xlsx', index=False)
            #logging.debug(f"Excel created for {user_id}")

        # Return combined response
        return jsonify(combined_response), 200

    except Exception as e:
        logging.error(f"Error in Technical document processing: {str(e)}", exc_info=True)
        return jsonify({
            "error": "An error occurred while processing the Technical document detailed spec.",
            "details": str(e)
        })
    
@app.route('/autoUploadFunctional', methods=['POST'])
def autoFunctional():
    """
    Extracts source_code from JSON data, ensures it is a string,
    and sequentially calls FS_document_generation and TS_document_generation functions.
    """
    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)

    try:
      access_token = request.headers.get('authorization')[7:]
    except:
      access_token = request.headers.get('Authorization')[7:]


    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')


            if not isAuthorized:
                abort(403)

    try:
        DOC_OBJ = DOCGEN()
        if not request.is_json:
            logging.error("No JSON data in request")
            return jsonify({"error": "No JSON data provided"}), 400

        # Parse JSON data
        json_data_combined = request.get_json()

        total_document = len(json_data_combined)

        # Extract source_code and ensure it's a string
        combined_list = []
        add_info_list = json_data_combined[0].get('ADD_INFO', []) # Consider one list of ADD_INFO

        # Create a mapping for each OBJECT_NAME to its corresponding ADD_INFO value
        add_info_mapping = {}

        if len(add_info_list) == 0:
            logging.error("ADD_INFO list is empty. Using default value for all mappings.")
            # Use a default value (e.g., "") for all mappings
            for json_data in json_data_combined:
                add_info_mapping[json_data['OBJECT_NAME']] = ""
        else:
            for i, json_data in enumerate(json_data_combined):
                add_info_mapping[json_data['OBJECT_NAME']] = add_info_list[i % len(add_info_list)]



        for json_data in json_data_combined:
            source_code = json_data.get('SOURCE_CODE')
            obj_type = json_data.get('OBJECT_TYPE')
            nameOfFile = json_data.get('OBJECT_NAME')
            user_id = json_data.get('USER_ID')
            user_id = encrypt_string(user_id.split("@")[0])
            context,system = extract_context_and_system(add_info_mapping.get(nameOfFile, ""))
            language = json_data.get('LANGUAGE')
            execution_summary_fs = json_data.get('ST03_TEXT'," ")

            obj_flag = False
            if obj_type == "PROG" or obj_type=="REPORT":
                obj_flag = True
            logging.info("Obj_flag : ", obj_flag)

            if not source_code:
                logging.error("source_code key is missing or empty in the JSON data")
                return jsonify({"error": "source_code key is missing or empty in the JSON data"}), 400
            if not nameOfFile:
                logging.error("object_name key is missing or empty in the JSON data")
                return jsonify({"error": "object_name key is missing or empty in the JSON data"}), 400

            combined_list.append((str(source_code), user_id, nameOfFile, context, language, system,execution_summary_fs,obj_flag,'single'))

        with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
            results = list(executor.map(lambda args:DOC_OBJ.FS_document_generationLat(*args), combined_list))
        outputJson, Flag = check_status(results)
        if not Flag:
            folderName = f"Documents_{user_id}"
            delete_folder(folderName)
            return json.dumps({"error": "Error Processing uploaded files post generation"}), 500
        combined_response = outputJson

        if combined_response == '':
            return jsonify({"error": "Error While generating FS document"}), 400
        else:
            document_dict = {
                "user_id": user_id,
                "type": "Functional document",
                "Count": total_document
            }

            df = pd.DataFrame([document_dict])
            df.to_excel(f'FS_tracker_{user_id}.xlsx', index=False)
            #logging.debug(f"Excel created for {user_id}")

        # Return combined response
        return jsonify(combined_response), 200

    except Exception as e:
        logging.error(f"Error in Functional document processing: {str(e)}", exc_info=True)
        return jsonify({
            "error": "An error occurred while processing the Functional document detailed spec.",
            "details": str(e)
        })
    
@app.route('/autoUploadboth', methods=['POST'])
def autoBothTsFS():
    """
    Extracts source_code from JSON data, ensures it is a string,
    and sequentially calls FS_document_generation and TS_document_generation functions.
    """

    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)

    try:
        access_token = request.headers.get('authorization')[7:]
    except:
        access_token = request.headers.get('Authorization')[7:]


    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')


            if not isAuthorized:
                abort(403)

    try:
        DOC_OBJ = DOCGEN()
        if not request.is_json:
            logging.error("No JSON data in request")
            return jsonify({"error": "No JSON data provided"}), 400

        # Parse JSON data
        json_data_combined = request.get_json()
        total_document = len(json_data_combined)

        # Extract source_code and ensure it's a string
        combined_list_1 = []
        combined_list_2 = []
        add_info_list = json_data_combined[0].get('ADD_INFO', [])  # Consider one list of ADD_INFO

        # Create a mapping for each OBJECT_NAME to its corresponding ADD_INFO value
        add_info_mapping = {}

        if len(add_info_list) == 0:
            logging.error("ADD_INFO list is empty. Using default value for all mappings.")
            # Use a default value (e.g., "") for all mappings
            for json_data in json_data_combined:
                add_info_mapping[json_data['OBJECT_NAME']] = ""
        else:
            for i, json_data in enumerate(json_data_combined):
                add_info_mapping[json_data['OBJECT_NAME']] = add_info_list[i % len(add_info_list)]



        for json_data in json_data_combined:
            source_code = json_data.get('SOURCE_CODE')
            obj_type = json_data.get('OBJECT_TYPE')
            nameOfFile = json_data.get('OBJECT_NAME')
            user_id = json_data.get('USER_ID')
            user_id = encrypt_string(user_id.split("@")[0])
            context, system = extract_context_and_system(add_info_mapping.get(nameOfFile, ""))
            language = json_data.get('LANGUAGE')
            system = json_data.get('SYSTEM')
            execution_summary_both_fs = json_data.get('ST03_TEXT'," ")
            execution_summary_both_ts = json_data.get('ST03_TEXT'," ")

            obj_flag = False
            if obj_type == "PROG" or obj_type=="REPORT":
                obj_flag = True
            logging.info("Obj_flag : ", obj_flag)

            if not source_code:
                logging.error("source_code key is missing or empty in the JSON data")
                return jsonify({"error": "source_code key is missing or empty in the JSON data"}), 400
            if not nameOfFile:
                logging.error("object_name key is missing or empty in the JSON data")
                return jsonify({"error": "object_name key is missing or empty in the JSON data"}), 400

            combined_list_1.append(
                (str(source_code), user_id, nameOfFile, context, language, system,execution_summary_both_fs,obj_flag,'single'))
            combined_list_2.append(
                (str(source_code), user_id, nameOfFile, context, language, system,execution_summary_both_ts,obj_flag, 'single'))

        with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
            FS_results = list(executor.map(lambda args:DOC_OBJ.FS_document_generationLat(*args), combined_list_1))
        FS_results, Flag = check_status(FS_results)
        if not Flag:
            folderName = f"Documents_{user_id}"
            delete_folder(folderName)
            return json.dumps({"error": "Error generating FS documents"}), 500

        with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
            TS_results = list(executor.map(lambda args:DOC_OBJ.TS_document_generationLat(*args), combined_list_2))
        TS_results, Flag = check_status(TS_results)
        if not Flag:
            folderName = f"Documents_{user_id}"
            delete_folder(folderName)
            return json.dumps({"error": "Error generating TS documents"}), 500

        combined_response = FS_results + TS_results

        if not combined_response:
            return jsonify({"error": "Error While generating FS and TS"}), 400
        else:
            document_dict = {
                "user_id": user_id,
                "type": "Combined FS and TS document",
                "Count": total_document
            }

            df = pd.DataFrame([document_dict])
            df.to_excel(f'FSTS_tracker_{user_id}.xlsx', index=False)
            #logging.debug(f"Excel created for {user_id}")

        return jsonify(combined_response), 200

    except Exception as e:
        logging.error(f"Error in both FSTS processing: {str(e)}", exc_info=True)
        return jsonify({
            "error": "An error occurred while processing the combined detailed spec.",
            "details": str(e)
        }), 500


def extract_context_and_system(main_context):
    # If main_context is empty, return empty values
    if not main_context:
        return "", ""

    # Remove square brackets if present
    main_context = main_context.strip('[]')

    # Pattern to find text within dollar signs
    pattern = r'\$(.*?)\$'
    match = re.search(pattern, main_context)

    # Assign the matched value to system or an empty string if no match
    system = match.group(1) if match else ""

    # If no dollar signs are found, or they are not at the start and end, use the entire string as context
    context = main_context if not match or match.start() > 0 or match.end() < len(main_context) else ""

    return context, system


def delete_all_subfolders(user_id):
    # Construct the full path to the main folder
    main_folder_path = f'Documents_{user_id}'
    #logging.debug(f"Attempting to delete all subfolders and files in: {main_folder_path}")

    delete_folder(main_folder_path)

@app.route('/upload', methods=['POST'])
def upload_file():

    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)

    try:
        access_token = request.headers.get('authorization')[7:]
    except:
        access_token = request.headers.get('Authorization')[7:]


    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')


            if not isAuthorized:
                abort(403)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    try:

        DOC_OBJ = DOCGEN()

        user_input = request.form.get('input_feature','')
        document_type = request.form.get('document_type','')

        template = request.form.get('template','')
        user_id = request.form.get('user_id','')
        main_context = request.form.get('add_info','')
        input_language = request.form.get('language','')
        execution_summary = "No Data Found.."
        context, system = extract_context_and_system(main_context)

        obj_flag = False


        user_id = encrypt_string(user_id.split("@")[0])

        delete_all_subfolders(user_id)

        input_feature =  user_input
        # Get the file extension
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No selected file"}), 400
        file_extension = os.path.splitext(file.filename)[1].lower()
        # Check if template is "detailed specs"
        if input_feature == "Reverse Engineering":
            if template == "detailed specs":

                if (document_type == "Functional Specification"):

                    file = request.files['file']
                    #logging.debug(f'-----------file-------------{file}')

                    if file.filename == '':
                        return jsonify({"error": "No selected file"}), 400

                    #logging.debug('---------file.filename--------{file.filename}')

                    file_extension = os.path.splitext(file.filename)[1].lower()

                    if file_extension in ['.txt']:  # Text/word file extension


                        file_stream = io.BytesIO(file.read())
                        NameOfFile = os.path.splitext(file.filename)[0].lower()
                        # NameOfFile = ''
                        #logging.debug('---------------call upload FS generation for Text/word file--------------')
                        file_content  = file_stream.read().decode('utf-8')
                        scontent = file_content[:50000].lower()
                        word = "report"
                        if re.search(r'\b' + re.escape(word) + r'\b', scontent):

                            obj_flag = True


                        if file_content:


                            response,status = DOC_OBJ.FS_document_generationLat(file_content,user_id,NameOfFile,context,input_language,system,execution_summary,obj_flag,combined_files='single')


                            if status!=200:
                                #remove_titles()
                                return jsonify({"error": "Error in functional document file Generation",
                                            "Description": f"{response}"}), 400
                                # return jsonify({"error": "Error in functional document Generation"}), 400
                            else:
                                document_dict = {
                                "user_id":user_id,
                                "type":"Functional document",
                                "filetype":"txt"
                            }

                            df = pd.DataFrame([document_dict])
                            df.to_excel(f'M_tracker_{user_id}.xlsx',index=False)

                            return jsonify(response),200
                        else:
                            return jsonify({"Empty file uploaded"}),400

                    elif file_extension in ['.zip']:
                        response,status = DOC_OBJ.process_main_zip(request,docType='FS')

                        if status!=200:
                            #remove_titles()
                            return jsonify({"error": "Error in functional document file Generation",
                                            "Description": f"{response}"}), 400
                        else:
                            document_dict = {
                                "user_id":user_id,
                                "type":"Functional document",
                                "filetype":"zip"
                            }

                            df = pd.DataFrame([document_dict])
                            df.to_excel(f'M_tracker_{user_id}.xlsx',index=False)
                            #logging.debug(f"Excel created for {user_id}")

                        #return response
                        return jsonify(response),200


                elif (document_type == "Technical Specification"):

                    if file.filename == '':
                        return jsonify({"error": "No selected file"}), 400


                    # Get the file extension
                    file_extension = os.path.splitext(file.filename)[1].lower()

                    if file_extension in ['.txt']:
                        # NameOfFile = ''
                        NameOfFile = os.path.splitext(file.filename)[0].lower()

                        file_stream = io.BytesIO(file.read()) # Text file extension
                        #logging.debug('---------------call upload TS generation for Text file--------------')
                        file_content  = file_stream.read().decode('utf-8')
                        scontent = file_content[:50000].lower()
                        word = "report"
                        if re.search(r'\b' + re.escape(word) + r'\b', scontent):

                            obj_flag = True


                        if file_content:

                            response,status = DOC_OBJ.TS_document_generationLat(file_content,user_id,NameOfFile,context,input_language,system,obj_flag,combined_files='single')
                            if status!=200:
                                #remove_titles()
                                return jsonify({"error": "Error in Technical document file Generation",
                                            "Description": f"{response}"}), 400
                            else:
                                document_dict = {
                                "user_id":user_id,
                                "type":"Technical document",
                                "filetype":"txt"
                            }

                            df = pd.DataFrame([document_dict])
                            df.to_excel(f'M_tracker_{user_id}.xlsx',index=False)
                            #logging.debug(f"Excel created for {user_id}")



                        return jsonify(response),200


                    elif file_extension in ['.zip']:
                        #logging.debug("In zip")

                        response,status = DOC_OBJ.process_main_zip(request,docType='TS')
                        if status!=200:
                            #remove_titles()
                            return json.dumps({"error": "Error in functional document file Generation",
                                            "Description": f"{response}"}), 400
                        else:
                            document_dict = {
                                "user_id":user_id,
                                "type":"Functional document",
                                "filetype":"zip"
                            }

                            df = pd.DataFrame([document_dict])
                            df.to_excel(f'M_tracker_{user_id}.xlsx',index=False)
                            #logging.debug(f"Excel created for {user_id}")


                        return jsonify(response),200

                    else:
                        return jsonify({"error": "Unsupported file type"}), 400

                elif (document_type == "BothFSTS"):

                    file = request.files['file']
                    if file.filename == '':
                        return jsonify({"error": "No selected file"}), 400


                    # Get the file extension
                    file_extension = os.path.splitext(file.filename)[1].lower()

                    if file_extension in ['.txt']:  # Text file extension
                        # NameOfFile = ''
                        NameOfFile = os.path.splitext(file.filename)[0].lower()

                        file_stream = io.BytesIO(file.read())
                        file_content  = file_stream.read().decode('utf-8')
                        scontent = file_content[:50000].lower()
                        word = "report"
                        if re.search(r'\b' + re.escape(word) + r'\b', scontent):

                            obj_flag = True

                        if file_content:

                            try:
                                #logging.debug('---------------call upload FS generation for Text file--------------')
                                FS_response,FS_status = DOC_OBJ.FS_document_generationLat(file_content,user_id,NameOfFile,context,input_language,system,execution_summary,obj_flag,'single')
                                if FS_status!=200:
                                    # #remove_titles()
                                    return jsonify({"error": "Error in FS Generation",
                                                    "Details":f"{FS_response}"}), 400
                            except Exception as e:
                                return jsonify({"Error in FS document creation"}),500


                            try:
                                #logging.debug('---------------call upload TS generation for Text file--------------')
                                TS_response,TS_status = DOC_OBJ.TS_document_generationLat(file_content,user_id,NameOfFile,context,input_language,system,execution_summary,obj_flag,'single')
                                if TS_status!=200:
                                    # #remove_titles()
                                    return jsonify({"error": "Error in TS Generation"}), 400
                            except Exception as e:
                                return jsonify({"Error in TS document creation"}),500

                            document_dict = {
                                "user_id":user_id,
                                "type":"Both document",
                                "filetype":"txt"
                            }

                            df = pd.DataFrame([document_dict])
                            df.to_excel(f'M_tracker_{user_id}.xlsx',index=False)
                            #logging.debug(f"Excel created for {user_id}")

                            response = FS_response+TS_response

                        return jsonify(response),200

                    elif file_extension in ['.zip']:

                        response,status = DOC_OBJ.process_main_zip(request,docType=['FS','TS'])
                        if status!=200:
                            # #remove_titles()
                            return jsonify({"error": "Error in both document file Generation",
                                            "Description": f"{response}"}), 400
                        else:
                            document_dict = {
                                "user_id":user_id,
                                "type":"Functional document",
                                "filetype":"zip"
                            }

                            df = pd.DataFrame([document_dict])
                            df.to_excel(f'M_tracker_{user_id}.xlsx',index=False)
                            #logging.debug(f"Excel created for {user_id}")

                        return jsonify(response),200

                    else:
                        return jsonify({"error": "Unsupported file type"}), 400


            elif template == "justification" and file_extension == '.zip':
                    if document_type == "Business Justification":
                        logging.info('---------------call upload_text_business--------------')
                        logging.debug("Received request for Business Justification")
                        set_business_prompt_and_tables(main_app)
                        return process_uploaded_text_file(request, main_app,cap_url,headers,"ReverseFSD")

                    elif document_type == "Technical Justification":
                        logging.info('---------------call upload_text_technical--------------')
                        logging.debug("Received request for Technical Justification")
                        set_technical_prompt_and_tables(main_app)
                        return process_uploaded_text_file(request, main_app,cap_url,headers,"ReverseTSD")
                    elif document_type == "bothbjtj":
                        logging.info('---------------call both Business and Technical Justification--------------')
                        logging.debug("Received request for both Business and Technical Justification")

                        # Process Business Justification
                        logging.debug("Processing Business Justification...")
                        set_business_prompt_and_tables(main_app)
                        business_response, business_status = process_uploaded_text_file(request, main_app,cap_url,headers,"ReverseFSD")

                        # Reset file pointer for reusing the file upload if necessary
                        if request.files:
                            for file in request.files.values():
                                file.stream.seek(0)

                        # Process Technical Justification
                        logging.debug("Processing Technical Justification...")
                        set_technical_prompt_and_tables(main_app)
                        technical_response, technical_status = process_uploaded_text_file(request, main_app,cap_url,headers,"ReverseTSD")

                        # Combine responses from both justifications
                        return jsonify({
                            "business_justification_response": business_response,
                            "technical_justification_response": technical_response
                        }), 200 if business_status == 200 and technical_status == 200 else 400
        else:
            return jsonify({"Error": "An unexpected error occurred. Please try again later."}), 500

    except Exception as e:
        # Log detailed exception (e.g., traceback) for debugging
        logging.error(f"Error: {traceback.format_exc()}")
        return jsonify({"Error": "An unexpected error occurred. Please try again later."}), 500


@app.route('/s3fileupload', methods=['POST'])
def s3fileupload():
    # Initialize a session using boto3
    session = boto3.session.Session()
    # Create S3 client
    s3_client = session.client(
        service_name='s3',
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region_name,
        verify=False
    )
    # Check if the 'file' is part of the request
    if 'files' not in request.files:
        return jsonify({"error": "No file part"}), 400
    files = request.files.getlist('files')  # Get the list of files
    if not files:
        return jsonify({"error": "No files selected"}), 400
    uploaded_files = []
    failed_files = []

    for file in files:
        try:
            # Use the original filename
            filename = file.filename
            if bucket_name:
                logging.info("OBJECT STORE")
                # Upload the file to S3
                s3_client.upload_fileobj(file, bucket_name, filename)
                uploaded_files.append(filename)
            elif CONTAINER_NAME:
                logging.info("AZURE")
                sas_url = f"{CONTAINER_URI}?{AZURE_STORAGE_ACCOUNT_KEY}"
                blob_service_client = BlobServiceClient(account_url=sas_url)
                BLOB_NAME = filename
                blob_client = BlobClient.from_blob_url(
                    f"{CONTAINER_URI}/{CONTAINER_NAME}/{BLOB_NAME}?{AZURE_STORAGE_ACCOUNT_KEY}")

                blob_client.upload_blob(file.stream, overwrite=True)
                uploaded_files.append(filename)
                print(f"Uploaded '{filename}' as '{BLOB_NAME}' to container '{CONTAINER_NAME}'")


        except Exception as e:
            failed_files.append(file.filename)

            error_message = str(e)

    # Response based on upload success/failure
    if uploaded_files:
        success_message = f"Files {', '.join(uploaded_files)} successfully uploaded."
    else:
        success_message = "No files were uploaded successfully."

    if failed_files:
        error_message = f"Failed to upload files: {', '.join(failed_files)}. Error: {error_message}"
    else:
        error_message = ""

    return jsonify({
        "message": success_message,
        "errors": error_message
    }), 200 if not failed_files else 500


@app.route('/s3filedownload', methods=['POST'])
def s3filedownload():
    # Initialize a session using boto3
    session = boto3.session.Session()
    # Create S3 client
    s3_client = session.client(
        service_name='s3',
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region_name,
        verify=False)
    # Check if 'files' are part of the request
    if 'files' not in request.json:
        return jsonify({"error": "No files specified for download"}), 400

    filenames = request.json['files']  # Get the list of filenames

    if not filenames:
        return jsonify({"error": "No filenames provided"}), 400

    files_to_download = []
    failed_files = []

    # Attempt to download each file from S3
    for filename in filenames:
        try:
            BLOB_NAME = filename
            if bucket_name:
                # Get the file object from S3
                file_obj = s3_client.get_object(Bucket=bucket_name, Key=filename)
                file_data = file_obj['Body'].read()
                files_to_download.append((filename, file_data))
            elif CONTAINER_NAME:
                logging.info("azure")
                sas_url = f"{CONTAINER_URI}?{AZURE_STORAGE_ACCOUNT_KEY}"

                blob_service_client = BlobServiceClient(account_url=sas_url)
                BLOB_NAME = filename

                blob_client = BlobClient.from_blob_url(
                    f"{CONTAINER_URI}/{CONTAINER_NAME}/{BLOB_NAME}?{AZURE_STORAGE_ACCOUNT_KEY}")

                file_data = blob_client.download_blob().readall()
                files_to_download.append((filename, file_data))
                logging.info(f"Downloaded blob '{BLOB_NAME}' to '{filename}'")


        except Exception as e:
            failed_files.append(filename)
            logging.error(f"Failed to download {filename}: {e}")

    # If no files are found or downloaded
    if not files_to_download:
        return jsonify({"error": "No files were downloaded successfully."}), 500

    # If files are downloaded successfully, we can either send them individually or zip them
    if len(files_to_download) == 1:
        # Return a single file
        filename, file_data = files_to_download[0]
        return send_file(BytesIO(file_data), download_name=filename, as_attachment=True)
    else:
        # Create a zip file for multiple files
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for filename, file_data in files_to_download:
                zip_file.writestr(filename, file_data)

        zip_buffer.seek(0)
        return send_file(zip_buffer, download_name="files.zip", as_attachment=True)# def s3fileupload():
    

    
'''
if __name__ == '__main__':
	app.run(host="localhost", port=8080, debug=True)
	
'''


@app.route('/file_processor', methods=['POST'])
def file_processor():
    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)

    try:
        access_token = request.headers.get('authorization')[7:]
    except:
        access_token = request.headers.get('Authorization')[7:]


    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')


            if not isAuthorized:
                abort(403)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    try:
        user_input = request.form.get('input_feature', '')
        document_type = request.form.get('document_type', '')
        template = request.form.get('template', '')
        execution_summary="No Data Found.."
        main_context = request.form.get('add_info','')
        input_language = request.form.get('language','')
        project_id = request.form.get('project_id')
        template_type = request.form.get('template_type')
        source_dpd = request.form.get("source_dpd")

        context, system = extract_context_and_system(main_context) #check 1
        
        user_id = str(uuid.uuid4())
        user_id=str(user_id)
        obj_flag=False
        obj_type = ""



        delete_all_subfolders(user_id)

        input_feature =  user_input
        # Get the file extension
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No selected file"}), 400
        file_extension = os.path.splitext(file.filename)[1].lower() 
        if file_extension in ['.txt']:  # Text/word file extension

                    file_stream = io.BytesIO(file.read())
                    NameOfFile = os.path.splitext(file.filename)[0].lower()
                    try:
                        file_content = file_stream.read().decode('utf-8')
                    except UnicodeDecodeError:
                        file_stream.seek(0)  # Reset stream position
                        file_content = file_stream.read().decode('ISO-8859-1')  # Latin-1 fallback
                    scontent=file_content[:50000].lower()

                    words = ["prog", "tran", "report", "enho", "program", "transaction", "enhancement" ,"badi",
                             "business add ins", "cmod", "customer modifications", "sxci"]

                    # Check for keywords in the additional information and source code
                    combined_content = main_context.lower() + " " + scontent  # Combine both contents for searching
                    # Split the combined content into lines
                    lines = combined_content.splitlines()

                    # Dictionary to count occurrences of each keyword
                    word_count = defaultdict(int)

                    # Search line by line
                    for line in lines:
                        for word in words:
                            if re.search(r'\b' + re.escape(word) + r'\b', line):
                                word_count[word] += 1  # Increment the count for the found word

                    # Determine the most frequently occurring keyword
                    if word_count:
                        obj_type = max(word_count, key=word_count.get)  # Get the word with the highest count
                        obj_flag = True if obj_type in ["prog", "program",
                                                        "report"] else False  # Set obj_flag based on specific words
                    if file_content:
                        response = [(file_content,user_id,NameOfFile,context,input_language,system,execution_summary,obj_type,obj_flag,'single')]

                        return jsonify({"data":response,"doc_type":document_type,"template":template,"input_feature":input_feature,"project_id":project_id,"template_type":template_type,"headers":headers,"source_dpd":source_dpd})
                    else:
                        return jsonify({"Empty file uploaded"})
                    
        elif file_extension in ['.zip']:
                    response = process_main_zip(request,user_id)
                    #return response
                    return ({"data":response,"doc_type":document_type,"template":template,"input_feature":input_feature,"project_id":project_id,"template_type":template_type,"headers":headers,"source_dpd":source_dpd})
        else:
            logging.info("Incorrect data format please give the file again")

        
    except Exception as e:
        # Log detailed exception (e.g., traceback) for debugging
        logging.error(f"Error: {traceback.format_exc()}")
        return jsonify({"Error": "An unexpected error occurred. Please try again later."}), 500
    


def read_file_with_fallback(file_path):
    """
    Read a file with UTF-8 encoding and fallback to ISO-8859-1 if UTF-8 fails.
    This ensures compatibility with files containing non-UTF-8 byte sequences.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return file.read()
    except UnicodeDecodeError:
        logging.warning(f"UnicodeDecodeError for file {file_path} with utf-8. Trying ISO-8859-1.")
        with open(file_path, 'r', encoding='ISO-8859-1') as file:
            return file.read()


def process_main_zip(request, user_id):
    main_context = request.form.get('add_info')
    input_language = request.form.get('language')
    execution_summary = "No Data Found"
    obj_flag = False
    obj_type = ""

    context, system = extract_context_and_system(main_context)

    if 'file' not in request.files:
        logging.error("No file part in the request")
        return jsonify({"error": "No file part in the request"}), 400

    file = request.files['file']

    if file.filename == '':
        logging.error("No file selected for uploading")
        return jsonify({"error": "No file selected for uploading"}), 400

    temp_path = 'main_extracted'
    result = []
    file_info_dict = dict()

    try:
        if not os.path.exists(temp_path):
            os.makedirs(temp_path)

        with zipfile.ZipFile(file, 'r') as main_zip:
            main_zip.extractall(temp_path)

        add_info_list = main_context.strip('[]').replace(" ", "").split(',') if main_context else []
        file_info_dict = {
            item: add_info_list[i] if i < len(add_info_list) else ""
            for i, item in enumerate(os.listdir(temp_path))
        }

        for item, main_context in file_info_dict.items():
            item_path = os.path.join(temp_path, item)
            context, system = extract_context_and_system(main_context)

        for root, dirs, files in os.walk(temp_path):
            for file in files:
                item_path = os.path.join(root, file)

                if zipfile.is_zipfile(item_path):
                    logging.info(f"Found inner zip file")
                    with zipfile.ZipFile(item_path, 'r') as inner_zip:
                        temp_folder = os.path.join(temp_path, "temp")
                        os.makedirs(temp_folder, exist_ok=True)
                        inner_zip.extractall(temp_folder)

                    combinedSourceCode = ""

                    for inner_root, inner_dirs, inner_files in os.walk(temp_folder):
                        for inner_file in inner_files:
                            if inner_file.lower().endswith('.txt'):
                                inner_file_path = os.path.join(inner_root, inner_file)
                                logging.info(f"Found .txt file in inner zip: {inner_file_path}")
                                try:
                                    source_code = read_file_with_fallback(inner_file_path)
                                    scontent = source_code[:50000].lower()
                                    words = [
                                        "prog", "tran", "report", "enho", "program", "transaction",
                                        "enhancement","badi", "business add ins", "cmod",
                                        "customer modifications", "sxci"
                                    ]

                                    combined_content = main_context.lower() + " " + scontent
                                    lines = combined_content.splitlines()
                                    word_count = defaultdict(int)

                                    for line in lines:
                                        for word in words:
                                            if re.search(r'\b' + re.escape(word) + r'\b', line):
                                                word_count[word] += 1

                                    if word_count:
                                        obj_type = max(word_count, key=word_count.get)
                                        obj_flag = obj_type in ["prog", "program", "report"]
                                except Exception as e:
                                    logging.error(f"Error reading file {inner_file_path}: {str(e)}", exc_info=True)
                                    return jsonify({
                                        "error": "Error reading file due to encoding issue.",
                                        "message": str(e)
                                    }), 400

                                combinedSourceCode += '#' * 50 + '\n\n' + source_code

                    NameofFile = os.path.splitext(file)[0]
                    logging.info(f"Adding result for file {NameofFile}")
                    temp_result = (
                        combinedSourceCode, user_id, NameofFile, context, input_language,
                        system,execution_summary,obj_type, obj_flag, 'many'
                    )
                    result.append(temp_result)

                    shutil.rmtree(temp_folder)

                elif file.lower().endswith('.txt'):
                    logging.info(f"Found .txt file in root zip: {item_path}")
                    try:
                        source_code = read_file_with_fallback(item_path)
                        scontent = source_code[:50000].lower()
                        words = [
                            "prog", "tran", "report", "enho", "program", "transaction",
                            "enhancement","badi", "business add ins", "cmod",
                            "customer modifications", "sxci"
                        ]

                        combined_content = main_context.lower() + " " + scontent
                        lines = combined_content.splitlines()
                        word_count = defaultdict(int)

                        for line in lines:
                            for word in words:
                                if re.search(r'\b' + re.escape(word) + r'\b', line):
                                    word_count[word] += 1

                        if word_count:
                            obj_type = max(word_count, key=word_count.get)
                            obj_flag = obj_type in ["prog", "program", "report"]
                    except Exception as e:
                        logging.error(f"Error reading file {item_path}: {str(e)}", exc_info=True)
                        return jsonify({
                            "error": "Error reading file due to encoding issue.",
                            "message": str(e)
                        }), 400

                    NameofFile = os.path.splitext(file)[0]
                    logging.info(f"Adding result for file {NameofFile}")
                    temp_result = (
                        source_code, user_id, NameofFile, context, input_language,
                        system,execution_summary,obj_type, obj_flag, 'single'
                    )
                    result.append(temp_result)

        logging.info(f"Total number of results: {len(result)}")

    finally:
        logging.info("Extraction done")

        if os.path.exists(temp_path):
            shutil.rmtree(temp_path)

        if result:
            logging.info(f"Returning {len(result)} results")
            return result
        else:
            logging.warning("No valid files processed")
            return jsonify({"error": "No valid files processed."}), 400
        
import gc

def process_document_both(index, item, doc_type,project_id,template_type,session_id,user_name,cap_url,headers,source_dpd=""):
    """Worker function to process both documents (FS and TS) in a separate background task"""
    try:
        DOC_OBJ = DOCGEN()
        input_data = item[0]
        user_id = item[1]
        NameOfFile = item[2]
        context = item[3]
        input_language = item[4]
        system = item[5]
        combined_files = item[9]
        obj_flag = item[8]
        obj_type=item[7]
        execution_summary=item[6]
        user_name = user_name
        project_id = project_id
        source_dpd = source_dpd
        template_type = template_type
        cap_url = cap_url
        headers = headers
        
 
        gc.collect()
        logging.info(f"Processing {index}: {NameOfFile}")
        socketio.emit(session_id, {'index': index, 'status': "Processing", 'NameOfFile': NameOfFile}, namespace="/document_generator")
        if doc_type == "Functional Specification":
            log_id = str(uuid.uuid4())
            Utils.job_logs_insert(HANADB_ADDRESS,HANADB_PORT,HANADB_USER,HANADB_PASSWORD,user_name,user_name,log_id,user_id,str(NameOfFile),project_id,'RE',"Functional Specification",'In-Progress',None,str(obj_type),0,0,"CURRENT_LLM_CONTENT","PREVIOUS_LLM_CONTENT","RAW_INPUT_DATA",hanadbschema,'APP_TSP_job_logs')

            if source_dpd == "X":
                cached_input_data, code = DOC_OBJ.get_chunking_summary(input_data, input_language)
            else:
                cached_input_data, code = DOC_OBJ.chunking_method(input_data)
                
            if code == 500 :
                socketio.emit(session_id, {'index': index, 'status': code, "thread_id": user_id, 'data': cached_input_data, 'NameOfFile': NameOfFile}, namespace="/document_generator")
            data_result, code = DOC_OBJ.FS_document_generationLat(cached_input_data, user_id, NameOfFile, context, input_language, system,execution_summary,obj_type, obj_flag,project_id,template_type,cap_url,headers,combined_files)
            if code == 200: 
                Utils.job_logs_update(HANADB_ADDRESS,HANADB_PORT,HANADB_USER,HANADB_PASSWORD,log_id,user_id,str(NameOfFile),"Success",data_result,None,hanadbschema,'APP_TSP_job_logs')
            else:
                Utils.job_logs_update(HANADB_ADDRESS,HANADB_PORT,HANADB_USER,HANADB_PASSWORD,log_id,user_id,str(NameOfFile),"Error",data_result,None,hanadbschema,'APP_TSP_job_logs')
    
        elif doc_type == "Technical Specification":
            log_id = str(uuid.uuid4())
            Utils.job_logs_insert(HANADB_ADDRESS,HANADB_PORT,HANADB_USER,HANADB_PASSWORD,user_name,user_name,log_id,user_id,str(NameOfFile),project_id,'RE',"Technical Specification",'In-Progress',None,str(obj_type),0,0,"CURRENT_LLM_CONTENT","PREVIOUS_LLM_CONTENT","RAW_INPUT_DATA",hanadbschema,'APP_TSP_job_logs')
            
            if source_dpd == "X":
                cached_input_data, code = DOC_OBJ.get_chunking_summary(input_data, input_language)
            else:
                cached_input_data, code = DOC_OBJ.chunking_method(input_data)

            if code == 500 :
                socketio.emit(session_id, {'index': index, 'status': code, "thread_id": user_id, 'data': cached_input_data, 'NameOfFile': NameOfFile}, namespace="/document_generator")
            data_result, code = DOC_OBJ.TS_document_generationLat(cached_input_data, user_id, NameOfFile, context, input_language, system,execution_summary,obj_type, obj_flag,project_id,template_type,cap_url,headers,combined_files,source_dpd)
            if code == 200: 
                Utils.job_logs_update(HANADB_ADDRESS,HANADB_PORT,HANADB_USER,HANADB_PASSWORD,log_id,user_id,str(NameOfFile),"Success",data_result,None,hanadbschema,'APP_TSP_job_logs')
            else:
                Utils.job_logs_update(HANADB_ADDRESS,HANADB_PORT,HANADB_USER,HANADB_PASSWORD,log_id,user_id,str(NameOfFile),"Error",data_result,None,hanadbschema,'APP_TSP_job_logs')
        else:
            fs_log_id = str(uuid.uuid4())
            Utils.job_logs_insert(HANADB_ADDRESS,HANADB_PORT,HANADB_USER,HANADB_PASSWORD,user_name,user_name,fs_log_id,user_id,str(NameOfFile),project_id,'RE',"Functional Specification",'In-Progress',None,str(obj_type),0,0,"CURRENT_LLM_CONTENT","PREVIOUS_LLM_CONTENT","RAW_INPUT_DATA",hanadbschema,'APP_TSP_job_logs')
            ts_log_id = str(uuid.uuid4())
            Utils.job_logs_insert(HANADB_ADDRESS,HANADB_PORT,HANADB_USER,HANADB_PASSWORD,user_name,user_name,ts_log_id,user_id,str(NameOfFile),project_id,'RE',"Technical Specification",'In-Progress',None,str(obj_type),0,0,"CURRENT_LLM_CONTENT","PREVIOUS_LLM_CONTENT","RAW_INPUT_DATA",hanadbschema,'APP_TSP_job_logs')
            
            if source_dpd == "X":
                cached_input_data, code = DOC_OBJ.get_chunking_summary(input_data, input_language)
            else:
                cached_input_data, code = DOC_OBJ.chunking_method(input_data)
                
            if code == 500 :
                socketio.emit(session_id, {'index': index, 'status': code, "thread_id": user_id, 'data': cached_input_data, 'NameOfFile': NameOfFile}, namespace="/document_generator")
            data_result, code = DOC_OBJ.FS_document_generationLat(cached_input_data, user_id, NameOfFile, context, input_language, system,execution_summary,obj_type,obj_flag,project_id,template_type,cap_url,headers,combined_files)
            if code == 200: 
                Utils.job_logs_update(HANADB_ADDRESS,HANADB_PORT,HANADB_USER,HANADB_PASSWORD,fs_log_id,user_id,str(NameOfFile),"Success",data_result,None,hanadbschema,'APP_TSP_job_logs')
            else:
                Utils.job_logs_update(HANADB_ADDRESS,HANADB_PORT,HANADB_USER,HANADB_PASSWORD,fs_log_id,user_id,str(NameOfFile),"Error",data_result,None,hanadbschema,'APP_TSP_job_logs')
            
            data_result, code = DOC_OBJ.TS_document_generationLat(cached_input_data, user_id, NameOfFile, context, input_language, system,execution_summary,obj_type,obj_flag,project_id,template_type,cap_url,headers,combined_files,source_dpd)
            if code == 200: 
                Utils.job_logs_update(HANADB_ADDRESS,HANADB_PORT,HANADB_USER,HANADB_PASSWORD,ts_log_id,user_id,str(NameOfFile),"Success",data_result,None,hanadbschema,'APP_TSP_job_logs')
            else:
                Utils.job_logs_update(HANADB_ADDRESS,HANADB_PORT,HANADB_USER,HANADB_PASSWORD,ts_log_id,user_id,str(NameOfFile),"Error",data_result,None,hanadbschema,'APP_TSP_job_logs')
        socketio.emit(session_id, {'index': index, 'status': code, "thread_id": user_id, 'data': data_result, 'NameOfFile': NameOfFile}, namespace="/document_generator")
    except Exception as e:
        socketio.emit(session_id, {'index': index, 'status': 'error', 'data': str(e), 'NameOfFile': NameOfFile}, namespace="/document_generator")


def keep_alive(threads, session_id):
    while any(t['alive'] for t in threads):
        socketio.emit(session_id, {'status': 'keep-alive'}, namespace="/document_generator")
        time.sleep(5)


@socketio.on('process_doc', namespace='/document_generator')
def handle_my_custom_event(json):
    data_list = json['data']
    doc_type = json['doc_type']
    project_id = json['project_id']
    source_dpd = json['source_dpd']
    template_type = json['template_type']
    session_id = json['session_id']
    user_name = json['user_name']
    source_dpd = json['source_dpd']
    headers = json['headers']

    socketio.emit(session_id, {'status': 'processing', 'message': 'Processing started...'}, namespace="/document_generator")

    threads = []

    for index, item in enumerate(data_list):
        def task_wrapper(idx=index, itm=item):
            process_document_both(idx, itm, doc_type, project_id, template_type, session_id, user_name,cap_url,headers,source_dpd)
            threads[idx]['alive'] = False

        thread_info = {'alive': True}
        threads.append(thread_info)
        socketio.start_background_task(task_wrapper)

    socketio.start_background_task(keep_alive, threads, session_id)

    # Final update after all tasks are done
    def wait_and_finalize():
        while any(t['alive'] for t in threads):
            time.sleep(1)
        socketio.emit(session_id, {'status': 'done'}, namespace="/document_generator")

    socketio.start_background_task(wait_and_finalize)


def cleanup_temp_folder(folder_path):
    """
    Delete all files and folders inside the given folder_path, but not the folder itself.
    """
    folder = Path(folder_path)
    if folder.exists() and folder.is_dir():
        for item in folder.iterdir():
            try:
                if item.is_file() or item.is_symlink():
                    item.unlink()
                    logging.info(f"Deleted file: {item}")
                elif item.is_dir():
                    shutil.rmtree(item)
                    logging.info(f"Deleted directory: {item}")
            except Exception as e:
                logging.error(f"Error deleting {item}: {e}")
                

def download_azure_blobs_and_zip(thread_id):
    sas_token = AZURE_STORAGE_ACCOUNT_KEY.lstrip('?')
    blob_service_client = BlobServiceClient(account_url=CONTAINER_URI, credential=sas_token)
    container_client = blob_service_client.get_container_client(CONTAINER_NAME)

    folder_name = f"document_{thread_id}"
    os.makedirs(folder_name, exist_ok=True)
    downloaded_files = []
    document_count = 0

    blobs = container_client.list_blobs()
    for blob in blobs:
        blob_name = blob.name
        if thread_id in blob_name:
            print(f"Downloading Azure blob: {blob_name}")
            blob_client = container_client.get_blob_client(blob_name)
            output_filename = os.path.basename(blob_name)
            local_file_path = os.path.join(folder_name, output_filename)

            with open(local_file_path, "wb") as f:
                download_stream = blob_client.download_blob()
                f.write(download_stream.readall())

            downloaded_files.append(local_file_path)

            if blob_name.lower().endswith('.docx'):
                document_count += 1

            blob_client.delete_blob()

    if not downloaded_files:
        return None, None, 0

    zip_filename = f"{folder_name}.zip"
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file_path in downloaded_files:
            zipf.write(file_path, os.path.basename(file_path))

    print(f"Created Azure zip file: {zip_filename}")
    return zip_filename, folder_name, document_count


# Flask app
@app.route('/download_folder', methods=['POST'])
def download_folder():

    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)

    try:
        access_token = request.headers.get('authorization')[7:]
    except:
        access_token = request.headers.get('Authorization')[7:]


    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')


            if not isAuthorized:
                abort(403)
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    thread_id = request.form.get("thread_id")
    project_id = request.form.get("project_id")
    user_id = request.form.get("USER_ID")
    folder_name = f"Documents_{thread_id}/"

    try:
        cap_client = CapServiceClient(cap_url)
        document_names = []

        if bucket_name and gcp_private_key:
            key_json = base64.b64decode(gcp_private_key).decode('utf-8')
            key_path = "temp_key.json"
            with open(key_path, "w") as f:
                f.write(key_json)

            client = storage.Client.from_service_account_json(key_path)
            gcp_bucket = client.bucket(bucket_name)

            if not gcp_bucket.exists():
                logging.error(f"Bucket '{bucket_name}' does not exist.")
                return {"error": "Bucket not found."}, 404

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                blobs = list(gcp_bucket.list_blobs(prefix=folder_name))
                for blob in blobs:
                    if blob.name.endswith('/'):
                        continue
                    file_stream = io.BytesIO()
                    blob.download_to_file(file_stream)
                    file_stream.seek(0)
                    relative_path = blob.name[len(folder_name):].lstrip('/')
                    zip_file.writestr(relative_path, file_stream.read())
                    blob.delete()

                    if blob.name.lower().endswith('.docx'):
                        document_count += 1

            zip_buffer.seek(0)
            response_data = zip_buffer

        elif bucket_name:
            # AWS S3 Logic
            session = boto3.Session(aws_access_key_id=access_key, aws_secret_access_key=secret_key)
            s3 = session.resource('s3', verify=False)
            my_bucket = s3.Bucket(bucket_name)

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for obj in my_bucket.objects.filter(Prefix=folder_name):
                    if obj.key.endswith('/'):
                        continue
                    file_stream = io.BytesIO()
                    s3.Object(bucket_name, obj.key).download_fileobj(file_stream)
                    file_stream.seek(0)
                    relative_path = obj.key[len(folder_name):].lstrip('/')
                    zip_file.writestr(relative_path, file_stream.read())
                    s3.Object(bucket_name, obj.key).delete()

                    if obj.key.lower().endswith('.docx'):
                        document_names.append(relative_path)

            zip_buffer.seek(0)
            response_data = zip_buffer

        elif CONTAINER_NAME:
            # Azure Blob Logic using your custom functions
            zip_path = process_thread(thread_id)

            with open(zip_path, "rb") as f:
                zip_data = f.read()

            response_data = io.BytesIO(zip_data)

            # Extract .docx file names from the zip
            with zipfile.ZipFile(zip_path, 'r') as zip_file:
                document_names.extend([name for name in zip_file.namelist() if name.lower().endswith('.docx')])

        # UUID-based document tracking
        if project_id and document_names:
            document_name_with_UUIDs = {name: str(uuid.uuid4()) for name in document_names}
            Flag = cap_client.insert_doccount_records(project_id, document_name_with_UUIDs, user_id, headers)
            if Flag:
                cap_client.update_documents_generated(project_id, len(document_name_with_UUIDs), headers)

        return send_file(
            response_data,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f"{folder_name.strip('/')}.zip"
        )

    except Exception as e:
        logging.error(f"Error processing download: {str(e)}")
        return {"error": "Failed to process download."}, 500


class FunctionReplacementProcessor:
    def _init_(self):
        pass
    
    def extract_all_source_code(self, obj):
        final_data = []
        
        def _extract(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key == 'SOURCE_CODE':
                        final_data.append(value)
                    _extract(value)
            elif isinstance(obj, list):
                for item in obj:
                    _extract(item)
        
        _extract(obj)
        return final_data

    def remove_duplicate_code(self, clean_text, line_list):
        clean_new_text = []
        ranges = []
        
        for flist in line_list:
            if flist[3] in ["FORM"]:
                ranges.append([flist[1], flist[2]])
        
        result = [i for start, end in ranges for i in range(start, end + 1)]
        
        for i, line in enumerate(clean_text.splitlines(), start=1):
            if i in result:
                pass
            else:
                clean_new_text.append(line)
        
        return "\n".join(clean_new_text)

    def perform_function_replacement(self, text, final_dict, passed_key=None):
        replace_string = []
        code_line_count = 1
        
        for i, line in enumerate(text.splitlines(), start=1):
            match = (re.search(r"\bCALL\s+FUNCTION\s+\\?'?z\w+'?\\?\b", line.strip().lower(),re.IGNORECASE) or
                    re.search(r'\s*perform\b:?\s*(\w+)', line.lower().strip(), re.IGNORECASE) or
                    re.search(r"\bCALL\s+METHOD\s+z\w+=>\w+\b", line.strip().lower(), re.IGNORECASE) or
                    re.search(r'\bZ\w+=>\w+\s*\b', line.strip().lower(), re.IGNORECASE) or
                    re.search(r'MODULE\s+(\w+)', line.strip().replace(".", "").lower(), re.IGNORECASE) or
                    re.search(r"\bCALL SCREEN\s*'?(\d+)'?\b(?:\s*STARTING AT\s*\d+\s*\d+\s*ENDING AT\s*\d+\s*\d+)?", line.strip(), re.IGNORECASE) or
                    re.search(r'\bSUBSCREEN\s*=\s*(\d+)\b', line.strip().replace("'", "").lower(), re.IGNORECASE) or
                    re.search(r"\s*SET\s+HANDLER\s*\w+->\w+\b", line.strip().lower(),re.IGNORECASE))
            
            if match:
                if not re.match(r'^\s*\*', line):
                    try:
                        if "=>" in line or "->" in line:

                            method_test = str(line).replace(")","").replace("(","").split("=>")
                            if len(method_test) > 1:
                                pass
                            else:
                                method_test = str(line).replace(")","").replace("(","").split("->")
                            method_test[-1] = method_test[-1].strip().split()[0]
                            if passed_key != method_test[-1]:
                                replace_string.insert(code_line_count, line+"~")
                                code_line_count = code_line_count+1
                                replace_string.insert(code_line_count+1, str(final_dict[method_test[-1]]))
                                code_line_count = code_line_count+len(final_dict[method_test[-1]])
                            else:
                                print("Fail Pass key", match)

                        elif "->" in line:
                            method_test = str(line).replace(")", "").replace("(", "").split("->")
                            if passed_key != method_test[-1]:
                                replace_string.insert(code_line_count, line+"~")
                                code_line_count = code_line_count+1
                                replace_string.insert(code_line_count+1, str(final_dict[method_test[-1]]))
                                code_line_count = code_line_count+len(final_dict[method_test[-1]])
                            else:
                                print("Fail Pass key", match)
                        
                        else:
                            try:
                                if passed_key != match.group(1):
                                    replace_string.insert(code_line_count, line+"~")
                                    code_line_count = code_line_count+1
                                    replace_string.insert(code_line_count+1, final_dict[str(match.group(1)).lower()])
                                    code_line_count = code_line_count+len(final_dict[str(match.group(1)).lower()])
                                    code_line_count = code_line_count + 2
                                else:
                                    print("Fail Pass key", match)
                            except Exception as ex:
                                if passed_key != str(match.group()).replace("'", "").replace("call function", "").replace("\\", "").strip().lower():
                                    replace_string.insert(code_line_count, line+"~")
                                    code_line_count = code_line_count+1
                                    
                                    replace_string.insert(code_line_count+1, final_dict[str(match.group()).replace("'", "").replace("call function", "").replace("\\", "").strip().lower()])
                                    code_line_count = code_line_count+len(final_dict[str(match.group()).replace("'", "").replace("call function", "").replace("\\", "").strip().lower()])
                                else:
                                    print("Fail Pass key", match)
                    except Exception as ex:
                        pass
                else:
                    replace_string.insert(code_line_count, line)
                    code_line_count = code_line_count+1
            else:
                replace_string.insert(code_line_count, line)
                code_line_count = code_line_count+1
                
        replace_string = "\n".join(replace_string)
        return replace_string

    def process_json_data(self, json_data_combined):
        """Main processing function that applies function replacement to JSON data"""
        try:
            
            final_data = self.extract_all_source_code(json_data_combined)
            combined_source_code = "\n".join(final_data)
            # final_data = json_data_combined
            
            # # Process first object's source code
            for d in json_data_combined[0]:  
                partial_data = d.get('SOURCE_CODE', '')

            partial_data = partial_data.split('###SRC_END###')[0].strip().replace(".", "")
            
                
            # print("$$$4", partial_data)
            clean_code = str(combined_source_code)
            clean_code = clean_code.split(",")
            clean_code = "\n".join(clean_code)
            clean_code = str(clean_code).replace('"', '').replace("OBJECT_TYPE:Function Module", "")
            clean_code = re.sub(r'ENDFORM[^\n]*', 'ENDFORM', clean_code.strip().replace(".", ""))
            
            
            def clean_ft_block(list_of_lists):
                unique_by_first = {}
                for sublist in list_of_lists:
                    key = sublist[0]
                    if key not in unique_by_first:
                        unique_by_first[key] = sublist
               
                # Convert back to list
                result = list(unique_by_first.values())
                return result
           
            FT = Chunking_process.main(clean_code)
            FT = clean_ft_block(FT)
           
            
            perform_dict = {}
            for f in FT:
                start_line = int(f[1])
                end_line = int(f[2])
                context = ""
                
                for i, line in enumerate(clean_code.splitlines(), start=1):
                    if start_line <= i <= end_line:
                        context = context + line.strip() + "\n"
                    elif i > end_line:
                        break
                
                perform_dict[str(f[0]).lower()] = context

            new_dict = {}
            for new_key, value in perform_dict.items():
                new_dic_val_list = []
                for i, line in enumerate(value.splitlines(), start=1):
                    new_dic_val_list.append(self.perform_function_replacement(line.strip(), perform_dict, new_key))
                perform_dict[new_key] = "\n".join(new_dic_val_list)
                new_dict[new_key] = "\n".join(new_dic_val_list)
            
            for new_key, value in new_dict.items():
                new_dic_val_list = []
                for i, line in enumerate(value.splitlines(), start=1):
                    if line.endswith("~"):
                        new_dic_val_list.append(line)
                    new_dic_val_list.append(self.perform_function_replacement(line, new_dict, new_key))
                new_dict[new_key] = "\n".join(new_dic_val_list)
            
            # Process main code
            clean_code_new = partial_data
            clean_code_new = str(clean_code_new).split(",")
            clean_code_new = "\n".join(clean_code_new)
            clean_code_new = str(clean_code_new).replace('"', '').replace("'", "")
            
            clean_code_new = self.remove_duplicate_code(clean_code_new, FT)
            
            
            perform_function_replacement_list = []
            for i, line in enumerate(clean_code_new.splitlines(), start=1):
                perform_function_replacement_list.append(self.perform_function_replacement(line.strip(), perform_dict, "get_batch_history_data"))
            
            perform_function_replacement_str = "\n".join(perform_function_replacement_list)
            
            # Final replacement iterations
            for item in range(4):
                final_replacement_list = []
                for i, line in enumerate(perform_function_replacement_str.splitlines(), start=1):
                    if line.endswith("~"):
                        final_replacement_list.append(line)
                    else:
                        final_replacement_list.append(self.perform_function_replacement(line, perform_dict, "get_batch_history_data"))
                
                final_replacement_list_str = "\n".join(final_replacement_list)
                perform_function_replacement_str = final_replacement_list_str
            
            final_replacement_list_str = str(final_replacement_list_str).replace("~", "")
            # final_replacement_list_str = re.sub(r'ENDFORM[^\n]*', 'ENDFORM', final_replacement_list_str)
            rearranged_list = []
            
            temp_dict = {}
            # temp_dict ['OBJECT_NAME']="ZCL_MDG_CHAR_UTILITY"
            temp_dict ['ADD_INFO']=[]
            temp_dict ['SOURCE_CODE']=[final_replacement_list_str]
            
            rearranged_list.append(temp_dict)
            return rearranged_list
                
        except Exception as e:
            logging.error(f"Error in function replacement processing: {str(e)}")
            return json_data_combined


@app.route('/autoUpload', methods=['POST'])
def autofileprocessor():
    """
    Extracts source_code from JSON data, ensures it is a string,
    and sequentially calls FS_document_generation and TS_document_generation functions.
    """
    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)
 
    try:
      access_token = request.headers.get('authorization')[7:]
    except:
      access_token = request.headers.get('Authorization')[7:]

 
    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')
 

            if not isAuthorized:
                abort(403)
    headers = {
    "Authorization": f"Bearer {access_token}",
    "Accept": "application/json",
    "Content-Type": "application/json"
    }
 
    try:
        DOC_OBJ = DOCGEN()
        
        # doc_type="Functional Specification"
        if not request.is_json:
            logging.error("No JSON data in request")
            return jsonify({"error": "No JSON data provided"}), 400
 
        # Parse JSON data
        json_data_combined = request.get_json()
 
        # total_document = len(json_data_combined)
 
        # Extract source_code and ensure it's a string
        combined_list = []
        add_info_list = json_data_combined[0].get('ADD_INFO', []) # Consider one list of ADD_INFO
 
        # Create a mapping for each OBJECT_NAME to its corresponding ADD_INFO value
        add_info_mapping = {}
 
        if len(add_info_list) == 0:
            logging.error("ADD_INFO list is empty. Using default value for all mappings.")
            # Use a default value (e.g., "") for all mappings
            for json_data in json_data_combined:
                add_info_mapping[json_data['OBJECT_NAME']] = ""
        else:
            for i, json_data in enumerate(json_data_combined):
                add_info_mapping[json_data['OBJECT_NAME']] = add_info_list[i % len(add_info_list)]
 

        document_type = None
        user_id=str(uuid.uuid4())
        for json_data in json_data_combined:
            obj_type=json_data.get('OBJECT_TYPE')
            source_code = json_data.get('SOURCE_CODE')
            nameOfFile = json_data.get('OBJECT_NAME')
            doc_type=json_data.get("document_type")
            project_id = json_data.get("project_id")
            template_type = json_data.get("template_type")
            source_dpd = json_data.get("source_dpd")
            document_type = doc_type
            project_id = project_id
            template_type = template_type
            source_dpd = source_dpd



            context,system = extract_context_and_system(add_info_mapping.get(nameOfFile, ""))
            language = json_data.get('LANGUAGE')
            execution_summary = json_data.get('ST03_TEXT'," ")
            obj_flag=False
            if obj_type=="PROG" or obj_type=="TRAN" or obj_type=="Transaction" or obj_type=="Program" or obj_type=="Report" or obj_type.lower() =="smartform" or obj_type.lower()=="class" or obj_type.lower() == "ssfo"or obj_type.lower() == "conv":
                obj_flag=True

            if not source_code:
                logging.error("source_code key is missing or empty in the JSON data")
                return jsonify({"error": "source_code key is missing or empty in the JSON data"}), 400
            if not nameOfFile:
                logging.error("object_name key is missing or empty in the JSON data")
                return jsonify({"error": "object_name key is missing or empty in the JSON data"}), 400
            obj_type_new=obj_type.lower()
            combined_list.append((str(source_code), user_id, nameOfFile, context, language, system,execution_summary,obj_type_new,obj_flag,'single'))
 
        return {"data":combined_list,"doc_type":document_type,"project_id":project_id,"template_type":template_type,"headers":headers,"source_dpd":source_dpd}
 
    except Exception as e:
        logging.error(f"Error in document processing: {str(e)}", exc_info=True)
        return jsonify({
            "error": "An error occurred while processing the document detailed spec.",
            "details": str(e)
        })
 

@app.route('/autoUploadNested', methods=['POST'])
def autofileprocessorNested():
    """
    Extracts source_code from JSON data, ensures it is a string,
    and sequentially calls FS_document_generation and TS_document_generation functions.
    """
    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)
 
    try:
      access_token = request.headers.get('authorization')[7:]
    except:
      access_token = request.headers.get('Authorization')[7:]
 
 
    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')
 
 
            if not isAuthorized:
                abort(403)

    headers = {
    "Authorization": f"Bearer {access_token}",
    "Accept": "application/json",
    "Content-Type": "application/json"
    }
   
    try:
        if not request.is_json:
            logging.error("No JSON data in request")
            return jsonify({"error": "No JSON data provided"}), 400
   
        # Parse JSON data
        Json_data_list = request.get_json()
        combined_list = []
        for json_payload in Json_data_list:
            json_data = json_payload
            json_pl_data = json_payload[0][0]
            source_code_str = json_pl_data['SOURCE_CODE']
            doc_type=json_pl_data["document_type"]
            project_id = json_pl_data["project_id"]
            template_type = json_pl_data["template_type"]
            source_dpd = json_pl_data["source_dpd"]
            function_processor = FunctionReplacementProcessor()
            rearranged_json_data = function_processor.process_json_data(json_data)

            data = json.loads(source_code_str)
            if data and isinstance(data, list):
                first_object = data[0]
                nameOfFile = first_object.get("OBJECT_NAME", "")
                obj_type = first_object.get("OBJECT_TYPE", "")
                execution_summary = first_object.get('ST03_TEXT'," ")
            else:
                logging.info("Invalid or empty data.")
            user_id=str(uuid.uuid4())
            source_code = rearranged_json_data
            document_type = doc_type
            project_id = project_id
            template_type = template_type
            source_dpd = source_dpd
            context, system = nameOfFile, ""
            language = json_pl_data['LANGUAGE']
 
            obj_flag=False
            if obj_type=="PROG" or obj_type=="TRAN" or obj_type=="Transaction" or obj_type=="Program" or obj_type=="Report" or obj_type.lower() =="smartform" or obj_type.lower() == "ssfo"or obj_type.lower() == "conv":
                obj_flag=True
 
            if not source_code:
                logging.error("source_code key is missing or empty in the JSON data")
                return jsonify({"error": "source_code key is missing or empty in the JSON data"}), 400
            if not nameOfFile:
                logging.error("object_name key is missing or empty in the JSON data")
                return jsonify({"error": "object_name key is missing or empty in the JSON data"}), 400
            obj_type_new=obj_type.lower()
 
            combined_list.append((str(source_code), user_id, nameOfFile, context, language, system,execution_summary,obj_type_new,obj_flag,'single'))
        return {"data":combined_list,"doc_type":document_type,"project_id":project_id,"template_type":template_type,"headers" :headers,"source_dpd":source_dpd}
 
    except Exception as e:
        logging.error(f"Error in document processing: {str(e)}", exc_info=True)
        return jsonify({
            "error": "An error occurred while processing the document detailed spec.",
            "details": str(e)
        })

@app.route('/get_session_id', methods=['GET'])
def generate_new_session_id():
    data  = str(uuid.uuid4())
    return {"data":data}

@app.route('/get_socket_url', methods=['GET'])
def get_socket_url():
    socket_url = os.getenv('SOCKET_URL')
    if socket_url:
        return jsonify({
            'status': 'success',
            'socketURL': socket_url
        }), 200
    else:
        return jsonify({
            'status': 'error',
            'message': 'SOCKET_URL not set in environment variables'
        }), 404


@app.route('/template_flag', methods=['POST'])
def get_template_flag():

    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)
 
    try:
      access_token = request.headers.get('authorization')[7:]
    except:
      access_token = request.headers.get('Authorization')[7:]

 
    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')
 

            if not isAuthorized:
                abort(403)
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    project_id = request.form.get("project_id")

    
    try:
        temp_df, flag = get_template_flag_count(project_id, headers)
        fs = not temp_df[temp_df['module'] == 'FS RE'].empty
        ts = not temp_df[temp_df['module'] == 'TS RE'].empty

        return jsonify({"flag": flag, "fs": fs, "ts": ts}), 200

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 404
    

@app.route('/download_listpage', methods=['POST'])
def get_download_list():

    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)

    try:
        access_token = request.headers.get('authorization')[7:]
    except:
        access_token = request.headers.get('Authorization')[7:]


    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')


            if not isAuthorized:
                abort(403)
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    user = request.form.get("user")
    project_id = request.form.get("project_id")

    try:

        job_logs = get_jobrun_data(user, project_id, headers)

        # Filter for RE + FS or TS + not Downloaded
        filtered_logs = [
            item for item in job_logs
            if item.get('module_feature_code') == 'RE' and
            item.get('document_type') in ['Functional Specification', 'Technical Specification'] and
            item.get('status_type') != 'Downloaded' and
            item.get('createdBy', '').lower() == user.lower() and
            item.get('project_id') == project_id
        ]

        # Merge FS and TS logs based on SESSION_ID and OBJECT_NAME
        merged = {}

        for item in filtered_logs:
            key = (item.get('session_id'), item.get('object_name'))
            if key not in merged:
                merged[key] = {
                    'SESSION_ID': key[0],
                    'OBJECT_NAME': key[1],
                    'CREATEDAT': item.get('createdAt'),
                    'FS_STATUS': None,
                    'TS_STATUS': None,
                    'FS_LOG': None,
                    'TS_LOG': None,
                    'FS_ID': None,
                    'TS_ID': None
                }

            # Update CREATEDAT if earlier value is None
            if merged[key]['CREATEDAT'] is None:
                merged[key]['CREATEDAT'] = item.get('createdAt')

            doc_type = item.get('document_type')
            if doc_type == 'Functional Specification':
                merged[key]['FS_STATUS'] = item.get('status_type')
                merged[key]['FS_LOG'] = item.get('current_llm_content')
                merged[key]['FS_ID'] = item.get('id')
            elif doc_type == 'Technical Specification':
                merged[key]['TS_STATUS'] = item.get('status_type')
                merged[key]['TS_LOG'] = item.get('current_llm_content')
                merged[key]['TS_ID'] = item.get('id')

        # No need to filter out 'Downloaded' again since we already did that above
        result = list(merged.values())

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Import Azure logic
def extract_account_url(container_uri):
    match = re.search(r'^https://.*?\.net', container_uri)
    if not match:
        raise ValueError("Invalid CONTAINER_URI format.")
    account_url = match.group(0)
    return account_url


def download_and_organize_blobs(thread_id):
    account_url = extract_account_url(CONTAINER_URI)
    client = BlobServiceClient(account_url=account_url, credential=AZURE_STORAGE_ACCOUNT_KEY)
    container_client = client.get_container_client(CONTAINER_NAME)

    blob_list = list(container_client.list_blobs())
    base_folder = Path.cwd() / f"Documents_{thread_id}"
    fs_folder = base_folder / "FS_Documents"
    ts_folder = base_folder / "TS_Documents"
    has_fs_docs = False
    has_ts_docs = False

    for blob in blob_list:
        blob_name = blob.name
        blob_name_lower = blob_name.lower()

        if thread_id.lower() not in blob_name_lower:
            continue

        if not blob_name_lower.endswith(('.docx', '.svg')):
            continue

        filename = os.path.basename(blob_name)

        is_functional = "sap_functional" in filename.lower() or f"fs_diagram_{thread_id.lower()}" in blob_name_lower
        is_technical = "sap_technical" in filename.lower()

        if is_functional:
            fs_folder.mkdir(parents=True, exist_ok=True)
            target_path = fs_folder / filename
            has_fs_docs = True
        elif is_technical:
            ts_folder.mkdir(parents=True, exist_ok=True)
            target_path = ts_folder / filename
            has_ts_docs = True
        else:
            continue

        blob_client = container_client.get_blob_client(blob_name)
        data = blob_client.download_blob().readall()
        with open(target_path, "wb") as f:
            f.write(data)
        blob_client.delete_blob()

    if not (has_fs_docs or has_ts_docs):
        raise FileNotFoundError(f"No matching files found for thread_id: {thread_id}")

    return base_folder


def zip_folder(folder_path):
    zip_path = folder_path.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file in folder_path.rglob("*"):
            if file.is_file():
                zipf.write(file, arcname=file.relative_to(folder_path))
    return zip_path


def process_thread(thread_id):
    print("onside process_thread",thread_id)
    folder = download_and_organize_blobs(thread_id)
    return zip_folder(folder)


# @app.route('/download_folder_all', methods=['POST'])
# def download_folderall():
    
#     if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
#         abort(403)

#     try:
#         access_token = request.headers.get('authorization')[7:]
#     except:
#         access_token = request.headers.get('Authorization')[7:]


#     if 'Referer' in request.headers:
#         referer = request.headers.get('Referer')
#         if 'localhost' not in referer.lower():
#             security_context = xssec.create_security_context(access_token, uaa_service)
#             isAuthorized = security_context.check_local_scope('scope_tsp_user')


#             if not isAuthorized:
#                 abort(403)

#     headers = {
#         "Authorization": f"Bearer {access_token}",
#         "Accept": "application/json",
#         "Content-Type": "application/json"
#     }

#     session = boto3.Session(
#         aws_access_key_id=access_key,
#         aws_secret_access_key=secret_key
#     )
#     s3 = session.resource('s3', verify=False)
#     my_bucket = s3.Bucket(bucket_name)
#     data = request.get_json()

#     # Ensure 'thread_ids' is provided in the JSON payload
#     if not data or 'thread_ids' not in data:
#         return {"error": "Missing 'thread_ids' in request data."}, 400

#     thread_ids = list(data['thread_ids'])
#     project_id = data.get("project_id")

#     document_count = 0

#     zip_buffer = io.BytesIO()
#     with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
#         try:
#             cap_client = CapServiceClient(cap_url)
#             if bucket_name:
#                 for thread in thread_ids:
#                     # Update status via CAP OData
#                     update_jobrun_status(thread,headers)

#                     folder_name = f"Documents_{thread}/"
#                     for obj in my_bucket.objects.filter(Prefix=folder_name):
#                         if obj.key.endswith('/'):
#                             continue

#                         file_stream = io.BytesIO()
#                         s3.Object(bucket_name, obj.key).download_fileobj(file_stream)
#                         file_stream.seek(0)
#                         relative_path = obj.key[len(folder_name):].lstrip('/')
#                         zip_file.writestr(relative_path, file_stream.read())
#                         s3.Object(bucket_name, obj.key).delete()

#                         # Count only .docx files
#                         if obj.key.lower().endswith('.docx'):
#                             document_count += 1

#             elif CONTAINER_NAME:
#                 sas_url = f"{CONTAINER_URI}?{AZURE_STORAGE_ACCOUNT_KEY}"
#                 blob_service_client = BlobServiceClient(account_url=sas_url)
#                 container_client = blob_service_client.get_container_client(CONTAINER_NAME)

#                 blob_list = container_client.list_blobs(name_starts_with=folder_name)

#                 for blob in blob_list:
#                     blob_client = container_client.get_blob_client(blob.name)
#                     download_stream = blob_client.download_blob()
#                     file_data = download_stream.readall()

#                     relative_path = blob.name[len(folder_name):].lstrip('/')
#                     zip_file.writestr(relative_path, file_data)
#                     blob_client.delete_blob()

#                     # Count only .docx files
#                     if blob.name.lower().endswith('.docx'):
#                         document_count += 1

#         except Exception as e:
#             logging.error(f"Error processing files: {e}")
#             raise e

#     zip_buffer.seek(0)

#     if project_id and document_count > 0:
#         cap_client.update_documents_generated(project_id, document_count,headers)

    

#     # --- Cleanup temp folder after all processing ---
#     # temp_dir = Path(tempfile.gettempdir()) / "process_png"
#     # cleanup_temp_folder(temp_dir)

#     return send_file(
#         zip_buffer,
#         mimetype='application/zip',
#         as_attachment=True,
#         download_name=f"Combined_doc.zip"
#     )

@app.route('/download_folder_all', methods=['POST'])
def download_folderall():
    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)

    try:
        access_token = request.headers.get('authorization')[7:]
    except:
        access_token = request.headers.get('Authorization')[7:]

    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')
            if not isAuthorized:
                abort(403)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    session = boto3.Session(
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key
    )
    s3 = session.resource('s3', verify=False)
    my_bucket = s3.Bucket(bucket_name)
    data = request.get_json()

    if not data or 'thread_ids' not in data:
        return {"error": "Missing 'thread_ids' in request data."}, 400

    thread_ids = list(data['thread_ids'])
    project_id = data.get("project_id")
    user_id = data.get("USER_ID")

    document_names = []

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        try:
            cap_client = CapServiceClient(cap_url)
            if bucket_name and gcp_private_key:
                key_json = base64.b64decode(gcp_private_key).decode('utf-8')
                key_path = "temp_key.json"
                with open(key_path, "w") as f:
                    f.write(key_json)

                client = storage.Client.from_service_account_json(key_path)
                gcp_bucket = client.bucket(bucket_name)

                if not gcp_bucket.exists():
                    logging.error(f"Bucket '{bucket_name}' does not exist.")
                    return {"error": "Bucket not found."}, 404
                for thread in thread_ids:
                    # query = f"""update {hanadbschema}.APP_TSP_JOB_LOGS SET STATUS_TYPE = 'Downloaded'
                    # where SESSION_ID = '{thread}' ;"""
                    # update_db(query)
                    folder_name = f"Documents_{thread}/"

                    blobs = list(gcp_bucket.list_blobs(prefix=folder_name))
                    for blob in blobs:
                        if blob.name.endswith('/'):
                            continue
                        file_stream = io.BytesIO()
                        blob.download_to_file(file_stream)
                        file_stream.seek(0)
                        relative_path = blob.name[len(folder_name):].lstrip('/')
                        zip_file.writestr(relative_path, file_stream.read())
                        blob.delete()

                        if obj.key.lower().endswith('.docx'):
                            document_names.append(relative_path)
            elif bucket_name:
                for thread in thread_ids:
                    # update_jobrun_status(thread, headers)
                    folder_name = f"Documents_{thread}/"

                    for obj in my_bucket.objects.filter(Prefix=folder_name):
                        if obj.key.endswith('/'):
                            continue

                        file_stream = io.BytesIO()
                        s3.Object(bucket_name, obj.key).download_fileobj(file_stream)
                        file_stream.seek(0)
                        relative_path = obj.key[len(folder_name):].lstrip('/')
                        zip_file.writestr(relative_path, file_stream.read())
                        s3.Object(bucket_name, obj.key).delete()

                        if obj.key.lower().endswith('.docx'):
                            document_names.append(relative_path)

            elif CONTAINER_NAME:
                for thread_id in thread_ids:
                    # Update status via CAP OData
                    # update_jobrun_status(thread_id, headers)

                    # Process the thread and get the zip path
                    zip_path = process_thread(thread_id)

                    # Read the zip file content
                    with open(zip_path, "rb") as f:
                        zip_data = f.read()

                    # Load zip into memory
                    response_data = io.BytesIO(zip_data)

                    # Add contents to the final zip buffer
                    with zipfile.ZipFile(response_data, 'r') as thread_zip:
                        for file_name in thread_zip.namelist():
                            file_data = thread_zip.read(file_name)
                            zip_file.writestr(file_name, file_data)

                    # Track .docx files for UUID generation
                    docx_files = [name for name in zipfile.ZipFile(zip_path).namelist() if name.lower().endswith('.docx')]
                    document_names.extend(docx_files)


        except Exception as e:
            logging.error(f"Error processing files: {e}")
            raise e

    zip_buffer.seek(0)

    if project_id and document_names:
        document_name_with_UUIDs = {name: str(uuid.uuid4()) for name in document_names}
        Flag = cap_client.insert_doccount_records(project_id, document_name_with_UUIDs, user_id, headers)
        if Flag:
            cap_client.update_documents_generated(project_id, len(document_name_with_UUIDs), headers)

    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f"{folder_name.strip('/')}.zip"
    )
 


@app.route('/status_update', methods=['POST'])
def update_status_to_error():

    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)
 
    try:
      access_token = request.headers.get('authorization')[7:]
    except:
      access_token = request.headers.get('Authorization')[7:]

 
    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')
 

            if not isAuthorized:
                abort(403)
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    user_name = request.form.get("user_name")
    try:
        updated_count = update_inprogress_status_to_error(user_name, headers)
        if updated_count > 0:
            return jsonify({"message": f"Updated {updated_count} record(s)"}), 200
        else:
            return jsonify({"message": "Nothing for update"}), 200
        
    except ValueError as ve:
        return str(ve), 400
    except Exception as e:
        return f"[ERROR] {str(e)}", 500
    
@app.route('/download_status_update', methods=['POST'])
def updated_download_status():
    
    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)
 
    try:
      access_token = request.headers.get('authorization')[7:]
    except:
      access_token = request.headers.get('Authorization')[7:]

 
    if 'Referer' in request.headers:
        referer = request.headers.get('Referer')
        if 'localhost' not in referer.lower():
            security_context = xssec.create_security_context(access_token, uaa_service)
            isAuthorized = security_context.check_local_scope('scope_tsp_user')
 

            if not isAuthorized:
                abort(403)
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    try:
        data = request.get_json()
        ids = data.get("ids")
        updated_count = update_jobrun_status_by_ids(ids, headers)

        if updated_count > 0:
            return jsonify({"message": f"Updated {updated_count} record(s)"}), 200

    except ValueError as ve:
        return str(ve), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500



if __name__ == '__main__':
    ip = "0.0.0.0" # insert LAN address here
    port = int(os.environ.get('PORT', 3000))
    socketio.run(app, host=ip, port=port,debug=False, use_reloader=False,allow_unsafe_werkzeug=True)
    

