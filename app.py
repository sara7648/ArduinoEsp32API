from flask import Flask, request, jsonify
import requests
import os
from datetime import datetime

app = Flask(__name__)

# ===== CONFIGURATION =====
# Arduino Cloud API Configuration
ARDUINO_CLIENT_ID = os.environ.get('ARDUINO_CLIENT_ID', 'your_client_id')
ARDUINO_CLIENT_SECRET = os.environ.get('ARDUINO_CLIENT_SECRET', 'your_client_secret')
ARDUINO_THING_ID = os.environ.get('ARDUINO_THING_ID', 'your_thing_id')

# Yemot Hamashiach Configuration
AUTHORIZED_PHONES = os.environ.get('AUTHORIZED_PHONES', '').split(',')  # e.g., "0501234567,0521234567"

# Variable names from your Arduino Cloud Thing
RELAY_VARIABLE = "relay_switch"
DISTANCE_VARIABLE = "distance_cm"

# ===== ARDUINO CLOUD API FUNCTIONS =====
def get_arduino_token():
    """Get OAuth2 token from Arduino Cloud"""
    url = "https://api2.arduino.cc/iot/v1/clients/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": ARDUINO_CLIENT_ID,
        "client_secret": ARDUINO_CLIENT_SECRET,
        "audience": "https://api2.arduino.cc/iot"
    }
    response = requests.post(url, json=data)
    if response.status_code == 200:
        return response.json()['access_token']
    return None

def get_arduino_property(property_name):
    """Get current value of an Arduino Cloud property"""
    token = get_arduino_token()
    if not token:
        return None
    
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://api2.arduino.cc/iot/v2/things/{ARDUINO_THING_ID}/properties/{property_name}"
    
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()['last_value']
    return None

def set_arduino_property(property_name, value):
    """Set value of an Arduino Cloud property"""
    token = get_arduino_token()
    if not token:
        return False
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    url = f"https://api2.arduino.cc/iot/v2/things/{ARDUINO_THING_ID}/properties/{property_name}/publish"
    
    data = {"value": value}
    response = requests.put(url, json=data, headers=headers)
    return response.status_code == 200

# ===== YEMOT API HELPERS =====
def is_authorized(phone):
    """Check if phone number is authorized"""
    return phone in AUTHORIZED_PHONES

def yemot_response(actions):
    """Format response for Yemot Hamashiach"""
    # Yemot expects response in format: action1=value1&action2=value2
    return '&'.join([f"{k}={v}" for k, v in actions.items()])

# ===== YEMOT API ENDPOINTS =====
@app.route('/yemot/control', methods=['GET', 'POST'])
def yemot_control():
    """Main endpoint for Yemot Hamashiach control menu"""
    
    # Get parameters from Yemot
    phone = request.args.get('ApiPhone', '')
    digits = request.args.get('ApiDIGITS', '')
    call_id = request.args.get('ApiCallId', '')
    
    print(f"[{datetime.now()}] Call from {phone}, Digits: {digits}, CallID: {call_id}")
    
    # Check authorization
    if not is_authorized(phone):
        return yemot_response({
            'read': 'ivr2:m_unauthorized',
            'goto': 'hangup'
        })
    
    # Main menu - no digits yet
    if not digits:
        return yemot_response({
            'read': 'ivr2:m_main_menu',  # "Press 1 for relay control, 2 for distance, 3 for status"
            'id_list_visible': '1,2,3,9',
            'id_list_tap_go': '1=/yemot/relay,2=/yemot/distance,3=/yemot/status,9=hangup'
        })
    
    # Should not reach here if using id_list_tap_go
    return yemot_response({'goto': 'hangup'})

