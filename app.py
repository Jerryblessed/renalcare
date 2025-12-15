
import os
import base64
import os
import json
import datetime
import uuid
import re
from flask import Flask, render_template_string, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, login_user, LoginManager, login_required, logout_user, current_user
from openai import AzureOpenAI


from azure.cognitiveservices.vision.customvision.prediction import CustomVisionPredictionClient
from msrest.authentication import ApiKeyCredentials

# =====================================================

# =====================================================
# 1. CONFIGURATION (UPDATED FOR FRUIT PROJECT)
# =====================================================

# ⚠️ REPLACE THESE WITH YOUR NEW "FRUIT DETECTOR" KEYS FROM CUSTOMVISION.AI
# =====================================================
# 1. CONFIGURATION (FRUIT PROJECT)
# =====================================================

FRUIT_PROJECT_ID = "c060e44f-532b-45b5-af7c-533f0d9b5c05"

# Note: This is the 'production' name you will type when you click 'Publish' later.
FRUIT_ITERATION_NAME = "FRUIT_ITERATION_NAME" 

# ⚠️ Use the Key from 'medicustomevsionme-Prediction' (Not the Training key)
FRUIT_KEY = "AkFG9x6IB3ih33uBUJK2QZP89uRjOZTVa5KfgXIPDzusOFCPaROkJQQJ99BAACYeBjFXJ3w3AAAIACOGEGnx"

# ⚠️ Use the Endpoint from 'medicustomevsionme-Prediction'
FRUIT_ENDPOINT = "https://medicustomevsionme-prediction.cognitiveservices.azure.com/"

# =======================================================
# =======================================================
# 1. CONFIGURATION
# =======================================================
app = Flask(__name__)
app.config['SECRET_KEY'] = 'renal-ai-final-fix-v12'
# =======================================================
# 2. DATABASE CONFIGURATION (SMART CLOUD)
# =======================================================

# 1. Check if Azure has injected the connection string automatically
# The "Web App + Database" wizard creates this specific variable:
# =======================================================
# 2. DATABASE CONFIGURATION (SMART CLOUD FIX)
# =======================================================

# 1. Check if Azure has injected the connection string automatically
azure_connection_string = os.environ.get('AZURE_POSTGRESQL_CONNECTIONSTRING')

if azure_connection_string:
    # WE ARE ON AZURE
    # CRITICAL FIX: Azure often sends 'postgres://' but SQLAlchemy needs 'postgresql://'
    if azure_connection_string.startswith("postgres://"):
        azure_connection_string = azure_connection_string.replace("postgres://", "postgresql://", 1)
        
    app.config['SQLALCHEMY_DATABASE_URI'] = azure_connection_string
    print("✅ Connected to Azure PostgreSQL!")
else:
    # WE ARE LOCAL
    print("⚠️ Azure DB not found, using Local SQLite")
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///renal_v12_stable.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# ⚠️ UPDATE THESE WITH YOUR VALID CREDENTIALS ⚠️
AZURE_API_KEY = "CoPHO7jDoUKoXD6zsLJQlj4FkLa1sLgGdpTnh5CTmqIE9KkJlFgIJQQJ99BHACL93NaXJ3w3AAABACOGIGtF" 
AZURE_API_BASE = "https://thisisoajo.openai.azure.com/"
AZURE_MODEL_NAME = "gpt-4o"
AZURE_API_VERSION = "2024-02-15-preview"


# Add this with your other keys
AZURE_MAPS_KEY = "AvB63h9BZTeEjAqzz1gSMJVYihx3wHp8w5htAoyRCvPkILJngHUTJQQJ99BLACYeBjFMW4spAAAgAZMP2TxK"

# Safe Client Initialization
client = None
try:
    if "YOUR_VALID" not in AZURE_API_KEY:
        client = AzureOpenAI(
            api_key=AZURE_API_KEY,
            api_version=AZURE_API_VERSION,
            azure_endpoint=AZURE_API_BASE
        )
except Exception as e:
    print(f"⚠️ OpenAI Client Error: {e}")

# =======================================================
# 2. DATABASE MODELS
# =======================================================
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    ckd_stage = db.Column(db.String(50), nullable=False) 
    next_lab_date = db.Column(db.Date, nullable=True)
    plans = db.relationship('Plan', backref='user', lazy=True)
    logs = db.relationship('DailyLog', backref='user', lazy=True)

class Plan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date_created = db.Column(db.DateTime, default=datetime.datetime.now)
    input_request = db.Column(db.String(200)) 
    final_json = db.Column(db.Text) 
    share_token = db.Column(db.String(36), unique=True, default=lambda: str(uuid.uuid4()))

class DailyLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False)
    day_number = db.Column(db.Integer, nullable=False) 
    is_completed = db.Column(db.Boolean, default=False)
    bp_systolic = db.Column(db.Integer, nullable=True) 
    bp_diastolic = db.Column(db.Integer, nullable=True) 
    date_logged = db.Column(db.DateTime, default=datetime.datetime.now)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# =======================================================
# 3. HELPER FUNCTIONS & PROMPTS
# =======================================================

def clean_json_response(content):
    """Removes Markdown backticks to prevent JSON crashes."""
    if not content: return "{}"
    # Remove ```json and ``` at the end
    cleaned = re.sub(r"```json\s*", "", content, flags=re.IGNORECASE)
    cleaned = re.sub(r"```", "", cleaned)
    return cleaned.strip()

