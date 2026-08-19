# ============================================================
# PAYMENT SYSTEM
# ============================================================

from datetime import datetime, timedelta

from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    request,
    flash
)

from flask_login import (
    login_required,
    current_user
)

from models import (
    db,
    User,
    Video,
    Series,
    Purchase
)

from invitation import process_invited_purchase


# ============================================================
# BLUEPRINT
# ============================================================

payment = Blueprint(
    'payment',
    __name__
)


# ============================================================
# PAYMENT SETTINGS
# ============================================================

MOVIE_PRICE = 700
SERIES_PRICE = 1500

PURCHASE_DURATION_DAYS = 30


# ============================================================
# MOVIE PURCHASE PAGE
# ============================================================

@payment.route(
    '/buy_movie/<int:video_id>',
    methods=['GET']
)
@login_required
def buy_movie(video_id):

    video = Video.query.get_or_404(
        video_id
    )

    # --------------------------------------------------------
    # FREE MOVIE
    # --------------------------------------------------------

    if video.free:

        return redirect(
            url_for(
                'movie',
                video_id=video.id
            )
        )

    # --------------------------------------------------------
    # CHECK EXISTING ACTIVE PURCHASE
    # --------------------------------------------------------

    now = datetime.utcnow()

    existing_purchase = Purchase.query.filter(

        Purchase.user_id == current_user.id,

        Purchase.video_id == video.id,

        Purchase.item_type == 'movie',

        Purchase.payment_status == 'Completed',

        Purchase.expires_at > now

    ).order_by(

        Purchase.expires_at.desc()

    ).first()

    if existing_purchase:

        return redirect(
            url_for(
                'movie',
                video_id=video.id
            )
        )

    return render_template(
        'buy_movie.html',

        video=video,

        price=MOVIE_PRICE,

        duration_days=PURCHASE_DURATION_DAYS
    )


# ============================================================
# SERIES PURCHASE PAGE
# ============================================================

@payment.route(
    '/buy_series/<int:series_id>',
    methods=['GET']
)
@login_required
def buy_series(series_id):

    series_item = Series.query.get_or_404(
        series_id
    )

    # --------------------------------------------------------
    # FREE SERIES
    # --------------------------------------------------------

    if series_item.free:

        return redirect(
            url_for(
                'series',
                series_id=series_item.id
            )
        )

    # --------------------------------------------------------
    # CHECK EXISTING ACTIVE PURCHASE
    # --------------------------------------------------------

    now = datetime.utcnow()

    existing_purchase = Purchase.query.filter(

        Purchase.user_id == current_user.id,

        Purchase.series_id == series_item.id,

        Purchase.item_type == 'series',

        Purchase.payment_status == 'Completed',

        Purchase.expires_at > now

    ).order_by(

        Purchase.expires_at.desc()

    ).first()

    if existing_purchase:

        return redirect(
            url_for(
                'series',
                series_id=series_item.id
            )
        )

    return render_template(
        'buy_series.html',

        series=series_item,

        price=SERIES_PRICE,

        duration_days=PURCHASE_DURATION_DAYS
    )


# ============================================================
# CREATE MOVIE PURCHASE
# ============================================================

def create_movie_purchase(
    user,
    video
):

    now = datetime.utcnow()

    expires_at = (
        now
        +
        timedelta(
            days=PURCHASE_DURATION_DAYS
        )
    )

    purchase = Purchase(

        user_id=user.id,

        video_id=video.id,

        series_id=None,

        item_type='movie',

        amount=MOVIE_PRICE,

        payment_status='Completed',

        purchased_at=now,

        expires_at=expires_at
    )

    db.session.add(
        purchase
    )

    db.session.commit()

    # --------------------------------------------------------
    # INVITATION SYSTEM
    # --------------------------------------------------------

    process_invited_purchase(
        user
    )

    return purchase


# ============================================================
# CREATE SERIES PURCHASE
# ============================================================

def create_series_purchase(
    user,
    series_item
):

    now = datetime.utcnow()

    expires_at = (
        now
        +
        timedelta(
            days=PURCHASE_DURATION_DAYS
        )
    )

    purchase = Purchase(

        user_id=user.id,

        video_id=None,

        series_id=series_item.id,

        item_type='series',

        amount=SERIES_PRICE,

        payment_status='Completed',

        purchased_at=now,

        expires_at=expires_at
    )

    db.session.add(
        purchase
    )

    db.session.commit()

    # --------------------------------------------------------
    # INVITATION SYSTEM
    # --------------------------------------------------------

    process_invited_purchase(
        user
    )

    return purchase


# ============================================================
# TEMPORARY MOVIE PAYMENT CONFIRMATION
# ============================================================
#
# IMPORTANT:
# Replace the payment confirmation section with
# your real payment provider callback.
#
# This route demonstrates what should happen AFTER
# the payment provider confirms that the user has paid.
# ============================================================

@payment.route(
    '/complete_movie/<int:video_id>',
    methods=['POST']
)
@login_required
def complete_movie_payment(video_id):

    video = Video.query.get_or_404(
        video_id
    )

    # --------------------------------------------------------
    # DO NOT USE THIS AS A REAL PAYMENT VERIFICATION
    # --------------------------------------------------------
    #
    # Your real payment provider should confirm
    # the transaction before this function is called.
    #

    purchase = create_movie_purchase(

        current_user,

        video
    )

    flash(
        'Malipo yamefanikiwa. Movie imefunguliwa kwa siku 30.',
        'success'
    )

    return redirect(
        url_for(
            'movie',
            video_id=video.id
        )
    )


# ============================================================
# TEMPORARY SERIES PAYMENT CONFIRMATION
# ============================================================

@payment.route(
    '/complete_series/<int:series_id>',
    methods=['POST']
)
@login_required
def complete_series_payment(series_id):

    series_item = Series.query.get_or_404(
        series_id
    )

    # --------------------------------------------------------
    # REAL PAYMENT PROVIDER SHOULD BE VERIFIED HERE
    # --------------------------------------------------------

    purchase = create_series_purchase(

        current_user,

        series_item
    )

    flash(
        'Malipo yamefanikiwa. Series imefunguliwa kwa siku 30.',
        'success'
    )

    return redirect(
        url_for(
            'series',
            series_id=series_item.id
        )
    )
