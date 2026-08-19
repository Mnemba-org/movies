# ============================================================
# INVITATION / ZAWADI SYSTEM
# ============================================================

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
    Invitation,
    InvitationReward
)


# ============================================================
# BLUEPRINT
# ============================================================

invitation = Blueprint(
    'invitation',
    __name__
)


# ============================================================
# CAMPAIGN SETTINGS
# ============================================================

# New users can enter an invitation code
# only during their first 10 days.
INVITATION_CODE_DAYS = 10

# Invited user must complete 3 paid purchases
# before inviter receives 1 free reward.
PURCHASES_REQUIRED = 3


# ============================================================
# GENERATE UNIQUE INVITATION CODE
# ============================================================

def generate_invitation_code():

    """
    Generate a permanent unique invitation code.

    Example:
        MZ8K4P2Q
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

        existing = Invitation.query.filter_by(
            invitation_code=code
        ).first()

        if not existing:

            return code


# ============================================================
# GET OR CREATE USER INVITATION
# ============================================================

def get_or_create_invitation(user):

    """
    Every user gets one permanent invitation code.

    The code never changes.
    """

    invitation_record = Invitation.query.filter_by(
        inviter_id=user.id
    ).first()

    if invitation_record:

        return invitation_record

    code = generate_invitation_code()

    invitation_record = Invitation(

        inviter_id=user.id,

        invitation_code=code,

        invited_purchases=0,

        available_rewards=0
    )

    db.session.add(
        invitation_record
    )

    db.session.commit()

    return invitation_record


# ============================================================
# CHECK IF USER CAN ENTER INVITATION CODE
# ============================================================

def can_enter_invitation_code(user):

    """
    User can enter an invitation code only
    within the first 10 days after registration.

    Once an inviter has been assigned,
    the user cannot change it.
    """

    # Already has an inviter
    if user.invited_by_id is not None:

        return False

    # No registration date
    if user.created_at is None:

        return False

    expires_at = (
        user.created_at
        +
        timedelta(
            days=INVITATION_CODE_DAYS
        )
    )

    return datetime.utcnow() < expires_at


# ============================================================
# ZAWADI PAGE
# ============================================================

@invitation.route(
    '/zawadi',
    methods=['GET']
)
@login_required
def zawadi():

    """
    Main Zawadi / Invitation Campaign page.
    """

    invitation_record = get_or_create_invitation(
        current_user
    )

    can_use_code = can_enter_invitation_code(
        current_user
    )

    days_remaining = 0

    if can_use_code:

        expires_at = (
            current_user.created_at
            +
            timedelta(
                days=INVITATION_CODE_DAYS
            )
        )

        remaining_seconds = (
            expires_at
            -
            datetime.utcnow()
        ).total_seconds()

        if remaining_seconds > 0:

            days_remaining = (
                int(
                    remaining_seconds
                    /
                    86400
                )
                + 1
            )

    return render_template(
        'zawadi.html',

        invitation=invitation_record,

        can_use_code=can_use_code,

        days_remaining=days_remaining,

        purchases_required=PURCHASES_REQUIRED
    )


# ============================================================
# ACCEPT INVITATION CODE
# ============================================================

@invitation.route(
    '/use-code',
    methods=['POST']
)
@login_required
def use_invitation_code():

    """
    Allow a new user to enter another user's
    permanent invitation code.

    Important:
        User cannot invite themselves.
    """

    # --------------------------------------------------------
    # CHECK 10-DAY PERIOD
    # --------------------------------------------------------

    if not can_enter_invitation_code(
        current_user
    ):

        flash(
            "Muda wa kutumia invitation code umeisha.",
            "error"
        )

        return redirect(
            url_for(
                'invitation.zawadi'
            )
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
            "Tafadhali ingiza invitation code.",
            "error"
        )

        return redirect(
            url_for(
                'invitation.zawadi'
            )
        )

    # --------------------------------------------------------
    # FIND INVITATION
    # --------------------------------------------------------

    invitation_record = Invitation.query.filter_by(
        invitation_code=code
    ).first()

    if not invitation_record:

        flash(
            "Invitation code si sahihi.",
            "error"
        )

        return redirect(
            url_for(
                'invitation.zawadi'
            )
        )

    # --------------------------------------------------------
    # PREVENT SELF INVITATION
    # --------------------------------------------------------

    if (
        invitation_record.inviter_id
        ==
        current_user.id
    ):

        flash(
            "Huwezi kutumia invitation code yako mwenyewe.",
            "error"
        )

        return redirect(
            url_for(
                'invitation.zawadi'
            )
        )

    # --------------------------------------------------------
    # PREVENT INVITER CHANGE
    # --------------------------------------------------------

    if current_user.invited_by_id is not None:

        flash(
            "Tayari una inviter.",
            "error"
        )

        return redirect(
            url_for(
                'invitation.zawadi'
            )
        )

    # --------------------------------------------------------
    # ASSIGN INVITER
    # --------------------------------------------------------

    current_user.invited_by_id = (
        invitation_record.inviter_id
    )

    db.session.commit()

    flash(
        "Invitation code imekubaliwa! "
        "Sasa kila manunuzi 3 utakayofanya "
        "yatampa inviter wako zawadi 1.",
        "success"
    )

    return redirect(
        url_for(
            'invitation.zawadi'
        )
    )


# ============================================================
# REDEEM REWARD
# ============================================================

@invitation.route(
    '/redeem',
    methods=['POST']
)
@login_required
def redeem_reward():

    """
    Redeem ONE available reward.

    One reward = one movie OR one series.

    The reward is reduced immediately when used.
    """

    invitation_record = Invitation.query.filter_by(
        inviter_id=current_user.id
    ).first()

    if not invitation_record:

        flash(
            "Huna zawadi yoyote.",
            "error"
        )

        return redirect(
            url_for(
                'invitation.zawadi'
            )
        )

    # --------------------------------------------------------
    # CHECK REWARD
    # --------------------------------------------------------

    if invitation_record.available_rewards <= 0:

        flash(
            "Huna zawadi inayopatikana.",
            "error"
        )

        return redirect(
            url_for(
                'invitation.zawadi'
            )
        )

    # --------------------------------------------------------
    # CREATE REWARD RECORD
    # --------------------------------------------------------

    reward = InvitationReward(

        user_id=current_user.id,

        invitation_id=invitation_record.id,

        reward_type='free_content',

        status='Available',

        created_at=datetime.utcnow()
    )

    db.session.add(
        reward
    )

    # --------------------------------------------------------
    # REDUCE REWARD
    # --------------------------------------------------------

    invitation_record.available_rewards -= 1

    db.session.commit()

    flash(
        "Zawadi yako iko tayari kutumika!",
        "success"
    )

    return redirect(
        url_for(
            'home'
        )
    )


# ============================================================
# REWARD COUNT
# ============================================================

def get_available_rewards(user_id):

    """
    Return number of available rewards.
    """

    invitation_record = Invitation.query.filter_by(
        inviter_id=user_id
    ).first()

    if not invitation_record:

        return 0

    return invitation_record.available_rewards


# ============================================================
# ADD PURCHASE TO INVITATION COUNTER
# ============================================================

def process_invited_purchase(user):

    """
    Called ONLY after a successful paid purchase.

    Example:

        Purchase 1 -> counter = 1
        Purchase 2 -> counter = 2
        Purchase 3 -> counter = 0 + reward = 1

    Then:

        Purchase 4 -> counter = 1
        Purchase 5 -> counter = 2
        Purchase 6 -> counter = 0 + reward = 1
    """

    # --------------------------------------------------------
    # USER HAS NO INVITER
    # --------------------------------------------------------

    if user.invited_by_id is None:

        return

    # --------------------------------------------------------
    # FIND INVITER
    # --------------------------------------------------------

    inviter_record = Invitation.query.filter_by(
        inviter_id=user.invited_by_id
    ).first()

    if not inviter_record:

        return

    # --------------------------------------------------------
    # INCREMENT PURCHASE COUNT
    # --------------------------------------------------------

    inviter_record.invited_purchases += 1

    # --------------------------------------------------------
    # CHECK WHETHER 3 PURCHASES ARE COMPLETED
    # --------------------------------------------------------

    if (
        inviter_record.invited_purchases
        >=
        PURCHASES_REQUIRED
    ):

        completed_groups = (
            inviter_record.invited_purchases
            //
            PURCHASES_REQUIRED
        )

        # Keep only purchases that belong
        # to the incomplete group.
        inviter_record.invited_purchases = (
            inviter_record.invited_purchases
            %
            PURCHASES_REQUIRED
        )

        # Add one reward for each completed group.
        inviter_record.available_rewards += (
            completed_groups
        )

        print(
            "🎁 Invitation reward added:",
            completed_groups
        )

        print(
            "🎁 Inviter:",
            user.invited_by_id
        )

        print(
            "🎁 Available rewards:",
            inviter_record.available_rewards
        )

    db.session.commit()
