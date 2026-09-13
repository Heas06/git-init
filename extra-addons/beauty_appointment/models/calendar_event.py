from odoo import fields, models


class CalendarEvent(models.Model):
    _inherit = "calendar.event"

    salon_appointment_ids = fields.One2many(
        "salon.appointment", "calendar_event_id", string="Salon Appointments"
    )
    salon_appointment_count = fields.Integer(compute="_compute_salon_appointment_count")

    def _compute_salon_appointment_count(self):
        for event in self:
            event.salon_appointment_count = len(event.salon_appointment_ids)

    def action_view_salon_appointments(self):
        self.ensure_one()
        appointments = self.salon_appointment_ids
        action = {
            "type": "ir.actions.act_window",
            "name": self.env._("Appointment"),
            "res_model": "salon.appointment",
        }
        if len(appointments) == 1:
            action.update({"view_mode": "form", "res_id": appointments.id})
        else:
            action.update(
                {"view_mode": "calendar,list,form", "domain": [("id", "in", appointments.ids)]}
            )
        return action