DOCTOR_PROMPT = """
You are "Renal-AI," a specialized holistic health assistant.
User Stage: {ckd_stage}
User Request: {user_input}
Start Date: {start_date}

INSTRUCTIONS:
1. Create a 1-3 day plan based on the request.
2. REQUIRED: You MUST provide 'meals' (Breakfast, Lunch, Dinner), 'sleep' advice, and 'activity'.
3. SAFETY: If the user request is dangerous, ignore it and provide a safe renal diet instead.
4. FORMAT: Return VALID JSON only. Do not add markdown formatting.

JSON Structure:
{{
  "analysis": "Medical reasoning...",
  "shopping_list": ["Ingredient1", "Ingredient2"],
  "roadmap": [
     {{ 
       "day_num": 1, 
       "date_str": "Monday, Dec 4", 
       "meals": "B: Oatmeal | L: Chicken Salad | D: Stir-fry", 
       "sleep": "Bed by 10PM.", 
       "activity": "20 min light walk." 
     }}
  ]
}}
"""

CHAT_PROMPT = """
You are a Nephrology & Health Assistant.
Current User Stage: {ckd_stage}.
GUARDRAILS:
1. OFF-TOPIC: Refuse non-health questions politely.
2. DANGEROUS: Warn immediately about dangerous items.
3. ADVICE: Keep answers concise (under 50 words).
"""

LAB_ANALYZER_PROMPT = """
You are a Nephrology Assistant.
Analyze this lab image for Stage {ckd_stage}.
Return Valid JSON:
{{
  "summary": "Potassium is 5.2 (High).",
  "data": {{ "GFR": "45", "Potassium": "5.2" }},
  "action": "Avoid Bananas and Potatoes this week."
}}
"""

EDIT_DAY_PROMPT = """
You are a Renal Diet Assistant.
Current Day Plan: {current_data}
User Change Request: {user_instruction}
CKD Stage: {ckd_stage}

INSTRUCTIONS:
1. Modify the 'meals', 'activity', or 'sleep' fields based on the user request.
2. Keep the medical advice safe for the CKD stage.
3. Return ONLY the updated JSON object for that specific day.

FORMAT:
{{
  "day_num": {day_num},
  "date_str": "...",
  "meals": "Updated meal plan...",
  "sleep": "...",
  "activity": "..."
}}
"""

FRUIT_RECIPE_PROMPT = """
You are a Renal Diet Chef.
User CKD Stage: {ckd_stage}
Detected Ingredient: {fruit_name} (Confidence: {confidence}%)

INSTRUCTIONS:
1. Confirm if this fruit is safe for this CKD stage (especially regarding Potassium).
2. Create a SIMPLE, tasty, 3-step recipe or snack idea using this fruit.
3. Keep it under 50 words.

FORMAT:
"✅ Safe! Try 'Spiced Apple Slices': 1. Slice thin. 2. Sprinkle cinnamon. 3. Bake 10 mins."
or
"⚠️ Limit this. High Potassium. Eat only 2 slices washed well."
"""
# =======================================================

# 4. FRONTEND TEMPLATE

