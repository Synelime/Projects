from flask import Flask, request, jsonify, send_file, abort, Response, make_response
import os
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
import sys
import io
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)),os.pardir))
from io import BytesIO
import zipfile

import get_values_fromexcel
import TSP_interface
import TSP_enhancement
import TSP_reports
import TSP_form
import TSP_conversion
import TSP_form_preview
import TSP_conversion_preview
import TSP_enhancement_preview
import TSP_reports_preview
import TSP_interface_preview
import TSP_workflow_preview
import TSP_workflow
import traceback
import uuid
from sap import xssec
from cfenv import AppEnv
import tempfile
import pathlib
import boto3
import document_count
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import re
import ast
from dotenv import load_dotenv
from azure.storage.blob import BlobClient
import json
import PyPDF2
import form_regenerate
import conversion_regenerate 
import enhancement_regenerate
import report_regenerate
import interface_regenerate
import workflow_regenerate
import json_storage_handler
from docx import Document
import pandas as pd
from json_storage_handler import *
from graphviz import Source
from get_diagram import create_diagram_svg


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


else:
   logger.error("Environment variable 'objectstore' not found.")

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

app = Flask(__name__)


limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["500 per day", "200 per hour", "100/minute"]
)

@app.before_request
def hide_server_header():
    import werkzeug.serving
    werkzeug.serving.WSGIRequestHandler.server_version = "MySecureServer"
    werkzeug.serving.WSGIRequestHandler.sys_version = ""


env = AppEnv()
uaa_service = env.get_service(label='xsuaa').credentials

def is_invalid(value):
    return value.strip().lower() in ['na', 'n/a', 'n.a','']

def mandatory_section_check(dictvalues, wricef_type):
    mandatory_filled = True
    if wricef_type.lower() == "interface":
        if dictvalues.get('DEPENDENCIES / CONSTRAINTS', '').strip() == '' or dictvalues.get('TRANSACTION VOLUME', '').strip() == '' or dictvalues.get('INITIATING PROCESS / TRANSACTION / PROGRAM', '').strip() == '' or dictvalues.get('PROCESSING LOGIC', '').strip() == '' or dictvalues.get('MAPPING SAP FIELDS TO SOURCE / TARGET', '').strip() == '' or dictvalues.get('SECURITY & AUTHORIZATION', '').strip() == '':
            mandatory_filled = False
            return mandatory_filled
    elif wricef_type.lower() == "enhancement":
        if dictvalues.get('PROCESS/ DATA FLOW DIAGRAM', '').strip() == '' or dictvalues.get('COMPLIANCE AND SECURITY', '').strip() == '':
            mandatory_filled = False
            return mandatory_filled
    elif wricef_type.lower() == "report":
        if dictvalues.get('Report Input Screen', '').strip() == '' or dictvalues.get('Report Output', '').strip() == '':
            mandatory_filled = False
            return mandatory_filled
    elif wricef_type.lower() == "form":
        if dictvalues.get('Testing Requirements', '').strip() == '' or dictvalues.get('Process/Data Flow Diagram', '').strip() == '':
            mandatory_filled = False
            return mandatory_filled
    elif wricef_type.lower() == "conversion":
        if dictvalues.get('Process/Data Flow Diagram', '').strip() == '' or dictvalues.get('Error Handling Details', '').strip() == '' or dictvalues.get('Functional Unit Tests', '').strip() == '':
            mandatory_filled = False
            return mandatory_filled
    elif wricef_type.lower() == "workflow":
        if dictvalues.get('Testing Requirements', '').strip() == '':
            mandatory_filled = False
            return mandatory_filled

    

@app.route('/check_ricefw_exists', methods = ['POST'])
def check_ricefw_exists():
    try:
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
        else:
            abort(403)
        token = request.headers.get('Authorization')
        RICEFW_type = request.form.get('RICEFW_type')
        logger.info(f'-----------RICEFW_type-------------', RICEFW_type) 
        project_id = request.form.get('project_id')
        logger.info(f'-----------project_id-------------', project_id) 
        RICEFW_name = request.form.get('RICEFW_name')
        logger.info(f'-----------RICEFW_name-------------', RICEFW_name)  
        message  = document_count.check_ricefw_exists(token, project_id, RICEFW_type,RICEFW_name)
        if message:
            return jsonify({'success': 'A document with same RICEFW Name already exists in the drafts for this project, do you want to overwrite it with this one?'}), 200
        else:
            return jsonify({'error': 'RICEFW name does not exist'}), 200
    except Exception as e:
        logger.error(f"Error occured during check ricefw api call: {e}")


