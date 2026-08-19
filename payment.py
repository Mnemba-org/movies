# payment.py

import os
import uuid
import requests

from datetime import datetime, timedelta

from flask import (
    Blueprint,
    request,
    redirect,
    url_for,
    flash,
    jsonify
)

from flask_login import login_required, current_user

from models import db, User, Video, Series, Purchase


# ============================================================
# PAYMENT BLUEPRINT
# ============================================================

payment = Blueprint(
    'payment',
    __name__
)


# ============================================================
# PESAPAL CONFIGURATION
# ============================================================

PESAPAL_CONSUMER_KEY = os.environ.get(
    'PESAPAL_CONSUMER_KEY'
)

PESAPAL_CONSUMER_SECRET = os.environ.get(
    'PESAPAL_CONSUMER_SECRET'
)

PESAPAL_BASE_URL = (
    "https://pay.pesapal.com/v3"
)

APP_BASE_URL = os.environ.get(
    'APP_BASE_URL',
    'https://muvizetu.com'
)


# ============================================================
# PRICES
# ============================================================

# IMPORTANT:
# Pesapal/payment method does not support transactions
# below 1,000 TSh.

MOVIE_PRICE = 1000.00

SERIES_PRICE = 2000.00

# Purchased content remains accessible for 30 days.
ACCESS_DAYS = 30


# ============================================================
# PESAPAL AUTHENTICATION
# ============================================================

def get_pesapal_auth_token():

    """
    Get a temporary authentication token
    from Pesapal.
    """

    url = (
        f"{PESAPAL_BASE_URL}"
        "/api/Auth/RequestToken"
    )

    payload = {

        "consumer_key":
            PESAPAL_CONSUMER_KEY,

        "consumer_secret":
            PESAPAL_CONSUMER_SECRET
    }

    headers = {

        "Content-Type":
            "application/json",

        "Accept":
            "application/json"
    }

    try:

        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=30
        )

        print(
            "Pesapal authentication status:",
            response.status_code
        )

        if response.status_code == 200:

            data = response.json()

            return data.get("token")

        print(
            "Pesapal authentication response:",
            response.text
        )

    except Exception as e:

        print(
            "Pesapal authentication error:",
            e
        )

    return None


# ============================================================
# REGISTER PESAPAL IPN
# ============================================================

def register_pesapal_ipn(token):

    """
    Register the IPN/webhook URL with Pesapal.

    Pesapal returns an IPN ID which is required
    when creating a payment order.
    """

    url = (
        f"{PESAPAL_BASE_URL}"
        "/api/URLSetup/RegisterIPN"
    )

    headers = {

        "Authorization":
            f"Bearer {token}",

        "Content-Type":
            "application/json",

        "Accept":
            "application/json"
    }

    payload = {

        "url":
            f"{APP_BASE_URL}/payment/pesapal/ipn",

        "ipn_notification_type":
            "GET"
    }

    try:

        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=30
        )

        print(
            "Pesapal IPN registration status:",
            response.status_code
        )

        if response.status_code == 200:

            data = response.json()

            print(
                "Pesapal IPN response:",
                data
            )

            return data.get("ipn_id")

        print(
            "Pesapal IPN registration response:",
            response.text
        )

    except Exception as e:

        print(
            "Pesapal IPN registration error:",
            e
        )

    return None


# ============================================================
# GET TRANSACTION STATUS
# ============================================================

def get_transaction_status(
    token,
    order_tracking_id
):

    """
    Ask Pesapal for the current status
    of a transaction.
    """

    url = (
        f"{PESAPAL_BASE_URL}"
        "/api/Transactions/GetTransactionStatus"
    )

    params = {

        "orderTrackingId":
            order_tracking_id
    }

    headers = {

        "Authorization":
            f"Bearer {token}",

        "Accept":
            "application/json"
    }

    try:

        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=30
        )

        print(
            "Transaction status:",
            response.status_code
        )

        if response.status_code == 200:

            return response.json()

        print(
            "Transaction status response:",
            response.text
        )

    except Exception as e:

        print(
            "Transaction status error:",
            e
        )

    return None