# =======================================================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Renal-AI | Complete Care</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/canvas-confetti@1.6.0/dist/confetti.browser.min.js"></script>
    
    <!-- Azure Maps SDK -->
    <link rel="stylesheet" href="https://atlas.microsoft.com/sdk/javascript/mapcontrol/3/atlas.min.css" type="text/css">
    <script src="https://atlas.microsoft.com/sdk/javascript/mapcontrol/3/atlas.min.js"></script>
    
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <style>
        :root { --primary: #2c3e50; --accent: #27ae60; --bg: #f4f7f6; }
        body { background: var(--bg); font-family: 'Segoe UI', sans-serif; color: #333; }
        .navbar { background: var(--primary); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
        .card { border: none; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); margin-bottom: 20px; background: white; }
        
        /* Timeline */
        .timeline-day { border-left: 5px solid #ddd; padding-left: 25px; margin-left: 10px; position: relative; }
        .timeline-day.done { border-left-color: var(--accent); background-color: #f9fffb; }
        .day-badge { position: absolute; left: -18px; top: 0; width: 36px; height: 36px; background: #ddd; color: #fff; border-radius: 50%; text-align: center; line-height: 36px; font-weight: bold; }
        .timeline-day.done .day-badge { background: var(--accent); }

        /* Floating Buttons */
        .fab-container { position: fixed; bottom: 30px; right: 30px; display: flex; flex-direction: column; gap: 15px; z-index: 2000; }
        .fab-btn { 
            width: 60px; height: 60px; border-radius: 50%; border:none; 
            color: white; text-align: center; line-height: 60px; font-size: 24px; 
            box-shadow: 0 4px 15px rgba(0,0,0,0.2); cursor: pointer; transition: transform 0.2s; 
            display: flex; align-items: center; justify-content: center;
            text-decoration: none;
        }
        .fab-btn:hover { transform: scale(1.1); color: white; }
        .fab-med { background: #e74c3c; } 
        .fab-chat { background: #3498db; }

        .chat-box { height: 300px; overflow-y: auto; background: #f8f9fa; border: 1px solid #ddd; border-radius: 8px; padding: 10px; margin-bottom: 10px; }
        .msg-user { text-align: right; margin: 5px; }
        .msg-user span { background: #3498db; color: white; padding: 5px 10px; border-radius: 15px 15px 0 15px; display: inline-block; }
        .msg-ai { text-align: left; margin: 5px; }
        .msg-ai span { background: #e9ecef; color: #333; padding: 5px 10px; border-radius: 15px 15px 15px 0; display: inline-block; }
        
        /* Custom Tab Styles for Diagnostics */
        .diag-tab .nav-link { color: #555; border-radius: 0; }
        .diag-tab .nav-link.active { color: #e74c3c; border-bottom: 3px solid #e74c3c; font-weight: bold; background: none; }
        
        /* Z-INDEX FIXES FOR CHAT */
        .modal-backdrop { z-index: 2000 !important; }
        .modal { z-index: 2001 !important; }
    </style>
</head>
<body>

<nav class="navbar navbar-dark navbar-expand-lg mb-4 sticky-top">
    <div class="container">
        <a class="navbar-brand" href="/">🧬 Renal-AI</a>
        <div class="d-flex align-items-center">
            {% if current_user.is_authenticated %}
                <span class="text-white me-3 d-none d-md-block">{{ current_user.username }} ({{ current_user.ckd_stage }})</span>
                <a href="/logout" class="btn btn-sm btn-outline-light">Logout</a>
            {% endif %}
        </div>
    </div>
</nav>

<div class="container">
    {% if not current_user.is_authenticated %}
        <!-- LOGIN SCREEN -->
        <div class="row justify-content-center align-items-center" style="height: 80vh;">
            <div class="col-md-5">
                <div class="card p-5 text-center">
                    <h2 class="mb-4">Renal Healing Portal</h2>
                    <form action="/login" method="post">
                        <div class="form-floating mb-3">
                            <input type="text" name="username" class="form-control" id="uInput" placeholder="User" required>
                            <label for="uInput">Username</label>
                        </div>
                        <select name="ckd_stage" class="form-select mb-4">
                            <option value="Prevention">Prevention Mode</option>
                            <option value="Stage 3">Stage 3 (Moderate)</option>
                            <option value="Stage 5">Stage 5 (Dialysis)</option>
                        </select>
                        <button type="submit" class="btn btn-primary w-100 btn-lg">Start Healing</button>
                    </form>
                </div>
            </div>
        </div>
    {% else %}
        
        <div class="row">
            <!-- HISTORY SIDEBAR -->
            <div class="col-md-3 d-none d-md-block">
                <div class="card p-3">
                    <h6 class="text-muted mb-3">Your Journey</h6>
                    <div class="list-group list-group-flush small">
                        {% for plan in history %}
                        <div class="list-group-item list-group-item-action d-flex justify-content-between px-0">
                            <a href="#" onclick="loadHistory({{ plan.id }}); return false;" class="text-decoration-none text-dark text-truncate" style="max-width: 80%;">
                                {{ plan.input_request }}
                            </a>
                            <a href="/delete_plan/{{ plan.id }}" class="text-danger" onclick="return confirm('Delete?')">✕</a>
                        </div>
                        {% endfor %}
                    </div>
                </div>
            </div>

            <!-- MAIN CONTENT -->
            <div class="col-md-9">
                <!-- GENERATOR -->
                <div class="card p-4">
                    <h4 class="mb-3">New Health Plan</h4>
                    <div class="input-group input-group-lg">
                        <input type="text" id="userInput" class="form-control" placeholder="E.g. 'Feeling tired, need energy food'">
                        <button type="button" class="btn btn-outline-secondary" onclick="startDictation('userInput')" title="Speak">
                            <i class="fas fa-microphone"></i>
                        </button>
                        <button type="button" onclick="generatePlan()" id="genBtn" class="btn btn-primary px-4">Generate</button>
                    </div>
                    
                    <div id="loading" class="mt-4 text-center" style="display:none;">
                        <div class="spinner-border text-primary" role="status"></div>
                        <p class="text-muted mt-2">Consulting Renal Specialist (Checking Diet, Sleep, Safety)...</p>
                    </div>
                    <div id="errorDisplay" class="alert alert-danger mt-3" style="display:none;"></div>
                </div>

                <!-- PLAN RESULTS -->
                <div id="planContainer" style="display:none;">
                    <div class="card p-4">
                        <div class="d-flex justify-content-between align-items-center mb-4">
                            <h3 class="m-0 text-primary">Your Roadmap</h3>
                            <button onclick="sharePlan()" class="btn btn-outline-primary btn-sm"><i class="fas fa-share-alt"></i> Share</button>
                        </div>
                        <p class="text-muted bg-light p-3 rounded" id="analysisText"></p>
                        <div class="mb-3">
                            <i class="fas fa-shopping-basket text-success"></i> <strong>Shopping:</strong> 
                            <span id="shoppingLinks"></span>
                        </div>
                        <div id="timelineArea" class="mt-4"></div>
                    </div>
                </div>
            </div>
        </div>

        <!-- FLOATING ACTION BUTTONS -->
        <div class="fab-container">
            <button class="fab-btn fab-chat" data-bs-toggle="modal" data-bs-target="#chatModal" title="Ask AI Assistant">
                <i class="fas fa-comments"></i>
            </button>
            <button class="fab-btn fab-med" data-bs-toggle="modal" data-bs-target="#medicalModal" title="Diagnostics & Vitals">
                <i class="fas fa-heartbeat"></i>
            </button>
        </div>

        <!-- MODALS -->
        
        <!-- 4. AZURE MAPS MODAL -->
        <div class="modal fade" id="mapsModal" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header bg-success text-white">
                        <h5 class="modal-title"><i class="fas fa-map-marked-alt"></i> Local Finder</h5>
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body p-0">
                        <!-- Map Container -->
                        <div id="myMap" style="position:relative;width:100%;height:400px;"></div>
                    </div>
                    <div class="modal-footer bg-light justify-content-between">
                        <span class="small text-muted" id="mapStatus">Searching area...</span>
                        <button type="button" class="btn btn-sm btn-secondary" data-bs-dismiss="modal">Close</button>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- 1. MEDICAL DIAGNOSTIC MODAL (UPDATED WITH FRUIT SCANNER) -->
        <div class="modal fade" id="medicalModal" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header bg-danger text-white">
                        <h5 class="modal-title"><i class="fas fa-heartbeat"></i> Diagnostic Hub</h5>
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body p-0">
                        <!-- TABS -->
                        <ul class="nav nav-tabs nav-fill diag-tab" id="diagTab" role="tablist">
                            <li class="nav-item">
                                <button class="nav-link active" data-bs-toggle="tab" data-bs-target="#tab-labs">
                                    <i class="fas fa-flask"></i> Blood/Lab Check
                                </button>
                            </li>
                            <li class="nav-item">
                                <button class="nav-link" data-bs-toggle="tab" data-bs-target="#tab-scans">
                                    <i class="fas fa-apple-alt"></i> Kitchen Helper
                                </button>
                            </li>
                        </ul>

                        <div class="tab-content p-4">
                            <!-- TAB 1: LABS -->
                            <div class="tab-pane fade show active" id="tab-labs">
                                <div class="alert alert-info small">
                                    Upload a picture of your blood test report. AI will extract GFR, Potassium, and Sodium levels.
                                </div>
                                <div class="card p-3 border shadow-sm">
                                    <h6>Upload Report</h6>
                                    <input type="file" id="labImg" class="form-control mb-3">
                                    <button onclick="analyzeLabs()" class="btn btn-info text-white w-100">
                                        Analyze Blood Report
                                    </button>
                                    <div id="labResult" class="mt-3 small p-2 border rounded bg-light" style="display:none;"></div>
                                </div>
                            </div>

                            <!-- TAB 2: HEALTHY SCANNER (REPLACES SCANS) -->
                            <div class="tab-pane fade" id="tab-scans">
                                <div class="alert alert-success small">
                                    <strong>Kitchen Helper:</strong> Don't know what to do with a fruit? Take a picture! 
                                    AI will identify it and suggest a safe recipe for <b>{{ current_user.ckd_stage }}</b>.
                                </div>
                                <div class="card p-3 border shadow-sm">
                                    <div class="mb-3">
                                        <label class="form-label fw-bold">Upload Fruit Photo:</label>
                                        <input type="file" id="fruitImg" class="form-control" accept="image/*">
                                    </div>
                                    <button onclick="analyzeFruit()" class="btn btn-success w-100">
                                        <i class="fas fa-camera"></i> Scan & Get Recipe
                                    </button>
                                    
                                    <!-- Result Area -->
                                    <div id="fruitResult" class="mt-3 text-center" style="display:none;">
                                        <!-- Vision Result -->
                                        <h3 class="text-success" id="fruitTag"></h3>
                                        <span class="badge bg-secondary mb-3" id="fruitConf"></span>
                                        
                                        <!-- GPT Recipe Result -->
                                        <div class="card bg-light p-3 text-start border-success">
                                            <h6 class="text-success"><i class="fas fa-utensils"></i> Chef's Recommendation:</h6>
                                            <p class="mb-0" id="fruitRecipe" style="white-space: pre-line;"></p>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Vitals Section (Bottom) -->
                        <div class="bg-light p-3 border-top">
                             <h6 class="text-primary mb-3">Your Vitals Tracker</h6>
                             <canvas id="bpChart" height="100"></canvas>
                             <hr>
                             <div class="d-flex justify-content-between align-items-center">
                                 <span class="small text-muted">Next Doctor Appointment:</span>
                                 <form action="/set_lab_date" method="post" class="d-flex">
                                     <input type="date" name="lab_date" class="form-control form-control-sm me-1" value="{{ current_user.next_lab_date }}">
                                     <button class="btn btn-sm btn-warning">Set</button>
                                 </form>
                             </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 2. CHAT MODAL (UPDATED WIDGET STYLE) -->
        <div class="modal fade" id="chatModal" tabindex="-1" data-bs-backdrop="false">
            <div class="modal-dialog" style="position: fixed; bottom: 100px; right: 20px; margin: 0; width: 350px; max-width: 90%;">
                <div class="modal-content shadow-lg border-0" style="border-radius: 15px;">
                    
                    <!-- Compact Header -->
                    <div class="modal-header bg-primary text-white py-2" style="border-radius: 15px 15px 0 0;">
                        <h6 class="modal-title small"><i class="fas fa-robot me-2"></i>Renal Assistant</h6>
                        <button type="button" class="btn-close btn-close-white small" data-bs-dismiss="modal"></button>
                    </div>

                    <!-- Chat Area -->
                    <div class="modal-body p-0">
                        <div id="chatBox" class="chat-box p-3" style="height: 300px; overflow-y: auto; background: #fff;">
                            <div class="msg-ai"><span>Hello! I'm here to help with your diet and health.</span></div>
                        </div>
                    </div>

                    <!-- Input Area -->
                    <div class="modal-footer p-2 bg-light" style="border-radius: 0 0 15px 15px;">
                        <div class="input-group">
                            <input type="text" id="chatInput" class="form-control border-0 bg-white shadow-sm" placeholder="Ask a question..." onkeypress="if(event.keyCode==13) sendChat()">
                            <button class="btn btn-primary shadow-sm" onclick="sendChat()"><i class="fas fa-paper-plane"></i></button>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 3. EDIT PLAN MODAL -->
        <div class="modal fade" id="editModal" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header bg-warning text-dark">
                        <h5 class="modal-title"><i class="fas fa-edit"></i> Edit Day <span id="editDayNum"></span></h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <ul class="nav nav-tabs mb-3" id="editTabs" role="tablist">
                            <li class="nav-item">
                                <button class="nav-link active" data-bs-toggle="tab" data-bs-target="#manual-tab">Manual</button>
                            </li>
                            <li class="nav-item">
                                <button class="nav-link" data-bs-toggle="tab" data-bs-target="#ai-tab">AI Miracle ✨</button>
                            </li>
                        </ul>

                        <div class="tab-content">
                            <!-- Manual Edit -->
                            <div class="tab-pane fade show active" id="manual-tab">
                                <label class="form-label text-muted small">Meals</label>
                                <textarea id="editMeals" class="form-control mb-2" rows="3"></textarea>
                                <label class="form-label text-muted small">Activity</label>
                                <input type="text" id="editActivity" class="form-control mb-2">
                                <label class="form-label text-muted small">Sleep</label>
                                <input type="text" id="editSleep" class="form-control mb-3">
                                <button onclick="saveManualEdit()" class="btn btn-dark w-100">Save Changes</button>
                            </div>

                            <!-- AI Edit -->
                            <div class="tab-pane fade" id="ai-tab">
                                <div class="alert alert-light border small">
                                    <i class="fas fa-info-circle"></i> Tell AI how to change this day.
                                </div>
                                <div class="input-group mb-3">
                                    <input type="text" id="aiEditInput" class="form-control" placeholder="Instructions...">
                                    <button type="button" class="btn btn-outline-secondary" onclick="startDictation('aiEditInput')">
                                        <i class="fas fa-microphone"></i>
                                    </button>
                                </div>
                                <button onclick="saveAiEdit()" id="btnAiSave" class="btn btn-warning w-100">Update with AI</button>
                                <div id="aiEditLoading" class="text-center mt-2 text-muted small" style="display:none;">
                                    <div class="spinner-border spinner-border-sm"></div> Consulting Renal Specialist...
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    {% endif %}
</div>

<!-- SCRIPTS -->
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
    let currentPlanId = null;
    let currentShareToken = null;
    let currentRoadmapData = [];
    let editingDayNum = null;
    let map, datasource; // AZURE MAPS VARIABLES

    function startDictation(id) {
        if (window.hasOwnProperty('webkitSpeechRecognition')) {
            var r = new webkitSpeechRecognition();
            r.lang = "en-US"; r.start();
            r.onresult = function(e) { document.getElementById(id).value = e.results[0][0].transcript; r.stop(); };
            r.onerror = function() { alert("Microphone access denied."); }
        } else { alert("Voice Dictation requires Google Chrome."); }
    }

    async function generatePlan() {
        const text = document.getElementById('userInput').value;
        if(!text) return alert("Please describe how you feel.");
        document.getElementById('genBtn').disabled = true;
        document.getElementById('loading').style.display = 'block';
        document.getElementById('planContainer').style.display = 'none';
        document.getElementById('errorDisplay').style.display = 'none';
        const fd = new FormData(); fd.append('text', text);
        try {
            const res = await fetch('/generate', { method: 'POST', body: fd });
            const data = await res.json();
            if (!res.ok || data.error) throw new Error(data.error || "Server Error");
            currentPlanId = data.plan_id;
            currentShareToken = data.share_token;
            document.getElementById('analysisText').innerText = data.analysis;
            renderTimeline(data.roadmap);
            renderShop(data.shopping_list);
            document.getElementById('planContainer').style.display = 'block';
        } catch(e) {
            document.getElementById('errorDisplay').innerText = "Failed: " + e.message;
            document.getElementById('errorDisplay').style.display = 'block';
        } finally {
            document.getElementById('genBtn').disabled = false;
            document.getElementById('loading').style.display = 'none';
        }
    }

    // --- UPDATED RENDER SHOP FOR AZURE MAPS ---
    function renderShop(items) {
        const div = document.getElementById('shoppingLinks');
        div.innerHTML = '';
        if(items) {
            items.forEach(i => {
                // Now calls openMap instead of Google Link
                div.innerHTML += `
                <button onclick="openMap('${i}')" class="btn btn-sm btn-outline-success me-1 mb-1">
                    <i class="fas fa-map-marker-alt"></i> Find ${i}
                </button>`;
            });
        }
    }

    // --- NEW AZURE MAPS LOGIC ---
    function openMap(query) {
        // 1. Show Modal
        const myModal = new bootstrap.Modal(document.getElementById('mapsModal'));
        myModal.show();
        
        document.getElementById('mapStatus').innerText = `Locating ${query}...`;

        // 2. Initialize Map (only once)
        if(!map) {
            map = new atlas.Map('myMap', {
                center: [3.3792, 6.5244], // Default View (Lagos)
                zoom: 13,
                view: 'Auto',
                authOptions: {
                    authType: 'subscriptionKey',
                    subscriptionKey: '{{ maps_key }}' // Passed from Python
                }
            });
            
            datasource = new atlas.source.DataSource();
            map.sources.add(datasource);
            
            // Add a layer to render point data
            map.layers.add(new atlas.layer.SymbolLayer(datasource, null, {
                iconOptions: { image: 'pin-round-darkblue', anchor: 'center', allowOverlap: true }
            }));
        }

        // 3. Search Logic
        if(map.map) { performSearch(query); }
        else { map.events.add('ready', function () { performSearch(query); }); }
    }

    function performSearch(query) {
        datasource.clear(); // Clear old pins
        
        // Get User Location
        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(function(position) {
                const userLat = position.coords.latitude;
                const userLon = position.coords.longitude;
                
                // Move map to user
                map.setCamera({ center: [userLon, userLat], zoom: 14 });

                // Construct Search URL
                const searchUrl = `https://atlas.microsoft.com/search/fuzzy/json?api-version=1.0&query=${query}&lat=${userLat}&lon=${userLon}&radius=5000&subscription-key={{ maps_key }}`;

                fetch(searchUrl)
                .then(response => response.json())
                .then(data => {
                    if(data.results) {
                        const pins = [];
                        data.results.forEach(result => {
                            const pos = [result.position.lon, result.position.lat];
                            pins.push(new atlas.Shape(new atlas.data.Point(pos)));
                        });
                        datasource.add(pins);
                        document.getElementById('mapStatus').innerText = `Found ${pins.length} locations near you.`;
                    }
                });

            }, function() {
                document.getElementById('mapStatus').innerText = "Location access denied. Showing default view.";
            });
        } else {
            document.getElementById('mapStatus').innerText = "Geolocation not supported.";
        }
    }

    function renderTimeline(roadmap) {
        currentRoadmapData = roadmap;
        const div = document.getElementById('timelineArea');
        div.innerHTML = '';
        roadmap.forEach((day, index) => {
            const isDone = day.is_completed ? 'done' : '';
            const btnHtml = day.is_completed ? '<i class="fas fa-check-circle text-success fs-3"></i>' : `<button class="btn btn-outline-success btn-sm" onclick="markDone(${day.day_num})">Complete</button>`;
            const editBtn = `<button class="btn btn-outline-secondary btn-sm me-2" onclick="openEditModal(${index})"><i class="fas fa-pencil-alt"></i> Edit</button>`;
            div.innerHTML += `
            <div class="card p-3 timeline-day ${isDone}" id="day-${day.day_num}">
                <div class="day-badge">${day.day_num}</div>
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <h5 class="m-0">${day.date_str}</h5>
                    <div id="act-${day.day_num}">${editBtn}${btnHtml}</div>
                </div>
                <div class="row g-2">
                    <div class="col-md-4"><div class="p-2 bg-light rounded small border h-100"><b>Meals:</b><br>${day.meals}</div></div>
                    <div class="col-md-4"><div class="p-2 bg-light rounded small border h-100"><b>Sleep:</b><br>${day.sleep}</div></div>
                    <div class="col-md-4"><div class="p-2 bg-light rounded small border h-100"><b>Activity:</b><br>${day.activity}</div></div>
                </div>
                <div class="input-group input-group-sm mt-3" style="max-width: 250px;">
                     <span class="input-group-text">BP</span>
                     <input type="number" class="form-control" placeholder="120" id="sys-${day.day_num}">
                     <input type="number" class="form-control" placeholder="80" id="dia-${day.day_num}">
                     <button class="btn btn-dark" onclick="logBP(${day.day_num})">Save</button>
                </div>
            </div>`;
        });
    }

    function openEditModal(index) {
        const day = currentRoadmapData[index];
        editingDayNum = day.day_num;
        document.getElementById('editDayNum').innerText = day.day_num;
        document.getElementById('editMeals').value = day.meals || '';
        document.getElementById('editActivity').value = day.activity || '';
        document.getElementById('editSleep').value = day.sleep || '';
        document.getElementById('aiEditInput').value = '';
        new bootstrap.Modal(document.getElementById('editModal')).show();
    }

    async function saveManualEdit() {
        const meals = document.getElementById('editMeals').value;
        const act = document.getElementById('editActivity').value;
        const sleep = document.getElementById('editSleep').value;
        try {
            const res = await fetch('/edit_day_manual', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ plan_id: currentPlanId, day_num: editingDayNum, meals: meals, activity: act, sleep: sleep })
            });
            const data = await res.json();
            if(data.success) { renderTimeline(data.roadmap); bootstrap.Modal.getInstance(document.getElementById('editModal')).hide(); }
        } catch(e) { alert("Save failed: " + e); }
    }

    async function saveAiEdit() {
        const txt = document.getElementById('aiEditInput').value;
        if(!txt) return alert("Please enter instructions");
        document.getElementById('btnAiSave').disabled = true;
        document.getElementById('aiEditLoading').style.display = 'block';
        try {
            const res = await fetch('/edit_day_ai', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ plan_id: currentPlanId, day_num: editingDayNum, instruction: txt })
            });
            const data = await res.json();
            if(data.success) { renderTimeline(data.roadmap); bootstrap.Modal.getInstance(document.getElementById('editModal')).hide(); }
            else { alert("AI Error: " + (data.error || "Unknown")); }
        } catch(e) { alert("Connection failed"); }
        finally { document.getElementById('btnAiSave').disabled = false; document.getElementById('aiEditLoading').style.display = 'none'; }
    }

    async function markDone(n) {
        try { confetti({ origin: { y: 0.7 } }); } catch(e) {}
        document.getElementById(`day-${n}`).classList.add('done');
        document.getElementById(`act-${n}`).innerHTML = '<i class="fas fa-check-circle text-success fs-3"></i>';
        await fetch('/log_daily', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ plan_id:currentPlanId, day_num:n, check:true }) });
    }

    async function logBP(n) {
        const s = document.getElementById(`sys-${n}`).value;
        const d = document.getElementById(`dia-${n}`).value;
        if(s && d) {
            await fetch('/log_daily', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ plan_id:currentPlanId, day_num:n, sys:s, dia:d }) });
            location.reload(); 
        } else { alert("Enter both numbers."); }
    }

    async function sendChat() {
        const inp = document.getElementById('chatInput');
        const txt = inp.value;
        if(!txt) return;
        const box = document.getElementById('chatBox');
        box.innerHTML += `<div class="msg-user"><span>${txt}</span></div>`;
        inp.value = '';
        try {
            const res = await fetch('/chat_agent', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ msg: txt }) });
            const data = await res.json();
            box.innerHTML += `<div class="msg-ai"><span>${data.reply}</span></div>`;
        } catch(e) { box.innerHTML += `<div class="msg-ai"><span class="text-danger">Error</span></div>`; }
        box.scrollTop = box.scrollHeight;
    }

    async function loadHistory(id) {
        const res = await fetch(`/get_plan/${id}`);
        const data = await res.json();
        currentPlanId = data.id;
        renderTimeline(JSON.parse(data.json).roadmap);
        renderShop(JSON.parse(data.json).shopping_list);
        document.getElementById('planContainer').style.display = 'block';
    }

    // --- OLD LAB ANALYZER (BLOOD) ---
    async function analyzeLabs() {
        const f = document.getElementById('labImg').files[0];
        if(!f) return alert("Upload image first");
        const fd = new FormData(); fd.append('lab_image', f);
        document.getElementById('labResult').style.display = 'block';
        document.getElementById('labResult').innerText = "Analyzing...";
        try {
            const res = await fetch('/analyze_labs', {method:'POST', body:fd});
            const d = await res.json();
            if(d.error) throw new Error(d.error);
            document.getElementById('labResult').innerHTML = `<b>${d.summary}</b><br>${d.action}`;
        } catch(e) { document.getElementById('labResult').innerText = "Analysis Failed: " + e.message; }
    }

    // --- NEW SCAN ANALYZER (CUSTOM VISION) ---
    async function analyzeFruit() {
            const f = document.getElementById('fruitImg').files[0];
            if(!f) return alert("Please upload a fruit image.");
            
            const fd = new FormData();
            fd.append('fruit_image', f);

            document.getElementById('fruitResult').style.display = 'block';
            document.getElementById('fruitTag').innerText = "Identifying...";
            document.getElementById('fruitConf').innerText = "";
            document.getElementById('fruitRecipe').innerText = "Consulting the AI Chef...";

            try {
                const res = await fetch('/analyze_fruit', { method: 'POST', body: fd });
                const data = await res.json();

                if (data.error) throw new Error(data.error);

                // 1. Show the Name (From Custom Vision)
                document.getElementById('fruitTag').innerText = data.fruit_detected;
                document.getElementById('fruitConf').innerText = data.confidence + "% Confidence";
                
                // 2. Show the Recipe (From GPT-4o)
                document.getElementById('fruitRecipe').innerText = data.recipe;
                
            } catch (e) {
                document.getElementById('fruitTag').innerText = "Error";
                document.getElementById('fruitRecipe').innerText = e.message;
            }
        }
    function sharePlan() {
        if(currentShareToken) {
            navigator.clipboard.writeText(window.location.origin + "/share/" + currentShareToken);
            alert("Link copied!");
        }
    }
    
    {% if current_user.is_authenticated %}
    document.addEventListener("DOMContentLoaded", function() {
        const ctx = document.getElementById('bpChart');
        if(ctx) {
            new Chart(ctx, {
                type: 'line',
                data: {
                    labels: {{ bp_dates | tojson }},
                    datasets: [
                        { label: 'Systolic', data: {{ bp_sys | tojson }}, borderColor: '#e74c3c', tension: 0.3 },
                        { label: 'Diastolic', data: {{ bp_dia | tojson }}, borderColor: '#3498db', tension: 0.3 }
                    ]
                },
                options: { responsive: true }
            });
        }
    });
    {% endif %}
