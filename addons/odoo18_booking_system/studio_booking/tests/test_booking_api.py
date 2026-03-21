# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

"""Tests for class booking and cancellation API, service, and validation."""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import SavepointCase

from ..services.booking_service import BookingService


class TestBookingApi(SavepointCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        manager_group = cls.env.ref("studio_booking.group_studio_booking_manager")
        cls.env.user.write({"groups_id": [(4, manager_group.id)]})

        cls.tenant = cls.env["studio.tenant"].create({"name": "Tenant A"})
        cls.branch = cls.env["studio.branch"].create(
            {"name": "Main Branch", "tenant_id": cls.tenant.id}
        )
        cls.room = cls.env["studio.room"].create(
            {"name": "Room A", "branch_id": cls.branch.id, "capacity": 3}
        )
        cls.instructor = cls.env["studio.instructor"].create(
            {"tenant_id": cls.tenant.id, "first_name": "John", "last_name": "Teacher"}
        )
        cls.class_template = cls.env["studio.class_template"].create(
            {"tenant_id": cls.tenant.id, "name": "Yoga Flow", "duration_minutes": 60}
        )
        cls.plan = cls.env["studio.membership_plan"].create(
            {"tenant_id": cls.tenant.id, "name": "Basic Plan"}
        )

        cls.member1 = cls.env["studio.member_profile"].create(
            {
                "tenant_id": cls.tenant.id,
                "first_name": "M1",
                "last_name": "User",
                "email": "member1@test.com",
            }
        )
        cls.member2 = cls.env["studio.member_profile"].create(
            {
                "tenant_id": cls.tenant.id,
                "first_name": "M2",
                "last_name": "User",
                "email": "member2@test.com",
            }
        )
        cls.member3 = cls.env["studio.member_profile"].create(
            {
                "tenant_id": cls.tenant.id,
                "first_name": "M3",
                "last_name": "User",
                "email": "member3@test.com",
            }
        )
        today = fields.Date.context_today(cls.env["studio.membership_subscription"])
        cls.env["studio.membership_subscription"].create(
            {
                "member_profile_id": cls.member1.id,
                "plan_id": cls.plan.id,
                "date_start": today,
                "date_end": today + timedelta(days=365),
                "state": "active",
            }
        )
        cls.env["studio.membership_subscription"].create(
            {
                "member_profile_id": cls.member2.id,
                "plan_id": cls.plan.id,
                "date_start": today,
                "date_end": today + timedelta(days=365),
                "state": "active",
            }
        )
        cls.env["studio.membership_subscription"].create(
            {
                "member_profile_id": cls.member3.id,
                "plan_id": cls.plan.id,
                "date_start": today,
                "date_end": today + timedelta(days=365),
                "state": "active",
            }
        )
        cls.env.user.write({"studio_tenant_ids": [(6, 0, [cls.tenant.id])]})

    def _make_session(self, minutes_before=15, checkin_close_at=None, **overrides):
        start = overrides.pop(
            "session_start", fields.Datetime.now() + timedelta(days=1, hours=2)
        )
        end = overrides.pop("session_end", start + timedelta(hours=1))
        vals = {
            "tenant_id": self.tenant.id,
            "branch_id": self.branch.id,
            "room_id": self.room.id,
            "instructor_id": self.instructor.id,
            "template_id": self.class_template.id,
            "capacity": 3,
            "session_start": start,
            "session_end": end,
        }
        if checkin_close_at is not None:
            vals["checkin_close_at"] = checkin_close_at
        elif minutes_before > 0:
            vals["checkin_close_at"] = start - timedelta(minutes=minutes_before)
        vals.update(overrides)
        return self.env["studio.class_session"].create(vals)

    def test_successful_booking(self):
        session = self._make_session()
        service = BookingService(self.env)
        booking, status = service.book(
            session_id=session.id,
            member_profile_id=self.member1.id,
            source="api",
        )
        self.assertEqual(status, "booked")
        self.assertEqual(booking.booking_status, "booked")
        self.assertEqual(booking.member_profile_id, self.member1)
        self.assertTrue(booking.booked_at)
        self.assertEqual(booking.booked_by_user_id, self.env.user)

    def test_booking_when_full_goes_to_waitlist(self):
        session = self._make_session(capacity=2)
        service = BookingService(self.env)
        b1, s1 = service.book(session.id, self.member1.id, source="api")
        b2, s2 = service.book(session.id, self.member2.id, source="api")
        b3, s3 = service.book(session.id, self.member3.id, source="api")
        self.assertEqual(s1, "booked")
        self.assertEqual(s2, "booked")
        self.assertEqual(s3, "waitlisted")
        self.assertEqual(b3.booking_status, "waitlisted")
        self.assertEqual(b3.waitlist_sequence, 1)

    def test_duplicate_booking_prevention(self):
        session = self._make_session()
        service = BookingService(self.env)
        service.book(session.id, self.member1.id, source="api")
        with self.assertRaises(ValidationError) as cm:
            service.book(session.id, self.member1.id, source="api")
        self.assertIn("already has a booking", str(cm.exception))

    def test_booking_allowed_when_checkin_close_zero_and_class_ongoing(self):
        start = fields.Datetime.now() - timedelta(minutes=30)
        end = start + timedelta(hours=1)
        session = self._make_session(
            session_start=start,
            session_end=end,
            checkin_close_at=False,
        )
        session.session_template_id = False
        session.flush()
        self.assertEqual(session.checkin_close_minutes_before, 0)
        service = BookingService(self.env)
        booking, status = service.book(session.id, self.member1.id, source="api")
        self.assertEqual(status, "booked")

    def test_booking_rejected_when_class_ended(self):
        start = fields.Datetime.now() - timedelta(hours=2)
        end = start + timedelta(hours=1)
        session = self._make_session(
            session_start=start,
            session_end=end,
            checkin_close_at=False,
        )
        session.session_template_id = False
        session.flush()
        service = BookingService(self.env)
        with self.assertRaises(ValidationError) as cm:
            service.book(session.id, self.member1.id, source="api")
        self.assertIn("already ended", str(cm.exception))

    def test_booking_rejected_when_checkin_close_passed(self):
        start = fields.Datetime.now() + timedelta(minutes=10)
        end = start + timedelta(hours=1)
        session = self._make_session(
            session_start=start,
            session_end=end,
            checkin_close_at=start - timedelta(minutes=15),
        )
        service = BookingService(self.env)
        with self.assertRaises(ValidationError) as cm:
            service.book(session.id, self.member1.id, source="api")
        self.assertIn("at least", str(cm.exception))

    def test_successful_cancel(self):
        session = self._make_session()
        service = BookingService(self.env)
        booking, _ = service.book(session.id, self.member1.id, source="api")
        cancelled, promoted = service.cancel(
            session_id=session.id,
            member_profile_id=self.member1.id,
            source="api",
        )
        self.assertEqual(cancelled.booking_status, "cancelled")
        self.assertTrue(cancelled.canceled_at)
        self.assertEqual(cancelled.canceled_by_user_id, self.env.user)
        self.assertIsNone(promoted)

    def test_auto_promotion_from_waitlist_after_cancel(self):
        session = self._make_session(capacity=2)
        service = BookingService(self.env)
        b1, _ = service.book(session.id, self.member1.id, source="api")
        b2, _ = service.book(session.id, self.member2.id, source="api")
        b3, _ = service.book(session.id, self.member3.id, source="api")
        self.assertEqual(b3.booking_status, "waitlisted")
        cancelled, promoted = service.cancel(
            session_id=session.id,
            member_profile_id=self.member1.id,
            source="api",
        )
        self.assertEqual(cancelled.booking_status, "cancelled")
        self.assertIsNotNone(promoted)
        self.assertEqual(promoted.member_profile_id, self.member3)
        self.assertEqual(promoted.booking_status, "promoted")
        self.assertTrue(promoted.promoted_at)

    def test_promotion_skips_ineligible_waitlist_member(self):
        session = self._make_session(capacity=2)
        service = BookingService(self.env)
        b1, _ = service.book(session.id, self.member1.id, source="api")
        b2, _ = service.book(session.id, self.member2.id, source="api")
        b3, _ = service.book(session.id, self.member3.id, source="api")
        self.member3.active_subscription_id.with_context(
            allow_set_expired=True
        ).write({"state": "expired"})
        cancelled, promoted = service.cancel(
            session_id=session.id,
            member_profile_id=self.member1.id,
            source="api",
        )
        self.assertIsNone(promoted)
        self.assertEqual(b3.booking_status, "waitlisted")