@app.route('/preview_upload', methods=['POST'])
def preview_upload_file():
    try:
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
        else:
            abort(403)
        # Get the input feature
        token = request.headers.get('Authorization')
        input_feature = request.form.get('input_feature')
        logger.info(f'-----------input_feature-------------', input_feature)  
        if not input_feature:
            return jsonify({"error": "Data should be provided"}), 400
           
        if (input_feature == "Functional Specification"):
            try:
                file = request.files['file']
                logger.info(f'-----------file-------------', file)
                if not file or file.filename == '':
                    return jsonify({"error": "No selected file"}), 400        
                # Use io.BytesIO to read the file directly in memory
                file_stream = io.BytesIO(file.read())              
                # Get the file extension
                file_extension = os.path.splitext(file.filename)[1].lower()              
                # Get the input feature
                RICEFW_type = request.form.get('RICEFW_type')
                logger.info(f'-----------RICEFW_type-------------', RICEFW_type) 
                uuid_value=str(uuid.uuid4())
                logger.info(f'-----------uuid_value-------------', uuid_value) 
                project_id = request.form.get('project_id')
                logger.info(f'-----------project_id-------------', project_id) 
                username = request.form.get('username')
                if username == None:
                    username = "system"
                logger.info(f'-----------username-------------', username)
                RICEFW_name = request.form.get('RICEFW_name')
                logger.info(f'-----------RICEFW_name-------------', RICEFW_name)
                L3_process = request.form.get('L3_process')
                logger.info(f'-----------L3_process-------------', L3_process)  
                try:
                     template_link, template_type = document_count.get_template_link(token, project_id, RICEFW_type, module="FS")
                     logger.info(f'-----------template_link-------------', template_link)
                except Exception as db_error:
                     # Handle database exceptions separately
                     traceback.print_exc()
                     return jsonify({"error": "Database error", "details": str(db_error)}), 500
                if template_link is None:
                     return jsonify({'error': 'Standard/Client template is not found for the specified project'}), 200
                if file_extension in ['.xlsx', '.xls']:  # Excel file extensions
                    if RICEFW_type.lower() == "form":
                        input_df = pd.read_excel(file_stream, engine='openpyxl', keep_default_na=False)
                        if "Are there any features or functionalities that are explicitly excluded from the scope of this form?" not in input_df['Sections in FS'][0]:
                            return jsonify({'error': "This is not the input template for Form WRICEF type"}), 400
                        # extracting values for Form
                        form_dictvalues = get_values_fromexcel.read_Report(file_stream)
                        logger.info(f'---------form_dictvalues:--------')
                        logger.info(form_dictvalues)

                        if form_dictvalues == "empty values":
                            return jsonify({'error': "No values provided for 'Functional Input' column"}), 400
                        else:
                            overview = form_dictvalues.get('Overview and Scope', '')
                            func_req = form_dictvalues.get('Detailed Functional Requirement', '')

                            if is_invalid(overview) or is_invalid(func_req):
                                return jsonify({'error': "Overview and Scope or Detailed Functional Requirement should not be empty or 'NA'"}), 400
                            if mandatory_section_check(form_dictvalues, RICEFW_type) == False:
                                return jsonify({'error': "Mandatory sections should not be left empty"}), 400
                            
                            # FS generation for form
                            form_data_cleaned, form_data_with_symbols,input_token_count, output_token_count = TSP_form_preview.TSP_form_main(form_dictvalues, RICEFW_type)
                            logger.info(f'----------inside3-----------')
                            # insert meta data into the HANADB table
                            document_count.upsert_logdata(token, project_id, RICEFW_type,uuid_value,RICEFW_name,username,input_token_count, output_token_count,form_dictvalues, form_data_with_symbols,previous_form_data = {},status_type = "Draft")
                            # Convert form_data to a JSON string without sorting keys
                            json_data = json.dumps(form_data_cleaned, sort_keys=False, indent=2)
                            return Response(json_data, mimetype='application/json')

                    elif RICEFW_type.lower() == "conversion":
                        # extracting values for Conversion
                        conversion_dictvalues, table_df = get_values_fromexcel.read_Conversion(file_stream)
                        logger.info(f'---------conversion_dictvalues:--------')
                        logger.info(conversion_dictvalues)

                        if conversion_dictvalues == "empty values":
                            return jsonify({'error': "No values provided for 'Functional Input' column"}), 400
                        else:
                            overview = conversion_dictvalues.get('Overview and Scope', '')
                            func_req = conversion_dictvalues.get('Functional Approach/Design', '')

                            if is_invalid(overview) or is_invalid(func_req):
                                return jsonify({'error': "Overview and Scope or Functional Approach/Design should not be empty or 'NA'"}), 400
                            if mandatory_section_check(conversion_dictvalues, RICEFW_type) == False:
                                return jsonify({'error': "Mandatory sections should not be left empty"}), 400
                            
                            # FS generation for conversion
                            conversion_data_cleaned, conversion_data_with_symbols,input_token_count, output_token_count = TSP_conversion_preview.TSP_conversion_main(conversion_dictvalues, RICEFW_type, table_df)
                            # insert meta data into the HANADB table
                            document_count.upsert_logdata(token, project_id, RICEFW_type,uuid_value,RICEFW_name,username,input_token_count, output_token_count,conversion_dictvalues, conversion_data_with_symbols,previous_form_data = {},status_type = "Draft")
                            # Convert form_data to a JSON string without sorting keys
                            json_data = json.dumps(conversion_data_cleaned, sort_keys=False, indent=2)
                            return Response(json_data, mimetype='application/json')

                    elif RICEFW_type.lower() == "workflow":
                        input_df = pd.read_excel(file_stream, engine='openpyxl', keep_default_na=False)
                        if "Please explain functional requirement for this Workflow?" not in input_df['Sections in FS'][0]:
                            return jsonify({'error': "This is not the input template for Workflow WRICEF type"}), 400
                        # extracting values for Workflow
                        workflow_dictvalues = get_values_fromexcel.read_Report(file_stream)
                        logger.info(f'---------workflow_dictvalues:--------')
                        logger.info(workflow_dictvalues)

                        if workflow_dictvalues == "empty values":
                            return jsonify({'error': "No values provided for 'Functional Input' column"}), 400
                        else:
                            overview = workflow_dictvalues.get('Overview and Scope', '')
                            func_req = workflow_dictvalues.get('Detailed Functional Requirement', '')

                            if is_invalid(overview) or is_invalid(func_req):
                                return jsonify({'error': "Overview and Scope or Detailed Functional Requirement should not be empty or 'NA'"}), 400
                            if mandatory_section_check(workflow_dictvalues, RICEFW_type) == False:
                                return jsonify({'error': "Mandatory sections should not be left empty"}), 400
                            # FS generation for workflow
                            workflow_data_cleaned, workflow_data_with_symbols,input_token_count, output_token_count = TSP_workflow_preview.TSP_workflow_main(workflow_dictvalues, RICEFW_type)
                            # insert meta data into the HANADB table
                            document_count.upsert_logdata(token, project_id, RICEFW_type,uuid_value,RICEFW_name,username,input_token_count, output_token_count,workflow_dictvalues, workflow_data_with_symbols,previous_form_data = {},status_type = "Draft")
                            # Convert form_data to a JSON string without sorting keys
                            json_data = json.dumps(workflow_data_cleaned, sort_keys=False, indent=2)
                            return Response(json_data, mimetype='application/json')
                          
                    elif RICEFW_type.lower() == "enhancement":
                        # extracting values for Enhancement
                        enhancement_dictvalues = get_values_fromexcel.read_Enhancement(file_stream)
                        logger.info(f'---------enhancement_dictvalues:--------')
                        logger.info(enhancement_dictvalues)

                        if enhancement_dictvalues == "empty values":
                            return jsonify({'error': "No values provided for 'Functional Input' column"}), 400

                        else:
                            overview = enhancement_dictvalues.get('BUSINESS OVERVIEW', '')
                            func_req = enhancement_dictvalues.get('FUNCTIONAL DESIGN', '')

                            if is_invalid(overview) or is_invalid(func_req):
                                return jsonify({'error': "Business Overview or Functional Design should not be empty or 'NA'"}), 400
                            if mandatory_section_check(enhancement_dictvalues, RICEFW_type) == False:
                                return jsonify({'error': "Mandatory sections should not be left empty"}), 400
                            
                            # FS generation for Report
                            enhancement_data_cleaned, enhancement_data_with_symbols,input_token_count, output_token_count = TSP_enhancement_preview.TSP_Enhancement_main(enhancement_dictvalues, RICEFW_type)
                            # insert meta data into the HANADB table
                            document_count.upsert_logdata(token, project_id, RICEFW_type,uuid_value,RICEFW_name,username,input_token_count, output_token_count,enhancement_dictvalues, enhancement_data_with_symbols,previous_form_data = {},status_type = "Draft")
                            # Convert form_data to a JSON string without sorting keys
                            json_data = json.dumps(enhancement_data_cleaned, sort_keys=False, indent=2)
                            return Response(json_data, mimetype='application/json')
                        
                    elif RICEFW_type.lower() == "interface":
                        # extracting values for Interface
                        interface_dictvalues = get_values_fromexcel.read_interface(file_stream)
                        logger.info(f'---------interface_dictvalues:--------')
                        logger.info(interface_dictvalues)

                        if interface_dictvalues == "empty values":
                            return jsonify({'error': "No values provided for 'Functional Input' column"}), 400

                        else:
                            overview = interface_dictvalues.get('OBJECT OVERVIEW', '')
                            func_req = interface_dictvalues.get('DETAILED FUNCTIONAL REQUIREMENT', '')

                            if is_invalid(overview) or is_invalid(func_req):
                                return jsonify({'error': "Object Overview or Detailed Functional Requirement should not be empty or 'NA'"}), 400
                            if mandatory_section_check(interface_dictvalues, RICEFW_type) == False:
                                return jsonify({'error': "Mandatory sections should not be left empty"}), 400
                            
                            # FS generation for Interface
                            interface_data_cleaned, interface_data_with_symbols,input_token_count, output_token_count = TSP_interface_preview.generate_interface_contents(interface_dictvalues, RICEFW_type)
                            # insert meta data into the HANADB table
                            document_count.upsert_logdata(token, project_id, RICEFW_type,uuid_value,RICEFW_name,username,input_token_count, output_token_count,interface_dictvalues, interface_data_with_symbols,previous_form_data = {},status_type = "Draft")
                            # Convert form_data to a JSON string without sorting keys
                            json_data = json.dumps(interface_data_cleaned, sort_keys=False, indent=2)
                            return Response(json_data, mimetype='application/json')
                    
                    elif RICEFW_type.lower() == "report":
                        # extracting values for Report
                        report_dictvalues = get_values_fromexcel.read_Report(file_stream)
                        logger.info(f'---------report_dictvalues:--------')
                        logger.info(report_dictvalues)

                        if report_dictvalues == "empty values":
                            return jsonify({'error': "No values provided for 'Functional Input' column"}), 400
                        else:
                            overview = report_dictvalues.get('Business Overview', '')
                            func_req = report_dictvalues.get('Functional Design', '')

                            if is_invalid(overview) or is_invalid(func_req):
                                return jsonify({'error': "Business Overview or Functional Design should not be empty or 'NA'"}), 400
                            if mandatory_section_check(report_dictvalues, RICEFW_type) == False:
                                return jsonify({'error': "Mandatory sections should not be left empty"}), 400
                            
                            # FS generation for Report
                            report_data_cleaned, report_data_with_symbols,input_token_count, output_token_count = TSP_reports_preview.TSP_report_main(report_dictvalues, RICEFW_type)
                            # insert meta data into the HANADB table
                            document_count.upsert_logdata(token, project_id, RICEFW_type,uuid_value,RICEFW_name,username,input_token_count, output_token_count,report_dictvalues, report_data_with_symbols,previous_form_data = {},status_type = "Draft")
                            # Convert form_data to a JSON string without sorting keys
                            json_data = json.dumps(report_data_cleaned, sort_keys=False, indent=2)
                            return Response(json_data, mimetype='application/json')
                            
                else:
                    return jsonify({"error": "Unsupported file type"}), 400
            
            except Exception as e:
                return jsonify({"error": f"Error in processing Functional Specification"}), 500
                      
    except Exception as e:
        # Log detailed exception (e.g., traceback) for debugging
        logger.error(f"Error: {traceback.format_exc()}")
        return jsonify({"Error": "An unexpected error occurred. Please try again later."}), 500


