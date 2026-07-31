from flask import Blueprint, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from models import Subscription, db
from datetime import datetime, timedelta
import uuid
import requests

# Create the payment blueprint
payment_bp = Blueprint('payment', __name__, url_prefix='/pesapal')

# ===== Helper Functions =====

def get_pesapal_auth_token():
    """Fetches a valid 5-minute authentication token from the live gateway"""
    url = f"{current_app.config['PESAPAL_BASE_URL']}/api/Auth/RequestToken"
    payload = {
        "consumer_key": current_app.config['PESAPAL_CONSUMER_KEY'],
        "consumer_secret": current_app.config['PESAPAL_CONSUMER_SECRET']
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            return response.json().get("token")
    except Exception as e:
        print(f"Pesapal Token Authentication Error: {e}")
    return None

def register_pesapal_ipn(token):
    """Registers your webhook route dynamically with the Pesapal API"""
    url = f"{current_app.config['PESAPAL_BASE_URL']}/api/URLSetup/RegisterIPN"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    payload = {
        "url": f"{current_app.config['APP_BASE_URL']}/pesapal/ipn",
        "ipn_notification_type": "GET"
    }
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            return response.json().get("ipn_id")
    except Exception as e:
        print(f"Pesapal Webhook Registry Error: {e}")
    return None

# ===== Payment Routes =====

@payment_bp.route('/subscribe')
@login_required
def subscribe():
    """Initiate subscription payment"""
    plan_type = request.args.get('plan', 'weekly')
    if plan_type not in ['weekly', 'monthly']:
        plan_type = 'weekly'
    
    amount = 2000.00 if plan_type == 'weekly' else 4000.00
    merchant_reference = str(uuid.uuid4())
    
    token = get_pesapal_auth_token()
    if not token:
        flash("Payment gateway currently offline. Please attempt later.", "error")
        return redirect(url_for('home'))
    
    ipn_id = register_pesapal_ipn(token)
    if not ipn_id:
        flash("Secure transaction tunnel failure.", "error")
        return redirect(url_for('home'))
    
    url = f"{current_app.config['PESAPAL_BASE_URL']}/api/Transactions/SubmitOrderRequest"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    payload = {
        "id": merchant_reference,
        "currency": "TZS",
        "amount": amount,
        "description": f"Muvi zetu Premium - {plan_type.capitalize()}",
        "callback_url": f"{current_app.config['APP_BASE_URL']}/pesapal/callback",
        "notification_id": ipn_id,
        "billing_address": {
            "email_address": current_user.email,
            "phone_number": "0700000000",
            "country_code": "TZ",
            "first_name": current_user.username,
            "last_name": "User",
            "line_1": "Dar es Salaam",
            "city": "Dar es Salaam",
            "state": "Tanzania"
        }
    }
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            redirect_url = response.json().get("redirect_url")
            return redirect(redirect_url)
    except Exception as e:
        print(f"Order submission error: {e}")
        flash("Could not initialize transaction with gateway.", "error")
        return redirect(url_for('home'))

@payment_bp.route('/callback', methods=['GET'])
@login_required
def callback():
    """User endpoint redirection destination upon billing completion"""
    flash("Malipo yanashughulikiwa. Tafadhali angalia hali ya usajili wako baada ya muda mfupi.", "success")
    return redirect(url_for('my_subscription'))

@payment_bp.route('/ipn', methods=['GET', 'POST'])
def ipn():
    """Instant Payment Notification webhook"""
    order_tracking_id = request.args.get('OrderTrackingId')
    notification_type = request.args.get('OrderNotificationType')
    merchant_reference = request.args.get('OrderMerchantReference')
    
    if notification_type in ["CHANGE", "IPNCHANGE"] and order_tracking_id:
        token = get_pesapal_auth_token()
        if token:
            url = f"{current_app.config['PESAPAL_BASE_URL']}/api/Transactions/GetTransactionStatus?orderTrackingId={order_tracking_id}"
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                status_data = response.json()
                print("IPN full response:", status_data)
                if status_data.get("payment_status_description") == "Completed":
                    sub = Subscription.query.filter_by(merchant_reference=merchant_reference).first()
                    if sub:
                        amount = status_data.get("amount", 0)
                        if amount == 2000.0:
                            sub.plan_type = "weekly"
                            sub.end_date = datetime.utcnow() + timedelta(days=7)
                        elif amount == 4000.0:
                            sub.plan_type = "monthly"
                            sub.end_date = datetime.utcnow() + timedelta(days=30)
                        db.session.commit()
    
    return jsonify({"ResultCode": 0, "ResponseDescription": "Success"}), 200
