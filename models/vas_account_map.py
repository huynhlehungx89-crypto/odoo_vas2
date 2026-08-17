# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

ACCOUNT_FIELDS = (
    'stock_account_id', 'revenue_account_id', 'cogs_account_id', 'expense_account_id',
)


class VasAccountMap(models.Model):
    """Ánh xạ sản phẩm / nhóm sản phẩm → tài khoản VAS, tách theo chế độ kế toán.

    Đây là nguồn duy nhất của TRỤC 1. Bảng nằm theo `regime_id` nên cùng một nhóm
    sản phẩm có thể khai tài khoản khác nhau cho TT133 và TT99 mà không đụng nhau.
    """

    _name = 'vas.account.map'
    _description = 'Ánh xạ tài khoản VAS theo sản phẩm'
    _order = 'regime_id, apply_to desc, id'

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
        default='category',
        index=True,
    )
    category_id = fields.Many2one(
        'product.category',
        string='Nhóm sản phẩm',
        index=True,
        ondelete='cascade',
    )
    product_id = fields.Many2one(
        'product.template',
        string='Sản phẩm',
        index=True,
        ondelete='cascade',
        help='Ngoại lệ cấp sản phẩm — thắng dòng khai theo nhóm.',
    )
    stock_account_id = fields.Many2one(
        'vas.account',
        string='TK tồn kho',
        ondelete='restrict',
        help='156 hàng hóa, 152 nguyên vật liệu, 153 công cụ, 155 thành phẩm. '
             'Để trống là hợp lệ (vd nhóm dịch vụ).',
    )
    revenue_account_id = fields.Many2one(
        'vas.account',
        string='TK doanh thu',
        ondelete='restrict',
        help='5111 hàng hóa, 5112 thành phẩm, 5113 dịch vụ.',
    )
    cogs_account_id = fields.Many2one(
        'vas.account',
        string='TK giá vốn',
        ondelete='restrict',
        help='Thường là 632.',
    )
    expense_account_id = fields.Many2one(
        'vas.account',
        string='TK chi phí',
        ondelete='restrict',
        help='TRỤC 2 — TT133 chỉ có ba đích: 154 chi phí sản xuất, '
             '6421 chi phí bán hàng, 6422 chi phí quản lý doanh nghiệp. '
             'Chia theo MỤC ĐÍCH chi, không theo bộ phận của người chi. '
             'Để trống là hợp lệ (vd nhóm hàng hóa) — khi đó engine dùng mặc định 6422.',
    )
    cost_item_id = fields.Many2one(
        'vas.cost.item',
        string='Khoản mục chi phí',
        ondelete='restrict',
        help='W12: chỉ nhận khoản mục lá (không nút tổng hợp, không CPD). '
             'Máy tra khi sinh bút toán mua ngoài (R08).',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Công ty',
        index=True,
        ondelete='cascade',
        default=lambda self: self.env.company,
        help='Để trống = áp dụng cho mọi công ty dùng chế độ này. '
             'Dòng khai đích danh công ty thắng dòng để trống.',
    )
    active = fields.Boolean(string='Đang dùng', default=True)

    # -------------------------------------------------------------------------
    # Onchange / constraints
    # -------------------------------------------------------------------------

    @api.onchange('apply_to')
    def _onchange_apply_to(self):
        for row in self:
            if row.apply_to == 'category':
                row.product_id = False
            else:
                row.category_id = False

    @api.constrains('cost_item_id')
    def _check_cost_item_leaf_not_cpd(self):
        for row in self:
            item = row.cost_item_id
            if not item:
                continue
            if item.is_aggregate_node:
                raise ValidationError(_(
                    'Ánh xạ tài khoản chỉ nhận khoản mục lá. '
                    '«%(code)s — %(name)s» là nút tổng hợp.',
                    code=item.code or '',
                    name=item.name or '',
                ))
            if item._is_cpd_seed():
                raise ValidationError(_(
                    'Không được khai khoản mục «Chưa phân loại» (CPD) trên '
                    'ánh xạ tài khoản. CPD chỉ dùng khi máy tra không ra.'
                ))

    @api.constrains('apply_to', 'category_id', 'product_id')
    def _check_target(self):
        for row in self:
            if row.apply_to == 'category':
                if not row.category_id:
                    raise ValidationError(_("Dòng ánh xạ theo nhóm phải chọn Nhóm sản phẩm."))
                if row.product_id:
                    raise ValidationError(_(
                        "Dòng ánh xạ theo nhóm không được chọn Sản phẩm. "
                        "Muốn khai riêng một sản phẩm thì tạo dòng 'Sản phẩm cụ thể'."
                    ))
            else:
                if not row.product_id:
                    raise ValidationError(_("Dòng ngoại lệ phải chọn Sản phẩm."))
                if row.category_id:
                    raise ValidationError(_(
                        "Dòng ngoại lệ theo sản phẩm không được chọn Nhóm sản phẩm."
                    ))

    @api.constrains('regime_id', 'category_id', 'product_id', 'company_id', 'active')
    def _check_unique_target(self):
        for row in self:
            if not row.active:
                continue
            domain = [
                ('id', '!=', row.id),
                ('regime_id', '=', row.regime_id.id),
                ('company_id', '=', row.company_id.id),
                ('apply_to', '=', row.apply_to),
            ]
            if row.apply_to == 'category':
                domain.append(('category_id', '=', row.category_id.id))
                label = row.category_id.display_name
            else:
                domain.append(('product_id', '=', row.product_id.id))
                label = row.product_id.display_name
            if self.search_count(domain):
                raise ValidationError(_(
                    "Đã có dòng ánh xạ cho %(target)s ở chế độ %(regime)s. "
                    "Sửa dòng cũ thay vì tạo dòng thứ hai — hai dòng sẽ đá nhau.",
                    target=label,
                    regime=row.regime_id.display_name,
                ))

    @api.constrains('regime_id', *ACCOUNT_FIELDS)
    def _check_account_regime(self):
        for row in self:
            for fname in ACCOUNT_FIELDS:
                account = row[fname]
                if account and account.regime_id != row.regime_id:
                    raise ValidationError(_(
                        "Tài khoản %(code)s thuộc chế độ %(acc_regime)s, không phải "
                        "%(regime)s của dòng ánh xạ này. Chọn tài khoản cùng chế độ.",
                        code=account.display_name,
                        acc_regime=account.regime_id.display_name,
                        regime=row.regime_id.display_name,
                    ))

    # -------------------------------------------------------------------------
    # Tra cứu (engine dùng)
    # -------------------------------------------------------------------------

    @api.model
    def _find_rows(self, regime, company, apply_to, target_id):
        """Các dòng ứng viên, XẾP THEO ĐỘ ƯU TIÊN: đích danh công ty trước, chung sau.

        Trả về nhiều dòng chứ không chốt một dòng, vì từng trường tra độc lập: dòng
        đích danh công ty có thể khai TK doanh thu mà bỏ trống TK tồn kho, khi đó
        riêng TK tồn kho phải rơi tiếp xuống dòng chung.
        """
        if not target_id:
            return self.browse()
        key = 'category_id' if apply_to == 'category' else 'product_id'
        rows = self.search([
            ('regime_id', '=', regime.id),
            ('apply_to', '=', apply_to),
            (key, '=', target_id),
            ('company_id', 'in', (company.id, False)),
        ])
        return rows.filtered('company_id') + rows.filtered(lambda r: not r.company_id)

    @api.model
    def _find_row(self, regime, company, apply_to, target_id):
        """Dòng ưu tiên cao nhất — dùng cho hiển thị, không dùng để tra từng trường."""
        return self._find_rows(regime, company, apply_to, target_id)[:1]