@app.route('/download_svg', methods=['POST'])
def download_svg():
    project_id = request.form.get("project_id")
    ricefw_name = request.form.get("RICEFW_name")
    ricefw_type = request.form.get('RICEFW_type')

    if not project_id or not ricefw_name or not ricefw_type:
        return jsonify({"error": "project_id and ricefw_name and ricefw_type are required"}), 400
    
    dot_code = document_count.fetch_dotcode_from_db(project_id, ricefw_name, ricefw_type)
    logger.info(f'---------dot_code-----------', dot_code)
    # if not dot_code:
    #     return {"error": "Diagram not found"}, 404
    
    if not dot_code or dot_code == "NA":
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


############# FS manual Edit API call #######
@app.route('/fs_manualedit', methods=['POST'])
def fs_manualedit():
    try:
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
        else:
            abort(403)
        token = request.headers.get('Authorization')
        RICEFW_type = request.form.get('RICEFW_type')
        logger.info(f'-----------RICEFW_type-------------', RICEFW_type)
        RICEFW_name = request.form.get('RICEFW_name')
        logger.info(f'-----------RICEFW_name-------------', RICEFW_name)  
        project_id = request.form.get('project_id')
        logger.info(f'-----------project_id-------------', project_id) 
        username = request.form.get('username')
        if username == None:
            username = "system"
        logger.info(f'-----------username-------------', username) 
        edited_section_name = request.form.get('section_name')
        logger.info(f'----------edited section_name-----------', edited_section_name)
        edited_content = request.form.get('edited_content')
        edited_content = edited_content.encode('utf-8').decode('unicode_escape')
        edited_content = re.sub(r'[\x00-\x1F]+', '', edited_content)
        logger.info(f'-------edited content---------', edited_content)
        dependent_sections = request.form.get('dependent_sections') 
        logger.info(f'-------dependent_sections-------',dependent_sections)

        if not edited_section_name or not edited_content:
            return jsonify({"error": "Both 'section_name' and 'edited content' are required"}), 400

        # extracting llm content and raw input data
        current_llm_content, previous_llm_content, dictvalues = document_count.get_data_fromdb(token, project_id, RICEFW_name, RICEFW_type)
        logger.info(f'-----------dictvalues-------------', dictvalues)
        logger.info(f'-----------previous_llm_content-------------', previous_llm_content)

        if RICEFW_type.lower() == "form":
            data = form_regenerate.update_contents_form(token, edited_section_name, edited_content, dependent_sections, current_llm_content, previous_llm_content, dictvalues, project_id, RICEFW_name, RICEFW_type)
        elif RICEFW_type.lower() == "conversion":
            # extracting values for Conversion
            #conversion_dictvalues, table_df = get_values_fromexcel.read_Conversion(file_stream)
            data = conversion_regenerate.update_contents_conversion(token, edited_section_name, edited_content, dependent_sections, current_llm_content, previous_llm_content, dictvalues, project_id, RICEFW_name, RICEFW_type)
        elif RICEFW_type.lower() == "enhancement":
            data = enhancement_regenerate.update_contents_enhancement(token, edited_section_name, edited_content, dependent_sections, current_llm_content, previous_llm_content, dictvalues, project_id, RICEFW_name, RICEFW_type)
        elif RICEFW_type.lower() == "report":
            data = report_regenerate.update_contents_report(token, edited_section_name, edited_content, dependent_sections, current_llm_content, previous_llm_content, dictvalues, project_id, RICEFW_name, RICEFW_type)
        elif RICEFW_type.lower() == "interface":
            data = interface_regenerate.update_contents_interface(token, edited_section_name, edited_content, dependent_sections, current_llm_content, previous_llm_content, dictvalues, project_id, RICEFW_name, RICEFW_type)
        elif RICEFW_type.lower() == "workflow":
            data = workflow_regenerate.update_contents_workflow(token, edited_section_name, edited_content, dependent_sections, current_llm_content, previous_llm_content, dictvalues, project_id, RICEFW_name, RICEFW_type)

        # Convert form_data to a JSON string without sorting keys
        json_data = json.dumps(data, sort_keys=False, indent=2)
        return Response(json_data, mimetype='application/json')
            
    except Exception as e:
        logger.error(f"Error in regenerate endpoint: {str(e)}")
        return jsonify({"error": "An unexpected error occurred during regeneration"}), 500


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
    

