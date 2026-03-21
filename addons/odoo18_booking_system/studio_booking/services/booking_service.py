# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

"""
Booking service layer: validation, orchestration, and business rules.
Keeps controllers thin; all booking/cancel logic lives here.
"""

import logging
from datetime import timedelta

from odoo import _, fields
from odoo.exceptions import AccessError, UserError, ValidationError

from ..utils import timezone as tz_utils

_logger = logging.getLogger(__name__)


class BookingService:
    """Service for class booking and cancellation with validation."""

    def __init__(self, env):
        self.env = env

    def is_session_bookable_or_member_booked(self, session, member_profile_id, at_dt=None):
        """
        Return True if session should be shown in the list for a member.
        Show when: member has active booking OR session is still bookable (not expired, not past checkin_close).
        Uses studio timezone (GMT+7) for date comparison.
        """
        from ..utils import timezone as tz_utils

        session.ensure_one()
        now = at_dt or tz_utils.utc_now()
        Booking = self.env["studio.booking"]
        has_booking = bool(
            Booking.sudo().search(
                [
                    ("session_id", "=", session.id),
                    ("member_profile_id", "=", member_profile_id),
                    ("booking_status", "in", ("booked", "promoted", "waitlisted")),
                ],
                limit=1,
            )
        )
        if has_booking:
            return True
        if session.state != "scheduled":
            return False
        if session.session_end and now >= session.session_end:
            return False
        if session.session_start:
            session_date_local = tz_utils.utc_to_studio_local(session.session_start).date()
            today_local = tz_utils.studio_today()
            if session_date_local > today_local:
                return True  # Future date, show session
        minutes_before = getattr(session, "checkin_close_minutes_before", 0) or 0
        if minutes_before > 0 and session.session_start:
            cutoff = session.session_start - timedelta(minutes=minutes_before)
            if now >= cutoff:
                return False
        return True

    def validate_checkin_close(self, session, at_dt=None):
        """
        Validate booking against checkin_close_minutes_before rule.
        - If checkin_close_minutes_before = 0: allow until session_end (reject only if session ended).
        - If checkin_close_minutes_before > 0: reject when now >= session_start - minutes_before.
        - Sessions on a future date (studio timezone): always allow.
        - Sessions on a future date + 24h: allow (within same day far in future).

        Uses studio timezone (GMT+7) for date comparison; UTC for time comparison.
        Raises ValidationError with clear message if booking is not allowed.
        """
        from ..utils import timezone as tz_utils

        session.ensure_one()
        now = at_dt or tz_utils.utc_now()
        if session.state == "cancelled":
            raise ValidationError(_("Cannot book a cancelled session."))
        if session.state == "completed":
            raise ValidationError(_("Cannot book a completed session."))
        if session.session_end and now >= session.session_end:
            raise ValidationError(
                _("Booking is closed. The class has already ended.")
            )
        if not session.session_start:
            return
        # Compare date in studio timezone (GMT+7): session on a future date = always allow
        session_date_local = tz_utils.utc_to_studio_local(session.session_start).date()
        today_local = tz_utils.studio_today()
        if session_date_local > today_local:
            return  # Session is on a future date, allow booking
        minutes_before = getattr(
            session, "checkin_close_minutes_before", 0
        ) or 0
        if minutes_before > 0:
            cutoff = session.session_start - timedelta(minutes=minutes_before)
            if now >= cutoff:
                raise ValidationError(
                    _(
                        "Booking is closed. Bookings must be made at least %(minutes)s minutes before the class starts."
                    )
                    % {"minutes": minutes_before}
                )

    def book(
        self,
        session_id,
        member_profile_id,
        source="api",
    ):
        """
        Create a booking for member on session.
        Returns (booking, status) where status is 'booked' or 'waitlisted'.
        """
        Session = self.env["studio.class_session"].sudo()
        Booking = self.env["studio.booking"].sudo()
        Member = self.env["studio.member_profile"].sudo()

        session = Session.browse(session_id)
        member = Member.browse(member_profile_id)
        if not session.exists():
            raise ValidationError(_("Session not found."))
        if not member.exists():
            raise ValidationError(_("Member not found."))
        if member.tenant_id != session.tenant_id:
            raise ValidationError(
                _("Member and session must belong to the same tenant.")
            )

        self.env.user.ensure_studio_tenant_allowed(session.tenant_id)
        self.validate_checkin_close(session)

        Booking._validate_eligibility_for_save(
            member_profile_id, session_id, at_dt=session.session_start
        )
        if Booking._member_has_active_booking_for_same_session(
            member_profile_id, session_id
        ):
            raise ValidationError(
                _(
                    "This member already has a booking or is on the waitlist for this session."
                )
            )
        if Booking._member_has_booking_overlap(member_profile_id, session_id):
            raise ValidationError(_("Member has another booking at the same time."))
        if Booking._member_has_waitlist_overlap(member_profile_id, session_id):
            raise ValidationError(
                _("Member is on a waitlist for another class at the same time.")
            )

        resolved_status = Booking._resolve_booking_status_for_save(session)
        audit = {
            "booked_by_user_id": self.env.user.id,
            "booked_at": fields.Datetime.now(),
            "booking_source": source,
        }

        vals = {
            "session_id": session.id,
            "member_profile_id": member_profile_id,
            "booking_status": resolved_status,
            "attendance_status": "pending",
            "booked_by_user_id": audit["booked_by_user_id"],
            "booked_at": audit["booked_at"],
            "booking_source": audit["booking_source"],
        }
        if resolved_status == "waitlisted":
            last = Booking.search(
                [
                    ("session_id", "=", session.id),
                    ("booking_status", "=", "waitlisted"),
                ],
                order="waitlist_sequence desc",
                limit=1,
            )
            vals["waitlist_sequence"] = (last.waitlist_sequence + 1) if last else 1
        else:
            vals["waitlist_sequence"] = 0

        booking = Booking.with_context(booking_source=source).create(vals)
        _logger.info(
            "Studio booking: created %s for member %s on session %s (status=%s)",
            booking.id,
            member_profile_id,
            session_id,
            resolved_status,
        )
        return booking, resolved_status

    def cancel(self, booking_id=None, session_id=None, member_profile_id=None, source="api"):
        """
        Cancel a booking. Provide either booking_id or (session_id + member_profile_id).
        Triggers waitlist promotion if a booked member cancels and capacity becomes available.
        Returns (booking, promoted_booking or None).
        """
        Booking = self.env["studio.booking"].sudo()

        if booking_id:
            booking = Booking.browse(booking_id)
            if not booking.exists():
                raise ValidationError(_("Booking not found."))
        elif session_id and member_profile_id:
            booking = Booking.search(
                [
                    ("session_id", "=", session_id),
                    ("member_profile_id", "=", member_profile_id),
                    ("booking_status", "in", ("booked", "promoted", "waitlisted")),
                ],
                limit=1,
            )
            if not booking:
                raise ValidationError(
                    _("No active booking found for this member and session.")
                )
        else:
            raise ValidationError(
                _("Provide either booking_id or (session_id and member_profile_id).")
            )

        if booking.booking_status in ("cancelled", "late_cancel", "completed"):
            raise ValidationError(
                _("Booking is already in final state: %s") % booking.booking_status
            )

        self.env.user.ensure_studio_tenant_allowed(booking.session_id.tenant_id)
        # Portal users (members) can only cancel their own bookings
        if self.env.user.has_group("base.group_portal") and not self.env.user.has_group(
            "studio_booking.group_studio_booking_user"
        ):
            if booking.member_profile_id.user_id.id != self.env.user.id:
                raise AccessError(_("You can only cancel your own bookings."))
        was_booked = booking.booking_status in ("booked", "promoted")

        cancel_vals = {
            "booking_status": "cancelled",
            "waitlist_sequence": 0,
            "canceled_by_user_id": self.env.user.id,
            "canceled_at": fields.Datetime.now(),
            "cancel_source": source,
        }
        booking.with_context(cancel_source=source, promotion_source=source).write(
            cancel_vals
        )
        booking.session_id._resequence_waitlist()

        promoted = self.env["studio.booking"].browse()
        if was_booked:
            promoted = self.env["studio.booking"].search(
                [
                    ("session_id", "=", booking.session_id.id),
                    ("booking_status", "=", "promoted"),
                    ("promoted_at", "!=", False),
                ],
                order="promoted_at desc",
                limit=1,
            )

        _logger.info(
            "Studio booking: cancelled %s (was %s), promoted=%s",
            booking.id,
            "booked" if was_booked else "waitlisted",
            promoted.id if promoted else None,
        )
        return booking, promoted if promoted else None
