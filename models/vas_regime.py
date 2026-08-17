# -*- coding: utf-8 -*-
from odoo import api, fields, models


class VasRegime(models.Model):
    _name = 'vas.regime'
    _description = 'Chế độ kế toán VAS'
    _order = 'code'

    code = fields.Char(string='Mã', required=True, index=True)
    name = fields.Char(string='Tên', required=True)
    active = fields.Boolean(string='Đang dùng', default=True)

    _code_uniq = models.Constraint(
        'UNIQUE(code)',
        'The regime code must be unique.',
    )

    @api.model
    def _connecta_seed_tt133(self):
        """Idempotent seed: TT133 regime + bind xmlid + set main company default."""
        regime = self.search([('code', '=', 'TT133')], limit=1)
        if not regime:
            regime = self.create({
                'code': 'TT133',
                'name': 'Thông tư 133/2016/TT-BTC',
                'active': True,
            })
        self.env['ir.model.data']._update_xmlids([{
            'xml_id': 'connecta_vas.vas_regime_tt133',
            'record': regime,
            'noupdate': True,
        }])
        company = self.env.ref('base.main_company')
        if not company.vas_regime_id:
            company.vas_regime_id = regime
        return True