@app.route('/fs_regenerate', methods=['POST'])
def fs_regenerate():
    try:
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
        else:
            abort(403)
        token = request.headers.get('authorization')
        RICEFW_type = request.form.get('RICEFW_type')
        logger.info(f'-----------RICEFW_type-------------', RICEFW_type)
        RICEFW_name = request.form.get('RICEFW_name')
        logger.info(f'-----------RICEFW_name-------------', RICEFW_name)  
        project_id = request.form.get('project_id')
        logger.info(f'-----------project_id-------------', project_id) 
        username = request.form.get('username')
        session_id=request.form.get('session_id')
        if username == None:
            username = "system"
        logger.info(f'-----------username-------------', username)  
        section_name = request.form.get('section_name')
        logger.info(f'regenerate section_name', section_name)
        user_feedback = request.form.get('user_feedback')
        logger.info(f'regenerate user_feedback', user_feedback)
        reference_sections = request.form.get('reference_sections')
        # Convert string to actual list if needed
        if isinstance(reference_sections, str):
            reference_sections = ast.literal_eval(reference_sections)
        logger.info(f'regenerate reference_sections', reference_sections)

        # extracting llm content and raw input data
        current_llm_content, previous_llm_content, dictvalues = document_count.get_data_fromdb(token, project_id, RICEFW_name, RICEFW_type)

        # convert json string to dictionary
        json_data = json.loads(current_llm_content)

        # Handle optional file content
        file_content = None
        if 'file' in request.files:
            file = request.files['file']
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
        # Find the section data by key
        section_data = next((item["value"] for item in content if item.get("key") == section_name), '{}')
        logger.info(f"--------Retrieved section data-----: {section_data}")

        if section_data == '{}':  # Check if we got empty data
            return jsonify({"error": f"Section '{section_name}' not found in the JSON content"}), 404

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

        logger.info(f"reference_sections_dict", reference_sections_dict)

        if RICEFW_type.lower() == "form":
            data = form_regenerate.regenerate_and_update_section_form(
                token = token,
                project_id = project_id,
                RICEFW_name = RICEFW_name,
                RICEFW_type = RICEFW_type,
                section_name=section_name,
                manual_feedback=user_feedback,
                section_content=section_data,
                json_section_contents=json_data,
                reference_sections=reference_sections_dict if reference_sections_dict else None,
                file_content=file_content  # Pass the file content to the regeneration function
            )
        elif RICEFW_type.lower() == "conversion":
            data = conversion_regenerate.regenerate_and_update_section_conversion(
                token = token,
                username=username,
                session_id = session_id,
                project_id = project_id,
                RICEFW_name = RICEFW_name,
                RICEFW_type = RICEFW_type,
                section_name=section_name,
                manual_feedback=user_feedback,
                section_content=section_data,
                json_section_contents=json_data,
                reference_sections=reference_sections_dict if reference_sections_dict else None,
                file_content=file_content  # Pass the file content to the regeneration function
            )
        elif RICEFW_type.lower() == "enhancement":
            data = enhancement_regenerate.regenerate_and_update_section_enhancement(
                token = token,
                project_id = project_id,
                RICEFW_name = RICEFW_name,
                RICEFW_type = RICEFW_type,
                section_name=section_name,
                manual_feedback=user_feedback,
                section_content=section_data,
                json_section_contents=json_data,
                reference_sections=reference_sections_dict if reference_sections_dict else None,
                file_content=file_content  # Pass the file content to the regeneration function
            )
        elif RICEFW_type.lower() == "report":
            data = report_regenerate.regenerate_and_update_section_report(
                token = token,
                project_id = project_id,
                RICEFW_name = RICEFW_name,
                RICEFW_type = RICEFW_type,
                section_name=section_name,
                manual_feedback=user_feedback,
                section_content=section_data,
                json_section_contents=json_data,
                reference_sections=reference_sections_dict if reference_sections_dict else None,
                file_content=file_content  # Pass the file content to the regeneration function
            )
        elif RICEFW_type.lower() == "interface":
            data = interface_regenerate.regenerate_and_update_section_interface(
                token = token,
                project_id = project_id,
                RICEFW_name = RICEFW_name,
                RICEFW_type = RICEFW_type,
                section_name=section_name,
                manual_feedback=user_feedback,
                section_content=section_data,
                json_section_contents=json_data,
                reference_sections=reference_sections_dict if reference_sections_dict else None,
                file_content=file_content  # Pass the file content to the regeneration function
            )
        elif RICEFW_type.lower() == "workflow":
            data = workflow_regenerate.regenerate_and_update_section_workflow(
                token = token,
                project_id = project_id,
                RICEFW_name = RICEFW_name,
                RICEFW_type = RICEFW_type,
                section_name=section_name,
                manual_feedback=user_feedback,
                section_content=section_data,
                json_section_contents=json_data,
                reference_sections=reference_sections_dict if reference_sections_dict else None,
                file_content=file_content,  # Pass the file content to the regeneration function
            )
        # Convert form_data to a JSON string without sorting keys
        json_data = json.dumps(data, sort_keys=False, indent=2)
        return Response(json_data, mimetype='application/json')

    except Exception as e:
        logger.error(f"Error in regenerate endpoint: {str(e)}")
        return jsonify({"error": "An unexpected error occurred during regeneration"}), 500