@app.route('/yemot/relay', methods=['GET', 'POST'])
def yemot_relay():
    """Relay control submenu"""
    
    phone = request.args.get('ApiPhone', '')
    digits = request.args.get('ApiDIGITS', '')
    
    if not is_authorized(phone):
        return yemot_response({'goto': 'hangup'})
    
    # Get current relay status
    current_status = get_arduino_property(RELAY_VARIABLE)
    
    if not digits:
        # Present relay menu
        if current_status == 1:
            message = 'ivr2:m_relay_on'  # "Relay is ON. Press 1 to turn OFF, 9 to return"
        else:
            message = 'ivr2:m_relay_off'  # "Relay is OFF. Press 1 to turn ON, 9 to return"
        
        return yemot_response({
            'read': message,
            'id_list_visible': '1,9',
            'id_list_tap_go': '1=/yemot/relay_toggle,9=/yemot/control'
        })
    
    return yemot_response({'goto': '/yemot/control'})

@app.route('/yemot/relay_toggle', methods=['GET', 'POST'])
def yemot_relay_toggle():
    """Toggle relay state"""
    
    phone = request.args.get('ApiPhone', '')
    
    if not is_authorized(phone):
        return yemot_response({'goto': 'hangup'})
    
    # Get current status and toggle
    current_status = get_arduino_property(RELAY_VARIABLE)
    new_status = 0 if current_status == 1 else 1
    
    success = set_arduino_property(RELAY_VARIABLE, new_status)
    
    if success:
        message = 'ivr2:m_relay_turned_on' if new_status == 1 else 'ivr2:m_relay_turned_off'
    else:
        message = 'ivr2:m_error'
    
    return yemot_response({
        'read': message,
        'goto': '/yemot/relay'
    })

@app.route('/yemot/distance', methods=['GET', 'POST'])
def yemot_distance():
    """Get distance sensor reading"""
    
    phone = request.args.get('ApiPhone', '')
    
    if not is_authorized(phone):
        return yemot_response({'goto': 'hangup'})
    
    distance = get_arduino_property(DISTANCE_VARIABLE)
    
    if distance is not None:
        # Play distance value using text-to-speech
        # Format: "The distance is X centimeters"
        return yemot_response({
            'read': f'ivr2:m_distance_is,n-{int(distance)},ivr2:m_centimeters',
            'goto': '/yemot/control'
        })
    else:
        return yemot_response({
            'read': 'ivr2:m_error',
            'goto': '/yemot/control'
        })

@app.route('/yemot/status', methods=['GET', 'POST'])
def yemot_status():
    """Get full system status"""
    
    phone = request.args.get('ApiPhone', '')
    
    if not is_authorized(phone):
        return yemot_response({'goto': 'hangup'})
    
    relay_status = get_arduino_property(RELAY_VARIABLE)
    distance = get_arduino_property(DISTANCE_VARIABLE)
    
    # Build status message
    relay_msg = 'ivr2:m_relay_on' if relay_status == 1 else 'ivr2:m_relay_off'
    
    return yemot_response({
        'read': f'{relay_msg},ivr2:m_distance_is,n-{int(distance)},ivr2:m_centimeters',
        'goto': '/yemot/control'
    })

# ===== OUTBOUND CALL TRIGGER (Optional) =====
@app.route('/trigger/alert', methods=['POST'])
def trigger_alert():
    """
    Trigger an outbound call to alert user
    Call this endpoint when you want to alert the user
    
    Example: POST to this endpoint when relay changes state unexpectedly
    """
    
    # This is a webhook you can call from Arduino Cloud or external service
    phone = request.json.get('phone')
    message = request.json.get('message', 'alert')
    
    # Make outbound call via Yemot API
    # You'll need to implement Yemot's outbound call API
    # Documentation: https://www.call2all.co.il/ym/api/
    
    return jsonify({"status": "alert_sent", "phone": phone})

# ===== MONITORING ENDPOINT =====
@app.route('/monitor', methods=['GET'])
def monitor():
    """Monitor endpoint to check Arduino connection"""
    
    relay_status = get_arduino_property(RELAY_VARIABLE)
    distance = get_arduino_property(DISTANCE_VARIABLE)
    
    return jsonify({
        "status": "online",
        "relay": relay_status,
        "distance": distance,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/', methods=['GET'])
def home():
    """Health check endpoint"""
    return jsonify({
        "status": "running",
        "service": "Yemot-Arduino Integration",
        "endpoints": {
            "control": "/yemot/control",
            "monitor": "/monitor"
        }
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
