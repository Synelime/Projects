from get_values_fromexcel import read_excel, validate_excel
from flask import Flask, request, jsonify, send_file, abort, Response, make_response
from werkzeug.utils import secure_filename
import ast
from azure.storage.blob import BlobServiceClient, BlobClient
import uuid
import zipfile
import os
import traceback
import io
import docx2txt
from cfenv import AppEnv
from sap import xssec
import jwt
import logging
import tempfile
import pathlib
import boto3
from tsp_utilities.objectstore import upload_to_objectstore, download_from_objectstore
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import json

# preview_ts_fs API's
from preview_fs_upload_conversion import conversion_fs_upload_preview
from preview_fs_upload_enhancement import enhancement_fs_upload_preview
from preview_fs_upload_form import form_fs_upload_preview
from preview_fs_upload_interface import interface_fs_upload_preview
from preview_fs_upload_report import create_ts_reports_fs_upload_preview
from preview_fs_upload_workflow import workflow_fs_upload_preview
# upload_ts API's
from preview_conversion import conversion_preview
from preview_enhancement import enhancement_preview
from preview_form import forms_preview
from preview_interface import interface_preview
from preview_report import report_preview
from preview_workflow import workflow_preview

import PyPDF2
from docx import Document
from datetime import datetime
from document_count import *
from report_regenerate import *  
from workflow_regenerate import *
from conversion_regenerate import *
from form_regenerate import *
from enhancement_regenerate import *
from interface_regenerate import * 
import re
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()
from graphviz import Source
from agentic_ricefwtype_classifier import *
from technical_flow_logic_prompt import *
from ricefw_agent import *
from flask_cors import CORS
from web_socket.socketio_instance import socketio
from multiagent_app_dev import *

# Set up logging
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

port = int(os.environ.get('PORT', 5000))

CORS(app)

socketio.init_app(app,cors_allowed_origins="*", async_mode='threading')

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "100 per hour", "50/minute"]
)

# -------------------------------
# Helper: Emit step status update
# -------------------------------
def emit_step_update(session_id, step_key, label, status):
    """
    Broadcasts step update to all connected clients.
    :param step_key: unique key for the step
    :param label: human-readable name of the step
    :param status: pending | in-progress | success | failed
    """
    logger.info(f"emitting step_key: {step_key}, label: {label} and status: {status}")
    socketio.emit(
        f"agentProgressStatus_{session_id}",
        {
            "section": label,
            "sectionStatus": status
        }   
    )
    return socketio

# -------------------------------
# API Route
# -------------------------------

@app.route('/get_socket_url', methods=['GET'])
def get_socket_url():
    socket_url = os.getenv('SOCKET_URL')
    if socket_url:
        # generate unique session id
        session_id = str(uuid.uuid4())
        return jsonify({
            'status': 'success',
            'socketURL': socket_url,
            'session_id': session_id
        }), 200
    else:
        return jsonify({
            'status': 'error',
            'message': 'SOCKET_URL not set in environment variables'
        }), 404
    
@app.before_request
def hide_server_header():
    import werkzeug.serving
    werkzeug.serving.WSGIRequestHandler.server_version = "MySecureServer"
    werkzeug.serving.WSGIRequestHandler.sys_version = ""

env = AppEnv()
uaa_service = env.get_service(label='xsuaa').credentials
    
@app.route('/')
def home():
    return "App is running!"

@app.route('/get_ricefw_name', methods=['POST','GET'])
def get_ricefw_name():
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

            logger.info(isAuthorized)
            if not isAuthorized:
                abort(403)
    try:
        file = request.files['file'] # read excel file
        if not file or file.filename == '':
            return jsonify({"error": "No selected file"}), 400
        # Use io.BytesIO to read the file directly in memory
        file_stream = io.BytesIO(file.read())
        # Get the file extension
        file_extension = os.path.splitext(file.filename)[1].lower() 
        if file_extension not in ['.xlsx', '.xls']:
            return jsonify({"error": "Invalid file type. Please upload an Excel file."}), 400
        excel_dictvalues = read_excel(file_stream)  # Excel file extensions
        #catch validation error separately
        try:
            validate_excel(file_stream)
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 400 
        # Extract the ricefw_name
        ricefw_name = excel_dictvalues.get('. TS Document Title (Mandatory)')
        if ricefw_name is None:
            return jsonify({"error": "Unable to retrieve the RICEFW Name."}), 400 
        logger.info(f"-----------ricefw_name-------------{ricefw_name}")  
        return jsonify({"RICEFW_name": ricefw_name}), 200
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        return jsonify({"error": "An unexpected error occurred. Please try again later."}), 500
    

@app.route('/ts_check_ricefw_exists', methods = ['POST'])
def ts_check_ricefw_exists():
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

            logger.info(isAuthorized)
            if not isAuthorized:
                abort(403)
            
    RICEFW_type = request.form.get('RICEFW_type')
    logger.info(f"-----------RICEFW_type-------------{RICEFW_type}")  
    project_id = request.form.get('project_id')
    logger.info(f"-----------project_id-------------{project_id}")  
    RICEFW_name = request.form.get('RICEFW_name')
    logger.info(f"-----------RICEFW_name-------------{RICEFW_name}")    
    message  = check_ricefw_exists(access_token, project_id, RICEFW_type,RICEFW_name)
    if message:
        return jsonify({'success': 'A document with same RICEFW Name already exists in the drafts for this project, do you want to overwrite it with this one?'}), 200
    else:
        return jsonify({'error': 'RICEFW name does not exist'}), 200

@app.route('/get_draft_list', methods=['POST'])
def get_draft_list():
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

            logger.info(isAuthorized)
            if not isAuthorized:
                abort(403)
    project_id = request.form.get('project_id')
    logger.info(f"-----------project_id-------------{project_id}") 
    data = get_draft_list_fromdb(access_token, project_id)
    # Serialize back without changing key order
    json_data = json.dumps(data, sort_keys=False, indent=2)
    # Return as a proper JSON response
    return Response(json_data, mimetype='application/json')


@app.route('/get_draft_details', methods=['POST'])
def get_draft_details():
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

            logger.info(isAuthorized)
            if not isAuthorized:
                abort(403)
    project_id = request.form.get('project_id')
    logger.info(f"-----------project_id-------------{project_id}")
    RICEFW_type = request.form.get('RICEFW_type')
    logger.info(f"-----------RICEFW_type-------------{RICEFW_type}")
    RICEFW_name = request.form.get('RICEFW_name')
    logger.info(f"-----------RICEFW_name-------------{RICEFW_name}")  
    response = get_draft_details_fromdb(access_token, project_id,RICEFW_type,RICEFW_name)
    # If json_section_contents and form_dictvalues is a string, parse it to dictionary
    data = json.loads(response)
    # Serialize back without changing key order
    json_data = json.dumps(data, sort_keys=False, indent=2)
    # Return as a proper JSON response
    return Response(json_data, mimetype='application/json')


@app.route('/technical_summary', methods=['POST', 'GET'])
def technical_summary():
    file = request.files['fs']
    ricefw_type = request.form.get('RICEFW_type', '').lower()
    
    # Map each RICEFW type to its respective summary function
    TECH_FLOW_GENERATORS = {
        "report": generate_report_technical_summary_from_fs,
        "form": generate_form_technical_summary_from_fs,
        "conversion": generate_conversion_technical_summary_from_fs,
        "enhancement": generate_enhancement_technical_summary_from_fs,
        "interface": generate_interface_technical_summary_from_fs,
        "workflow": generate_workflow_technical_summary_from_fs
    }

    if ricefw_type not in TECH_FLOW_GENERATORS:
        return jsonify({"error": f"Unsupported ricefw_id: '{ricefw_type}'"}), 400

    if 'fs' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    if file.filename == '':
        return jsonify({"error": "Empty filename"}), 400

    try:
        # Save to temporary file for docx2txt to process
        with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as temp_docx:
            temp_docx.write(file.read())
            temp_docx_path = temp_docx.name

        # Extract plain text from the docx file
        extracted_text = docx2txt.process(temp_docx_path)

        # Clean up temp file
        os.remove(temp_docx_path)

        # Call the appropriate function with the extracted text
        generate_summary = TECH_FLOW_GENERATORS[ricefw_type]
        tech_flow_logic = generate_summary(extracted_text)  # Pass plain text, not stream
        logger.info(f"Tech_Flow_Logic:{tech_flow_logic}")
        return jsonify({
            "technical_flow_logic": tech_flow_logic
        }), 200

    except Exception as e:
        return jsonify({"error": f"Failed to process file: {str(e)}"}), 500
    

