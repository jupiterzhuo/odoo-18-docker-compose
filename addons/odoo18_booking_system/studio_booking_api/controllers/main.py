# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class StudioBookingController(http.Controller):
    """Skeleton HTTP endpoints for future mobile app API.
    All methods are placeholders; implement auth (e.g. API key or JWT per tenant)
    and call the service-layer methods on models.
    """

    @http.route("/studio/api/v1/sessions", type="json", auth="user")
    def sessions_list(self, tenant_id=None, branch_id=None, from_dt=None, to_dt=None):
        """List class sessions (filter by tenant, branch, date range)."""
        # TODO: map to studio.class_session search + read; respect record rules
        return {"sessions": [], "count": 0}

    @http.route("/studio/api/v1/sessions/<int:session_id>", type="json", auth="user")
    def session_detail(self, session_id):
        """Get one session with capacity and counts."""
        # TODO: session.read([session_id]); return capacity, booked_count, waitlist_count
        return {}

    @http.route("/studio/api/v1/sessions/<int:session_id>/book", type="json", auth="user")
    def session_book(self, session_id, member_profile_id):
        """Book a seat. Calls session.action_book(member_profile_id)."""
        # TODO: session = request.env["studio.class_session"].browse(session_id)
        #       session.action_book(member_profile_id)
        #       return {"success": True, "booking_id": booking.id}
        return {"success": False, "error": "Not implemented"}

    @http.route("/studio/api/v1/sessions/<int:session_id>/waitlist", type="json", auth="user")
    def session_join_waitlist(self, session_id, member_profile_id):
        """Join waitlist. Calls session.action_join_waitlist(member_profile_id)."""
        # TODO: session.action_join_waitlist(member_profile_id)
        return {"success": False, "error": "Not implemented"}

    @http.route("/studio/api/v1/bookings/<int:booking_id>/cancel", type="json", auth="user")
    def booking_cancel(self, booking_id):
        """Cancel booking. Calls booking.action_cancel()."""
        # TODO: booking.action_cancel()
        return {"success": False, "error": "Not implemented"}

    @http.route("/studio/api/v1/bookings/<int:booking_id>/checkin", type="json", auth="user")
    def booking_checkin(self, booking_id, source="member_app"):
        """Check-in. Calls booking.action_check_in(source=source)."""
        # TODO: booking.action_check_in(source=source)
        return {"success": False, "error": "Not implemented"}

    @http.route("/studio/api/v1/members/eligible", type="json", auth="user")
    def members_eligible_for_session(self, session_id, at_dt=None):
        """Return member_profile ids eligible to book session at given datetime."""
        # TODO: session._get_eligible_members_for_session(session, at_dt)
        return {"member_profile_ids": []}
