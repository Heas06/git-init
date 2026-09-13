from datetime import datetime, timedelta

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSalonCalendarSync(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["hr.employee"].create(
            {
                "name": "Test Sync Stylist",
                "is_salon_staff": True,
                "resource_calendar_id": cls.env.ref("resource.resource_calendar_std").id,
            }
        )
        cls.service = cls.env["product.template"].create(
            {
                "name": "Test Sync Service",
                "type": "service",
                "salon_service": True,
                "salon_duration": 1.0,
                "salon_buffer": 0.25,
            }
        )
        cls.partner = cls.env["res.partner"].create({"name": "Test Sync Client"})
        cls.start = datetime.now().replace(microsecond=0) + timedelta(days=10)

    def _new_appointment(self, **extra):
        vals = {
            "partner_id": self.partner.id,
            "service_id": self.service.id,
            "employee_id": self.employee.id,
            "start": self.start,
        }
        vals.update(extra)
        return self.env["salon.appointment"].create(vals)

    def test_no_event_while_draft(self):
        appt = self._new_appointment()
        self.assertEqual(appt.state, "draft")
        self.assertFalse(appt.calendar_event_id)

    def test_confirm_creates_event(self):
        appt = self._new_appointment()
        appt.action_confirm()
        self.assertTrue(appt.calendar_event_id)
        event = appt.calendar_event_id
        self.assertEqual(event.start, appt.start)
        self.assertEqual(event.stop, appt.stop_with_buffer)  # buffer is blocked too
        self.assertIn(self.partner, event.partner_ids)
        self.assertIn(self.employee.work_contact_id, event.partner_ids)
        self.assertTrue(event.active)
        self.assertEqual(len(event.alarm_ids), 2)

    def test_creating_confirmed_directly_also_syncs(self):
        # Mirrors how the public booking controller creates appointments:
        # state='confirmed' passed straight to create(), no action_confirm().
        appt = self._new_appointment(state="confirmed")
        self.assertTrue(appt.calendar_event_id)

    def test_cancel_archives_event_without_deleting(self):
        appt = self._new_appointment()
        appt.action_confirm()
        event = appt.calendar_event_id
        appt.action_cancel()
        self.assertEqual(event.exists(), event)  # still there
        self.assertFalse(event.active)

    def test_reconfirm_reuses_and_reactivates_same_event(self):
        appt = self._new_appointment()
        appt.action_confirm()
        first_event_id = appt.calendar_event_id.id
        appt.action_cancel()
        self.assertFalse(appt.calendar_event_id.active)
        appt.action_draft()
        appt.action_confirm()
        self.assertEqual(appt.calendar_event_id.id, first_event_id)
        self.assertTrue(appt.calendar_event_id.active)

    def test_reschedule_updates_the_mirrored_event(self):
        appt = self._new_appointment()
        appt.action_confirm()
        new_start = self.start + timedelta(hours=3)
        appt.write({"start": new_start})
        self.assertEqual(appt.calendar_event_id.start, new_start)
        self.assertEqual(appt.calendar_event_id.stop, appt.stop_with_buffer)

    def test_view_back_reference_from_event(self):
        appt = self._new_appointment()
        appt.action_confirm()
        self.assertEqual(appt.calendar_event_id.salon_appointment_count, 1)
        action = appt.calendar_event_id.action_view_salon_appointments()
        self.assertEqual(action["res_id"], appt.id)