def remove_symbol_from_dict(data, symbol="^^"):
    if isinstance(data, dict):
        return {k: remove_symbol_from_dict(v, symbol) for k, v in data.items()}
    elif isinstance(data, list):
        return [remove_symbol_from_dict(item, symbol) for item in data]
    elif isinstance(data, str):
        return data.replace(symbol, "")
    else:
        return data
    
############# FS UNDO API call #######
@app.route('/fs_undo', methods=['POST'])
def fs_undo():
    try:
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
        else:
            abort(403)
        token = request.headers.get('Authorization')
        RICEFW_type = request.form.get('RICEFW_type')
        logger.info(f'-----------RICEFW_type-------------', RICEFW_type)
        RICEFW_name = request.form.get('RICEFW_name')
        logger.info(f'-----------RICEFW_name-------------', RICEFW_name)  
        project_id = request.form.get('project_id')
        logger.info(f'-----------project_id-------------', project_id) 
        section_name = request.form.get('section_name')
        logger.info(f'----------section_name-----------', section_name)

        if not section_name:
            return jsonify({"error": "'section_name' is required"}), 400
        
        # extracting llm content and raw input data
        current_llm_content, previous_llm_content, dictvalues = document_count.get_data_fromdb(token, project_id, RICEFW_name, RICEFW_type)

        # convert json string to dictionary
        current_json_data = json.loads(current_llm_content)
        previous_json_data = json.loads(previous_llm_content)
        # undo specific section
        response = document_count.undo_section_update_in_db(token, project_id, RICEFW_name, RICEFW_type, section_name, current_json_data, previous_json_data)
        # remove this character(^^) and return the response
        data = remove_symbol_from_dict(response)

        # Convert form_data to a JSON string without sorting keys
        json_data = json.dumps(data, sort_keys=False, indent=2)
        return Response(json_data, mimetype='application/json')
            
    except Exception as e:
        logger.error(f"Error in regenerate endpoint: {str(e)}")
        return jsonify({"error": "An unexpected error occurred during regeneration"}), 500
    