@app.route('/agentic_ts_fs', methods=['POST'])
def agentic_ts_fs_generation():
    if ('authorization' not in request.headers) and ('Authorization' not in request.headers):
        abort(403)
    try:
        access_token = request.headers.get('authorization')[7:]
    except:
        access_token = request.headers.get('Authorization')[7:]

    try:
        file = request.files.get('file')
        fs = request.files.get('fs') 

        # Save excel file temporarily
        temp_file_path = None  # default None
        if file and file.filename != '':
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
            temp_file.write(file.read())
            temp_file_path = temp_file.name
            temp_file.close()

        # fs file
        temp_fs_path = None  # default None
        if fs and fs.filename != '':
            temp_fs = tempfile.NamedTemporaryFile(delete=False, suffix='.docx')
            temp_fs.write(fs.read())
            temp_fs_path = temp_fs.name
            temp_fs.close()

        try:
            # Extract form data
            user_choice = request.form.get('RICEFW_type')
            ricefw_name = request.form.get('RICEFW_name')
            ricefw_id = request.form.get('RICEFW_id')
            technical_flow_logic = request.form.get('technical_flow_logic')
            configuration = request.form.get('configuration')
            project_id = request.form.get('project_id')
            author = request.form.get('userName') or 'User'
            session_id = request.form.get('session_id')

            
            # Run the document generation workflow
            result = run_document_generation(
                file=temp_file_path,
                fs=temp_fs_path,
                user_choice=user_choice,
                technical_flow_logic = technical_flow_logic,
                configuration = configuration,
                ricefw_name = ricefw_name,
                ricefw_id = ricefw_id,
                project_id=project_id,
                token = access_token,
                author=author,
                session_id = session_id
            )

        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
            if temp_fs_path and os.path.exists(temp_fs_path):
                os.unlink(temp_fs_path)
                    
         # --- Handle output---
        if "preview" in result:
            print(result["preview"])
            #return result["preview"]
            # Convert form_data to a JSON string without sorting keys
            json_data = json.dumps(result["preview"], sort_keys=False, indent=2)
            return Response(json_data, mimetype='application/json')

        else:
            return jsonify({
                "success": False,
                "error": result.get("error", "Unknown error"),
                "failed_steps": result.get("failed_steps", [])
            }), 500

    except Exception as e:
        logger.error("Error in /agentic_ts_fs: %s", str(e))
        return jsonify({"error": f"Error in processing Technical Specification"}), 500
    

@app.route('/preview_ts_fs', methods=['POST', 'GET'])
def ts_preview_fs():
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

            logger.info("Authorization: ",isAuthorized)
            if not isAuthorized:
                abort(403)
    try:
        if request.method == 'POST' or request.method == 'GET':
            try:
                file = request.files['file'] # read excel file
                fs = request.files['fs'] # read fs word file
                if not file or file.filename == '':
                    return jsonify({"error": "No selected file"}), 400
                if not fs or fs.filename == '':
                    return jsonify({"error": "No selected file"}), 400        
                # Use io.BytesIO to read the file directly in memory
                file_stream = io.BytesIO(file.read())
                #fs_file_stream = io.BytesIO(file.read()) 
                                
                fs_filename = secure_filename(fs.filename)
                temp_dir = tempfile.gettempdir()  # Gets the system temp directory
                temp_path = os.path.join(temp_dir, fs_filename)
                fs.save(temp_path)

                # Extract text from the .docx file using docx2txt
                fs_text = docx2txt.process(temp_path)
                
                # Remove the temporary file
                os.remove(temp_path)             
                # Get the file extension
                file_extension = os.path.splitext(file.filename)[1].lower() 
                fs_file_extension = os.path.splitext(fs.filename)[1].lower()             
                # Get the input feature
                user_choice = request.form.get('RICEFW_type')
                RICEFW_name = request.form.get('RICEFW_name')
                project_id = request.form.get('project_id')
                author = request.form.get('userName')
                if author==None:
                    author = 'User'
                logger.info(f"-----------RICEFW_type-------------{user_choice}")  
                logger.info(f"-----------project_id------------- {project_id}")
                logger.info(f"-----------RICEFW_name------------- {RICEFW_name}")
                uuid_value=str(uuid.uuid4())
                try:
                    template_link, template_type  = get_template_link(project_id, user_choice, access_token, module = "TS")
                    logger.info(f"-----------template_link------------- {template_link}")
                    logger.info(f"-----------template_type------------- {template_type}")
                except Exception as db_error:
                    # Handle database exceptions separately
                    traceback.print_exc()
                    return jsonify({"error": "Database error", "details": str(db_error)}), 500
                if template_link is None:
                    return jsonify({'error': 'Client/Standard template is not found for the specified project'}), 404
            
                if ((file_extension in ['.xlsx', '.xls']) and (fs_file_extension in ['.docx'])):
                    excel_dictvalues = read_excel(file_stream)  # Excel file extensions
                    validate_excel(file_stream)

                    # Perform corresponding action based on the user choice
                    if user_choice.lower() == "report":
                        preview_report_data, INPUT_TOKEN_COUNT, OUTPUT_TOKEN_COUNT = create_ts_reports_fs_upload_preview(excel_dictvalues, fs_text)
                        # insert meta data into the HANADB table
                        upsert_logdata(access_token, project_id, user_choice,uuid_value,RICEFW_name,author,INPUT_TOKEN_COUNT, OUTPUT_TOKEN_COUNT,excel_dictvalues, preview_report_data,previous_data = {},status_type = "Draft")
                        
                        # Convert form_data to a JSON string without sorting keys
                        json_data = json.dumps(preview_report_data, sort_keys=False, indent=2)
                        return Response(json_data, mimetype='application/json')
                    
                    elif user_choice.lower() == "workflow":
                        preview_workflow_data, INPUT_TOKEN_COUNT, OUTPUT_TOKEN_COUNT = workflow_fs_upload_preview(excel_dictvalues, fs_text)
                        # insert meta data into the HANADB table
                        upsert_logdata(access_token, project_id, user_choice,uuid_value,RICEFW_name,author,INPUT_TOKEN_COUNT, OUTPUT_TOKEN_COUNT,excel_dictvalues, preview_workflow_data,previous_data = {},status_type = "Draft")
                        
                        # Convert form_data to a JSON string without sorting keys
                        json_data = json.dumps(preview_workflow_data, sort_keys=False, indent=2)
                        return Response(json_data, mimetype='application/json')
                    
                    elif user_choice.lower() == "conversion":
                        preview_conversion_data, INPUT_TOKEN_COUNT, OUTPUT_TOKEN_COUNT = conversion_fs_upload_preview(excel_dictvalues, fs_text)
                        # insert meta data into the HANADB table
                        upsert_logdata(access_token,project_id, user_choice,uuid_value,RICEFW_name,author,INPUT_TOKEN_COUNT, OUTPUT_TOKEN_COUNT,excel_dictvalues, preview_conversion_data,previous_data = {},status_type = "Draft")
                        
                        # Convert form_data to a JSON string without sorting keys
                        json_data = json.dumps(preview_conversion_data, sort_keys=False, indent=2)
                        return Response(json_data, mimetype='application/json')
                    
                    elif user_choice.lower() == "enhancement":
                        preview_enhancement_data, INPUT_TOKEN_COUNT, OUTPUT_TOKEN_COUNT = enhancement_fs_upload_preview(excel_dictvalues, fs_text)
                        # insert meta data into the HANADB table
                        upsert_logdata(access_token,project_id, user_choice,uuid_value,RICEFW_name,author,INPUT_TOKEN_COUNT, OUTPUT_TOKEN_COUNT,excel_dictvalues, preview_enhancement_data,previous_data = {},status_type = "Draft")
                        
                        # Convert form_data to a JSON string without sorting keys
                        json_data = json.dumps(preview_enhancement_data, sort_keys=False, indent=2)
                        return Response(json_data, mimetype='application/json')
                    
                    elif user_choice.lower() == "form":
                        preview_form_data, INPUT_TOKEN_COUNT, OUTPUT_TOKEN_COUNT = form_fs_upload_preview(excel_dictvalues, fs_text)
                        # insert meta data into the HANADB table
                        upsert_logdata(access_token,project_id, user_choice,uuid_value,RICEFW_name,author,INPUT_TOKEN_COUNT, OUTPUT_TOKEN_COUNT,excel_dictvalues, preview_form_data,previous_data = {},status_type = "Draft")
                        
                        # Convert form_data to a JSON string without sorting keys
                        json_data = json.dumps(preview_form_data, sort_keys=False, indent=2)
                        return Response(json_data, mimetype='application/json')
                    
                    elif user_choice.lower() == "interface":
                        preview_interface_data, INPUT_TOKEN_COUNT, OUTPUT_TOKEN_COUNT = interface_fs_upload_preview(excel_dictvalues, fs_text)
                        # insert meta data into the HANADB table
                        upsert_logdata(access_token,project_id, user_choice,uuid_value,RICEFW_name,author,INPUT_TOKEN_COUNT, OUTPUT_TOKEN_COUNT,excel_dictvalues, preview_interface_data,previous_data = {},status_type = "Draft")
                        
                        # Convert form_data to a JSON string without sorting keys
                        json_data = json.dumps(preview_interface_data, sort_keys=False, indent=2)
                        return Response(json_data, mimetype='application/json')
                                
                else:
                    return jsonify({"error": "Unsupported file type"}), 400
            
            except Exception as e:
                logging.error(f"Error processing file: {traceback.format_exc()}")
                return jsonify({"error": f"Error in processing Technical Specification"}), 500
                      
    except Exception as e:
        # Log detailed exception (e.g., traceback) for debugging
        logger.info(f"Error: {traceback.format_exc()}")
        logging.error(f"Unexpected error: {traceback.format_exc()}")
        return jsonify({"Error": "An unexpected error occurred. Please try again later."}), 500


