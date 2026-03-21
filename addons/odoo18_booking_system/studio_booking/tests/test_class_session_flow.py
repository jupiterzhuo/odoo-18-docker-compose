from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import SavepointCase


class TestStudioClassSessionFlow(SavepointCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        manager_group = cls.env.ref("studio_booking.group_studio_booking_manager")
        cls.env.user.write({"groups_id": [(4, manager_group.id)]})

        cls.tenant = cls.env["studio.tenant"].create({"name": "Tenant A"})
        cls.branch = cls.env["studio.branch"].create(
            {"name": "Main Branch", "tenant_id": cls.tenant.id}
        )
        cls.other_branch = cls.env["studio.branch"].create(
            {"name": "Other Branch", "tenant_id": cls.tenant.id}
        )
        cls.room = cls.env["studio.room"].create(
            {"name": "Room A", "branch_id": cls.branch.id, "capacity": 10}
        )
        cls.other_room = cls.env["studio.room"].create(
            {"name": "Room B", "branch_id": cls.other_branch.id, "capacity": 10}
        )
        cls.instructor = cls.env["studio.instructor"].create(
            {"tenant_id": cls.tenant.id, "first_name": "John", "last_name": "Teacher"}
        )
        cls.other_instructor = cls.env["studio.instructor"].create(
            {"tenant_id": cls.tenant.id, "first_name": "Jane", "last_name": "Coach"}
        )
        cls.class_template = cls.env["studio.class_template"].create(
            {"tenant_id": cls.tenant.id, "name": "Yoga Flow", "duration_minutes": 60}
        )

    def _session_template_vals(self, **overrides):
        vals = {
            "tenant_id": self.tenant.id,
            "branch_id": self.branch.id,
            "room_id": self.room.id,
            "instructor_id": self.instructor.id,
            "class_template_id": self.class_template.id,
            "capacity": 12,
            "day_of_week": "monday",
            "start_time": "09:00",
            "end_time": "10:00",
            "is_active": True,
            "is_recurring": True,
            "checkin_close_minutes_before": 15,
        }
        vals.update(overrides)
        return vals

    def _make_manual_session(self, **overrides):
        start = overrides.pop("session_start", fields.Datetime.now() + timedelta(days=1))
        end = overrides.pop("session_end", start + timedelta(hours=1))
        vals = {
            "tenant_id": self.tenant.id,
            "branch_id": self.branch.id,
            "room_id": self.room.id,
            "instructor_id": self.instructor.id,
            "template_id": self.class_template.id,
            "capacity": 12,
            "session_start": start,
            "session_end": end,
        }
        vals.update(overrides)
        return self.env["studio.class_session"].create(vals)

    def test_session_template_can_be_created_without_real_date(self):
        # ✅ Template uses weekday/time only
        template = self.env["studio.session_template"].create(
            self._session_template_vals(name=False)
        )
        self.assertTrue(template)
        self.assertEqual(template.day_of_week, "monday")
        self.assertEqual(template.start_time, "09:00")
        self.assertEqual(template.end_time, "10:00")

    def test_session_template_stores_weekday_and_time_only(self):
        template = self.env["studio.session_template"].create(
            self._session_template_vals(
                day_of_week="wednesday",
                start_time="14:30",
                end_time="15:30",
            )
        )
        self.assertEqual(template.day_of_week, "wednesday")
        self.assertEqual(template.start_time, "14:30")
        self.assertEqual(template.end_time, "15:30")

    def test_class_session_can_exist_without_manual_name(self):
        session = self._make_manual_session(name=False)
        self.assertTrue(session)
        self.assertTrue(session.name)

    def test_backend_autofills_internal_display_name(self):
        session = self._make_manual_session(name=False)
        self.assertIn("Yoga Flow", session.name)

    def test_cron_generates_class_session_from_session_template(self):
        template = self.env["studio.session_template"].create(self._session_template_vals())
        self.env["studio.session_template"]._cron_generate_upcoming_sessions(horizon_days=14)
        generated = self.env["studio.class_session"].search(
            [("session_template_id", "=", template.id)],
            limit=1,
        )
        self.assertTrue(generated)
        self.assertTrue(generated.generated_by_cron)

    def test_cron_does_not_generate_duplicates(self):
        template = self.env["studio.session_template"].create(self._session_template_vals())
        SessionTemplate = self.env["studio.session_template"]
        SessionTemplate._cron_generate_upcoming_sessions(horizon_days=14)
        SessionTemplate._cron_generate_upcoming_sessions(horizon_days=14)
        sessions = self.env["studio.class_session"].search([("session_template_id", "=", template.id)])
        unique_starts = {session.session_start for session in sessions}
        self.assertEqual(len(sessions), len(unique_starts))

    def test_generated_session_inherits_template_fields(self):
        template = self.env["studio.session_template"].create(
            self._session_template_vals(
                branch_id=self.other_branch.id,
                room_id=self.other_room.id,
                instructor_id=self.other_instructor.id,
                capacity=25,
                checkin_close_minutes_before=30,
            )
        )
        template._generate_upcoming_sessions(horizon_days=14)
        generated = self.env["studio.class_session"].search(
            [("session_template_id", "=", template.id)],
            limit=1,
        )
        self.assertEqual(generated.tenant_id, template.tenant_id)
        self.assertEqual(generated.branch_id, template.branch_id)
        self.assertEqual(generated.room_id, template.room_id)
        self.assertEqual(generated.instructor_id, template.instructor_id)
        self.assertEqual(generated.template_id, template.class_template_id)
        self.assertEqual(generated.capacity, template.capacity)

    def test_room_overlap_is_blocked(self):
        start = fields.Datetime.now() + timedelta(days=2)
        self._make_manual_session(session_start=start, session_end=start + timedelta(hours=1))
        with self.assertRaises(ValidationError):
            self._make_manual_session(
                session_start=start + timedelta(minutes=30),
                session_end=start + timedelta(hours=1, minutes=30),
            )

    def test_instructor_overlap_is_blocked_even_across_branches(self):
        start = fields.Datetime.now() + timedelta(days=3)
        self._make_manual_session(
            session_start=start,
            session_end=start + timedelta(hours=1),
            branch_id=self.branch.id,
            room_id=self.room.id,
            instructor_id=self.instructor.id,
        )
        with self.assertRaises(ValidationError):
            self._make_manual_session(
                session_start=start + timedelta(minutes=15),
                session_end=start + timedelta(hours=1, minutes=15),
                branch_id=self.other_branch.id,
                room_id=self.other_room.id,
                instructor_id=self.instructor.id,
            )

    def test_cancelling_one_session_cancels_related_bookings(self):
        session = self._make_manual_session()
        member_1 = self.env["studio.member_profile"].create(
            {
                "tenant_id": self.tenant.id,
                "first_name": "M1",
                "last_name": "User",
                "email": "member1@example.com",
            }
        )
        member_2 = self.env["studio.member_profile"].create(
            {
                "tenant_id": self.tenant.id,
                "first_name": "M2",
                "last_name": "User",
                "email": "member2@example.com",
            }
        )
        booking = self.env["studio.booking"].create(
            {
                "session_id": session.id,
                "member_profile_id": member_1.id,
                "booking_status": "booked",
                "attendance_status": "attended",
                "checkin_source": "staff",
                "checked_in_at": fields.Datetime.now(),
                "checked_in_by_user_id": self.env.user.id,
            }
        )
        waitlist = self.env["studio.booking"].create(
            {
                "session_id": session.id,
                "member_profile_id": member_2.id,
                "booking_status": "waitlisted",
                "attendance_status": "pending",
                "waitlist_sequence": 1,
            }
        )
        session.action_cancel_session()
        self.assertEqual(session.state, "cancelled")
        self.assertEqual(booking.booking_status, "cancelled")
        self.assertEqual(waitlist.booking_status, "cancelled")

    def test_cancelling_session_does_not_deactivate_session_template(self):
        template = self.env["studio.session_template"].create(self._session_template_vals())
        template._generate_upcoming_sessions(horizon_days=14)
        session = self.env["studio.class_session"].search(
            [("session_template_id", "=", template.id)],
            limit=1,
        )
        session.action_cancel_session()
        self.assertTrue(template.is_active)

    def test_inactive_session_template_does_not_generate_future_sessions(self):
        template = self.env["studio.session_template"].create(
            self._session_template_vals(is_active=False)
        )
        self.env["studio.session_template"]._cron_generate_upcoming_sessions(horizon_days=14)
        generated_count = self.env["studio.class_session"].search_count(
            [("session_template_id", "=", template.id)]
        )
        self.assertEqual(generated_count, 0)

    def test_template_instructor_overlap_is_blocked_on_same_day_time(self):
        self.env["studio.session_template"].create(
            self._session_template_vals(
                day_of_week="tuesday",
                start_time="07:15",
                end_time="08:15",
                instructor_id=self.instructor.id,
                branch_id=self.branch.id,
                room_id=self.room.id,
            )
        )
        with self.assertRaises(ValidationError):
            self.env["studio.session_template"].create(
                self._session_template_vals(
                    day_of_week="tuesday",
                    start_time="07:30",
                    end_time="08:30",
                    instructor_id=self.instructor.id,  # same instructor across branch must be blocked
                    branch_id=self.other_branch.id,
                    room_id=self.other_room.id,
                )
            )

    def test_template_room_overlap_is_blocked_on_same_day_time(self):
        self.env["studio.session_template"].create(
            self._session_template_vals(
                day_of_week="friday",
                start_time="10:00",
                end_time="11:00",
                room_id=self.room.id,
                instructor_id=self.instructor.id,
            )
        )
        with self.assertRaises(ValidationError):
            self.env["studio.session_template"].create(
                self._session_template_vals(
                    day_of_week="friday",
                    start_time="10:30",
                    end_time="11:30",
                    room_id=self.room.id,  # same room must be blocked
                    instructor_id=self.other_instructor.id,
                )
            )
