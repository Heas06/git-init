from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    is_salon_staff = fields.Boolean(
        string="Salon Staff",
        help="This employee can be booked for salon services. "
        "Their working schedule drives the available time slots.",
    )
    salon_service_ids = fields.Many2many(
        comodel_name="product.template",
        relation="salon_service_employee_rel",
        column1="employee_id",
        column2="product_tmpl_id",
        string="Salon Services",
        domain=[("salon_service", "=", True)],
        help="Services this staff member is able to perform.",
    )
