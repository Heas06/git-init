from odoo import fields, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    salon_appointment_ids = fields.One2many(
        "salon.appointment", "lead_id", string="Salon Appointments"
    )
    salon_appointment_count = fields.Integer(compute="_compute_salon_appointment_count")

    def _compute_salon_appointment_count(self):
        for lead in self:
            lead.salon_appointment_count = len(lead.salon_appointment_ids)

    def action_view_salon_appointments(self):
        self.ensure_one()
        appointments = self.salon_appointment_ids
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Appointments"),
            "res_model": "salon.appointment",
            "view_mode": "calendar,list,form",
            "domain": [("id", "in", appointments.ids)],
        }