</script>
</body>
</html>
"""

# =======================================================
# 5. ROUTES
# =======================================================
@app.route('/')
def home():
    if current_user.is_authenticated:
        history = Plan.query.filter_by(user_id=current_user.id).order_by(Plan.date_created.desc()).limit(10).all()
        logs = DailyLog.query.filter_by(user_id=current_user.id).filter(DailyLog.bp_systolic.isnot(None)).order_by(DailyLog.date_logged.asc()).all()
        return render_template_string(HTML_TEMPLATE, 
                                      history=history, 
                                      bp_dates=[l.date_logged.strftime('%b %d') for l in logs], 
                                      bp_sys=[l.bp_systolic for l in logs], 
                                      bp_dia=[l.bp_diastolic for l in logs],
                                      maps_key=AZURE_MAPS_KEY) # <--- ADD THIS
    return render_template_string(HTML_TEMPLATE, maps_key=AZURE_MAPS_KEY) # <--- AND THIS

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    stage = request.form.get('ckd_stage')
    if not username: return redirect('/')
    user = User.query.filter_by(username=username).first()
    if not user:
        user = User(username=username, ckd_stage=stage)
        db.session.add(user)
        db.session.commit()
    login_user(user)
    return redirect('/')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/')

@app.route('/generate', methods=['POST'])
@login_required
def generate():
    if not client: 
        return jsonify({"error": "System Error: Azure API Key is missing or invalid."}), 500

    text = request.form.get('text', '')
    prompt = DOCTOR_PROMPT.format(ckd_stage=current_user.ckd_stage, user_input=text, start_date=datetime.date.today())
    
    try:
        response = client.chat.completions.create(
            model=AZURE_MODEL_NAME,
            messages=[{"role": "system", "content": prompt}],
            max_tokens=800
        )
        # CRITICAL FIX: CLEAN JSON
        content = clean_json_response(response.choices[0].message.content)
        data = json.loads(content)
        
        new_plan = Plan(user_id=current_user.id, input_request=text, final_json=json.dumps(data))
        db.session.add(new_plan)
        db.session.commit()
        
        return jsonify({
            "plan_id": new_plan.id, 
            "roadmap": data.get('roadmap', []), 
            "shopping_list": data.get('shopping_list', []), 
            "share_token": new_plan.share_token, 
            "analysis": data.get('analysis', '')
        })
    except json.JSONDecodeError:
        return jsonify({"error": "AI Response Format Error. Please try again."}), 500
    except Exception as e:
        print(f"Generate Error: {e}")
        return jsonify({"error": f"Azure AI Error: {str(e)}"}), 500

@app.route('/chat_agent', methods=['POST'])
@login_required
def chat_agent():
    if not client: return jsonify({"reply": "API Key Error."}), 500
    msg = request.json.get('msg', '')
    prompt = CHAT_PROMPT.format(ckd_stage=current_user.ckd_stage)
    
    try:
        response = client.chat.completions.create(
            model=AZURE_MODEL_NAME,
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": msg}],
            max_tokens=100
        )
        return jsonify({"reply": response.choices[0].message.content})
    except Exception as e:
        return jsonify({"reply": "Connection Error."})

@app.route('/log_daily', methods=['POST'])
@login_required
def log_daily():
    d = request.json
    log = DailyLog.query.filter_by(user_id=current_user.id, plan_id=d['plan_id'], day_number=d['day_num']).first()
    if not log:
        log = DailyLog(user_id=current_user.id, plan_id=d['plan_id'], day_number=d['day_num'])
        db.session.add(log)
    if 'check' in d: log.is_completed = True
    if 'sys' in d: 
        log.bp_systolic = int(d['sys'])
        log.bp_diastolic = int(d['dia'])
        log.date_logged = datetime.datetime.now()
    db.session.commit()
    return jsonify({"success": True})

@app.route('/analyze_labs', methods=['POST'])
@login_required
def analyze_labs():
    if not client: return jsonify({"error": "API Key Missing"}), 500
    f = request.files.get('lab_image')
    if not f: return jsonify({"error": "No file"}), 400
    try:
        img_b64 = base64.b64encode(f.read()).decode('utf-8')
        prompt = LAB_ANALYZER_PROMPT.format(ckd_stage=current_user.ckd_stage)
        res = client.chat.completions.create(
            model=AZURE_MODEL_NAME,
            messages=[
                {"role": "system", "content": prompt}, 
                {"role": "user", "content": [{"type":"text","text":"analyze"}, {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{img_b64}"}}]}
            ]
        )
        content = clean_json_response(res.choices[0].message.content)
        return jsonify(json.loads(content))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get_plan/<int:pid>')
@login_required
def get_plan(pid):
    p = Plan.query.get_or_404(pid)
    if p.user_id != current_user.id: return jsonify({"error": "Unauthorized"}), 403
    return jsonify({"id": p.id, "share_token": p.share_token, "json": p.final_json})

@app.route('/set_lab_date', methods=['POST'])
@login_required
def set_lab_date():
    d = request.form.get('lab_date')
    if d:
        current_user.next_lab_date = datetime.datetime.strptime(d, '%Y-%m-%d').date()
        db.session.commit()
    return redirect('/')

@app.route('/delete_plan/<int:pid>')
@login_required
def delete_plan(pid):
    p = Plan.query.get_or_404(pid)
    if p.user_id == current_user.id:
        DailyLog.query.filter_by(plan_id=pid).delete()
        db.session.delete(p)
        db.session.commit()
    return redirect('/')

@app.route('/share/<token>')
def share(token):
    plan = Plan.query.filter_by(share_token=token).first_or_404()
    data = json.loads(plan.final_json)
    html = """<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet"><div class="container mt-5"><div class="card p-4"><h2>Shared Plan</h2>"""
    for day in data.get('roadmap', []):
        html += f"<div class='alert alert-info'>Day {day['day_num']}: {day['meals']}</div>"
    html += """<a href="/" class="btn btn-primary">Join</a></div></div>"""
    return html