# ============================================================
# FIND EXISTING PURCHASE
# ============================================================

def get_pending_purchase(
    merchant_reference
):

    return Purchase.query.filter_by(
        merchant_reference=merchant_reference
    ).first()


# ============================================================
# CREATE PURCHASE
# ============================================================

def create_purchase(
    user_id,
    video_id=None,
    series_id=None,
    item_type=None,
    amount=0,
    merchant_reference=None
):

    """
    Create a pending purchase.

    It becomes Completed only after
    Pesapal confirms payment.
    """

    purchase = Purchase(

        user_id=user_id,

        video_id=video_id,

        series_id=series_id,

        item_type=item_type,

        amount=amount,

        merchant_reference=
            merchant_reference,

        payment_status="Pending",

        purchased_at=datetime.utcnow(),

        expires_at=None
    )

    db.session.add(purchase)

    db.session.commit()

    return purchase


# ============================================================
# COMPLETE PURCHASE
# ============================================================

def complete_purchase(
    purchase,
    order_tracking_id,
    amount
):

    """
    Mark a purchase as completed and
    give the user 30 days of access.
    """

    purchase.payment_status = "Completed"

    purchase.order_tracking_id = (
        order_tracking_id
    )

    purchase.amount = amount

    purchase.purchased_at = (
        datetime.utcnow()
    )

    purchase.expires_at = (
        datetime.utcnow()
        +
        timedelta(days=ACCESS_DAYS)
    )

    db.session.commit()

    print(
        "Purchase completed:",
        purchase.id
    )

    print(
        "Amount:",
        amount
    )

    print(
        "Expires:",
        purchase.expires_at
    )

    return purchase


# ============================================================
# FAIL PURCHASE
# ============================================================

def fail_purchase(
    purchase,
    order_tracking_id=None
):

    purchase.payment_status = "Failed"

    if order_tracking_id:

        purchase.order_tracking_id = (
            order_tracking_id
        )

    db.session.commit()

    return purchase


# ============================================================
# BUY MOVIE
# ============================================================

@payment.route(
    '/buy_movie/<int:video_id>',
    methods=['GET']
)
@login_required
def buy_movie(video_id):

    """
    Start payment for one movie.

    Movie price = 1,000 TSh
    Access = 30 days
    """

    video = Video.query.get_or_404(
        video_id
    )

    # --------------------------------------------------------
    # FREE MOVIE
    # --------------------------------------------------------

    if video.free:

        return redirect(
            video.video_path
        )

    # --------------------------------------------------------
    # PRICE
    # --------------------------------------------------------

    amount = float(
        video.price
        if video.price is not None
        else MOVIE_PRICE
    )

    # --------------------------------------------------------
    # SAFETY CHECK
    # --------------------------------------------------------
    # Make sure no movie payment can accidentally
    # be submitted below 1,000 TSh.

    if amount < MOVIE_PRICE:

        amount = MOVIE_PRICE

    # --------------------------------------------------------
    # GENERATE UNIQUE REFERENCE
    # --------------------------------------------------------

    merchant_reference = str(
        uuid.uuid4()
    )

    # --------------------------------------------------------
    # CREATE PENDING PURCHASE
    # --------------------------------------------------------

    purchase = create_purchase(

        user_id=current_user.id,

        video_id=video.id,

        series_id=None,

        item_type="movie",

        amount=amount,

        merchant_reference=
            merchant_reference
    )

    # --------------------------------------------------------
    # GET PESAPAL TOKEN
    # --------------------------------------------------------

    token = get_pesapal_auth_token()

    if not token:

        db.session.delete(
            purchase
        )

        db.session.commit()

        flash(
            "Payment gateway currently offline. Please try again later.",
            "error"
        )

        return redirect(
            url_for('home')
        )

    # --------------------------------------------------------
    # REGISTER IPN
    # --------------------------------------------------------

    ipn_id = register_pesapal_ipn(
        token
    )

    if not ipn_id:

        purchase.payment_status = "Failed"

        db.session.commit()

        flash(
            "Secure transaction setup failed. Please try again.",
            "error"
        )

        return redirect(
            url_for('home')
        )

    # --------------------------------------------------------
    # CREATE PESAPAL ORDER
    # --------------------------------------------------------

    url = (
        f"{PESAPAL_BASE_URL}"
        "/api/Transactions/SubmitOrderRequest"
    )

    headers = {

        "Authorization":
            f"Bearer {token}",

        "Content-Type":
            "application/json",

        "Accept":
            "application/json"
    }

    payload = {

        "id":
            merchant_reference,

        "currency":
            "TZS",

        "amount":
            amount,

        "description":
            f"Muvi Zetu Movie - {video.title}",

        "callback_url":
            f"{APP_BASE_URL}/payment/pesapal/callback",

        "notification_id":
            ipn_id,

        "billing_address": {

            "email_address":
                current_user.email,

            "phone_number":
                "0700000000",

            "country_code":
                "TZ",

            "first_name":
                current_user.username,

            "last_name":
                "User",

            "line_1":
                "Tanzania",

            "city":
                "Dar es Salaam",

            "state":
                "Tanzania"
        }
    }

    try:

        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=30
        )

        print(
            "Movie payment response:",
            response.status_code,
            response.text
        )

        if response.status_code == 200:

            data = response.json()

            redirect_url = data.get(
                "redirect_url"
            )

            if redirect_url:

                return redirect(
                    redirect_url
                )

        purchase.payment_status = "Failed"

        db.session.commit()

    except Exception as e:

        print(
            "Movie order submission error:",
            e
        )

        purchase.payment_status = "Failed"

        db.session.commit()

    flash(
        "Could not initialize movie payment.",
        "error"
    )

    return redirect(
        url_for('home')
    )


