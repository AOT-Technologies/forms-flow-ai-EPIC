"""Report resource for displaying immudb audit logs with enhanced search and JSON viewer."""

import json
import re
import os
from flask import Blueprint, render_template_string, request, jsonify
from ..services.immudb_service import ImmudbService
import html

REPORT = Blueprint("report", __name__)

EHR_CONNECTOR_URL = os.getenv("EHR_CONNECTOR_URL", "http://localhost:8002").rstrip("/")

def find_key_value(data, target_keys):
    """Recursively search for values of target_keys in a dictionary or list."""
    if isinstance(data, dict):
        for key in target_keys:
            if key in data and data[key]:
                val = data[key]
                if isinstance(val, (str, int)):
                    return str(val)
                elif isinstance(val, dict) and "value" in val and isinstance(val["value"], (str, int)):
                    return str(val["value"])
        for value in data.values():
            found = find_key_value(value, target_keys)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = find_key_value(item, target_keys)
            if found:
                return found
    return None

def extract_patient_id(data):
    val = find_key_value(data, ["patientId", "patient_id", "patientIdInput"])
    if val:
        return val
    if isinstance(data, dict):
        patient_ref = None
        subject = data.get("subject")
        if isinstance(subject, dict):
            patient_ref = subject.get("reference")
        elif not patient_ref:
            patient_ref = data.get("patient")
        
        if isinstance(patient_ref, str):
            if patient_ref.startswith("Patient/"):
                return patient_ref.split("/")[-1]
            return patient_ref
            
        for v in data.values():
            found = extract_patient_id(v)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = extract_patient_id(item)
            if found:
                return found
    return None

def extract_docref_id(data):
    val = find_key_value(data, ["documentrefId", "docrefId", "documentref_id", "docref_id", "docrefIdInput"])
    if val:
        return val
    if isinstance(data, dict):
        if data.get("resourceType") == "DocumentReference" and isinstance(data.get("id"), str):
            return data["id"]
        for v in data.values():
            found = extract_docref_id(v)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = extract_docref_id(item)
            if found:
                return found
    return None

def extract_encounter_id(data):
    val = find_key_value(data, ["encounterId", "encounter_id", "encounterIdInput"])
    if val:
        return val
    if isinstance(data, dict):
        if data.get("resourceType") == "Encounter" and isinstance(data.get("id"), str):
            return data["id"]
        for v in data.values():
            found = extract_encounter_id(v)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = extract_encounter_id(item)
            if found:
                return found
    return None

def generate_ehr_links_html(req_str, res_str):
    """Parse request and response payloads, extract IDs, and return HTML links."""
    req_data = {}
    res_data = {}
    
    if req_str:
        try:
            req_data = json.loads(req_str)
        except Exception:
            pass
            
    if res_str:
        try:
            res_data = json.loads(res_str)
        except Exception:
            pass
            
    # Try to extract via explicitly provided _viewer_links first
    patient_id = None
    docref_id = None
    encounter_id = None
    
    def get_links_from_dict(d):
        if not isinstance(d, dict):
            return None
        if "_viewer_links" in d:
            return d["_viewer_links"]
        for v in d.values():
            if isinstance(v, dict):
                found = get_links_from_dict(v)
                if found:
                    return found
        return None
        
    vl = get_links_from_dict(req_data) or get_links_from_dict(res_data)
    if isinstance(vl, dict):
        pat_path = vl.get("patient_details")
        if pat_path and pat_path.startswith("/patient/"):
            patient_id = pat_path.split("/")[-1]
            
        doc_path = vl.get("documentref_details")
        if doc_path and doc_path.startswith("/documentref/"):
            docref_id = doc_path.split("/")[-1]
            
        enc_path = vl.get("encounter_details")
        if enc_path and enc_path.startswith("/encounter/"):
            encounter_id = enc_path.split("/")[-1]

    # Fallback to key-based extraction if not found in _viewer_links
    if not patient_id:
        patient_id = extract_patient_id(req_data) or extract_patient_id(res_data)
    if not docref_id:
        docref_id = extract_docref_id(req_data) or extract_docref_id(res_data)
    if not encounter_id:
        encounter_id = extract_encounter_id(req_data) or extract_encounter_id(res_data)
    
    links = []
    
    summary_items = []
    if patient_id:
        summary_items.append(f'👤 <strong>Patient ID:</strong> {patient_id}')
    
    first_name = find_key_value(req_data, ["firstName", "first_name"]) or find_key_value(res_data, ["firstName", "first_name"])
    last_name = find_key_value(req_data, ["lastName", "last_name"]) or find_key_value(res_data, ["lastName", "last_name"])
    mrn = find_key_value(req_data, ["medicalRecordNumber", "mrn"]) or find_key_value(res_data, ["medicalRecordNumber", "mrn"])
    
    if first_name or last_name:
        name = " ".join([x for x in (first_name, last_name) if x])
        summary_items.append(f'📝 <strong>Name:</strong> {name}')
    if mrn:
        summary_items.append(f'🔢 <strong>MRN:</strong> {mrn}')
        
    if summary_items:
        summary_html = '<div style="font-size:11px; color:#8b949e; line-height:1.5; margin-bottom:8px; border-bottom:1px solid #30363d; padding-bottom:6px; font-family:inherit;">' + "<br/>".join(summary_items) + '</div>'
        links.append(summary_html)
        
    if patient_id:
        links.append(
            f'<a href="{EHR_CONNECTOR_URL}/patient/{patient_id}" target="_blank" class="btn-ehr" style="display:inline-flex; align-items:center; gap:6px; background:#58a6ff; color:#0d1117; padding:4px 8px; border-radius:4px; font-size:11px; font-weight:600; text-decoration:none; margin:2px;"><i class="fas fa-user-injured"></i> View Patient</a>'
        )
        links.append(
            f'<a href="{EHR_CONNECTOR_URL}/documentref/patient/{patient_id}" target="_blank" class="btn-ehr" style="display:inline-flex; align-items:center; gap:6px; background:#3fb950; color:#0d1117; padding:4px 8px; border-radius:4px; font-size:11px; font-weight:600; text-decoration:none; margin:2px;"><i class="fas fa-file-medical"></i> Patient Docs</a>'
        )
        links.append(
            f'<a href="{EHR_CONNECTOR_URL}/encounter/patient/{patient_id}" target="_blank" class="btn-ehr" style="display:inline-flex; align-items:center; gap:6px; background:#a371f7; color:#0d1117; padding:4px 8px; border-radius:4px; font-size:11px; font-weight:600; text-decoration:none; margin:2px;"><i class="fas fa-hospital-user"></i> Patient Encounters</a>'
        )
        
    if docref_id:
        links.append(
            f'<a href="{EHR_CONNECTOR_URL}/documentref/{docref_id}" target="_blank" class="btn-ehr" style="display:inline-flex; align-items:center; gap:6px; background:#34d058; color:#0d1117; padding:4px 8px; border-radius:4px; font-size:11px; font-weight:600; text-decoration:none; margin:2px;"><i class="fas fa-file-alt"></i> View Consent</a>'
        )
        
    if encounter_id:
        links.append(
            f'<a href="{EHR_CONNECTOR_URL}/encounter/{encounter_id}" target="_blank" class="btn-ehr" style="display:inline-flex; align-items:center; gap:6px; background:#f97316; color:#0d1117; padding:4px 8px; border-radius:4px; font-size:11px; font-weight:600; text-decoration:none; margin:2px;"><i class="fas fa-notes-medical"></i> View Encounter</a>'
        )
        
    if not links:
        return '<span style="color:#6e7781; font-style:italic; font-size:11px;">No EHR Data</span>'
        
    return '<div style="display:flex; flex-direction:column; gap:4px; max-width:200px;">' + "".join(links) + '</div>'