@app.route('/edit_day_manual', methods=['POST'])
@login_required
def edit_day_manual():
    data = request.json
    plan = Plan.query.get_or_404(data['plan_id'])
    
    # Security check
    if plan.user_id != current_user.id:
        return jsonify({"error": "Unauthorized"}), 403

    # Load current JSON
    full_plan = json.loads(plan.final_json)
    
    # Update specific day
    for day in full_plan['roadmap']:
        if day['day_num'] == data['day_num']:
            day['meals'] = data['meals']
            day['activity'] = data['activity']
            break
            
    # Save back to DB
    plan.final_json = json.dumps(full_plan)
    db.session.commit()
    
    return jsonify({"success": True, "roadmap": full_plan['roadmap']})

@app.route('/edit_day_ai', methods=['POST'])
@login_required
def edit_day_ai():
    data = request.json
    plan = Plan.query.get_or_404(data['plan_id'])
    
    if plan.user_id != current_user.id:
        return jsonify({"error": "Unauthorized"}), 403

    full_plan = json.loads(plan.final_json)
    target_day = next((item for item in full_plan['roadmap'] if item['day_num'] == data['day_num']), None)
    
    if not target_day:
        return jsonify({"error": "Day not found"}), 404

    # Call AI
    prompt = EDIT_DAY_PROMPT.format(
        current_data=json.dumps(target_day),
        user_instruction=data['instruction'],
        ckd_stage=current_user.ckd_stage,
        day_num=data['day_num']
    )

    try:
        response = client.chat.completions.create(
            model=AZURE_MODEL_NAME,
            messages=[{"role": "system", "content": prompt}],
            max_tokens=400
        )
        content = clean_json_response(response.choices[0].message.content)
        updated_day_data = json.loads(content)
        
        # Merge updates into main plan
        for i, day in enumerate(full_plan['roadmap']):
            if day['day_num'] == data['day_num']:
                # Preserve completion status, just update content
                is_completed = day.get('is_completed', False)
                full_plan['roadmap'][i] = updated_day_data
                full_plan['roadmap'][i]['is_completed'] = is_completed
                break
        
        plan.final_json = json.dumps(full_plan)
        db.session.commit()
        
        return jsonify({"success": True, "roadmap": full_plan['roadmap']})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/analyze_fruit', methods=['POST'])
