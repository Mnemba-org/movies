# invitation.py

import secrets
import string

from datetime import datetime, timedelta

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
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


# ============================================================
# INVITATION BLUEPRINT
# ============================================================

invitation = Blueprint(
    'invitation',
    __name__
)


# ============================================================
# CAMPAIGN SETTINGS
# ============================================================

INVITATION_DAYS = 10

PURCHASES_FOR_REWARD = 3

REWARD_EXPIRATION_DAYS = 30


# ============================================================
# GENERATE PERMANENT INVITATION CODE
# ============================================================

def generate_invitation_code():
    """
    Generate a unique permanent invitation code.

    The code is generated only once for a user
    and remains unchanged.
    """

    characters = (
        string.ascii_uppercase
        + string.digits
    )

    while True:

        code = ''.join(
            secrets.choice(characters)
            for _ in range(8)
        )

        existing_user = User.query.filter_by(
            invitation_code=code
        ).first()

        if not existing_user:

            return code


# ============================================================
# GET OR CREATE USER INVITATION CODE
# ============================================================

def get_or_create_invitation_code(user):
    """
    Return the user's permanent invitation code.

    If the user doesn't have one yet,
    generate it and save it.

    Once generated, it never changes.
    """

    if user.invitation_code:

        return user.invitation_code

    user.invitation_code = (
        generate_invitation_code()
    )

    db.session.commit()

    return user.invitation_code


# ============================================================
# CHECK WHETHER USER CAN ENTER AN INVITATION CODE
# ============================================================

def can_apply_invitation_code(user):
    """
    Users can enter an invitation code only
    within 10 days after registration.

    They also must not already have an inviter.
    """

    if user.invited_by_id is not None:

        return False

    if not user.created_at:

        return False

    age = (
        datetime.utcnow()
        - user.created_at
    )

    return age <= timedelta(
        days=INVITATION_DAYS
    )


# ============================================================
# FIND INVITER BY CODE
# ============================================================

def get_inviter_by_code(code):

    if not code:

        return None

    code = code.strip().upper()

    return User.query.filter_by(
        invitation_code=code
    ).first()


# ============================================================
# APPLY INVITATION CODE
# ============================================================

@invitation.route(
    '/zawadi/apply',
    methods=['POST']
)
@login_required
def apply_invitation_code():

    """
    Attach the current user to an inviter.

    Important:

    - User must be logged in.
    - User must be within 10 days of registration.
    - User cannot already have an inviter.
    - User cannot use their own code.
    """

    # --------------------------------------------------------
    # CHECK WHETHER CODE CAN STILL BE USED
    # --------------------------------------------------------

    if not can_apply_invitation_code(
        current_user
    ):

        flash(
            'Muda wa kutumia invitation code umeisha au tayari una inviter.',
            'error'
        )

        return redirect(
            url_for('invitation.zawadi')
        )

    # --------------------------------------------------------
    # GET CODE
    # --------------------------------------------------------

    code = request.form.get(
        'invitation_code',
        ''
    ).strip().upper()

    if not code:

        flash(
            'Tafadhali ingiza invitation code.',
            'error'
        )

        return redirect(
            url_for('invitation.zawadi')
        )

    # --------------------------------------------------------
    # FIND INVITER
    # --------------------------------------------------------

    inviter = get_inviter_by_code(
        code
    )

    if not inviter:

        flash(
            'Invitation code si sahihi.',
            'error'
        )

        return redirect(
            url_for('invitation.zawadi')
        )

    # --------------------------------------------------------
    # PREVENT SELF INVITATION
    # --------------------------------------------------------

    if inviter.id == current_user.id:

        flash(
            'Huwezi kutumia invitation code yako mwenyewe.',
            'error'
        )

        return redirect(
            url_for('invitation.zawadi')
        )

    # --------------------------------------------------------
    # ASSIGN INVITER
    # --------------------------------------------------------

    current_user.invited_by_id = inviter.id

    db.session.commit()

    flash(
        f'Umefanikiwa kutumia invitation code ya {inviter.username}. '
        f'Sasa manunuzi yako yatachangia zawadi yake.',
        'success'
    )

    return redirect(
        url_for('invitation.zawadi')
    )


