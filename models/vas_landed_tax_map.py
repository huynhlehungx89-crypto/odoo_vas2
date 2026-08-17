# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class VasLandedTaxMap(models.Model):
    """Cấu hình SP / nhóm SP landed cost → TK thuế phải nộp (3333 / 3332 / 33381…).

    Dùng để R25 phân nhánh: dòng LC thuế → Có TK này; dòng cước → vẫn Có 331.
    Many2one tới vas.account — thêm sắc thuế mới chỉ cần thêm dòng cấu hình.
    """

    _name = 'vas.landed.tax.map'
    _description = 'Ánh xạ landed cost thuế phải nộp'
    _order = 'regime_id, apply_to desc, id'

    name = fields.Char(string='Tên', compute='_compute_name', store=True)
    regime_id = fields.Many2one(
        'vas.regime',
        string='Chế độ kế toán',
        required=True,
        index=True,
        ondelete='cascade',
        default=lambda self: self.env.company.vas_regime_id,
    )
    apply_to = fields.Selection(
        selection=[
            ('category', 'Nhóm sản phẩm'),
            ('product', 'Sản phẩm cụ thể'),
        ],
        string='Áp dụng cho',
        required=True,
        default='product',
        index=True,
    )
    category_id = fields.Many2one(
        'product.category',
        string='Nhóm sản phẩm',
        index=True,
        ondelete='cascade',
        help='Nhóm SP dịch vụ landed (vd nhóm Thuế NK / TTĐB / BVMT).',
    )
    product_id = fields.Many2one(
        'product.template',
        string='Sản phẩm',
        index=True,
        ondelete='cascade',
        help='SP landed cost đại diện sắc thuế (landed_cost_ok).',
    )
    credit_account_id = fields.Many2one(
        'vas.account',
        string='TK thuế phải nộp (Có)',
        required=True,
        ondelete='restrict',
        domain="[('regime_id', '=', regime_id)]",
        help='3333 thuế xuất nhập khẩu, 3332 TTĐB, 33381 BVMT, …',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Công ty',
        index=True,
        ondelete='cascade',
        default=lambda self: self.env.company,
        help='Để trống = mọi công ty dùng chế độ này. '
             'Dòng khai đích danh công ty thắng dòng trống.',
    )
    active = fields.Boolean(string='Đang dùng', default=True)

    @api.depends(
        'apply_to', 'product_id', 'category_id', 'credit_account_id', 'regime_id',
    )
    def _compute_name(self):
        for row in self:
            target = (
                row.product_id.display_name
                if row.apply_to == 'product' and row.product_id
                else (
                    row.category_id.display_name
                    if row.category_id else _('(chưa chọn)')
                )
            )
            code = row.credit_account_id.code or '?'
            row.name = f'{target} → Có {code}'

    @api.onchange('apply_to')
    def _onchange_apply_to(self):
        for row in self:
            if row.apply_to == 'category':
                row.product_id = False
            else:
                row.category_id = False

    @api.constrains('apply_to', 'category_id', 'product_id')
    def _check_target(self):
        for row in self:
            if row.apply_to == 'category':
                if not row.category_id:
                    raise ValidationError(_("Phải chọn Nhóm sản phẩm."))
                if row.product_id:
                    raise ValidationError(_("Dòng theo nhóm không được chọn Sản phẩm."))
            else:
                if not row.product_id:
                    raise ValidationError(_("Phải chọn Sản phẩm."))
                if row.category_id:
                    raise ValidationError(_("Dòng theo sản phẩm không được chọn Nhóm."))

    @api.constrains('credit_account_id', 'regime_id')
    def _check_account_regime(self):
        for row in self:
            if (
                row.credit_account_id
                and row.regime_id
                and row.credit_account_id.regime_id != row.regime_id
            ):
                raise ValidationError(_(
                    "TK %(code)s không thuộc chế độ %(regime)s.",
                    code=row.credit_account_id.code,
                    regime=row.regime_id.display_name,
                ))

    def _find_for_product(self, product, regime, company):
        """Tra map: sản phẩm cụ thể thắng nhóm; company cụ thể thắng dòng trống."""
        if not product or not regime:
            return self.browse()
        Map = self.sudo()
        domain_base = [
            ('regime_id', '=', regime.id),
            ('active', '=', True),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', company.id if company else False),
        ]
        # Product template level
        tmpl = product.product_tmpl_id if product._name == 'product.product' else product
        rows = Map.search(domain_base + [
            ('apply_to', '=', 'product'),
            ('product_id', '=', tmpl.id),
        ], order='company_id desc, id')
        if rows:
            return rows[:1]
        categ = tmpl.categ_id
        if categ:
            rows = Map.search(domain_base + [
                ('apply_to', '=', 'category'),
                ('category_id', '=', categ.id),
            ], order='company_id desc, id')
            if rows:
                return rows[:1]
        return self.browse()