@login_required
def analyze_fruit():
    f = request.files.get('fruit_image')
    if not f: return jsonify({"error": "No file uploaded"}), 400

    try:
        # 1. VISUAL IDENTIFICATION (Azure Custom Vision)
        credentials = ApiKeyCredentials(in_headers={"Prediction-key": FRUIT_KEY})
        predictor = CustomVisionPredictionClient(FRUIT_ENDPOINT, credentials)
        
        # Send image to Custom Vision
        results = predictor.classify_image(FRUIT_PROJECT_ID, FRUIT_ITERATION_NAME, f.read())
        
        # Get the top result (e.g., "Banana-Ripe")
        predictions = sorted(results.predictions, key=lambda x: x.probability, reverse=True)
        top_result = predictions[0]
        fruit_name = top_result.tag_name
        confidence = round(top_result.probability * 100, 2)

        # 2. DIETARY CREATIVITY (Azure OpenAI GPT-4o)
        # We ask GPT to invent a recipe based on what the vision model saw
        prompt = FRUIT_RECIPE_PROMPT.format(
            ckd_stage=current_user.ckd_stage,
            fruit_name=fruit_name,
            confidence=confidence
        )

        gpt_response = client.chat.completions.create(
            model=AZURE_MODEL_NAME,
            messages=[{"role": "system", "content": prompt}],
            max_tokens=150
        )
        recipe_advice = gpt_response.choices[0].message.content

        return jsonify({
            "fruit_detected": fruit_name,
            "confidence": confidence,
            "recipe": recipe_advice
        })
        
    except Exception as e:
        print(e)
        return jsonify({"error": str(e)}), 500
   
if __name__ == '__main__':
    with app.app_context():
        db.create_all()

    app.run(debug=True, port=5000)