# ============================================================
# BUY SERIES
# ============================================================

@payment.route(
    '/buy_series/<int:series_id>',
    methods=['GET']
)
@login_required
def buy_series(series_id):

    """
    Start payment for one series.

    Series price = 2,000 TSh
    Access = 30 days
    """

    series = Series.query.get_or_404(
        series_id
    )

    # --------------------------------------------------------
    # FREE SERIES
    # --------------------------------------------------------

    if series.free:

        return redirect(
            url_for(
                'series',
                series_id=series.id
            )
        )

    # --------------------------------------------------------
    # PRICE
    # --------------------------------------------------------

    amount = float(
        series.price
        if series.price is not None
        else SERIES_PRICE
    )

    # --------------------------------------------------------
    # SAFETY CHECK
    # --------------------------------------------------------
    # Make sure no series payment can accidentally
    # be submitted below 2,000 TSh.

    if amount < SERIES_PRICE:

        amount = SERIES_PRICE

    # --------------------------------------------------------
    # UNIQUE REFERENCE
    # --------------------------------------------------------

    merchant_reference = str(
        uuid.uuid4()
    )

    # --------------------------------------------------------
    # CREATE PENDING PURCHASE
    # --------------------------------------------------------

    purchase = create_purchase(

        user_id=current_user.id,

        video_id=None,

        series_id=series.id,

        item_type="series",

        amount=amount,

        merchant_reference=
            merchant_reference
    )

    # --------------------------------------------------------
    # GET TOKEN
    # --------------------------------------------------------

    token = get_pesapal_auth_token()

    if not token:

        db.session.delete(
            purchase
        )

        db.session.commit()

        flash(
            "Payment gateway currently offline. Please try again later.",
            "error"
        )

        return redirect(
            url_for('home')
        )

    # --------------------------------------------------------
    # REGISTER IPN
    # --------------------------------------------------------

    ipn_id = register_pesapal_ipn(
        token
    )

    if not ipn_id:

        purchase.payment_status = "Failed"

        db.session.commit()

        flash(
            "Secure transaction setup failed. Please try again.",
            "error"
        )

        return redirect(
            url_for('home')
        )

    # --------------------------------------------------------
    # CREATE PESAPAL ORDER
    # --------------------------------------------------------

    url = (
        f"{PESAPAL_BASE_URL}"
        "/api/Transactions/SubmitOrderRequest"
    )

    headers = {

        "Authorization":
            f"Bearer {token}",

        "Content-Type":
            "application/json",

        "Accept":
            "application/json"
    }

    payload = {

        "id":
            merchant_reference,

        "currency":
            "TZS",

        "amount":
            amount,

        "description":
            f"Muvi Zetu Series - {series.title}",

        "callback_url":
            f"{APP_BASE_URL}/payment/pesapal/callback",

        "notification_id":
            ipn_id,

        "billing_address": {

            "email_address":
                current_user.email,

            "phone_number":
                "0700000000",

            "country_code":
                "TZ",

            "first_name":
                current_user.username,

            "last_name":
                "User",

            "line_1":
                "Tanzania",

            "city":
                "Dar es Salaam",

            "state":
                "Tanzania"
        }
    }

    try:

        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=30
        )

        print(
            "Series payment response:",
            response.status_code,
            response.text
        )

        if response.status_code == 200:

            data = response.json()

            redirect_url = data.get(
                "redirect_url"
            )

            if redirect_url:

                return redirect(
                    redirect_url
                )

        purchase.payment_status = "Failed"

        db.session.commit()

    except Exception as e:

        print(
            "Series order submission error:",
            e
        )

        purchase.payment_status = "Failed"

        db.session.commit()

    flash(
        "Could not initialize series payment.",
        "error"
    )

    return redirect(
        url_for('home')
    )