# ============================================================
# ZAWADI PAGE
# ============================================================

@invitation.route(
    '/zawadi'
)
@login_required
def zawadi():

    """
    Main invitation campaign page.
    """

    invitation_code = (
        get_or_create_invitation_code(
            current_user
        )
    )

    can_apply = can_apply_invitation_code(
        current_user
    )

    return render_template(
        'zawadi.html',
        invitation_code=invitation_code,
        can_apply_invitation=can_apply,
        reward_count=current_user.free_rewards,
        purchase_count=current_user.invitation_purchase_count,
        purchases_needed=(
            PURCHASES_FOR_REWARD
        )
    )


# ============================================================
# PROCESS INVITATION REWARD
# ============================================================

def process_invitation_reward(user_id):
    """
    Called after a user's REAL payment has been
    successfully completed.

    Every 3 completed purchases by an invited user:

        3 purchases → 1 reward
        6 purchases → 2 rewards
        9 purchases → 3 rewards

    Only completed paid purchases should call this function.
    """

    user = User.query.get(
        user_id
    )

    if not user:

        return None

    # --------------------------------------------------------
    # USER MUST HAVE AN INVITER
    # --------------------------------------------------------

    if not user.invited_by_id:

        return None

    inviter = User.query.get(
        user.invited_by_id
    )

    if not inviter:

        return None

    # --------------------------------------------------------
    # COUNT COMPLETED PAID PURCHASES
    # --------------------------------------------------------

    completed_purchases = Purchase.query.filter(
        Purchase.user_id == user.id,
        Purchase.payment_status == 'Completed',
        Purchase.amount > 0
    ).count()

    # --------------------------------------------------------
    # CALCULATE REWARDS EARNED
    # --------------------------------------------------------

    rewards_earned = (
        completed_purchases
        //
        PURCHASES_FOR_REWARD
    )

    # --------------------------------------------------------
    # CURRENT REWARDS ALREADY GIVEN
    # --------------------------------------------------------

    previous_records = (
        InvitationReward.query.filter_by(
            inviter_id=inviter.id,
            invited_user_id=user.id
        ).count()
    )

    # --------------------------------------------------------
    # GIVE ONLY NEW REWARDS
    # --------------------------------------------------------

    new_rewards = (
        rewards_earned
        -
        previous_records
    )

    if new_rewards <= 0:

        return None

    # --------------------------------------------------------
    # ADD REWARDS
    # --------------------------------------------------------

    inviter.free_rewards += new_rewards

    for _ in range(new_rewards):

        reward = InvitationReward(

            inviter_id=inviter.id,

            invited_user_id=user.id,

            reward_type='free_content',

            created_at=datetime.utcnow()
        )

        db.session.add(
            reward
        )

    db.session.commit()

    return new_rewards


# ============================================================
# USE FREE MOVIE REWARD
# ============================================================

