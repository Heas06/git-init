from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    salon_service = fields.Boolean(
        string="Salon Service",
        help="List this product as a bookable service on the salon booking page.",
    )
    salon_duration = fields.Float(
        string="Duration",
        digits=(4, 2),
        default=1.0,
        help="Default time (in hours) a booking for this service occupies in the agenda.",
    )
    salon_buffer = fields.Float(
        string="Cleanup Buffer",
        digits=(4, 2),
        default=0.0,
        help="Extra time (in hours) blocked after the service before the staff member is free again.",
    )
    salon_employee_ids = fields.Many2many(
        comodel_name="hr.employee",
        relation="salon_service_employee_rel",
        column1="product_tmpl_id",
        column2="employee_id",
        string="Staff",
        help="Employees able to perform this service. Leave empty to allow any salon staff.",
    )
