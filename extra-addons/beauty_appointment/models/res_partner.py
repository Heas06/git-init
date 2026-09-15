from odoo import models, fields

class ResPartner(models.Model):
    _inherit = 'res.partner'

    x_preferencia_bebida = fields.Selection(
        selection=[
            ('1', 'Agua'),
            ('2', 'Tea'),
            ('3', 'Aromatica'),
            ('4', 'Ninguna'),
        ],
        string='Preferencia de Bebida'
    )
    x_condiciones_alergias = fields.Text(string='Condiciones / Alergias')
    x_formulas_tonalidades = fields.Text(string='Fórmulas / Tonalidades')