@invitation.route(
    '/zawadi/use/movie/<int:video_id>',
    methods=['POST']
)
@login_required
def use_movie_reward(video_id):

    """
    Spend ONE free reward to unlock one movie.

    One reward = one movie.

    The reward is reduced immediately after
    successful creation of the free purchase.
    """

    video = Video.query.get_or_404(
        video_id
    )

    # --------------------------------------------------------
    # CHECK REWARD BALANCE
    # --------------------------------------------------------

    if current_user.free_rewards <= 0:

        flash(
            'Huna zawadi ya kutumia.',
            'error'
        )

        return redirect(
            url_for(
                'movie',
                video_id=video.id
            )
        )

    # --------------------------------------------------------
    # FREE MOVIE DOES NOT NEED A REWARD
    # --------------------------------------------------------

    if video.free:

        flash(
            'Movie hii tayari ni bure.',
            'info'
        )

        return redirect(
            url_for(
                'movie',
                video_id=video.id
            )
        )

    # --------------------------------------------------------
    # CHECK EXISTING ACTIVE PURCHASE
    # --------------------------------------------------------

    existing_purchase = Purchase.query.filter(
        Purchase.user_id == current_user.id,
        Purchase.video_id == video.id,
        Purchase.item_type == 'movie',
        Purchase.payment_status == 'Completed',
        Purchase.expires_at > datetime.utcnow()
    ).first()

    if existing_purchase:

        flash(
            'Tayari una access ya movie hii.',
            'info'
        )

        return redirect(
            url_for(
                'movie',
                video_id=video.id
            )
        )

    # --------------------------------------------------------
    # CREATE FREE PURCHASE
    # --------------------------------------------------------

    purchase = Purchase(

        user_id=current_user.id,

        video_id=video.id,

        series_id=None,

        item_type='movie',

        amount=0,

        merchant_reference=(
            'REWARD-'
            + secrets.token_hex(16)
        ),

        payment_status='Completed',

        purchased_at=datetime.utcnow(),

        expires_at=(
            datetime.utcnow()
            +
            timedelta(
                days=REWARD_EXPIRATION_DAYS
            )
        )
    )

    db.session.add(
        purchase
    )

    # --------------------------------------------------------
    # REDUCE REWARD BY ONE
    # --------------------------------------------------------

    current_user.free_rewards -= 1

    db.session.commit()

    flash(
        f'Umetumia zawadi moja kufungua "{video.title}".',
        'success'
    )

    return redirect(
        url_for(
            'movie',
            video_id=video.id
        )
    )


# ============================================================
# USE FREE SERIES REWARD
# ============================================================

@invitation.route(
    '/zawadi/use/series/<int:series_id>',
    methods=['POST']
)
@login_required
def use_series_reward(series_id):

    """
    Spend ONE free reward to unlock one series.

    One reward = one series.
    """

    series = Series.query.get_or_404(
        series_id
    )

    # --------------------------------------------------------
    # CHECK REWARD BALANCE
    # --------------------------------------------------------

    if current_user.free_rewards <= 0:

        flash(
            'Huna zawadi ya kutumia.',
            'error'
        )

        return redirect(
            url_for(
                'series',
                series_id=series.id
            )
        )

    # --------------------------------------------------------
    # FREE SERIES
    # --------------------------------------------------------

    if series.free:

        flash(
            'Series hii tayari ni bure.',
            'info'
        )

        return redirect(
            url_for(
                'series',
                series_id=series.id
            )
        )

    # --------------------------------------------------------
    # CHECK EXISTING ACTIVE PURCHASE
    # --------------------------------------------------------

    existing_purchase = Purchase.query.filter(
        Purchase.user_id == current_user.id,
        Purchase.series_id == series.id,
        Purchase.item_type == 'series',
        Purchase.payment_status == 'Completed',
        Purchase.expires_at > datetime.utcnow()
    ).first()

    if existing_purchase:

        flash(
            'Tayari una access ya series hii.',
            'info'
        )

        return redirect(
            url_for(
                'series',
                series_id=series.id
            )
        )

    # --------------------------------------------------------
    # CREATE FREE PURCHASE
    # --------------------------------------------------------

    purchase = Purchase(

        user_id=current_user.id,

        video_id=None,

        series_id=series.id,

        item_type='series',

        amount=0,

        merchant_reference=(
            'REWARD-'
            + secrets.token_hex(16)
        ),

        payment_status='Completed',

        purchased_at=datetime.utcnow(),

        expires_at=(
            datetime.utcnow()
            +
            timedelta(
                days=REWARD_EXPIRATION_DAYS
            )
        )
    )

    db.session.add(
        purchase
    )

    # --------------------------------------------------------
    # REDUCE REWARD BY ONE
    # --------------------------------------------------------

    current_user.free_rewards -= 1

    db.session.commit()

    flash(
        f'Umetumia zawadi moja kufungua "{series.title}".',
        'success'
    )

    return redirect(
        url_for(
            'series',
            series_id=series.id
        )
    )