# HTML template for server-side rendered report page
REPORT_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Audit Logs Report</title>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: #333;
            margin: 0;
            padding: 0;
            line-height: 1.6;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
            min-height: 100vh;
        }

        .header {
            background: white;
            padding: 40px;
            border-radius: 20px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            margin-bottom: 30px;
            backdrop-filter: blur(20px);
            background: rgba(255, 255, 255, 0.98);
            border: 1px solid rgba(255, 255, 255, 0.2);
            position: relative;
            overflow: hidden;
        }

        .header::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 4px;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 50%, #667eea 100%);
            background-size: 200% 100%;
            animation: gradientShift 3s ease-in-out infinite;
        }

        @keyframes gradientShift {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }

        .header h1 {
            color: #2c3e50;
            margin-bottom: 15px;
            font-size: 2.8rem;
            font-weight: 800;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            text-align: center;
            position: relative;
        }

        .header h1::after {
            content: '';
            position: absolute;
            bottom: -10px;
            left: 50%;
            transform: translateX(-50%);
            width: 100px;
            height: 3px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 2px;
        }

        .header .subtitle {
            color: #6c757d;
            font-size: 1.2rem;
            margin-bottom: 40px;
            text-align: center;
            font-weight: 400;
        }

        .search-form {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 30px;
            margin-bottom: 0;
            padding: 35px;
            background: linear-gradient(135deg, rgba(102, 126, 234, 0.05) 0%, rgba(118, 75, 162, 0.05) 100%);
            border-radius: 16px;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(102, 126, 234, 0.1);
            position: relative;
        }

        .search-form::before {
            content: '';
            position: absolute;
            top: -1px;
            left: -1px;
            right: -1px;
            bottom: -1px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 50%, #667eea 100%);
            border-radius: 16px;
            z-index: -1;
            opacity: 0.1;
        }

        .form-group {
            display: flex;
            flex-direction: column;
            position: relative;
            transition: transform 0.3s ease;
        }

        .form-group:hover {
            transform: translateY(-2px);
        }

        .form-group label {
            font-weight: 700;
            margin-bottom: 12px;
            color: #495057;
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .form-group label i {
            color: #667eea;
            font-size: 0.9rem;
        }

        .form-group input, .form-group select {
            padding: 16px 20px;
            border: 2px solid rgba(102, 126, 234, 0.15);
            border-radius: 12px;
            font-size: 14px;
            transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        }

        .form-group input:focus, .form-group select:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 4px rgba(102, 126, 234, 0.15), 0 8px 25px rgba(102, 126, 234, 0.2);
            transform: translateY(-3px);
            background: rgba(255, 255, 255, 1);
        }

        .form-group input::placeholder {
            color: #adb5bd;
            font-style: italic;
        }

        .button-group {
            display: flex;
            gap: 20px;
            align-items: center;
            justify-content: center;
            grid-column: span 2;
            margin-top: 20px;
        }

        .btn {
            padding: 16px 32px;
            border: none;
            border-radius: 12px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 700;
            transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
            text-transform: uppercase;
            letter-spacing: 0.8px;
            display: inline-flex;
            align-items: center;
            gap: 12px;
            position: relative;
            overflow: hidden;
            min-width: 140px;
            justify-content: center;
        }

        .btn::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.2), transparent);
            transition: left 0.5s;
        }

        .btn:hover::before {
            left: 100%;
        }

        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            box-shadow: 0 8px 25px rgba(102, 126, 234, 0.4);
        }

        .btn-primary:hover {
            transform: translateY(-3px);
            box-shadow: 0 12px 35px rgba(102, 126, 234, 0.5);
        }

        .btn-primary:active {
            transform: translateY(-1px);
        }

        .btn-secondary {
            background: linear-gradient(135deg, #6c757d 0%, #495057 100%);
            color: white;
            box-shadow: 0 8px 25px rgba(108, 117, 125, 0.4);
        }

        .btn-secondary:hover {
            background: linear-gradient(135deg, #5a6268 0%, #343a40 100%);
            transform: translateY(-3px);
            box-shadow: 0 12px 35px rgba(108, 117, 125, 0.5);
        }

        .btn-secondary:active {
            transform: translateY(-1px);
        }

        .results {
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            overflow: hidden;
            backdrop-filter: blur(20px);
            background: rgba(255, 255, 255, 0.98);
            border: 1px solid rgba(255, 255, 255, 0.2);
            position: relative;
            min-height: 200px;
        }

        /* Loading Overlay */
        .loading-overlay {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(255, 255, 255, 0.8);
            backdrop-filter: blur(3px);
            display: none;
            justify-content: center;
            align-items: center;
            z-index: 10;
        }
        
        .loading-overlay.active {
            display: flex;
        }

        .spinner {
            width: 50px;
            height: 50px;
            border: 4px solid rgba(102, 126, 234, 0.1);
            border-radius: 50%;
            border-top: 4px solid #667eea;
            animation: spin 1s linear infinite;
        }

        .btn-ehr {
            transition: all 0.2s ease-in-out;
            box-shadow: 0 1px 3px rgba(0,0,0,0.15);
        }
        .btn-ehr:hover {
            transform: translateY(-1px);
            box-shadow: 0 3px 6px rgba(0,0,0,0.25);
            filter: brightness(0.9);
        }

        .results-header {
            padding: 25px 35px;
            background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
            border-bottom: 1px solid #dee2e6;
            display: flex;
            justify-content: space-between;
            align-items: center;
            position: relative;
        }

        .results-header::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 50%, #667eea 100%);
            background-size: 200% 100%;
            animation: gradientShift 3s ease-in-out infinite;
        }

        .results-count {
            font-weight: 700;
            color: #495057;
            font-size: 1.2rem;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .table-container {
            overflow-x: auto;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            background: rgba(255, 255, 255, 0.98);
            border-radius: 0;
            overflow: hidden;
        }

        th, td {
            padding: 20px 18px;
            text-align: left;
            border-bottom: 1px solid rgba(233, 236, 239, 0.8);
            position: relative;
        }

        th {
            background: linear-gradient(135deg, rgba(102, 126, 234, 0.12) 0%, rgba(118, 75, 162, 0.12) 100%);
            font-weight: 700;
            color: #495057;
            position: sticky;
            top: 0;
            text-transform: uppercase;
            font-size: 0.85rem;
            letter-spacing: 0.8px;
            backdrop-filter: blur(20px);
            border-bottom: 2px solid rgba(102, 126, 234, 0.2);
        }

        tr:hover {
            background: linear-gradient(135deg, rgba(102, 126, 234, 0.08) 0%, rgba(118, 75, 162, 0.08) 100%);
            transform: scale(1.005);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.1);
        }

        tr:nth-child(even) {
            background: rgba(248, 249, 250, 0.5);
        }

        tr:nth-child(even):hover {
            background: linear-gradient(135deg, rgba(102, 126, 234, 0.08) 0%, rgba(118, 75, 162, 0.08) 100%);
        }

        .json-preview-card {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: linear-gradient(135deg, rgba(102, 126, 234, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%);
            color: #764ba2;
            padding: 8px 16px;
            border-radius: 20px;
            border: 1px solid rgba(118, 75, 162, 0.2);
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            user-select: none;
            white-space: nowrap;
        }

        .json-preview-card:hover {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(118, 75, 162, 0.25);
            border-color: transparent;
        }

        .json-preview-card i {
            font-size: 14px;
        }

        /* Modal Tabs Styling */
        .modal-tabs {
            display: flex;
            background: #f8f9fa;
            border-bottom: 1px solid #dee2e6;
            padding: 0 24px;
            margin-top: -16px;
            margin-bottom: 16px;
        }

        .tab-btn {
            background: none;
            border: none;
            outline: none;
            padding: 12px 20px;
            font-size: 14px;
            font-weight: 600;
            color: #495057;
            cursor: pointer;
            transition: all 0.2s ease;
            border-bottom: 3px solid transparent;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }

        .tab-btn:hover {
            color: #764ba2;
        }

        .tab-btn.active {
            color: #764ba2;
            border-bottom-color: #764ba2;
        }

        .tab-pane {
            display: none;
        }

        .tab-pane.active-pane {
            display: block;
            animation: fadeIn 0.3s ease;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(5px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* Summary Table Styling */
        .summary-table-container {
            padding: 8px 0;
            max-height: 450px;
            overflow-y: auto;
        }

        .summary-table {
            width: 100%;
            border-collapse: collapse;
            font-family: inherit;
            background: #ffffff;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid #e9ecef;
        }

        .summary-table th, .summary-table td {
            padding: 12px 16px;
            text-align: left;
            border-bottom: 1px solid #f1f3f5;
        }

        .summary-table th {
            background-color: #f8f9fa;
            font-weight: 600;
            color: #495057;
            width: 35%;
        }

        .summary-table tr:hover {
            background-color: #f8f9fa;
        }

        .summary-table td {
            color: #212529;
            word-break: break-all;
        }

        .summary-badge {
            background-color: rgba(102, 126, 234, 0.1);
            color: #667eea;
            padding: 4px 8px;
            border-radius: 4px;
            font-weight: 600;
            font-size: 11px;
            display: inline-block;
        }

        .summary-badge-green {
            background-color: rgba(40, 167, 69, 0.1);
            color: #28a745;
            padding: 4px 8px;
            border-radius: 4px;
            font-weight: 600;
            font-size: 11px;
            display: inline-block;
        }
        }

        .see-more-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(40, 167, 69, 0.4);
        }

        .see-more-btn:active {
            transform: translateY(0);
        }

        .pagination {
            padding: 20px 30px;
            background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
            border-top: 1px solid #dee2e6;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .pagination-info {
            color: #6c757d;
            font-size: 14px;
        }

        .pagination-controls {
            display: flex;
            gap: 8px;
        }

        .pagination-controls button {
            padding: 8px 12px;
            border: 1px solid #dee2e6;
            background: white;
            cursor: pointer;
            border-radius: 6px;
            transition: all 0.3s ease;
        }

        .pagination-controls button:hover:not(:disabled) {
            background: #667eea;
            color: white;
            border-color: #667eea;
            transform: translateY(-1px);
        }

        .pagination-controls button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .pagination-controls button.active {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border-color: #667eea;
        }

        .no-results {
            text-align: center;
            padding: 80px 40px;
            color: #6c757d;
            background: rgba(255, 255, 255, 0.95);
            border-radius: 16px;
            margin: 20px 0;
            display: none; /* Hidden by default, toggled via JS or server */
        }
        
        /* Show when container has class empty */
        .results.empty .table-container, 
        .results.empty .pagination {
            display: none;
        }
        
        .results.empty .no-results {
            display: block;
        }

        .no-results i {
            font-size: 4rem;
            margin-bottom: 25px;
            color: #dee2e6;
            opacity: 0.7;
        }

        .no-results h3 {
            color: #495057;
            margin-bottom: 15px;
            font-size: 1.5rem;
        }

        .no-results p {
            margin-bottom: 10px;
            font-size: 1.1rem;
            line-height: 1.6;
        }

        .search-suggestions {
            background: rgba(102, 126, 234, 0.1);
            border-radius: 12px;
            padding: 20px;
            margin-top: 20px;
            border-left: 4px solid #667eea;
        }

        .search-suggestions h4 {
            color: #667eea;
            margin-bottom: 15px;
            font-size: 1.1rem;
        }

        .search-suggestions ul {
            text-align: left;
            list-style: none;
            padding: 0;
        }

        .search-suggestions li {
            margin-bottom: 8px;
            padding: 8px 12px;
            background: rgba(255, 255, 255, 0.8);
            border-radius: 6px;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 0.9rem;
        }

        .loading {
            text-align: center;
            padding: 40px;
            color: #6c757d;
        }

        .loading i {
            font-size: 2rem;
            animation: spin 1s linear infinite;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .error {
            background: linear-gradient(135deg, #f8d7da 0%, #f5c6cb 100%);
            color: #721c24;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            border-left: 4px solid #dc3545;
        }

        /* Highlighting */
        .highlight {
            background-color: yellow;
            font-weight: bold;
        }

        /* Modal Styles */
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.5);
            backdrop-filter: blur(5px);
        }

        .modal-content {
            background-color: white;
            margin: 2% auto;
            padding: 0;
            border-radius: 16px;
            width: 95%;
            max-width: 1200px;
            max-height: 95vh;
            overflow: hidden;
            box-shadow: 0 25px 80px rgba(0,0,0,0.15);
            animation: modalSlideIn 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
        }

        @keyframes modalSlideIn {
            from {
                transform: translateY(-50px);
                opacity: 0;
            }
            to {
                transform: translateY(0);
                opacity: 1;
            }
        }

        .modal-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .modal-header h2 {
            margin: 0;
            font-size: 1.5rem;
        }

        .close {
            color: white;
            font-size: 28px;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s ease;
        }

        .close:hover {
            transform: rotate(90deg);
        }

        .modal-body {
            padding: 20px;
            max-height: 70vh;
            overflow-y: auto;
        }

        /* Enhanced JSON Tree Styles */
        .json-tree {
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', 'Consolas', monospace;
            font-size: 14px;
            line-height: 1.6;
            background: #f8f9fa;
            border-radius: 8px;
            padding: 20px;
            border: 1px solid #e9ecef;
            overflow: auto;
            max-height: 60vh;
        }

        .json-node {
            margin-left: 0;
            position: relative;
        }

        .json-node .json-node {
            margin-left: 24px;
            border-left: 1px dashed #dee2e6;
            padding-left: 8px;
        }

        .json-key {
            color: #0969da;
            font-weight: 600;
            margin-right: 6px;
        }

        .json-string {
            color: #032f62;
        }

        .json-number {
            color: #8250df;
            font-weight: 500;
        }

        .json-boolean {
            color: #cf222e;
            font-weight: 600;
        }

        .json-null {
            color: #6e7781;
            font-style: italic;
        }

        .json-toggle {
            cursor: pointer;
            user-select: none;
            color: #656d76;
            margin-right: 8px;
            transition: all 0.2s ease;
            display: inline-block;
            width: 16px;
            height: 16px;
            position: relative;
            font-size: 12px;
            font-weight: bold;
        }

        .json-toggle:hover {
            color: #0969da;
            transform: scale(1.1);
        }

        .json-toggle.collapsed::before {
            content: '▶';
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
        }

        .json-toggle:not(.collapsed)::before {
            content: '▼';
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
        }

        .json-collapsed {
            display: none;
        }

        .json-bracket {
            color: #24292f;
            font-weight: 600;
        }

        .json-comma {
            color: #656d76;
            margin-right: 4px;
        }

        .json-controls {
            display: flex;
            gap: 10px;
            margin-bottom: 15px;
            flex-wrap: wrap;
        }

        .json-btn {
            background: linear-gradient(135deg, #f6f8fa 0%, #e9ecef 100%);
            color: #24292f;
            border: 1px solid #d0d7de;
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 12px;
            cursor: pointer;
            transition: all 0.3s ease;
            font-family: inherit;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }

        .json-btn:hover {
            background: linear-gradient(135deg, #f3f4f6 0%, #e5e7eb 100%);
            border-color: #9ca3af;
            transform: translateY(-1px);
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }

        .json-btn:active {
            transform: translateY(0);
        }

        .json-btn i {
            font-size: 10px;
        }

        .copy-btn {
            background: linear-gradient(135deg, #0969da 0%, #0550ae 100%);
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 12px;
            cursor: pointer;
            margin-bottom: 15px;
            transition: all 0.3s ease;
            font-family: inherit;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }

        .copy-btn:hover {
            background: linear-gradient(135deg, #0550ae 0%, #033d8b 100%);
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(9, 105, 218, 0.3);
        }

        .copy-btn.copied {
            background: linear-gradient(135deg, #1a7f37 0%, #0d5f2d 100%);
        }

        .json-line {
            display: block;
            padding: 2px 0;
            transition: background-color 0.2s ease;
        }

        .json-line:hover {
            background-color: rgba(9, 105, 218, 0.05);
            border-radius: 4px;
        }

        .json-summary {
            color: #6e7781;
            font-style: italic;
            font-size: 0.9em;
            margin-left: 8px;
        }

        .json-modal-content {
            background: white;
            margin: 2% auto;
            padding: 0;
            border-radius: 16px;
            width: 95%;
            max-width: 1200px;
            max-height: 95vh;
            overflow: hidden;
            box-shadow: 0 25px 80px rgba(0,0,0,0.15);
            animation: modalSlideIn 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1><i class="fas fa-chart-line"></i> Audit Logs Report</h1>
            <p class="subtitle">Search and analyze audit  data with advanced filtering capabilities</p>
            <form id="searchForm" class="search-form">
                <div class="form-group">
                    <label for="tenant_id"><i class="fas fa-building"></i> Tenant ID</label>
                    <input type="text" id="tenant_id" name="tenant_id" value="{{ search_params.get('tenant_id', '') }}" placeholder="Enter tenant ID">
                </div>
                <div class="form-group">
                    <label for="event_name"><i class="fas fa-event"></i> Event Name</label>
                    <input type="text" id="event_name" name="event_name" value="{{ search_params.get('event_name', '') }}" placeholder="Enter event name">
                </div>
                <div class="form-group">
                    <label for="user_id"><i class="fas fa-user"></i> User ID</label>
                    <input type="text" id="user_id" name="user_id" value="{{ search_params.get('user_id', '') }}" placeholder="Enter user ID">
                </div>
                <div class="form-group">
                    <label for="date_from"><i class="fas fa-calendar-alt"></i> Date From</label>
                    <input type="datetime-local" id="date_from" name="date_from" value="{{ search_params.get('date_from', '') }}">
                </div>
                <div class="form-group">
                    <label for="date_to"><i class="fas fa-calendar-alt"></i> Date To</label>
                    <input type="datetime-local" id="date_to" name="date_to" value="{{ search_params.get('date_to', '') }}">
                </div>
                <div class="form-group">
                    <label for="search_text"><i class="fas fa-search"></i> Search in Data</label>
                    <input type="text" id="search_text" name="search_text" value="{{ search_params.get('search_text', '') }}" placeholder="Search in request/response data">
                </div>
                <div class="form-group">
                    <label for="per_page"><i class="fas fa-list"></i> Per Page</label>
                    <select id="per_page" name="per_page">
                        <option value="10" {% if search_params.get('per_page') == '10' %}selected{% endif %}>10</option>
                        <option value="25" {% if search_params.get('per_page') == '25' %}selected{% endif %}>25</option>
                        <option value="50" {% if search_params.get('per_page') == '50' %}selected{% endif %}>50</option>
                        <option value="100" {% if search_params.get('per_page') == '100' %}selected{% endif %}>100</option>
                    </select>
                </div>
                <div class="button-group">
                    <button type="submit" class="btn btn-primary">
                        <i class="fas fa-search"></i> Search
                    </button>
                    <button type="button" class="btn btn-secondary" onclick="clearForm()">
                        <i class="fas fa-times"></i> Clear
                    </button>
                </div>
            </form>
        </div>

        {% if error %}
        <div class="error"><i class="fas fa-exclamation-triangle"></i> {{ error }}</div>
        {% endif %}

        <div class="results {% if not results and not error %}empty{% endif %}" id="resultsContainer">
            <div class="loading-overlay" id="loadingOverlay">
                <div class="spinner"></div>
            </div>
            
            <div class="results-header">
                <div class="results-count" id="resultsCount">
                    {% if total_count > 0 %}
                        <i class="fas fa-database"></i> Showing {{ start_item }}-{{ end_item }} of {{ total_count }} results
                    {% else %}
                        <i class="fas fa-info-circle"></i> No results found
                    {% endif %}
                </div>
            </div>

            <div class="table-container">
                <table id="resultsTable">
                    <thead>
                        <tr>
                            <th><i class="fas fa-hashtag"></i> ID</th>
                            <th><i class="fas fa-clock"></i> Created At</th>
                            <th><i class="fas fa-building"></i> Tenant ID</th>
                            <th><i class="fas fa-event"></i> Event Name</th>
                            <th><i class="fas fa-user"></i> User ID</th>
                            <th><i class="fas fa-upload"></i> Request Data</th>
                            <th><i class="fas fa-download"></i> Response Data</th>
                            <th><i class="fas fa-link"></i> EHR Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% if results %}
                            {% for row in results %}
                            <tr>
                                <td><strong>{{ row[0] }}</strong></td>
                                <td>{{ row[6] }}</td>
                                <td>{{ row[1] or '' }}</td>
                                <td>{{ row[2] or '' }}</td>
                                <td>{{ row[3] or '' }}</td>
                                <td>
                                    {% if row[4] %}
                                    <div class="json-preview-card" onclick="showJsonModal('Request Data', '{{ row[4] | replace('"', '\\"') | replace("'", "\\'") | replace('\n', '\\n') | replace('\r', '\\r') }}')">
                                        <i class="fas fa-upload icon"></i> <span>View Request</span>
                                    </div>
                                    {% else %}
                                    <span class="badge badge-secondary">No Data</span>
                                    {% endif %}
                                </td>
                                <td>
                                    {% if row[5] %}
                                    <div class="json-preview-card" onclick="showJsonModal('Response Data', '{{ row[5] | replace('"', '\\"') | replace("'", "\\'") | replace('\n', '\\n') | replace('\r', '\\r') }}')">
                                        <i class="fas fa-download icon"></i> <span>View Response</span>
                                    </div>
                                    {% else %}
                                    <span class="badge badge-secondary">No Data</span>
                                    {% endif %}
                                </td>
                                <td>
                                    {{ row[7] | safe if row[7] else '' }}
                                </td>
                            </tr>
                            {% endfor %}
                        {% endif %}
                    </tbody>
                </table>
            </div>

            <div class="pagination" id="paginationContainer">
                {% if total_pages > 1 %}
                <div class="pagination-info">
                    <i class="fas fa-file-alt"></i> Page {{ current_page }} of {{ total_pages }}
                </div>
                <div class="pagination-controls">
                    {% if current_page > 1 %}
                        <button onclick="goToPage({{ current_page - 1 }})"><i class="fas fa-chevron-left"></i> Previous</button>
                    {% endif %}

                    {% for page_num in page_range %}
                        {% if page_num == current_page %}
                            <button class="active">{{ page_num }}</button>
                        {% elif page_num == '...' %}
                            <button disabled>...</button>
                        {% else %}
                            <button onclick="goToPage({{ page_num }})">{{ page_num }}</button>
                        {% endif %}
                    {% endfor %}

                    {% if current_page < total_pages %}
                        <button onclick="goToPage({{ current_page + 1 }})">Next <i class="fas fa-chevron-right"></i></button>
                    {% endif %}
                </div>
                {% endif %}
            </div>

            <div class="no-results">
                <i class="fas fa-search"></i>
                <h3>No audit logs found</h3>
                <p>
                    No audit logs found matching your search criteria.
                </p>
                <div class="search-suggestions">
                    <h4><i class="fas fa-lightbulb"></i> Search Tips</h4>
                    <ul>
                        <li>Try using partial matches (e.g., "user" instead of full username)</li>
                        <li>Check for case sensitivity - try different variations</li>
                        <li>Verify the date range includes your expected timeframe</li>
                        <li>Try clearing some filters to broaden your search</li>
                        <li>Ensure the tenant, event, or user ID exists in the system</li>
                    </ul>
                </div>
            </div>
        </div>
    </div>

    <!-- JSON Modal -->
    <div id="jsonModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h2 id="modalTitle"><i class="fas fa-code"></i> JSON Data</h2>
                <span class="close" onclick="closeJsonModal()">&times;</span>
            </div>
            <!-- Tab Navigation -->
            <div class="modal-tabs">
                <button id="summaryTabBtn" class="tab-btn active" onclick="switchModalTab(this, 'summaryTab')">
                    <i class="fas fa-list-ul"></i> Summary
                </button>
                <button id="rawJsonTabBtn" class="tab-btn" onclick="switchModalTab(this, 'rawJsonTab')">
                    <i class="fas fa-code"></i> Raw JSON
                </button>
            </div>
            <div class="modal-body">
                <!-- Summary Tab Pane -->
                <div id="summaryTab" class="tab-pane active-pane">
                    <div id="summaryTableContainer" class="summary-table-container"></div>
                </div>
                
                <!-- Raw JSON Tab Pane -->
                <div id="rawJsonTab" class="tab-pane">
                    <div class="json-controls">
                        <button class="copy-btn" onclick="copyJsonToClipboard()">
                            <i class="fas fa-copy"></i> Copy JSON
                        </button>
                        <button class="json-btn" onclick="expandAllJson()">
                            <i class="fas fa-expand-alt"></i> Expand All
                        </button>
                        <button class="json-btn" onclick="collapseAllJson()">
                            <i class="fas fa-compress-alt"></i> Collapse All
                        </button>
                        <button class="json-btn" onclick="formatJson()">
                            <i class="fas fa-magic"></i> Format
                        </button>
                    </div>
                    <div id="jsonContent" class="json-tree"></div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let currentJsonData = '';
        let searchTimeout;
        // Global variable to store current API results for modal access
        let currentApiResults = [];

        function clearForm() {
            document.getElementById('searchForm').reset();
            // Trigger a search with empty params to clear results/reset to defaults without page reload
            goToPage(1);
            // Optionally clean URL
            window.history.pushState({}, '', '/report');
        }

        function goToPage(page) {
            // Updated to fetch data instead of redirecting
            fetchResults(page);
        }

        // Intercept form submission
        document.getElementById('searchForm').addEventListener('submit', function(e) {
            e.preventDefault();
            fetchResults(1);
        });

        function fetchResults(page) {
            const form = document.getElementById('searchForm');
            const formData = new FormData(form);
            const params = new URLSearchParams(formData);
            params.set('page', page);
            
            // Show loading
            const loadingOverlay = document.getElementById('loadingOverlay');
            if (loadingOverlay) loadingOverlay.classList.add('active');
            
            // Update URL without reload
            window.history.pushState({}, '', '/report?' + params.toString());

            fetch('/report/api/search?' + params.toString())
                .then(response => {
                    if (!response.ok) throw new Error('Network response was not ok');
                    return response.json();
                })
                .then(data => {
                    // Store results for modal access
                    currentApiResults = data.results || [];
                    
                    updateResultsHeader(data);
                    updateTable(data);
                    updatePagination(data);
                    
                    // Toggle empty state/results
                    const resultsContainer = document.getElementById('resultsContainer');
                    const hasResults = data.total_count > 0;
                    
                    if (hasResults) {
                        resultsContainer.classList.remove('empty');
                    } else {
                        resultsContainer.classList.add('empty');
                    }
                })
                .catch(error => {
                    console.error('Error:', error);
                    // Could show an error message in the UI here
                })
                .finally(() => {
                    if (loadingOverlay) loadingOverlay.classList.remove('active');
                });
        }

        function updateResultsHeader(data) {
            const container = document.getElementById('resultsCount');
            if (data.total_count > 0) {
                container.innerHTML = `<i class="fas fa-database"></i> Showing ${data.start_item}-${data.end_item} of ${data.total_count} results`;
            } else {
                container.innerHTML = `<i class="fas fa-info-circle"></i> No results found`;
            }
        }

        function updateTable(data) {
            const tbody = document.querySelector('#resultsTable tbody');
            tbody.innerHTML = '';

            if (!data.results || data.results.length === 0) return;

            data.results.forEach((row, index) => {
                const tr = document.createElement('tr');
                
                // Helper to generate the JSON cell content
                const createJsonCell = (displayHtml, type) => {
                    const content = displayHtml || '';
                    if (!content || content.trim() === '') {
                        return '<span class="badge badge-secondary">No Data</span>';
                    }
                    
                    const iconClass = type === 'request' ? 'fa-upload' : 'fa-download';
                    const btnText = type === 'request' ? 'View Request' : 'View Response';
                    
                    return `
                        <div class="json-preview-card" onclick="showAjaxJsonModal(${index}, '${type}')">
                            <i class="fas ${iconClass} icon"></i> <span>${btnText}</span>
                        </div>
                    `;
                };

                tr.innerHTML = `
                    <td><strong>${row.id}</strong></td>
                    <td>${row.created_at || ''}</td>
                    <td>${row.tenant_id || ''}</td>
                    <td>${row.event_name || ''}</td>
                    <td>${row.user_id || ''}</td>
                    <td>${createJsonCell(row.request_data, 'request')}</td>
                    <td>${createJsonCell(row.response_data, 'response')}</td>
                    <td>${row.ehr_links_html || ''}</td>
                `;
                tbody.appendChild(tr);
            });
        }

        function updatePagination(data) {
            const container = document.getElementById('paginationContainer');
            if (data.total_pages <= 1) {
                container.innerHTML = '';
                return;
            }

            let html = `
                <div class="pagination-info">
                    <i class="fas fa-file-alt"></i> Page ${data.current_page} of ${data.total_pages}
                </div>
                <div class="pagination-controls">
            `;

            if (data.current_page > 1) {
                html += `<button onclick="goToPage(${data.current_page - 1})"><i class="fas fa-chevron-left"></i> Previous</button>`;
            }

            // Simple logic for page numbers similar to Python one
            const total = data.total_pages;
            const current = data.current_page;
            let range = [];
            
            if (total <= 5) {
                for(let i=1; i<=total; i++) range.push(i);
            } else {
                if (current <= 3) {
                    range = [1, 2, 3, 4, '...', total];
                } else if (current >= total - 2) {
                    range = [1, '...', total-3, total-2, total-1, total];
                } else {
                    range = [1, '...', current-1, current, current+1, '...', total];
                }
            }

            range.forEach(p => {
                if (p === current) {
                    html += `<button class="active">${p}</button>`;
                } else if (p === '...') {
                    html += `<button disabled>...</button>`;
                } else {
                    html += `<button onclick="goToPage(${p})">${p}</button>`;
                }
            });

            if (data.current_page < data.total_pages) {
                html += `<button onclick="goToPage(${data.current_page + 1})">Next <i class="fas fa-chevron-right"></i></button>`;
            }

            html += `</div>`;
            container.innerHTML = html;
        }

        // Add real-time search feedback
        function addSearchFeedback() {
            const searchInputs = document.querySelectorAll('input[type="text"], input[type="datetime-local"]');
            searchInputs.forEach(input => {
                input.addEventListener('input', function() {
                    clearTimeout(searchTimeout);
                    const searchIcon = this.parentElement.querySelector('i');
                    if (searchIcon) {
                        searchIcon.className = 'fas fa-spinner fa-spin';
                    }
                    
                    searchTimeout = setTimeout(() => {
                        if (searchIcon) {
                            searchIcon.className = searchIcon.className.replace('fa-spinner fa-spin', 'fa-search');
                        }
                    }, 500);
                });

                input.addEventListener('focus', function() {
                    this.parentElement.style.transform = 'scale(1.02)';
                });

                input.addEventListener('blur', function() {
                    this.parentElement.style.transform = 'scale(1)';
                });
            });
        }

        // Add keyboard shortcuts
        function addKeyboardShortcuts() {
            document.addEventListener('keydown', function(event) {
                // Ctrl/Cmd + K to focus search
                if ((event.ctrlKey || event.metaKey) && event.key === 'k') {
                    event.preventDefault();
                    document.getElementById('search_text')?.focus();
                }
                
                // Escape to clear form
                if (event.key === 'Escape' && !event.target.matches('input, textarea')) {
                    // Logic to clear
                }
            });
        }

        // Initialize enhancements
        document.addEventListener('DOMContentLoaded', function() {
            addSearchFeedback();
            addKeyboardShortcuts();
            
            // Add smooth scroll behavior
            document.querySelectorAll('a[href^="#"]').forEach(anchor => {
                anchor.addEventListener('click', function (e) {
                    e.preventDefault();
                    const target = document.querySelector(this.getAttribute('href'));
                    if (target) {
                        target.scrollIntoView({ behavior: 'smooth' });
                    }
                });
            });
        });

        function unescapeHtml(text) {
            const doc = new DOMParser().parseFromString(text, 'text/html');
            return doc.documentElement.textContent;
        }

        function switchModalTab(btn, paneId) {
            // Deactivate all tab buttons
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            // Activate clicked button
            btn.classList.add('active');
            
            // Hide all tab panes
            document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active-pane'));
            // Show targeted pane
            document.getElementById(paneId).classList.add('active-pane');
        }

        function buildSummaryTable(data) {
            const container = document.getElementById('summaryTableContainer');
            if (!data) {
                container.innerHTML = '<div style="color: #6c757d; padding: 20px; text-align: center;">No summary data available.</div>';
                return;
            }
            
            let flatData = {};
            
            function flatten(obj, prefix = '') {
                if (obj === null) {
                    flatData[prefix] = null;
                    return;
                }
                if (typeof obj !== 'object') {
                    flatData[prefix] = obj;
                    return;
                }
                
                // If it is a Camunda-like variable structure: {"value": X, "type": Y}
                if (typeof obj === 'object' && 'value' in obj && Object.keys(obj).length <= 3) {
                    flatData[prefix] = obj.value;
                    return;
                }
                
                for (let k in obj) {
                    if (obj.hasOwnProperty(k)) {
                        let newKey = prefix ? prefix + '.' + k : k;
                        // Special handling for the main form "data" block
                        if (k === 'data' && typeof obj[k] === 'object' && obj[k] !== null) {
                            flatten(obj[k], ''); // Merge form fields at root of summary for readability
                        } else {
                            flatten(obj[k], newKey);
                        }
                    }
                }
            }
            
            flatten(data);
            
            if (Object.keys(flatData).length === 0) {
                container.innerHTML = '<div style="color: #6c757d; padding: 20px; text-align: center;">Empty payload.</div>';
                return;
            }
            
            let html = '<table class="summary-table">';
            html += '<thead><tr><th>Property Name</th><th>Value</th></tr></thead>';
            html += '<tbody>';
            
            for (let key in flatData) {
                let val = flatData[key];
                if (val === undefined || val === null) val = 'null';
                
                // Format keys to look human-readable (e.g. firstName -> First Name)
                let label = key;
                if (label.includes('.')) {
                    label = label.split('.').pop();
                }
                label = label.replace(/([A-Z])/g, ' $1') // insert spaces before caps
                             .replace(/^./, str => str.toUpperCase()); // capitalize first letter
                
                // Apply badges for specific keys
                let valHtml = '';
                if (typeof val === 'boolean') {
                    valHtml = val ? '<span class="summary-badge-green">True</span>' : '<span class="summary-badge">False</span>';
                } else if (key.toLowerCase().includes('url') && String(val).startsWith('http')) {
                    valHtml = `<a href="${val}" target="_blank" style="color: #667eea; text-decoration: underline;">${val}</a>`;
                } else if (key.toLowerCase().includes('id') || key.toLowerCase().includes('key') || key.toLowerCase().includes('token')) {
                    valHtml = `<span class="summary-badge">${escapeHtml(String(val))}</span>`;
                } else {
                    valHtml = escapeHtml(String(val));
                }
                
                html += `<tr><td><strong>${escapeHtml(label)}</strong></td><td>${valHtml}</td></tr>`;
            }
            
            html += '</tbody></table>';
            container.innerHTML = html;
        }

        // Function used by server-side rendered buttons
        function showJsonModal(title, jsonData) {
            const modal = document.getElementById('jsonModal');
            const modalTitle = document.getElementById('modalTitle');
            const jsonContent = document.getElementById('jsonContent');

            modalTitle.innerHTML = '<i class="fas fa-code"></i> ' + title;
            
            // Unescape HTML entities in the JSON data before storing and parsing
            const unescapedJsonData = unescapeHtml(jsonData);
            currentJsonData = unescapedJsonData;

            // Reset tab navigation state to Summary tab
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.getElementById('summaryTabBtn').classList.add('active');
            document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active-pane'));
            document.getElementById('summaryTab').classList.add('active-pane');

            try {
                const parsedData = JSON.parse(unescapedJsonData);
                buildSummaryTable(parsedData);
                jsonContent.innerHTML = renderJsonTree(parsedData);
            } catch (e) {
                // If parsing fails, display the unescaped string as plain text
                document.getElementById('summaryTableContainer').innerHTML = '<div style="color: #6c757d; padding: 20px; text-align: center;">Not a valid JSON payload.</div>';
                jsonContent.innerHTML = '<div class="json-string">' + escapeHtml(unescapedJsonData) + '</div>';
            }

            modal.style.display = 'block';
            document.body.style.overflow = 'hidden';
        }

        // Function used by AJAX rendered buttons
        function showAjaxJsonModal(index, type) {
            const rowData = currentApiResults[index];
            if (!rowData) return;

            let title = type === 'request' ? 'Request Data' : 'Response Data';
            // Use the raw data sent by API, not the HTML version
            let rawData = type === 'request' ? rowData.raw_request_data : rowData.raw_response_data;
            
            // Re-use existing function logic
            showJsonModal(title, rawData);
        }

        function closeJsonModal() {
            const modal = document.getElementById('jsonModal');
            modal.style.display = 'none';
            document.body.style.overflow = 'auto';
        }

        function renderJsonTree(obj, level = 0, path = '') {
            if (obj === null) {
                return '<span class="json-line"><span class="json-null">null</span></span>';
            }

            if (typeof obj === 'string') {
                return '<span class="json-line"><span class="json-string">"' + escapeHtml(obj) + '"</span></span>';
            }

            if (typeof obj === 'number') {
                return '<span class="json-line"><span class="json-number">' + obj + '</span></span>';
            }

            if (typeof obj === 'boolean') {
                return '<span class="json-line"><span class="json-boolean">' + obj + '</span></span>';
            }

            if (Array.isArray(obj)) {
                if (obj.length === 0) {
                    return '<span class="json-line"><span class="json-bracket">[]</span></span>';
                }

                const summary = obj.length + ' items';
                let html = '<span class="json-line">';
                html += '<span class="json-bracket">[</span>';
                html += '<span class="json-toggle" onclick="toggleJsonNode(this)" data-summary="' + summary + '"></span>';
                html += '<span class="json-summary">' + summary + '</span>';
                html += '<div class="json-node">';
                
                obj.forEach((item, index) => {
                    html += '<div class="json-line">';
                    html += '<span style="color: #6e7781; margin-right: 8px;">' + index + ':</span>';
                    html += renderJsonTree(item, level + 1, path + '[' + index + ']');
                    if (index < obj.length - 1) {
                        html += '<span class="json-comma">,</span>';
                    }
                    html += '</div>';
                });
                
                html += '</div></span><span class="json-bracket">]</span>';
                return html;
            }

            if (typeof obj === 'object') {
                const keys = Object.keys(obj);
                if (keys.length === 0) {
                    return '<span class="json-line"><span class="json-bracket">{}</span></span>';
                }

                const summary = keys.length + ' properties';
                let html = '<span class="json-line">';
                html += '<span class="json-bracket">{</span>';
                html += '<span class="json-toggle" onclick="toggleJsonNode(this)" data-summary="' + summary + '"></span>';
                html += '<span class="json-summary">' + summary + '</span>';
                html += '<div class="json-node">';
                
                keys.forEach((key, index) => {
                    html += '<div class="json-line">';
                    html += '<span class="json-key">"' + escapeHtml(key) + '"</span>';
                    html += ': ';
                    html += renderJsonTree(obj[key], level + 1, path + '.' + key);
                    if (index < keys.length - 1) {
                        html += '<span class="json-comma">,</span>';
                    }
                    html += '</div>';
                });
                
                html += '</div></span><span class="json-bracket">}</span>';
                return html;
            }

            return '<span class="json-line">' + escapeHtml(String(obj)) + '</span>';
        }

        function toggleJsonNode(element) {
            const isCollapsed = element.classList.contains('collapsed');
            element.classList.toggle('collapsed');
            
            // Find the correct node to toggle - it should be the next element after the toggle
            let currentElement = element.nextElementSibling;
            
            // Skip over the summary element to get to the actual json-node
            if (currentElement && currentElement.classList.contains('json-summary')) {
                currentElement = currentElement.nextElementSibling;
            }
            
            if (currentElement && currentElement.classList.contains('json-node')) {
                currentElement.classList.toggle('json-collapsed');
            }
            
            // Update summary visibility
            const summary = element.nextElementSibling;
            if (summary && summary.classList.contains('json-summary')) {
                summary.style.display = isCollapsed ? 'none' : 'inline';
            }
        }

        function expandAllJson() {
            const toggles = document.querySelectorAll('.json-toggle.collapsed');
            const nodes = document.querySelectorAll('.json-collapsed');
            const summaries = document.querySelectorAll('.json-summary');
            
            toggles.forEach(toggle => toggle.classList.remove('collapsed'));
            nodes.forEach(node => node.classList.remove('json-collapsed'));
            summaries.forEach(summary => summary.style.display = 'inline');
        }

        function collapseAllJson() {
            const toggles = document.querySelectorAll('.json-toggle:not(.collapsed)');
            const nodes = document.querySelectorAll('.json-node:not(.json-collapsed)');
            const summaries = document.querySelectorAll('.json-summary');
            
            toggles.forEach(toggle => toggle.classList.add('collapsed'));
            nodes.forEach(node => node.classList.add('json-collapsed'));
            summaries.forEach(summary => summary.style.display = 'inline');
        }

        function formatJson() {
            const jsonContent = document.getElementById('jsonContent');
            try {
                const parsedData = JSON.parse(currentJsonData);
                jsonContent.innerHTML = renderJsonTree(parsedData);
            } catch (e) {
                // If parsing fails, just re-render with current data
                jsonContent.innerHTML = '<div class="json-string">' + escapeHtml(currentJsonData) + '</div>';
            }
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function copyJsonToClipboard() {
            const copyBtn = document.querySelector('.copy-btn');

            navigator.clipboard.writeText(currentJsonData).then(function() {
                copyBtn.classList.add('copied');
                copyBtn.innerHTML = '<i class="fas fa-check"></i> Copied!';

                setTimeout(function() {
                    copyBtn.classList.remove('copied');
                    copyBtn.innerHTML = '<i class="fas fa-copy"></i> Copy JSON';
                }, 2000);
            }).catch(function(err) {
                console.error('Failed to copy: ', err);
                // Fallback for older browsers
                const textArea = document.createElement('textarea');
                textArea.value = currentJsonData;
                document.body.appendChild(textArea);
                textArea.select();
                document.execCommand('copy');
                document.body.removeChild(textArea);
                
                copyBtn.classList.add('copied');
                copyBtn.innerHTML = '<i class="fas fa-check"></i> Copied!';
                setTimeout(function() {
                    copyBtn.classList.remove('copied');
                    copyBtn.innerHTML = '<i class="fas fa-copy"></i> Copy JSON';
                }, 2000);
            });
        }

        window.onclick = function(event) {
            const modal = document.getElementById('jsonModal');
            if (event.target === modal) {
                closeJsonModal();
            }
        }

        document.addEventListener('keydown', function(event) {
            if (event.key === 'Escape') {
                closeJsonModal();
            }
        });
    </script>
</body>
</html>
"""

def highlight_search_term(text, search_term):
    """
    Highlight the search term in the text.

    Args:
        text (str): The text to highlight.
        search_term (str): The term to highlight.

    Returns:
        str: The text with the search term highlighted.
    """
    if not search_term:
        return text
    
    # Escape HTML in the text first to prevent XSS
    text_escaped = html.escape(str(text))
    
    # Escape regex special characters in search term
    escaped_term = re.escape(search_term)
    
    # Highlight with case-insensitive matching
    highlighted_text = re.sub(
        f'({escaped_term})',
        r'<span class="highlight">\1</span>',
        text_escaped,
        flags=re.IGNORECASE
    )
    return highlighted_text

@REPORT.route("/")
def index():
    """Main report page with server-side rendering."""
    try:
        search_params = {
            'tenant_id': request.args.get('tenant_id', '').strip(),
            'event_name': request.args.get('event_name', '').strip(),
            'user_id': request.args.get('user_id', '').strip(),
            'date_from': request.args.get('date_from', '').strip(),
            'date_to': request.args.get('date_to', '').strip(),
            'search_text': request.args.get('search_text', '').strip(),
            'per_page': int(request.args.get('per_page', 25)),
            'page': int(request.args.get('page', 1))
        }

        if search_params['per_page'] not in [10, 25, 50, 100]:
            search_params['per_page'] = 25

        immudb_service = ImmudbService.get_instance()

        if not immudb_service.enabled:
            return render_template_string(
                REPORT_TEMPLATE,
                search_params=search_params,
                error="ImmuDB is not enabled. Please check your configuration.",
                total_count=0,
                current_page=1,
                total_pages=1,
                page_range=[],
                start_item=0,
                end_item=0,
                results=[]
            )

        # Simple query without LOWER() - we'll filter in Python
        query = "SELECT id, tenant_id, event_name, user_id, request_data, response_data, created_at FROM audit_logs WHERE 1=1"
        
        # Add date filters only (these are exact matches)
        if search_params['date_from']:
            query += f" AND created_at >= '{search_params['date_from']}'"
        
        if search_params['date_to']:
            query += f" AND created_at <= '{search_params['date_to']}'"

        try:
            import random
            import time
            results = None
            MAX_ATTEMPTS = 3
            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    client = immudb_service._get_client()
                    if not client:
                        raise Exception("ImmuDB client is not available")
                    results = client.sqlQuery(query)
                    if results:
                        results.sort(key=lambda x: x[6] if x[6] is not None else "", reverse=True)
                    break
                except Exception as e:
                    err_str = str(e)
                    _retryable = ("RPC" in err_str or "Channel" in err_str or
                                  "not logged in" in err_str or
                                  "please select a database" in err_str or
                                  "StatusCode.CANCELLED" in err_str or
                                  "Stream removed" in err_str or
                                  "Socket closed" in err_str or
                                  "UNAVAILABLE" in err_str or
                                  "invalid token" in err_str or
                                  "invalid session" in err_str or
                                  "INTERNAL" in err_str)
                    if _retryable and attempt < MAX_ATTEMPTS:
                        jitter = 0.1 + random.uniform(0, 0.2)
                        time.sleep(jitter)
                        immudb_service._connect(failed_client=client)
                        continue
                    raise e
            
            # Filter results in Python for case-insensitive matching
            filtered_results = []
            for row in results:
                match = True
                
                # Check tenant_id
                if search_params['tenant_id']:
                    if search_params['tenant_id'].lower() not in str(row[1]).lower():
                        match = False
                
                # Check event_name
                if match and search_params['event_name']:
                    if search_params['event_name'].lower() not in str(row[2]).lower():
                        match = False
                
                # Check user_id
                if match and search_params['user_id']:
                    if search_params['user_id'].lower() not in str(row[3]).lower():
                        match = False
                
                # Check search_text in request_data and response_data
                if match and search_params['search_text']:
                    search_term = search_params['search_text'].lower()
                    if not (search_term in str(row[4]).lower() or search_term in str(row[5]).lower()):
                        match = False
                
                if match:
                    filtered_results.append(row)
            
            results = filtered_results

        except Exception as e:
            return render_template_string(
                REPORT_TEMPLATE,
                search_params=search_params,
                error=f"An error occurred: {str(e)}",
                total_count=0,
                current_page=1,
                total_pages=1,
                page_range=[],
                start_item=0,
                end_item=0,
                results=[]
            )

        per_page = search_params['per_page']
        current_page = search_params['page']
        total_count = len(results)
        total_pages = max(1, (total_count + per_page - 1) // per_page)

        # Ensure current_page is within valid range
        current_page = max(1, min(current_page, total_pages))

        start_idx = (current_page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_results = results[start_idx:end_idx]

        formatted_results = []
        for row in paginated_results:
            row_list = list(row)
            # Extract IDs and generate EHR links html from raw row[4] and row[5]
            ehr_links_html = generate_ehr_links_html(row_list[4], row_list[5])
            
            # Apply highlighting to request_data and response_data
            if search_params.get('search_text'):
                row_list[4] = highlight_search_term(row_list[4], search_params['search_text'])
                row_list[5] = highlight_search_term(row_list[5], search_params['search_text'])
            else:
                # Escape HTML even when not highlighting
                row_list[4] = html.escape(str(row_list[4]))
                row_list[5] = html.escape(str(row_list[5]))
                
            row_list.append(ehr_links_html)
            formatted_results.append(row_list)

        start_item = start_idx + 1 if total_count > 0 else 0
        end_item = min(start_idx + per_page, total_count)

        # Calculate page range for pagination
        page_range = []
        max_visible = 5

        if total_pages <= max_visible:
            page_range = list(range(1, total_pages + 1))
        else:
            if current_page <= 3:
                page_range = list(range(1, 5)) + ['...', total_pages]
            elif current_page >= total_pages - 2:
                page_range = [1, '...'] + list(range(total_pages - 3, total_pages + 1))
            else:
                page_range = [1, '...', current_page - 1, current_page, current_page + 1, '...', total_pages]

        return render_template_string(
            REPORT_TEMPLATE,
            results=formatted_results,
            total_count=total_count,
            current_page=current_page,
            total_pages=total_pages,
            page_range=page_range,
            start_item=start_item,
            end_item=end_item,
            search_params=search_params,
            error=None
        )

    except Exception as e:
        return render_template_string(
            REPORT_TEMPLATE,
            search_params={},
            error=f"An error occurred: {str(e)}",
            total_count=0,
            current_page=1,
            total_pages=1,
            page_range=[],
            start_item=0,
            end_item=0,
            results=[]
        )

@REPORT.route("/api/search")
def api_search():
    """API endpoint for AJAX search functionality."""
    try:
        search_params = {
            'tenant_id': request.args.get('tenant_id', '').strip(),
            'event_name': request.args.get('event_name', '').strip(),
            'user_id': request.args.get('user_id', '').strip(),
            'date_from': request.args.get('date_from', '').strip(),
            'date_to': request.args.get('date_to', '').strip(),
            'search_text': request.args.get('search_text', '').strip(),
            'per_page': int(request.args.get('per_page', 25)),
            'page': int(request.args.get('page', 1))
        }

        if search_params['per_page'] not in [10, 25, 50, 100]:
            search_params['per_page'] = 25

        immudb_service = ImmudbService.get_instance()

        if not immudb_service.enabled:
            return jsonify({'error': 'ImmuDB is not enabled'}), 500

        # Simple query without LOWER() - we'll filter in Python
        query = "SELECT id, tenant_id, event_name, user_id, request_data, response_data, created_at FROM audit_logs WHERE 1=1"
        
        # Add date filters only (these are exact matches)
        if search_params['date_from']:
            query += f" AND created_at >= '{search_params['date_from']}'"
        
        if search_params['date_to']:
            query += f" AND created_at <= '{search_params['date_to']}'"

        try:
            import random
            import time
            results = None
            MAX_ATTEMPTS = 3
            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    client = immudb_service._get_client()
                    if not client:
                        raise Exception("ImmuDB client is not available")
                    results = client.sqlQuery(query)
                    if results:
                        results.sort(key=lambda x: x[6] if x[6] is not None else "", reverse=True)
                    break
                except Exception as e:
                    err_str = str(e)
                    _retryable = ("RPC" in err_str or "Channel" in err_str or
                                  "not logged in" in err_str or
                                  "please select a database" in err_str or
                                  "StatusCode.CANCELLED" in err_str or
                                  "Stream removed" in err_str or
                                  "Socket closed" in err_str or
                                  "UNAVAILABLE" in err_str or
                                  "invalid token" in err_str or
                                  "invalid session" in err_str or
                                  "INTERNAL" in err_str)
                    if _retryable and attempt < MAX_ATTEMPTS:
                        jitter = 0.1 + random.uniform(0, 0.2)
                        time.sleep(jitter)
                        immudb_service._connect(failed_client=client)
                        continue
                    raise e
            
            # Filter results in Python for case-insensitive matching
            filtered_results = []
            for row in results:
                match = True
                
                # Check tenant_id
                if search_params['tenant_id']:
                    if search_params['tenant_id'].lower() not in str(row[1]).lower():
                        match = False
                
                # Check event_name
                if match and search_params['event_name']:
                    if search_params['event_name'].lower() not in str(row[2]).lower():
                        match = False
                
                # Check user_id
                if match and search_params['user_id']:
                    if search_params['user_id'].lower() not in str(row[3]).lower():
                        match = False
                
                # Check search_text in request_data and response_data
                if match and search_params['search_text']:
                    search_term = search_params['search_text'].lower()
                    if not (search_term in str(row[4]).lower() or search_term in str(row[5]).lower()):
                        match = False
                
                if match:
                    filtered_results.append(row)
            
            results = filtered_results

        except Exception as e:
            return jsonify({'error': f"An error occurred: {str(e)}"}), 500

        per_page = search_params['per_page']
        current_page = search_params['page']
        total_count = len(results)
        total_pages = max(1, (total_count + per_page - 1) // per_page)

        # Ensure current_page is within valid range
        current_page = max(1, min(current_page, total_pages))

        start_idx = (current_page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_results = results[start_idx:end_idx]

        start_item = start_idx + 1 if total_count > 0 else 0
        end_item = min(start_idx + per_page, total_count)

        formatted_results = []
        for row in paginated_results:
            row_list = list(row)
            # Store raw data before any modification for the JSON modal usage
            raw_request = str(row_list[4]) if row_list[4] else ""
            raw_response = str(row_list[5]) if row_list[5] else ""
            
            # Generate EHR links
            ehr_links_html = generate_ehr_links_html(raw_request, raw_response)

            # Apply highlighting or escaping for the HTML table display
            if search_params.get('search_text'):
                display_request = highlight_search_term(row_list[4], search_params['search_text'])
                display_response = highlight_search_term(row_list[5], search_params['search_text'])
            else:
                display_request = html.escape(str(row_list[4]))
                display_response = html.escape(str(row_list[5]))
            
            formatted_results.append({
                'id': row_list[0],
                'tenant_id': row_list[1],
                'event_name': row_list[2],
                'user_id': row_list[3],
                'request_data': display_request,
                'response_data': display_response,
                'raw_request_data': raw_request, # Send raw data for JS modal access
                'raw_response_data': raw_response,
                'created_at': row_list[6],
                'ehr_links_html': ehr_links_html
            })

        return jsonify({
            'results': formatted_results,
            'total_count': total_count,
            'current_page': current_page,
            'total_pages': total_pages,
            'per_page': per_page,
            'start_item': start_item,
            'end_item': end_item
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500