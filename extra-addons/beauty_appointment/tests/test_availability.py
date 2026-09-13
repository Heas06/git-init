from datetime import date, datetime, time, timedelta

import psycopg2
import pytz

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger

# A blocked double-booking can surface as either guard, depending on exactly
# when the ORM flushes the new record's computed `stop`/`stop_with_buffer`:
# our own `_check_no_overlap` (a clean ValidationError) or PostgreSQL's
# `_no_overlap` EXCLUDE constraint firing first (a raw psycopg2 error). Both
# are real safety nets; the request layer maps the second to the same
# friendly message shown to end users, so a test only needs to know booking
# was refused either way.
OVERLAP_BLOCKED = (ValidationError, psycopg2.Error)

TZ = pytz.timezone("America/Bogota")  # UTC-5, no DST -> predictable slot math


@tagged("post_install", "-at_install")
class TestSalonAvailability(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Opening hours: Monday-Friday, 08:00-20:00, in Bogota time.
        cls.calendar = cls.env["resource.calendar"].create(
            {
                "name": "Salon 08-20 Mon-Fri",
                "tz": "America/Bogota",
                "attendance_ids": [
                    (0, 0, {
                        "name": f"Day {i}",
                        "dayofweek": str(i),
                        "day_period": "full_day",
                        "hour_from": 8.0,
                        "hour_to": 20.0,
                    })
                    for i in range(5)
                ],
            }
        )
        cls.employee = cls.env["hr.employee"].create(
            {
                "name": "Test Stylist A",
                "is_salon_staff": True,
                "resource_calendar_id": cls.calendar.id,
            }
        )
        cls.employee_b = cls.env["hr.employee"].create(
            {
                "name": "Test Stylist B",
                "is_salon_staff": True,
                "resource_calendar_id": cls.calendar.id,
            }
        )
        cls.service = cls.env["product.template"].create(
            {
                "name": "Test Cut 1h",
                "type": "service",
                "salon_service": True,
                "salon_duration": 1.0,
                "salon_buffer": 0.25,
                "list_price": 50.0,
            }
        )
        cls.atype = cls.env["salon.appointment.type"].create(
            {
                "name": "Test Booking Page",
                "tz": "America/Bogota",
                "min_hours_before": 1.0,
                "max_days_ahead": 90,
                "slot_granularity": 0.5,
                "service_ids": [(6, 0, cls.service.ids)],
                "employee_ids": [(6, 0, (cls.employee | cls.employee_b).ids)],
            }
        )
        cls.partner = cls.env["res.partner"].create({"name": "Test Client"})

        # A weekday well inside the booking window and clear of the notice period.
        target = date.today() + timedelta(days=10)
        while target.weekday() != 0:  # 0 = Monday
            target += timedelta(days=1)
        cls.monday = target
        cls.saturday = target + timedelta(days=5)

    @classmethod
    def _utc(cls, day, hour, minute=0):
        """Bogota wall-clock time -> naive UTC datetime (how Odoo stores it)."""
        local = TZ.localize(datetime.combine(day, time(hour, minute)))
        return local.astimezone(pytz.utc).replace(tzinfo=None)

    def _book(self, employee, day, hour, minute=0, state="confirmed"):
        return self.env["salon.appointment"].create(
            {
                "partner_id": self.partner.id,
                "appointment_type_id": self.atype.id,
                "service_id": self.service.id,
                "employee_id": employee.id,
                "start": self._utc(day, hour, minute),
                "state": state,
            }
        )

    # ------------------------------------------------------------------
    def test_slots_stay_within_working_hours(self):
        slots = self.atype.get_available_slots(
            self.service, day_from=self.monday, day_to=self.monday
        )
        self.assertTrue(slots)
        local_times = [s["start_local"] for s in slots]

        self.assertTrue(all(t.date() == self.monday for t in local_times))
        self.assertEqual(min(local_times).strftime("%H:%M"), "08:00")
        # last start must leave room for 1h service + 0:15 buffer before 20:00
        self.assertEqual(max(local_times).strftime("%H:%M"), "18:30")
        for s in slots:
            end = s["start_local"] + timedelta(hours=1.25)
            self.assertLessEqual(end.timetz().replace(tzinfo=None), time(20, 0))

        # both employees are offered, with the same number of slots
        by_emp = {}
        for s in slots:
            by_emp.setdefault(s["employee_id"], 0)
            by_emp[s["employee_id"]] += 1
        self.assertEqual(set(by_emp), set((self.employee | self.employee_b).ids))
        self.assertEqual(len(set(by_emp.values())), 1)

    def test_existing_appointment_removes_overlapping_slots(self):
        self._book(self.employee, self.monday, 10, 0)  # 10:00-11:00 (+0:15 buffer)

        slots = self.atype.get_available_slots(
            self.service,
            employee=self.employee,
            day_from=self.monday,
            day_to=self.monday,
        )
        times = {s["start_local"].strftime("%H:%M") for s in slots}

        for blocked in ("09:00", "09:30", "10:00", "10:30", "11:00"):
            self.assertNotIn(blocked, times, f"{blocked} should be blocked")
        for free in ("08:00", "08:30", "11:30", "12:00"):
            self.assertIn(free, times, f"{free} should still be free")

    def test_buffer_is_respected_between_bookings(self):
        self._book(self.employee, self.monday, 12, 0)  # ends 13:00, buffer to 13:15
        slots = self.atype.get_available_slots(
            self.service,
            employee=self.employee,
            day_from=self.monday,
            day_to=self.monday,
        )
        times = {s["start_local"].strftime("%H:%M") for s in slots}
        self.assertNotIn("13:00", times)  # inside the cleanup buffer
        self.assertIn("13:30", times)     # first slot clear of the buffer

    def test_minimum_notice_is_enforced(self):
        self.atype.min_hours_before = 72.0
        slots = self.atype.get_available_slots(self.service)
        self.assertTrue(slots)
        floor = datetime.now(TZ) + timedelta(hours=71)
        for s in slots:
            self.assertGreaterEqual(s["start_local"], floor)

    def test_weekend_is_closed(self):
        slots = self.atype.get_available_slots(
            self.service, day_from=self.saturday, day_to=self.saturday
        )
        self.assertEqual(slots, [])

    def test_service_not_on_page_yields_no_slots(self):
        other = self.env["product.template"].create(
            {
                "name": "Not offered here",
                "type": "service",
                "salon_service": True,
                "salon_duration": 1.0,
            }
        )
        slots = self.atype.get_available_slots(
            other, day_from=self.monday, day_to=self.monday
        )
        self.assertEqual(slots, [])

    def test_is_slot_free(self):
        outside = self.env["salon.appointment"].new(
            {
                "appointment_type_id": self.atype.id,
                "service_id": self.service.id,
                "employee_id": self.employee.id,
                "start": self._utc(self.monday, 22, 0),
            }
        )
        self.assertFalse(outside._is_slot_free())

        inside = self.env["salon.appointment"].new(
            {
                "appointment_type_id": self.atype.id,
                "service_id": self.service.id,
                "employee_id": self.employee.id,
                "start": self._utc(self.monday, 9, 0),
            }
        )
        self.assertTrue(inside._is_slot_free())

    @mute_logger("odoo.sql_db")
    def test_double_booking_is_refused(self):
        self._book(self.employee, self.monday, 14, 0)
        with self.assertRaises(Exception) as cm:
            self._book(self.employee, self.monday, 14, 30)
        self.assertIsInstance(cm.exception, OVERLAP_BLOCKED)
        # a different staff member at the same time is fine
        other = self._book(self.employee_b, self.monday, 14, 30)
        self.assertTrue(other.id)

    def test_cancelling_frees_the_slot(self):
        appt = self._book(self.employee, self.monday, 15, 0)
        appt.action_cancel()
        again = self._book(self.employee, self.monday, 15, 0)
        self.assertTrue(again.id)

    def test_db_exclusion_constraint_is_installed(self):
        self.env.cr.execute(
            """
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conname = 'salon_appointment_no_overlap'
            """
        )
        row = self.env.cr.fetchone()
        self.assertTrue(row, "the btree_gist EXCLUDE constraint should exist")
        self.assertIn("EXCLUDE", row[0])
