from datetime import datetime, timedelta

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSalonSalesCrm(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["hr.employee"].create(
            {
                "name": "Test CRM Stylist",
                "is_salon_staff": True,
                "resource_calendar_id": cls.env.ref("resource.resource_calendar_std").id,
            }
        )
        cls.service = cls.env["product.template"].create(
            {
                "name": "Test CRM Service",
                "type": "service",
                "salon_service": True,
                "salon_duration": 1.0,
                "list_price": 42.0,
            }
        )
        cls.partner = cls.env["res.partner"].create({"name": "Test CRM Client"})
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

    def test_create_attaches_lead_and_draft_order(self):
        appt = self._new_appointment()
        self.assertTrue(appt.lead_id)
        self.assertEqual(appt.lead_id.partner_id, self.partner)
        self.assertTrue(appt.sale_order_id)
        self.assertEqual(appt.sale_order_id.state, "draft")
        self.assertEqual(len(appt.sale_order_id.order_line), 1)
        self.assertEqual(
            appt.sale_order_id.order_line.product_id, self.service.product_variant_id
        )

    def test_second_appointment_reuses_lead_but_gets_own_order(self):
        appt1 = self._new_appointment()
        appt2 = self._new_appointment(start=self.start + timedelta(hours=2))
        self.assertEqual(appt1.lead_id, appt2.lead_id)
        self.assertNotEqual(appt1.sale_order_id, appt2.sale_order_id)

    def test_confirm_confirms_the_order(self):
        appt = self._new_appointment()
        appt.action_confirm()
        self.assertEqual(appt.sale_order_id.state, "sale")

    def test_done_creates_and_posts_invoice(self):
        appt = self._new_appointment()
        appt.action_confirm()
        appt.action_done()
        order = appt.sale_order_id
        self.assertTrue(order.invoice_ids)
        self.assertTrue(all(inv.state == "posted" for inv in order.invoice_ids))

    def test_cancel_cancels_the_order(self):
        appt = self._new_appointment()
        appt.action_confirm()
        appt.action_cancel()
        self.assertEqual(appt.sale_order_id.state, "cancel")

    def test_smart_button_openers(self):
        appt = self._new_appointment()
        appt.action_confirm()
        self.assertEqual(appt.action_view_lead()["res_id"], appt.lead_id.id)
        self.assertEqual(appt.action_view_sale_order()["res_id"], appt.sale_order_id.id)
        self.assertEqual(appt.action_view_calendar_event()["res_id"], appt.calendar_event_id.id)

    def test_reverse_counts_on_lead_and_order(self):
        appt1 = self._new_appointment()
        appt2 = self._new_appointment(start=self.start + timedelta(hours=2))
        self.assertEqual(appt1.lead_id.salon_appointment_count, 2)
        self.assertEqual(appt1.sale_order_id.salon_appointment_count, 1)
        self.assertEqual(appt2.sale_order_id.salon_appointment_count, 1)
