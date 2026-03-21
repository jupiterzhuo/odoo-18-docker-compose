# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

from odoo import api, fields, models


class StudioSessionBookingDetail(models.TransientModel):
    _name = "studio.session_booking_detail"
    _description = "Session Booking Detail (Who is Booking / Who is Waitlist)"

    session_id = fields.Many2one(
        "studio.class_session",
        string="Session",
        required=True,
        readonly=True,
        ondelete="cascade",
    )
    booked_ids = fields.Many2many(
        "studio.booking",
        "studio_session_detail_booked_rel",
        "wizard_id",
        "booking_id",
        string="Who is Booking",
        readonly=True,
    )
    waitlist_ids = fields.Many2many(
        "studio.booking",
        "studio_session_detail_waitlist_rel",
        "wizard_id",
        "booking_id",
        string="Who is Waitlist",
        readonly=True,
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        session_id = res.get("session_id") or self.env.context.get("default_session_id")
        if not session_id and self.env.context.get("active_model") == "studio.class_session":
            session_id = self.env.context.get("active_id")
        if session_id:
            session = self.env["studio.class_session"].browse(session_id)
            # Exclude cancelled / late_cancel
            active = session.booking_ids.filtered(
                lambda b: b.booking_status not in ("cancelled", "late_cancel")
            )
            booked = active.filtered(
                lambda b: b.booking_status in ("booked", "promoted", "completed")
            )
            waitlist = active.filtered(lambda b: b.booking_status == "waitlisted")
            res["booked_ids"] = [(6, 0, booked.ids)]
            res["waitlist_ids"] = [(6, 0, waitlist.ids)]
        return res