# ============================================================
# PESAPAL CALLBACK
# ============================================================

@payment.route(
    '/pesapal/callback',
    methods=['GET']
)
def pesapal_callback():

    """
    User is redirected here after completing
    the payment page.

    The actual payment verification is done
    against Pesapal rather than trusting the
    callback alone.
    """

    merchant_reference = request.args.get(
        'OrderMerchantReference'
    )

    order_tracking_id = request.args.get(
        'OrderTrackingId'
    )

    print(
        "Pesapal callback:",
        merchant_reference,
        order_tracking_id
    )

    if not merchant_reference:

        flash(
            "Payment reference was not received.",
            "error"
        )

        return redirect(
            url_for('home')
        )

    purchase = Purchase.query.filter_by(
        merchant_reference=
            merchant_reference
    ).first()

    if not purchase:

        flash(
            "Payment record could not be found.",
            "error"
        )

        return redirect(
            url_for('home')
        )

    # --------------------------------------------------------
    # ALREADY COMPLETED
    # --------------------------------------------------------

    if purchase.payment_status == "Completed":

        if purchase.item_type == "movie":

            return redirect(
                url_for(
                    'movie',
                    video_id=purchase.video_id
                )
            )

        if purchase.item_type == "series":

            return redirect(
                url_for(
                    'series',
                    series_id=purchase.series_id
                )
            )

    # --------------------------------------------------------
    # VERIFY WITH PESAPAL
    # --------------------------------------------------------

    if order_tracking_id:

        token = get_pesapal_auth_token()

        if token:

            status_data = get_transaction_status(
                token,
                order_tracking_id
            )

            if status_data:

                status = status_data.get(
                    "payment_status_description"
                )

                amount = status_data.get(
                    "amount"
                )

                print(
                    "Verified payment status:",
                    status
                )

                # ------------------------------------------------
                # SUCCESS
                # ------------------------------------------------

                if status == "Completed":

                    expected_amount = float(
                        purchase.amount
                    )

                    try:

                        paid_amount = float(
                            amount
                        )

                    except (
                        TypeError,
                        ValueError
                    ):

                        paid_amount = 0

                    # ------------------------------------------------
                    # VERIFY AMOUNT
                    # ------------------------------------------------

                    if abs(
                        paid_amount
                        -
                        expected_amount
                    ) < 0.01:

                        complete_purchase(

                            purchase,

                            order_tracking_id,

                            paid_amount
                        )

                        flash(
                            "Malipo yamekamilika! Unaweza kuangalia maudhui yako kwa siku 30.",
                            "success"
                        )

                    else:

                        print(
                            "WARNING: Payment amount mismatch."
                        )

                        fail_purchase(
                            purchase,
                            order_tracking_id
                        )

                        flash(
                            "Payment amount verification failed.",
                            "error"
                        )

                # ------------------------------------------------
                # FAILED
                # ------------------------------------------------

                elif status in [
                    "Failed",
                    "Invalid"
                ]:

                    fail_purchase(
                        purchase,
                        order_tracking_id
                    )

                    flash(
                        "Payment was not completed.",
                        "error"
                    )

    # --------------------------------------------------------
    # REDIRECT AFTER PAYMENT
    # --------------------------------------------------------

    if purchase.payment_status == "Completed":

        if purchase.item_type == "movie":

            return redirect(
                url_for(
                    'movie',
                    video_id=purchase.video_id
                )
            )

        elif purchase.item_type == "series":

            return redirect(
                url_for(
                    'series',
                    series_id=purchase.series_id
                )
            )

    return redirect(
        url_for('home')
    )