@app.route('/preview_get_word_document', methods=['POST'])
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
    else:
        abort(403)
    try:
        token = request.headers.get('Authorization')
        RICEFW_type = request.form.get('RICEFW_type')
        logger.info(f'-----------RICEFW_type-------------', RICEFW_type)
        RICEFW_name = request.form.get('RICEFW_name')
        logger.info(f'-----------RICEFW_name-------------', RICEFW_name)  
        project_id = request.form.get('project_id')
        logger.info(f'-----------project_id-------------', project_id) 
        username = request.form.get('username')
        if username == None:
            username = "system"
        logger.info(f'-----------username-------------', username)  
        try:
            template_link, template_type = document_count.get_template_link(token, project_id, RICEFW_type, module="FS")
            logger.info(f'-----------template_link-------------', template_link)
        except Exception as db_error:
            # Handle database exceptions separately
            traceback.print_exc()
            return jsonify({"error": "Database error", "details": str(db_error)}), 500
    
        if (template_type == "Client"):
            # function to map the client and TFS headings
            mapping_dict = document_count.get_mapping_headings(token, project_id, RICEFW_type, module = "FS")  
            mapping_dict = {k.lstrip(". ").strip(): v.lstrip(". ").strip() for k, v in mapping_dict.items() if k and v}             
        else:
            mapping_dict = None             
        logger.info(f'-------mapping_dict-----------------', mapping_dict)

        # extracting llm content 
        current_llm_content, session_id = document_count.get_content_sessionid_fromdb(token, project_id, RICEFW_name, RICEFW_type)
        logger.info(f'-------current_llm_content-----------------', current_llm_content)
        logger.info(f'-------session_id-----------------', session_id)
        # convert json string to dictionary
        current_json_data = json.loads(current_llm_content)
        
        #print('------json_section_contents-----',json_section_contents)
        if RICEFW_type.lower() == "form":
            word_local_path = form_regenerate.generate_word_document_form(token, current_json_data, RICEFW_type, project_id,template_type, mapping_dict, session_id, module = "FS")
        elif RICEFW_type.lower() == "conversion":
            word_local_path = conversion_regenerate.generate_word_document_conversion(token, current_json_data, RICEFW_type, project_id,template_type, mapping_dict, session_id, module = "FS")
        elif RICEFW_type.lower() == "enhancement":
            word_local_path = enhancement_regenerate.generate_word_document_enhancement(token, current_json_data, RICEFW_type, project_id,template_type, mapping_dict, session_id, module = "FS")
        elif RICEFW_type.lower() == "report":
            word_local_path = report_regenerate.generate_word_document_report(token, current_json_data, RICEFW_type, project_id,template_type, mapping_dict, session_id, module = "FS")
        elif RICEFW_type.lower() == "interface":
            word_local_path = interface_regenerate.generate_word_document_interface(token, current_json_data, RICEFW_type, project_id,template_type, mapping_dict, session_id, module = "FS")
        elif RICEFW_type.lower() == "workflow":
            word_local_path = workflow_regenerate.generate_word_document_workflow(token, current_json_data, RICEFW_type, project_id,template_type, mapping_dict, session_id, module = "FS")
        logger.info(f'-----word_local_path-----', word_local_path)
        output_word_filename  = os.path.basename(word_local_path)
        logger.info(f'-----output_word_filename -----', output_word_filename )

        # Extract 'content' as a list of dictionaries
        content = current_json_data.get('content', {})
        # extract dot code from process flow diagram dict
        pfd_dotcode = next((item["value"] for item in content if item.get("key") == 'Process Flow Diagram'), '{}')
        logger.info(f"--------pfd_dotcode-----: {pfd_dotcode}")
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

        '''
        # Clean up local SVG file
        if svg_local_path and os.path.exists(svg_local_path):
            os.remove(svg_local_path)
            print(f"Deleted temp SVG file: {svg_local_path}")

        # Clean up local Word file
        if os.path.exists(word_local_path):
            os.remove(word_local_path)
            print(f"Deleted temp Word file: {word_local_path}")
        '''
        # update document count in HANADB table
        document_count.insert_doccount(token, project_id, session_id,output_word_filename,username)
        document_count.update_doccount(token, project_id)

        # once the document is downloaded, delete the current, previous and raw data and update the status type to be "downloaded"
        document_count.delete_llmcontent_fromdb(token, project_id, RICEFW_name, RICEFW_type)
        # Return the ZIP to Angular UI
        return send_file(
            zip_buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f'FS_{RICEFW_type}_{session_id}.zip'
        )

    except Exception as e:
        return jsonify({"error": f"Failed to download file"}), 500

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
            if not isAuthorized:
                abort(403)
    else:
        abort(403)
    token = request.headers.get('Authorization')
    project_id = request.form.get('project_id')
    logger.info(f'-----------project_id-------------', project_id) 
    data = document_count.get_draft_list_fromdb(token, project_id)
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
            if not isAuthorized:
                abort(403)
    else:
        abort(403)
    token = request.headers.get('Authorization')
    project_id = request.form.get('project_id')
    logger.info(f'-----------project_id-------------', project_id)
    RICEFW_type = request.form.get('RICEFW_type')
    logger.info(f'-----------RICEFW_type-------------', RICEFW_type)
    RICEFW_name = request.form.get('RICEFW_name')
    logger.info(f'-----------RICEFW_name-------------', RICEFW_name)  
    response = document_count.get_draft_details_fromdb(token, project_id,RICEFW_type,RICEFW_name)
    # If json_section_contents and form_dictvalues is a string, parse it to dictionary
    logger.info(f'-------type----------', type(response))
    parsed_data = json.loads(response)
    # remove this character(^^) and return the response
    data = remove_symbol_from_dict(parsed_data)
    # Serialize back without changing key order
    json_data = json.dumps(data, sort_keys=False, indent=2)
    # Return as a proper JSON response
    return Response(json_data, mimetype='application/json')
    

    s3_key = request.args.get('file')
    #print('-----download_s3_key----------',s3_key )
    if not s3_key:
        return abort(400, "Missing 'file' parameter")

    try:
        if bucket_name:
            # Stream the file from object store
            response = s3_client.get_object(Bucket= bucket_name, Key=s3_key)
            file_data = response['Body'].read()
        else:
            # Azure Blob
            blob_url = f"{CONTAINER_URI}/{CONTAINER_NAME}/{s3_key}?{AZURE_STORAGE_ACCOUNT_KEY}"
            blob_client = BlobClient.from_blob_url(blob_url)
            file_data = blob_client.download_blob().readall()
            
        # Send file back to user
        return send_file(
            io.BytesIO(file_data),
            mimetype='image/svg+xml',
            as_attachment=True,
            download_name=s3_key.split("/")[-1]
        )

    except Exception as e:
        logger.error(f"An error occurred: {e}")
        return abort(500, "Error retrieving file")


@app.route('/s3fileupload', methods=['POST'])
def s3fileupload():
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
                BLOB_NAME = filename
                blob_client = BlobClient.from_blob_url(
                    f"{CONTAINER_URI}/{CONTAINER_NAME}/{BLOB_NAME}?{AZURE_STORAGE_ACCOUNT_KEY}")

                blob_client.upload_blob(file.stream, overwrite=True)
                uploaded_files.append(filename)
                logger.info(f"Uploaded '{filename}' as '{BLOB_NAME}' to container '{CONTAINER_NAME}'")
        
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
        return send_file(zip_buffer, download_name="files.zip", as_attachment=True)
    


if __name__ == '__main__':
     app.run(host='0.0.0.0', port=8080, debug=True)
