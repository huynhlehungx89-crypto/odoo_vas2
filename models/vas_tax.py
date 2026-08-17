# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class VasTax(models.Model):
    """Danh mục thuế VAS — phục vụ gắn tax_id trên sổ và tờ khai GTGT.

    Thuế suất, mốc hiệu lực, chỉ tiêu tờ khai nằm ở DỮ LIỆU (XML seed),
    không hardcode trong engine.
    """
    _name = 'vas.tax'
    _description = 'Thuế VAS'
    _order = 'sequence, code'

    code = fields.Char(string='Mã', required=True, index=True)
    name = fields.Char(string='Tên', required=True)
    sequence = fields.Integer(string='Thứ tự', default=10)
    active = fields.Boolean(default=True)
    regime_id = fields.Many2one(
        'vas.regime', string='Chế độ', required=True, index=True, ondelete='restrict',
    )
    rate = fields.Float(
        string='Thuế suất (%)',
        help='Số % khớp với account.tax.amount khi match_mode=rate. '
             'Không chịu thuế (empty_line) để 0.',
    )
    tax_scope = fields.Selection(
        [
            ('output', 'Đầu ra'),
            ('input', 'Đầu vào'),
            ('both', 'Đầu ra và đầu vào'),
        ],
        string='Phạm vi',
        required=True,
        default='both',
    )
    date_start = fields.Date(string='Hiệu lực từ', required=True)
    date_end = fields.Date(
        string='Hiệu lực đến',
        help='Trống = không giới hạn. Mức 8% NQ 204: đến 31/12/2026.',
    )
    declaration_value_tag = fields.Char(
        string='Chỉ tiêu giá trị HHĐV (01/GTGT)',
        required=True,
        help='Số hiệu cột «Giá trị hàng hóa, dịch vụ (chưa có thuế GTGT)» '
             'trên mẫu 01/GTGT (vd 26, 29, 30, 32, 32a). '
             'Mức 8% NQ 204 trỏ [32] (giảm từ 10%).',
    )
    declaration_tax_tag = fields.Char(
        string='Chỉ tiêu tiền thuế (01/GTGT)',
        help='Số hiệu cột «Thuế GTGT» trên mẫu 01/GTGT (vd 31, 33). '
             'Để trống có chủ đích khi mức không phát sinh tiền thuế '
             '(không chịu, không tính, 0%). Không ghi 0. '
             'Mức 8% NQ 204 trỏ [33].',
    )
    declaration_annex_tag = fields.Char(
        string='Tag phụ lục giảm thuế',
        help='Vd NQ204 — mức 8% đồng thời lên phụ lục giảm thuế (NĐ 174 Mẫu 01). '
             'Trống = không lên phụ lục giảm.',
    )
    match_mode = fields.Selection(
        [
            ('empty_line', 'Dòng HĐ không gắn thuế Odoo'),
            ('rate', 'Khớp theo thuế suất Odoo'),
        ],
        string='Cách khớp chứng từ',
        required=True,
        default='rate',
    )
    odoo_name_token = fields.Char(
        string='Token tên thuế Odoo',
        help='Khi nhiều mức cùng thuế suất (vd 0%%): chỉ khớp nếu token này '
             'xuất hiện trong account.tax.name. Trống = khớp mọi thuế cùng suất.',
    )
    account_id = fields.Many2one(
        'vas.account',
        string='TK thuế mặc định',
        ondelete='restrict',
        help='33311 (đầu ra) hoặc 1331 (đầu vào) — tham chiếu, không bắt buộc lúc khớp.',
    )

    _code_regime_uniq = models.Constraint(
        'unique(code, regime_id)',
        'Mã thuế phải duy nhất trong một chế độ kế toán.',
    )

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for tax in self:
            if tax.date_end and tax.date_start and tax.date_end < tax.date_start:
                raise ValidationError(_(
                    'Ngày kết thúc hiệu lực phải sau hoặc bằng ngày bắt đầu (%s).',
                    tax.display_name,
                ))

    @api.depends('code', 'name', 'rate')
    def _compute_display_name(self):
        for tax in self:
            code = tax.code or ''
            name = tax.name or ''
            tax.display_name = f'{code} — {name} ({tax.rate:g}%)'

    @api.model
    def _domain_on_date(self, date):
        return [
            ('active', '=', True),
            ('date_start', '<=', date),
            '|', ('date_end', '=', False), ('date_end', '>=', date),
        ]

    @api.model
    def find_for_invoice_line(self, company, date, scope, odoo_taxes=None, empty_taxes=False):
        """Tra vas.tax theo dữ liệu. Không mặc định thuế suất.

        Trả (tax_record_or_empty, status, warning_msg_or_False)
        status: 'resolved' | 'undetermined'
        """
        if not company or not company.vas_regime_id or not date:
            return self.browse(), 'undetermined', _(
                'Thiếu công ty/chế độ/ngày — không xác định được thuế suất.'
            )
        Tax = self.sudo()
        base = [
            ('regime_id', '=', company.vas_regime_id.id),
            '|', ('tax_scope', '=', 'both'), ('tax_scope', '=', scope),
        ]
        on_date = self._domain_on_date(date)

        if empty_taxes:
            found = Tax.search(base + on_date + [('match_mode', '=', 'empty_line')], limit=2)
            if len(found) == 1:
                return found, 'resolved', False
            if not found:
                return self.browse(), 'undetermined', _(
                    'Dòng HĐ không có thuế Odoo nhưng danh mục VAS không có mức '
                    '«không chịu thuế» còn hiệu lực ngày %s.',
                    date,
                )
            return self.browse(), 'undetermined', _(
                'Nhiều mức «không chịu thuế» khớp ngày %s — không tự chọn.',
                date,
            )

        odoo_taxes = odoo_taxes or self.env['account.tax']
        if len(odoo_taxes) != 1:
            return self.browse(), 'undetermined', _(
                'Dòng HĐ có %s thuế Odoo — chưa hỗ trợ ghép nhiều thuế trên một dòng.',
                len(odoo_taxes),
            )
        odoo_tax = odoo_taxes[0]
        rate = odoo_tax.amount
        candidates = Tax.search(base + on_date + [
            ('match_mode', '=', 'rate'),
            ('rate', '=', rate),
        ])
        # Ưu tiên bản ghi có token khớp tên Odoo
        named = candidates.filtered(
            lambda t: t.odoo_name_token
            and t.odoo_name_token.lower() in (odoo_tax.name or '').lower()
        )
        if len(named) == 1:
            return named, 'resolved', False
        if len(named) > 1:
            return self.browse(), 'undetermined', _(
                'Nhiều mức VAS khớp token tên thuế Odoo «%s».',
                odoo_tax.name,
            )
        plain = candidates.filtered(lambda t: not t.odoo_name_token)
        if len(plain) == 1:
            return plain, 'resolved', False
        if len(plain) > 1:
            return self.browse(), 'undetermined', _(
                'Nhiều mức VAS cùng thuế suất %s%% còn hiệu lực ngày %s.',
                rate, date,
            )
        # Không có bản ghi còn hiệu lực — kiểm tra có bản ghi hết hạn cùng suất?
        expired = Tax.search(base + [
            ('match_mode', '=', 'rate'),
            ('rate', '=', rate),
            ('date_end', '!=', False),
            ('date_end', '<', date),
        ], limit=1)
        if expired:
            return self.browse(), 'undetermined', _(
                'Thuế suất %s%% («%s») đã HẾT HIỆU LỰC từ sau %s '
                '(chứng từ ngày %s) — không gán lặng lẽ.',
                rate, expired.display_name, expired.date_end, date,
            )
        return self.browse(), 'undetermined', _(
            'Không có mức VAS khớp thuế Odoo «%s» (%s%%) ngày %s.',
            odoo_tax.name, rate, date,
        )