# ============================================================
# PESAPAL IPN
# ============================================================

@payment.route(
    '/pesapal/ipn',
    methods=['GET', 'POST']
)
def pesapal_ipn():

    """
    Pesapal server-to-server notification.

    This endpoint verifies the transaction
    directly with Pesapal before completing
    the purchase.
    """

    order_tracking_id = request.args.get(
        'OrderTrackingId'
    )

    notification_type = request.args.get(
        'OrderNotificationType'
    )

    merchant_reference = request.args.get(
        'OrderMerchantReference'
    )

    print(
        "Pesapal IPN received:"
    )

    print(
        "Notification type:",
        notification_type
    )

    print(
        "Tracking ID:",
        order_tracking_id
    )

    print(
        "Merchant reference:",
        merchant_reference
    )

    if not merchant_reference:

        return jsonify({

            "ResultCode": 0,

            "ResponseDescription":
                "Success"

        }), 200

    purchase = Purchase.query.filter_by(
        merchant_reference=
            merchant_reference
    ).first()

    if not purchase:

        print(
            "Purchase not found:",
            merchant_reference
        )

        return jsonify({

            "ResultCode": 0,

            "ResponseDescription":
                "Success"

        }), 200

    # --------------------------------------------------------
    # DO NOT PROCESS TWICE
    # --------------------------------------------------------

    if purchase.payment_status == "Completed":

        return jsonify({

            "ResultCode": 0,

            "ResponseDescription":
                "Success"

        }), 200

    # --------------------------------------------------------
    # VERIFY TRANSACTION
    # --------------------------------------------------------

    if order_tracking_id:

        token = get_pesapal_auth_token()

        if token:

            status_data = get_transaction_status(

                token,

                order_tracking_id
            )

            if status_data:

                status = status_data.get(
                    "payment_status_description"
                )

                amount = status_data.get(
                    "amount"
                )

                print(
                    "IPN verified status:",
                    status
                )

                if status == "Completed":

                    expected_amount = float(
                        purchase.amount
                    )

                    try:

                        paid_amount = float(
                            amount
                        )

                    except (
                        TypeError,
                        ValueError
                    ):

                        paid_amount = 0

                    # ------------------------------------------------
                    # VERIFY PAYMENT AMOUNT
                    # ------------------------------------------------

                    if abs(
                        paid_amount
                        -
                        expected_amount
                    ) < 0.01:

                        complete_purchase(

                            purchase,

                            order_tracking_id,

                            paid_amount
                        )

                        print(
                            "✅ Purchase completed from IPN."
                        )

                    else:

                        print(
                            "❌ Payment amount mismatch."
                        )

                        fail_purchase(

                            purchase,

                            order_tracking_id
                        )

                elif status in [
                    "Failed",
                    "Invalid"
                ]:

                    fail_purchase(

                        purchase,

                        order_tracking_id
                    )

                    print(
                        "❌ Payment failed."
                    )

    # --------------------------------------------------------
    # PESAPAL EXPECTS SUCCESS RESPONSE
    # --------------------------------------------------------

    return jsonify({

        "ResultCode": 0,

        "ResponseDescription":
            "Success"

    }), 200
