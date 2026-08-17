# -*- coding: utf-8 -*-
"""Chiều nhận diện sản phẩm cho VAS (ô tô ngoại lệ + NQ 204)."""
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    vas_passenger_car_business_exception = fields.Boolean(
        string='Ô tô ≤09 chỗ — ngoại lệ KD vận tải/du lịch/KS hoặc xe mẫu',
        default=False,
        help='Tích: không áp giới hạn khấu trừ 1,6 tỷ (181 Điều 24). Mặc định không tích.',
    )
    vas_vsic_code = fields.Char(
        string='Mã VSIC / Cap (NQ 204)',
        index=True,
        help='Mã ngành/cấp sản phẩm đối chiếu Phụ lục I NĐ 174. '
             'Trống + không có HS/TTĐB → CHƯA XÁC ĐỊNH khi HĐ 8%.',
    )
    vas_hs_code = fields.Char(
        string='Mã HS (NQ 204)',
        index=True,
        help='Mã HS đối chiếu Phụ lục I (khâu NK).',
    )
    vas_ttdb_code = fields.Char(
        string='Mã nhóm TTĐB (NQ 204)',
        index=True,
        help='Vd TTDB_TOBACCO — đối chiếu Phụ lục II NĐ 174.',
    )
    vas_gtgt_direct_industry_id = fields.Many2one(
        'vas.gtgt.direct.industry',
        string='Nhóm ngành GTGT trực tiếp',
        ondelete='restrict',
        index=True,
        help='Chặng 7: đối chiếu mẫu 04/GTGT (hoặc vàng bạc mẫu 03). '
             'Trống → CHƯA XÁC ĐỊNH, chặn lập tờ trực tiếp.',
    )


class ProductProduct(models.Model):
    _inherit = 'product.product'

    vas_passenger_car_business_exception = fields.Boolean(
        related='product_tmpl_id.vas_passenger_car_business_exception',
        readonly=False,
    )
    vas_vsic_code = fields.Char(
        related='product_tmpl_id.vas_vsic_code', readonly=False,
    )
    vas_hs_code = fields.Char(
        related='product_tmpl_id.vas_hs_code', readonly=False,
    )
    vas_ttdb_code = fields.Char(
        related='product_tmpl_id.vas_ttdb_code', readonly=False,
    )
    vas_gtgt_direct_industry_id = fields.Many2one(
        related='product_tmpl_id.vas_gtgt_direct_industry_id',
        readonly=False,
    )