@app.route('/download_svg', methods=['POST'])
def download_svg():
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

            logger.info("Authorization: ",isAuthorized)
            if not isAuthorized:
                abort(403)
    project_id = request.form.get("project_id")
    ricefw_name = request.form.get("RICEFW_name")
    ricefw_type = request.form.get('RICEFW_type')
    section_name = request.form.get("section_name")
    logger.info(f"-----------project_id-------------{project_id}")  
    logger.info(f"-----------RICEFW_name-------------{ricefw_name}")  
    logger.info(f"-----------RICEFW_type-------------{ricefw_type}")  
    logger.info(f"-----------section_name-------------{section_name}")  

    #if ricefw_type.lower() == 'interface':
        #flowdiagram_type = request.form.get('flowdiagram_type')

    if not project_id or not ricefw_name or not ricefw_type:
        return jsonify({"error": "project_id and ricefw_name and ricefw_type are required"}), 400
    
    dot_code = fetch_dotcode_from_db(access_token, project_id, ricefw_name, ricefw_type, section_name)
    logger.info('---------fetched dot_code-----------')
    # if not dot_code:
    #     return {"error": "Diagram not found"}, 404
    
    na_values = ["n/a","na","n.a"]
    if not dot_code or dot_code.lower() in na_values:
        return jsonify({"error": "Could not generate the image for NA input"}), 404

    svg_file_path = None
    try:
        # Create a dot file with dot code
        with tempfile.NamedTemporaryFile(delete=False, suffix=".dot") as tmp_file:
            tmp_file.write(dot_code.encode('utf-8'))
            tmp_file_path = tmp_file.name

        # render dot file into SVG format
        graph = Source.from_file(tmp_file_path)
        svg_file_path = tmp_file_path + '.svg'
        graph.render(filename=tmp_file_path, format='svg', cleanup=True)

        # Ensure file is closed before access
        if not os.path.exists(svg_file_path):
            return {"error": "SVG generation failed"}, 500

        # Send file as downloadable response
        response = make_response(send_file(svg_file_path, as_attachment=True, download_name=f"{ricefw_name}_diagram.svg"))
        response.headers['Content-Type'] = 'image/svg+xml'
        return response

    finally:
        # Clean up all temp files
        if svg_file_path and os.path.exists(svg_file_path):
            try:
                os.remove(svg_file_path)
            except PermissionError:
                pass  # In case file is still locked, skip
        if 'tmp_file_path' in locals() and os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)


