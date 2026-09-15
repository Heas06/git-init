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

    x_consentimiento_archivo = fields.Binary(
        string='Consentimiento Firmado',
        attachment=True,
        help='PDF o Word con el consentimiento informado firmado por el cliente.',
    )
    x_consentimiento_nombre_archivo = fields.Char(string='Nombre del archivo')
    x_consentimiento_fecha = fields.Date(string='Fecha de firma')