def read_pdf_content(file):
    """Read content from PDF file"""
    try:
        pdf_reader = PyPDF2.PdfReader(file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text()
        return text
    except Exception as e:
        logger.error(f"Error reading PDF: {str(e)}")
        return None

def read_docx_content(file):
    """Read content from DOCX file"""
    try:
        doc = Document(file)
        text = ""
        for paragraph in doc.paragraphs:
            text += paragraph.text + "\n"
        return text
    except Exception as e:
        logger.error(f"Error reading DOCX: {str(e)}")
        return None
    

@app.route('/regenerate', methods=['POST', 'GET'])
def ts_regenerate_section():
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
        if request.method == 'POST' or request.method == 'GET':
            try:
                project_id = request.form.get("project_id")
                user_choice = request.form.get("RICEFW_type")
                logger.info(f"-----------RICEFW_type-------------{user_choice}")  
                ricefw_name = request.form.get("RICEFW_name")
                logger.info(f"-----------RICEFW_name-------------{ricefw_name}") 

                # json_data = request.form.get("json_section_contents") #output from orginal responce
                section_name = request.form.get("section_name")
                logger.info(f"-----------section_name-------------{section_name}") 
                user_feedback = request.form.get("user_feedback")
                logger.info(f"-----------user_feedback-------------{user_feedback}") 
                reference_sections = request.form.get('reference_sections')   
                # Convert string to actual list if needed
                if isinstance(reference_sections, str):
                    reference_sections = ast.literal_eval(reference_sections)
                logger.info(f"-----------reference_sections-------------{reference_sections}")

                # extracting llm content and raw input data
                current_llm_content, previous_llm_content, dictvalues = get_data_fromdb(access_token, project_id, ricefw_name, user_choice)
                
                # convert json string to dictionary
                json_data = json.loads(current_llm_content)

                # Handle optional file content
                file_content = None
                if 'additional_file' in request.files:
                    file = request.files['additional_file']
                    if file and file.filename:
                        try:
                            # Create a temporary file to store the uploaded file
                            temp_file = tempfile.NamedTemporaryFile(delete=False)
                            temp_file_path = temp_file.name
                            temp_file.close()  # Close the file handle
                            
                            # Save the uploaded file
                            file.save(temp_file_path)
                            file_extension = os.path.splitext(file.filename)[1].lower()
                            
                            if file_extension == '.pdf':
                                file_content = read_pdf_content(temp_file_path)
                            elif file_extension == '.docx':
                                file_content = read_docx_content(temp_file_path)
                            else:
                                return jsonify({"error": "Unsupported file type. Only PDF and DOCX files are allowed."}), 400
                        except Exception as e:
                            logger.error(f"Error processing file: {str(e)}")
                            return jsonify({"error": f"Error processing file: {str(e)}"}), 500
                        finally:
                            # Clean up the temporary file
                            if temp_file_path and os.path.exists(temp_file_path):
                                try:
                                    os.unlink(temp_file_path)
                                except Exception as e:
                                    logger.warning(f"Could not delete temporary file {temp_file_path}: {str(e)}")

                # Extract 'content' as a list of dictionaries
                content = json_data.get('content', {})
                
                # Process reference sections if provided (exact matching)
                reference_sections_dict = {}
                if reference_sections:
                    for ref_name in reference_sections:
                        # Extract the reference section data in the same way as section data
                        reference_data = next((item["value"] for item in content if item.get("key") == ref_name), '{}')  # Try to find the reference section
                        if reference_data != '{}':  # If the reference section exists
                            reference_sections_dict[ref_name] = reference_data
                            logger.info(f"Found reference section - Key: {ref_name}")
                        else:
                            logger.info(f"Reference section '{ref_name}' not found.")

                if user_choice.lower() == "report":
                    data = regenerate_and_update_section_report(access_token, project_id,ricefw_name,user_choice,section_name,user_feedback,
                        json_data, file_content, reference_sections=reference_sections_dict if reference_sections_dict else None
                    )
                elif user_choice.lower() == 'workflow':
                    data = regenerate_and_update_section_workflow(access_token,project_id,ricefw_name,user_choice,section_name,user_feedback,
                        json_data, file_content, reference_sections=reference_sections_dict if reference_sections_dict else None
                    )
                elif user_choice.lower() == 'conversion':
                    data = regenerate_and_update_section_conversion(access_token,project_id,ricefw_name,user_choice,section_name,user_feedback,
                        json_data, file_content, reference_sections=reference_sections_dict if reference_sections_dict else None
                    )
                elif user_choice.lower() == 'form':
                    data = regenerate_and_update_section_form(access_token,project_id,ricefw_name,user_choice,section_name,user_feedback,
                        json_data, file_content, reference_sections=reference_sections_dict if reference_sections_dict else None
                    )
                elif user_choice.lower() == 'enhancement':
                    data = regenerate_and_update_section_enhancement(access_token, project_id,ricefw_name,user_choice,section_name,user_feedback,
                        json_data, file_content, reference_sections=reference_sections_dict if reference_sections_dict else None
                    )
                elif user_choice.lower() == 'interface':
                    data = regenerate_and_update_section_interface(access_token, project_id,ricefw_name,user_choice,section_name,user_feedback,
                        json_data, file_content, reference_sections=reference_sections_dict if reference_sections_dict else None
                    )

                # Convert form_data to a JSON string without sorting keys
                json_data = json.dumps(data, sort_keys=False, indent=2)
                return Response(json_data, mimetype='application/json')

            except Exception as e:
                logger.error(f"Error in regenerate endpoint: {str(e)}")
                return jsonify({"error": "An unexpected error occurred during regeneration"}), 500
            
    except Exception as e:
        # Log detailed exception (e.g., traceback) for debugging
        logger.info(f"Error: {traceback.format_exc()}")
        logging.error(f"Unexpected error: {traceback.format_exc()}")
        return jsonify({"Error": "An unexpected error occurred. Please try again later."}), 500


@app.route('/manual_edit', methods=['POST', 'GET'])
def ts_manual_edit():
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
        if request.method == 'POST' or request.method == 'GET':
            try:
                project_id = request.form.get("project_id")
                user_choice = request.form.get("RICEFW_type")
                ricefw_name = request.form.get("RICEFW_name")
                section_name = request.form.get("section_name")
                edited_content = request.form.get('edited_content')
                edited_content = edited_content.encode('utf-8').decode('unicode_escape')
                #edited_content = re.sub(r'[\x00-\x1F]+', '', edited_content)
                logger.info(f"-----------edited_content-------------{edited_content}")
                dependent_sections = request.form.get('dependent_sections') 
                logger.info(f"-----------dependent_sections-------------{dependent_sections}")

                if not section_name or not edited_content:
                    return jsonify({"error": "Both 'section_name' and 'edited content' are required"}), 400

                # extracting llm content and raw input data
                current_llm_content, previous_llm_content, dictvalues = get_data_fromdb(access_token, project_id, ricefw_name, user_choice)

                if user_choice.lower() == "report":
                    data = manual_edit_report(access_token, section_name, edited_content, dependent_sections, current_llm_content, previous_llm_content, dictvalues, project_id, ricefw_name, user_choice)
                elif user_choice.lower() == "workflow":
                    data = manual_edit_workflow(access_token, section_name, edited_content, dependent_sections, current_llm_content, previous_llm_content, dictvalues, project_id, ricefw_name, user_choice)
                elif user_choice.lower() == "form":
                    data = manual_edit_form(access_token, section_name, edited_content, dependent_sections, current_llm_content, previous_llm_content, dictvalues, project_id, ricefw_name, user_choice)
                elif user_choice.lower() == "enhancement":
                    data = manual_edit_enhancement(access_token, section_name, edited_content, dependent_sections, current_llm_content, previous_llm_content, dictvalues, project_id, ricefw_name, user_choice)
                elif user_choice.lower() == "interface":
                    data = manual_edit_interface(access_token, section_name, edited_content, dependent_sections, current_llm_content, previous_llm_content, dictvalues, project_id, ricefw_name, user_choice)
                elif user_choice.lower() == "conversion":
                    data = manual_edit_conversion(access_token, section_name, edited_content, dependent_sections, current_llm_content, previous_llm_content, dictvalues, project_id, ricefw_name, user_choice)

                # Convert form_data to a JSON string without sorting keys
                json_data = json.dumps(data, sort_keys=False, indent=2)
                return Response(json_data, mimetype='application/json')
                    
            except Exception as e:
                logger.error(f"Error in regenerate endpoint: {str(e)}")
                return jsonify({"error": "An unexpected error occurred during regeneration"}), 500
    
    except Exception as e:
        # Log detailed exception (e.g., traceback) for debugging
        logger.info(f"Error: {traceback.format_exc()}")
        logging.error(f"Unexpected error: {traceback.format_exc()}")
        return jsonify({"Error": "An unexpected error occurred. Please try again later."}), 500


@app.route('/ts_undo', methods=['POST'])
def fs_undo():
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
        if request.method == 'POST' or request.method == 'GET':
            try:
                user_choice = request.form.get('RICEFW_type')
                logger.info(f"-----------RICEFW_type-------------{user_choice}")
                RICEFW_name = request.form.get('RICEFW_name')
                logger.info(f"-----------RICEFW_name-------------{RICEFW_name}")  
                project_id = request.form.get('project_id')
                logger.info(f"-----------project_id-------------{project_id}")
                section_name = request.form.get('section_name')
                logger.info(f"-----------section_name-------------{section_name}")

                if not section_name:
                    return jsonify({"error": "'section_name' is required"}), 400

                # undo specific section
                data = undo_section_update_in_db(access_token, project_id, RICEFW_name, user_choice, section_name)
                # Convert form_data to a JSON string without sorting keys
                json_data = json.dumps(data, sort_keys=False, indent=2)
                return Response(json_data, mimetype='application/json')
                    
            except Exception as e:
                logger.error(f"Error in regenerate endpoint: {str(e)}")
                return jsonify({"error": "An unexpected error occurred during regeneration"}), 500
    except Exception as e:
        # Log detailed exception (e.g., traceback) for debugging
        logger.info(f"Error: {traceback.format_exc()}")
        logging.error(f"Unexpected error: {traceback.format_exc()}")
        return jsonify({"Error": "An unexpected error occurred. Please try again later."}), 500
    
@app.route('/preview_download_ts', methods=['POST'])
def preview_get_word_document():
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
        if request.method == 'POST' or request.method == 'GET':
            try:
                user_choice = request.form.get('RICEFW_type')
                logger.info(f"-----------RICEFW_type-------------{user_choice}")
                RICEFW_name = request.form.get('RICEFW_name')
                logger.info(f"-----------RICEFW_name-------------{RICEFW_name}") 
                project_id = request.form.get('project_id')
                logger.info(f"-----------project_id-------------{project_id}")
                author = request.form.get('userName')
                if author == None:
                    author = "system"
                try:
                    template_link, template_type = get_template_link(project_id, user_choice, access_token, module="TS")
                    logger.info(f"-----------template_link-------------{template_link}")
                except Exception as db_error:
                    # Handle database exceptions separately
                    traceback.print_exc()
                    return jsonify({"error": "Database error", "details": str(db_error)}), 500
            
                if (template_type == "Client"):
                    # function to map the client and TFS headings
                    mapping_dict = get_mapping_headings(access_token, project_id, user_choice, module = "TS") 
                    mapping_dict = {k.lstrip(". ").strip(): v.lstrip(". ").strip() for k, v in mapping_dict.items() if k and v}             
                else:
                    mapping_dict = None             
                logger.info(f"-----------mapping_dict-------------{mapping_dict}")

                # extracting llm content 
                current_llm_content, raw_input_content, session_id = get_content_sessionid_fromdb(access_token, project_id, RICEFW_name, user_choice)
                logger.info("---------extracted current llm content and raw input content-----")
                # convert json string to dictionary
                current_json_data = json.loads(current_llm_content)
                
                #print('------json_section_contents-----',json_section_contents)
                if user_choice.lower() == "report":
                    word_local_path = generate_word_document_report(access_token, current_json_data, raw_input_content, user_choice, author, project_id,template_type, mapping_dict, session_id, module = "TS")
                elif user_choice.lower() == "workflow":
                    word_local_path = generate_word_document_workflow(access_token, current_json_data, raw_input_content, user_choice, author, project_id,template_type, mapping_dict, session_id, module = "TS")
                elif user_choice.lower() == "form":
                    word_local_path = generate_word_document_form(access_token, current_json_data, raw_input_content, user_choice, author, project_id,template_type, mapping_dict, session_id, module = "TS")
                elif user_choice.lower() == "enhancement":
                    word_local_path = generate_word_document_enhancement(access_token, current_json_data, raw_input_content, user_choice, author, project_id,template_type, mapping_dict, session_id, module = "TS")
                elif user_choice.lower() == "interface":
                    word_local_path = generate_word_document_interface(access_token, current_json_data, raw_input_content, user_choice, author, project_id,template_type, mapping_dict, session_id, module = "TS")
                elif user_choice.lower() == "conversion":
                    word_local_path = generate_word_document_conversion(access_token, current_json_data, raw_input_content, user_choice, author, project_id,template_type, mapping_dict, session_id, module = "TS")
                
                output_word_filename  = os.path.basename(word_local_path)

                # Extract 'content' as a list of dictionaries
                content = current_json_data.get('content', {})
                # extract dot code from process flow diagram dict
                pfd_dotcode = next((item["value"] for item in content if item.get("key") == 'Technical Flow Diagram'), '{}')
                svg_local_path = create_diagram_svg(pfd_dotcode)
                svg_filename = f"fs_diagram_{session_id}.svg"

                #Create in-memory zip buffer
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    # Add Word file
                    if os.path.exists(word_local_path):
                        zipf.write(word_local_path, arcname=os.path.basename(word_local_path))
                    else:
                        raise FileNotFoundError(f"Word file missing: {word_local_path}")
                
                    # Add SVG file
                    if svg_local_path and os.path.exists(svg_local_path):
                        zipf.write(svg_local_path, arcname=svg_filename)
                    else:
                        logger.info(f"SVG file missing: {svg_local_path}")
                zip_buffer.seek(0)

                # Clean up local SVG file
                if svg_local_path and os.path.exists(svg_local_path):
                    os.remove(svg_local_path)
                    logger.info(f"Deleted temp SVG file: {svg_local_path}")

                # Clean up local Word file
                if os.path.exists(word_local_path):
                    os.remove(word_local_path)
                    logger.info(f"Deleted temp Word file: {word_local_path}")

                # update document count in HANADB table
                insert_doccount(access_token, project_id, session_id, output_word_filename, author)
                update_doccount(access_token, project_id)

                # once the document is downloaded, delete the current, previous and raw data and update the status type to be "downloaded"
                delete_llmcontent_fromdb(access_token, project_id, RICEFW_name, user_choice)
                # Return the ZIP to Angular UI
                return send_file(
                    zip_buffer,
                    mimetype='application/zip',
                    as_attachment=True,
                    download_name=f'TS_{user_choice}_{session_id}.zip'
                )

            except Exception as e:
                return jsonify({"error": f"Failed to download file"}), 500
    
    except Exception as e:
        # Log detailed exception (e.g., traceback) for debugging
        logger.info(f"Error: {traceback.format_exc()}")
        logging.error(f"Unexpected error: {traceback.format_exc()}")
        return jsonify({"Error": "An unexpected error occurred. Please try again later."}), 500
    

@app.route('/upload_ts', methods=['POST', 'GET'])
def ts_interface():
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

            logger.info("Authorization: ",isAuthorized)
            if not isAuthorized:
                abort(403)
    try:
        if request.method == 'POST' or request.method == 'GET':
            try:
                file = request.files['file']
                logger.info('-----------file-------------', file)
                if not file or file.filename == '':
                    return jsonify({"error": "No selected file"}), 400        
                # Use io.BytesIO to read the file directly in memory
                file_stream = io.BytesIO(file.read())              
                # Get the file extension
                file_extension = os.path.splitext(file.filename)[1].lower()              
                # Get the input feature
                user_choice = request.form.get('RICEFW_type')
                project_id = request.form.get('project_id')
                author = request.form.get('userName')
                if author==None:
                    author = 'User'
                logger.info(f'-----------RICEFW_type-------------{user_choice}')  

                uuid_value=str(uuid.uuid4())
                logger.info(f'-------uuid_value---------{uuid_value}')

                # Get current timestamp
                current_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.') + f'{datetime.now().microsecond:06d}'
                try:
                    template_link, template_type = get_template_link(project_id, user_choice, access_token, module="TS")
                    logger.info(f'-----------template_link-------------{template_link}')
                except Exception as db_error:
                    # Handle database exceptions separately
                    traceback.logger.info_exc()
                    return jsonify({"error": "Database error", "details": str(db_error)}), 500
                if template_link is None:
                    return jsonify({'error': 'Client template is not found for the specified project'}), 404
                if (template_type.lower() == "client"):
                    mapping_dict = get_mapping_headings(access_token, project_id, user_choice, module = "TS")  
                    mapping_dict = {k: v for k, v in mapping_dict.items() if k and v}             
                else:
                    mapping_dict = None             
                logger.info(f'-------mapping_dict-----------------{mapping_dict}')
                if file_extension in ['.xlsx', '.xls']:
                    row_data = {}
                    RICFEW_name = None
                    current_llm_content = {}
                    INPUT_TOKEN_COUNT = 0
                    OUTPUT_TOKEN_COUNT = 0
                    formated_data = {}
                    excel_dictvalues = read_excel(file_stream)
                    validate_excel(file_stream)

                    # ---- Extract RICFEW_name ----
                    try:
                        import pandas as pd
                        file_stream.seek(0)
                        df = pd.read_excel(file_stream)  # Read the first sheet (no sheet name specified)
                        df.columns = df.columns.str.strip()

                        section_col = 'Section in TS'
                        column_name = 'Technical Input Required'
                        row_label = '1. TS Document Title (Mandatory)'

                        # Strip and convert column values to string for comparison
                        df[section_col] = df[section_col].astype(str).str.strip()

                        # Find the matching row
                        match = df[df[section_col] == row_label]
                        if not match.empty:
                            RICFEW_name = match.iloc[0][column_name]
                            logger.info(f'RICFEW_name extracted: {RICFEW_name}')
                            logger.info(f'RICFEW_name extracted: {RICFEW_name}')
                        else:
                            logger.warning(f"No match found for '{row_label}' in '{section_col}' column.")
                            logger.info("Available 'Section in TS' values:")
                            logger.info(df[section_col].dropna().tolist())

                    except Exception as e:
                        logger.warning(f'Failed to extract RICFEW_name: {str(e)}')

                    # ---- Generate content from first and third columns ----
                    try:
                        content_data = {}
                        # Ensure that the file has at least 3 columns
                        if df.shape[1] >= 3:
                            for index, row in df.iterrows():
                                key = row[0]  # First column as key
                                value = row[2]  # Third column as value
                                content_data[key] = value
                            row_data = content_data  # Directly assign the content data to row_data
                        else:
                            logger.warning("The Excel file doesn't have enough columns to generate the required content.")
                    except Exception as e:
                        logger.warning(f'Failed to extract content data: {str(e)}')

                    # Proceed with document generation based on user_choice (using preview functions for consistent data)
                    if user_choice.lower() == "interface":
                        # interface_preview returns: preview, title, ricefwid, current_date, flowchart_name, svg_name, flowchart_abap_name, svg_abap_name, output_blob_name, uuid_value, INPUT_TOKEN_COUNT, OUTPUT_TOKEN_COUNT, formatted_data
                        generated_contents, heading, ricefw_id, date, flowdiagram, flowsvg, abapdiagram, abapsvg, generated_filename, _, INPUT_TOKEN_COUNT, OUTPUT_TOKEN_COUNT, formated_data = interface_preview(excel_dictvalues, uuid_value, author, template_link, template_type, mapping_dict, project_id, user_choice)
                        session_id = None
                    elif user_choice.lower() == "enhancement":
                        generated_contents, heading, ricefw_id, date, flowdiagram, flowsvg, generated_filename, INPUT_TOKEN_COUNT, OUTPUT_TOKEN_COUNT, formated_data = enhancement_preview(excel_dictvalues, uuid_value, author, template_link, template_type, mapping_dict, project_id, user_choice)
                        # Set default values for missing fields
                        abapdiagram, abapsvg, session_id = None, None, None
                    elif user_choice.lower() == "report":
                        generated_contents, heading, ricefw_id, date, flowdiagram, flowsvg, generated_filename, INPUT_TOKEN_COUNT, OUTPUT_TOKEN_COUNT, formated_data = report_preview(excel_dictvalues, uuid_value, author, template_link, template_type, mapping_dict, project_id, user_choice)
                        # Set default values for missing fields
                        abapdiagram, abapsvg, session_id = None, None, None
                    elif user_choice.lower() == "conversion":
                        generated_contents, heading, ricefw_id, date, flowdiagram, flowsvg, generated_filename, INPUT_TOKEN_COUNT, OUTPUT_TOKEN_COUNT, formated_data = conversion_preview(excel_dictvalues, uuid_value, author, template_link, template_type, mapping_dict, project_id, user_choice)
                        # Set default values for missing fields
                        abapdiagram, abapsvg, session_id = None, None, None
                    elif user_choice.lower() == "form":
                        generated_contents, heading, ricefw_id, date, flowdiagram, flowsvg, generated_filename, session_id, INPUT_TOKEN_COUNT, OUTPUT_TOKEN_COUNT, formated_data = forms_preview(excel_dictvalues, uuid_value, author, template_link, template_type, mapping_dict, project_id, user_choice)
                        # Set default values for missing fields
                        abapdiagram, abapsvg = None, None
                    else:
                        generated_contents, heading, ricefw_id, date, flowdiagram, flowsvg, generated_filename, INPUT_TOKEN_COUNT, OUTPUT_TOKEN_COUNT, formated_data = workflow_preview(excel_dictvalues, uuid_value, author, template_link, template_type, mapping_dict, project_id, user_choice)
                        # Set default values for missing fields
                        abapdiagram, abapsvg, session_id = None, None, None

                    insert_doccount(access_token, project_id, uuid_value, generated_filename, author)
                    update_doccount(access_token, project_id)

                    # Return consistent response structure like preview_ts API
                    response_data = {
                        'content': generated_contents,
                        'heading': heading,
                        'ricefw_id': ricefw_id,
                        'date': date,
                        'author': author,
                        'project_id': project_id,
                        'template_type': template_type,
                        'RICEFW_type': user_choice,
                        'flowdiagram': flowdiagram,
                        'flowdiagram_svg': flowsvg,
                        'filename': generated_filename
                    }
                    
                    # Add type-specific fields
                    if user_choice.lower() == "interface":
                        response_data['abap_diagram'] = abapdiagram
                        response_data['abap_svg'] = abapsvg
                    elif user_choice.lower() == "form":
                        response_data['session_id'] = session_id
                    
                    return jsonify(response_data)
                else:
                    return jsonify({"error": "Unsupported file type"}), 400

            except Exception as e:
                logging.error(f"Error processing file: {traceback.format_exc()}")
                return jsonify({"error": "Error in processing Technical Specification"}), 500

    except Exception as e:
        logger.info(f"Error: {traceback.format_exc()}")
        logging.error(f"Unexpected error: {traceback.format_exc()}")
        return jsonify({"Error": "An unexpected error occurred. Please try again later."}), 500


@app.route('/download_ts', methods=['POST'])
def get_word_document():
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

            logger.info(isAuthorized)
            if not isAuthorized:
                abort(403)
    try:
        # Attempt to get JSON data from the request
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON payload"}), 400
        # Get query parameters from the URL
        filename = data.get('filename')
        RICEFW_type = data.get('RICEFW_type')
        
        # Check if essential query parameters are missing
        if not RICEFW_type or not filename:
            return jsonify({"error": "Missing 'RICEFW_type' or 'filename' parameter"}), 400
        # Create a temporary directory
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            temp_file_path = pathlib.Path(tmp.name)

        s3_key = f'{filename}'
        logger.info('------s3_key--------', s3_key)
        objectstore_env = os.getenv('objectstore')

        AZURE_STORAGE_ACCOUNT_KEY = None
        CONTAINER_NAME = None
        CONTAINER_URI = None
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

        else:
            logging.info("Environment variable 'objectstore' not found.")

        if bucket_name:
            # Initialize a session using boto3
            session = boto3.session.Session()
            # Create S3 client
            s3_client = session.client(
            service_name='s3',
            endpoint_url=endpoint_url,  
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region_name)
            # Download the file from S3 to the temporary file path
            s3_client.download_file(bucket_name, s3_key, str(temp_file_path))
        # else:
        #     sas_url = f"{CONTAINER_URI}?{AZURE_STORAGE_ACCOUNT_KEY}"
        #     blob_service_client = BlobServiceClient(account_url=CONTAINER_URI, credential=AZURE_STORAGE_ACCOUNT_KEY)
        #     BLOB_NAME = s3_key
        #     blob_client = blob_service_client.get_blob_client(container=CONTAINER_NAME, blob=BLOB_NAME)

        #     file_data = blob_client.download_blob().readall()
        #     with open(temp_file_path, 'wb') as f:
        #         f.write(file_data)
        else:

            sas_url = f"{CONTAINER_URI}?{AZURE_STORAGE_ACCOUNT_KEY}"
            blob_service_client = BlobServiceClient(account_url=sas_url)
            BLOB_NAME = s3_key
            blob_client = BlobClient.from_blob_url(
                f"{CONTAINER_URI}/{CONTAINER_NAME}/{BLOB_NAME}?{AZURE_STORAGE_ACCOUNT_KEY}")

            file_data = blob_client.download_blob().readall()
            with open(temp_file_path, 'wb') as f:
                f.write(file_data)

       
        svg_file_data = None
        svg_filename = None
        svg_abap_filename = None
        svg_abap_file_data = None
        # if uuid:
        try:
            if bucket_name:
                svg_filename = f"ts_flowdiagram.svg"
                svg_s3key = f"ts_flowdiagram.svg"
                svg_response = s3_client.get_object(Bucket=bucket_name, Key=svg_s3key)
                svg_file_data = svg_response['Body'].read()
                if RICEFW_type.lower() == "interface":
                    svg_abap_filename = f"ts_flowdiagram_abap.svg"
                    svg_abap_s3key = f"ts_flowdiagram_abap.svg"
                    svg_abap_response = s3_client.get_object(Bucket=bucket_name, Key=svg_abap_s3key)
                    svg_abap_file_data = svg_abap_response['Body'].read()
                logger.info('SVG file downloaded')
            else:
                svg_filename = f"ts_flowdiagram.svg"
                svg_s3key = f"ts_flowdiagram.svg"
                # Azure Blob logic
                svg_blob_url = f"{CONTAINER_URI}/{CONTAINER_NAME}/{svg_s3key}?{AZURE_STORAGE_ACCOUNT_KEY}"
                svg_blob_client = BlobClient.from_blob_url(svg_blob_url)
                svg_file_data = svg_blob_client.download_blob().readall()
                if RICEFW_type.lower() == "interface":
                    svg_abap_filename = f"ts_flowdiagram_abap.svg"
                    svg_abap_s3key = f"ts_flowdiagram_abap.svg"
                    svg_abap_blob_url = f"{CONTAINER_URI}/{CONTAINER_NAME}/{svg_abap_s3key}?{AZURE_STORAGE_ACCOUNT_KEY}"
                    svg_abap_blob_client = BlobClient.from_blob_url(svg_abap_blob_url)
                    svg_abap_file_data = svg_abap_blob_client.download_blob().readall()
        except Exception as svg_err:
            logger.info(f"SVG not found or failed to download: {svg_err}")
            svg_filename = None
            svg_file_data = None
            svg_abap_filename = None
            svg_abap_file_data = None

        # Create ZIP
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
            zip_file.write(str(temp_file_path), arcname=filename)
            if svg_file_data:
                zip_file.writestr(svg_filename, svg_file_data)
            if svg_abap_file_data:
                zip_file.writestr(svg_abap_filename, svg_abap_file_data)

        zip_buffer.seek(0)

        if bucket_name:
            # Delete the file from S3 after sending it to the user
            s3_client.delete_object(Bucket=bucket_name, Key=s3_key)
            logger.info(f'Successfully deleted {filename} from S3.')
        else:
            blob_client.delete_blob()
            logger.info(f'Successfully deleted {BLOB_NAME} from Azure Blob Storage.')

        if svg_file_data and svg_filename:
            try:
                s3_client.delete_object(Bucket=bucket_name, Key=svg_s3key)
                logger.info(f'Deleted SVG: {svg_filename} from S3')
            except Exception as e:
                logger.info(f"Failed to delete SVG from S3: {e}")
        if svg_abap_file_data and svg_abap_filename:
            try:
                s3_client.delete_object(Bucket=bucket_name, Key=svg_abap_s3key)
                logger.info(f'Deleted SVG: {svg_abap_filename} from S3')
            except Exception as e:
                logger.info(f"Failed to delete SVG from S3: {e}")

        # Cleanup local temp file
        if temp_file_path.exists():
            os.remove(str(temp_file_path))
            logger.info(f'Deleted local temp Word file: {temp_file_path}')
            
        # Send the zip file to the user
        return send_file(
            zip_buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name='TS documents.zip'  # Set the desired filename for the download
        )

    except Exception as e:
        logger.info(f"error occured : {e}")
        return jsonify({"error": f"Failed to download file, {e}"}), 500
    
    
@app.route('/download_ts_excel_template', methods=['POST'])
def get_excel_file():
    try:
        # Get request parameters
        mode = request.form.get('activeUploadTab')
        RICEFW_type = request.form.get('RICEFW_type')
        if not RICEFW_type or not mode:
            return jsonify({"error": "Missing 'RICEFW_type' or 'activeUploadTab' parameter"}), 400

        # Determine filename
        r_type = RICEFW_type.lower()
        has_fs = mode != 'withoutFS'
        filename_map = {
            "interface": f'TS_Interface_Static_Template{"_withFS" if has_fs else "_withoutFS"}.xlsx',
            "report": f'TS_Report_Static_Template{"_withFS" if has_fs else "_withoutFS"}.xlsx',
            "enhancement": f'TS_Enhancement_Static_Template{"_withFS" if has_fs else "_withoutFS"}.xlsx',
            "conversion": f'TS_Conversion_Static_Template{"_withFS" if has_fs else "_withoutFS"}.xlsx',
            "form": f'TS_Form_Static_template{"_withFS" if has_fs else "_withoutFS"}.xlsx',
            "workflow": f'TS_Workflow_Static_Template{"_withFS" if has_fs else "_withoutFS"}.xlsx'
        }
        filename = filename_map.get(r_type, f'TS_Workflow_StaticTemplate{"_withFS" if has_fs else "_withoutFS"}.xlsx')
        s3_key = filename
        logging.info(f"Requesting file: {s3_key}")

        # Load object store config from env
        objectstore_env = os.getenv('objectstore')
        if not objectstore_env:
            logging.error("Environment variable 'objectstore' not found.")
            return jsonify({"error": "Server configuration missing"}), 500

        config = json.loads(objectstore_env)

        # Extract relevant config fields
        file_stream = download_from_objectstore(
            bucket_name=config.get('bucket'),
            url=config.get('uri').replace("s3", "https", 1) if config.get('uri') else None,
            access_key=config.get('access_key_id'),
            secret_key=config.get('secret_access_key'),
            region_name=config.get('region'),
            file_key=s3_key,
            container_name=config.get('container_name'),
            azure_url=config.get('container_uri'),
            azure_key=config.get('sas_token'),
            gcp=config.get('gcp')  # Optional
        )

        if not file_stream:
            return jsonify({"error": f"File '{s3_key}' not found in object store"}), 404

        # Send the file
        return send_file(
            file_stream,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

    except Exception as e:
        logging.exception("Failed to download file")
        return jsonify({"error": f"Failed to download file: {str(e)}"}), 500
# @app.route('/download_ts_excel_template', methods=['POST'])
# def get_excel_file():
#     try:
#         # Get parameters
#         mode = request.form.get('activeUploadTab')
#         RICEFW_type = request.form.get('RICEFW_type')
#         if not RICEFW_type or not mode:
#             return jsonify({"error": "Missing 'RICEFW_type' or 'activeUploadTab' parameter"}), 400

#         # Determine filename
#         r_type = RICEFW_type.lower()
#         has_fs = mode != 'withoutFS'
#         filename_map = {
#             "interface": f'TS_Interface_Static_Template{"_withFS" if has_fs else "_withoutFS"}.xlsx',
#             "report": f'TS_Report_Static_Template{"_withFS" if has_fs else "_withoutFS"}.xlsx',
#             "enhancement": f'TS_Enhancement_Static_Template{"_withFS" if has_fs else "_withoutFS"}.xlsx',
#             "conversion": f'TS_Conversion_Static_Template{"_withFS" if has_fs else "_withoutFS"}.xlsx',
#             "form": f'TS_Form_Static_template{"_withFS" if has_fs else "_withoutFS"}.xlsx',
#             "workflow": f'TS_Workflow_Static_Template{"_withFS" if has_fs else "_withoutFS"}.xlsx'
#         }
#         filename = filename_map.get(r_type, f'TS_Workflow_StaticTemplate{"_withFS" if has_fs else "_withoutFS"}.xlsx')
#         s3_key = filename
#         logging.info(f"Downloading s3_key: {s3_key}")

#         # Load object store config
#         objectstore_env = os.getenv('objectstore')
#         if not objectstore_env:
#             logger.error("Environment variable 'objectstore' not found.")
#             return jsonify({"error": "Server configuration missing"}), 500
        
#         objectstore = json.loads(objectstore_env)
#         endpoint_url = objectstore.get('uri')
#         if endpoint_url:
#             endpoint_url = endpoint_url.replace("s3", "https", 1)
#         access_key = objectstore.get('access_key_id')
#         secret_key = objectstore.get('secret_access_key')
#         bucket_name = objectstore.get('bucket')
#         region_name = objectstore.get('region')
#         AZURE_STORAGE_ACCOUNT_KEY = objectstore.get('sas_token')
#         CONTAINER_NAME = objectstore.get('container_name')
#         CONTAINER_URI = objectstore.get('container_uri')

#         if bucket_name:  # S3
#             s3_client = boto3.client(
#                 's3',
#                 endpoint_url=endpoint_url,
#                 aws_access_key_id=access_key,
#                 aws_secret_access_key=secret_key,
#                 region_name=region_name,
#             )

#             # Verify file exists
#             try:
#                 s3_client.head_object(Bucket=bucket_name, Key=s3_key)
#             except s3_client.exceptions.ClientError as e:
#                 return jsonify({"error": f"File '{s3_key}' not found in bucket '{bucket_name}'"}), 404

#             # Download into BytesIO
#             file_stream = io.BytesIO()
#             s3_client.download_fileobj(Bucket=bucket_name, Key=s3_key, Fileobj=file_stream)
#             file_stream.seek(0)

#         else:  # Azure Blob
#             sas_url = f"{CONTAINER_URI}?{AZURE_STORAGE_ACCOUNT_KEY}"
#             blob_client = BlobClient.from_blob_url(
#                 f"{CONTAINER_URI}/{CONTAINER_NAME}/{s3_key}?{AZURE_STORAGE_ACCOUNT_KEY}"
#             )
#             try:
#                 file_data = blob_client.download_blob().readall()
#             except Exception:
#                 return jsonify({"error": f"File '{s3_key}' not found in container '{CONTAINER_NAME}'"}), 404
#             file_stream = io.BytesIO(file_data)
#             file_stream.seek(0)

#         # Send file to user
#         return send_file(
#             file_stream,
#             as_attachment=True,
#             download_name=filename,
#             mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
#         )

#     except Exception as e:
#         logging.exception("Failed to download file")
#         return jsonify({"error": f"Failed to download file: {str(e)}"}), 500



@app.route('/upload_template_obj_store', methods=['POST'])
def upload_template():
    try:
        file = request.files.get('file')
        if not file or file.filename == '':
            return jsonify({'error': 'No selected file'}), 400
        if not file.filename.endswith('.zip'):
            return jsonify({'error': 'Only .zip files are allowed'}), 400

        objectstore_env = os.getenv('objectstore')
        if not objectstore_env:
            return jsonify({'error': 'Missing objectstore environment variable'}), 500

        objectstore = json.loads(objectstore_env)
        endpoint_url = objectstore.get('uri')
        if endpoint_url:
            endpoint_url = endpoint_url.replace("s3", "https", 1)
        access_key = objectstore.get('access_key_id')
        secret_key = objectstore.get('secret_access_key')
        bucket_name = objectstore.get('bucket')
        region_name = objectstore.get('region')
        AZURE_STORAGE_ACCOUNT_KEY = objectstore.get('sas_token')
        CONTAINER_NAME = objectstore.get('container_name')
        CONTAINER_URI = objectstore.get('container_uri')
        gcp_key = objectstore.get('gcp')

        uploaded_files = []
        failed_uploads = []

        # Extract ZIP into temp directory
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = os.path.join(temp_dir, 'uploaded.zip')
            file.save(zip_path)

            try:
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
            except zipfile.BadZipFile:
                return jsonify({'error': 'Invalid ZIP file'}), 400

            for root, dirs, files in os.walk(temp_dir):
                for filename in files:
                    if filename.endswith('.docx') or filename.endswith('.xlsx'):
                        file_path = os.path.join(root, filename)

                        try:
                            # Call the upload helper function
                            upload_to_objectstore(
                                access_key_id=access_key,
                                secret_access_key=secret_key,
                                local_file_path=file_path,
                                aws_file_path=filename,
                                bucket_name=bucket_name,
                                CONTAINER_NAME=CONTAINER_NAME,
                                CONTAINER_URI=CONTAINER_URI,
                                AZURE_STORAGE_ACCOUNT_KEY=AZURE_STORAGE_ACCOUNT_KEY,
                                azure_file_path=filename,
                                gcp=gcp_key,
                                gcp_file_path=filename
                            )
                            uploaded_files.append(filename)

                        except Exception as e:
                            logging.error(f"Failed to upload {filename}: {e}")
                            failed_uploads.append({'file': filename, 'error': str(e)})

        return jsonify({
            'message': 'Upload process completed.',
            'uploaded': uploaded_files,
            'failed': failed_uploads
        }), 200

    except Exception as e:
        logging.exception("Error in upload_template")
        return jsonify({"error": f"Failed to upload file: {str(e)}"}), 500

# @app.route('/upload_template_obj_store', methods=['POST'])

# def upload_template():
#     try:
#         file = request.files['file']
#         if file.filename == '':
#             return jsonify({'error': 'No selected file'}), 400
#         if not file.filename.endswith('.zip'):
#             return jsonify({'error': 'Only .zip files are allowed'}), 400
        
#         objectstore_env = os.getenv('objectstore')
#         if not objectstore_env:
#             return jsonify({'error': 'Missing objectstore environment variable'}), 500
            
#         if objectstore_env:
#             objectstore = json.loads(objectstore_env)
#             endpoint_url = objectstore.get('uri')
#             if endpoint_url:
#                 endpoint_url = endpoint_url.replace("s3", "https", 1)
#             access_key = objectstore.get('access_key_id')
#             secret_key = objectstore.get('secret_access_key')
#             bucket_name = objectstore.get('bucket')
#             region_name = objectstore.get('region')

#             AZURE_STORAGE_ACCOUNT_KEY = objectstore.get('sas_token')
#             CONTAINER_NAME = objectstore.get('container_name')
#             CONTAINER_URI = objectstore.get('container_uri')

#             # Initialize S3 client
#             s3_client = boto3.client(
#                 service_name='s3',
#                 endpoint_url=endpoint_url,
#                 aws_access_key_id=access_key,
#                 aws_secret_access_key=secret_key,
#                 region_name=region_name,
#             )

#             uploaded_files = []
#             failed_uploads = []

#             # Extract ZIP into temp directory
#             with tempfile.TemporaryDirectory() as temp_dir:
#                 zip_path = os.path.join(temp_dir, 'uploaded.zip')
#                 file.save(zip_path)

#                 try:
#                     with zipfile.ZipFile(zip_path, 'r') as zip_ref:
#                         zip_ref.extractall(temp_dir)
#                 except zipfile.BadZipFile:
#                     return jsonify({'error': 'Invalid ZIP file'}), 400

#                 for root, dirs, files in os.walk(temp_dir):
#                     for filename in files:
#                         if filename.endswith('.docx') or filename.endswith('.xlsx'):
#                             file_path = os.path.join(root, filename)
#                             s3_key = filename  # or customize path in bucket
#                             try:
#                                 if bucket_name:  # S3 Upload
#                                     s3_client.upload_file(file_path, bucket_name, s3_key)
                                    
#                                     # Verify upload
#                                     try:
#                                         s3_client.head_object(Bucket=bucket_name, Key=s3_key)
#                                         uploaded_files.append(filename)
#                                     except s3_client.exceptions.ClientError as e:
#                                         failed_uploads.append({'file': filename, 'error': f"Upload verification failed: {str(e)}"})

#                                 else:  # Azure Upload
#                                     sas_url = f"{CONTAINER_URI}?{AZURE_STORAGE_ACCOUNT_KEY}"
#                                     blob_client = BlobClient.from_blob_url(f"{CONTAINER_URI}/{CONTAINER_NAME}/{filename}?{AZURE_STORAGE_ACCOUNT_KEY}")
#                                     with open(file_path, 'rb') as f:
#                                         blob_client.upload_blob(f, overwrite=True)

#                                     # Verify upload
#                                     try:
#                                         blob_client.get_blob_properties()
#                                         uploaded_files.append(filename)
#                                     except Exception as e:
#                                         failed_uploads.append({'file': filename, 'error': f"Upload verification failed: {str(e)}"})

#                             except Exception as e:
#                                 failed_uploads.append({'file': filename, 'error': str(e)})

#             return jsonify({
#                 'message': 'Upload process completed.',
#                 'uploaded': uploaded_files,
#                 'failed': failed_uploads
#             }), 200

#     except Exception as e:
#         logging.exception("Error in upload_template")
#         return jsonify({"error": f"Failed to upload file: {str(e)}"}), 500


@app.route('/download_svgfile', methods=['GET'])
def download_svgfile():
    s3_key = request.args.get('file')
    objectstore_env = os.getenv('objectstore')

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
    else:
        logging.info("Environment variable 'objectstore' not found.")
    # Initialize a session using boto3
    session = boto3.session.Session()
    # Create S3 client
    s3_client = session.client(
    service_name='s3',
    endpoint_url=endpoint_url,  
    aws_access_key_id=access_key,
    aws_secret_access_key=secret_key,
    region_name=region_name
    )

    #logger.info('-----download_s3_key----------',s3_key )
    if not s3_key:
        return abort(400, "Missing 'file' parameter")

    try:
        if bucket_name:
            # Stream the file from object store
            response = s3_client.get_object(Bucket= bucket_name, Key=s3_key)
            file_data = response['Body'].read()
        else:
            sas_url = f"{CONTAINER_URI}?{AZURE_STORAGE_ACCOUNT_KEY}"
            blob_service_client = BlobServiceClient(account_url=sas_url)
            blob_client = BlobClient.from_blob_url(f"{CONTAINER_URI}/{CONTAINER_NAME}/{s3_key}?{AZURE_STORAGE_ACCOUNT_KEY}")
            # Stream the file data
            file_data = blob_client.download_blob().readall()


        # Send file back to user
        return send_file(
            io.BytesIO(file_data),
            mimetype='image/svg+xml',
            as_attachment=True,
            download_name=s3_key.split("/")[-1]
        )

    except Exception as e:
        logger.info("❌ Error:", e)
        return abort(500, "Error retrieving file")    
    

@app.route('/read_ts_flag', methods=['GET'])
def read_fs_flag():
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

            logger.info("Authorization: ",isAuthorized)
            if not isAuthorized:
                abort(403)
    try:
        isTSPreviewEnabled=os.getenv("isTSPreviewEnabled",'False')
        logger.info(os.getenv("isTSPreviewEnabled"))
        return jsonify({
            "isTSPreviewEnabled": isTSPreviewEnabled
        }), 200
 
 
    except Exception as e:
        return jsonify({"error": f"Failed to download file,{e}"}), 500 
    

@app.route('/health', methods=['GET'])
def health_check():
    return "OK", 200

if __name__ == '__main__':
    host = '0.0.0.0'
    socketio.run(app,host=host,port=port, allow_unsafe_werkzeug=True)

