# -*- coding: utf-8 -*-
"""Lưu nội dung người điền B09 — tách khỏi bản báo cáo, sống sót khi lập lại.

Khóa: (company_id, period_from_id, period_to_id, code).
Bản snapshot đã nộp khóa phần đã chép vào snapshot; kho này vẫn sửa được
cho lần lập sau (xem docs/nguon/_w11_bctc_design.md §6.4).
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError
# (a) Đoạn văn
B09_TEXT_CODES = tuple(
    ['I.%s' % i for i in range(1, 7)]
    + ['III.1']
    + ['IV.%s' % i for i in range(1, 13)]
    + ['V.16']
    + ['VII.1']
    + ['VIII.%s' % i for i in range(1, 6)]
)

# (b) Số tiền (đầu năm / cuối kỳ)
B09_AMOUNT_CODES = (
    'V.1.equiv',
    'V.3a.related', 'V.3b.related',
    'V.3d.cash', 'V.3d.inv', 'V.3d.fa', 'V.3d.other',
    'V.3đ.total',
    'V.4.stagnant', 'V.4.pledged',
    'V.9a.related', 'V.9b.related', 'V.9d',
    'V.10.total',
    'V.11.st', 'V.11.lt',
    'VI.1b',
    'VI.7.disposal', 'VI.8.disposal',
)

# (c) Bảng nhiều dòng
B09_TABLE_CODES = (
    'V.13a',
    'V.14a', 'V.14b', 'V.14c', 'V.14d', 'V.14đ', 'V.14f',
    'V.15',
    'VI.1c',
)

B09_ENTRY_CODES = B09_TEXT_CODES + B09_AMOUNT_CODES + B09_TABLE_CODES

B09_CONTENT_KIND = {
    **{c: 'text' for c in B09_TEXT_CODES},
    **{c: 'amount' for c in B09_AMOUNT_CODES},
    **{c: 'table' for c in B09_TABLE_CODES},
}

SUGGESTION_PREFIX = '[Gợi ý máy — chưa xác nhận]\n'
PRIOR_PREFIX = '[Nội dung năm trước — cần rà lại]\n'

TT133_COMPLIANCE_TEMPLATE = (
    'Ban Giám đốc / kế toán doanh nghiệp khẳng định Báo cáo tài chính được lập '
    'và trình bày phù hợp với chuẩn mực kế toán Việt Nam, chế độ kế toán doanh '
    'nghiệp nhỏ và vừa theo Thông tư số 133/2016/TT-BTC và các quy định pháp '
    'luật hiện hành có liên quan.'
)


class VasB09Entry(models.Model):
    _name = 'vas.b09.entry'
    _description = 'Nội dung người điền B09 (tách khỏi bản báo cáo)'
    _order = 'code, id'

    company_id = fields.Many2one(
        'res.company', required=True, index=True, ondelete='cascade',
    )
    period_from_id = fields.Many2one(
        'vas.period', required=True, index=True, ondelete='restrict',
    )
    period_to_id = fields.Many2one(
        'vas.period', required=True, index=True, ondelete='restrict',
    )
    code = fields.Char(required=True, index=True)
    content_kind = fields.Selection(
        selection=[
            ('text', 'Đoạn văn'),
            ('amount', 'Số tiền'),
            ('table', 'Bảng nhiều dòng'),
        ],
        required=True,
        index=True,
    )
    text_value = fields.Text(string='Nội dung văn bản')
    amount_opening = fields.Float(string='Số đầu năm')
    amount_closing = fields.Float(string='Số cuối kỳ')
    has_opening = fields.Boolean(
        string='Có số đầu năm',
        help='False = để trống (N/A), không ghi 0 im lặng.',
    )
    has_closing = fields.Boolean(string='Có số cuối kỳ')
    origin = fields.Selection(
        selection=[
            ('user', 'Người khai'),
            ('suggestion', 'Gợi ý máy'),
            ('copied_prior', 'Chép từ kỳ trước'),
        ],
        required=True,
        default='user',
        index=True,
    )
    is_confirmed = fields.Boolean(
        string='Đã xác nhận',
        default=True,
        help='False với gợi ý máy / nội dung năm trước chưa rà.',
    )
    is_from_prior_year = fields.Boolean(
        string='Nguồn năm trước',
        default=False,
    )
    prior_label = fields.Char(string='Nhãn kỳ nguồn')
    row_ids = fields.One2many(
        'vas.b09.entry.row', 'entry_id', string='Dòng bảng', copy=True,
    )

    _sql_constraints = [
        (
            'vas_b09_entry_uniq',
            'unique(company_id, period_from_id, period_to_id, code)',
            'Đã có nội dung B09 cho công ty / kỳ / mã dòng này.',
        ),
    ]

    @api.depends('code', 'company_id.display_name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s — %s' % (
                rec.code or '', rec.company_id.display_name or '',
            )

    def write(self, vals):
        # Sửa nội dung → coi là người khai đã xác nhận (trừ khi chỉ đổi cờ)
        content_keys = {
            'text_value', 'amount_opening', 'amount_closing',
            'has_opening', 'has_closing', 'row_ids',
        }
        if content_keys.intersection(vals) and 'is_confirmed' not in vals:
            vals = dict(vals, is_confirmed=True, origin='user', is_from_prior_year=False)
        return super().write(vals)

    def is_filled(self):
        self.ensure_one()
        if self.content_kind == 'text':
            return bool((self.text_value or '').strip())
        if self.content_kind == 'amount':
            return bool(self.has_opening or self.has_closing)
        return bool(self.row_ids)

    def to_snapshot_payload(self):
        """Giá trị chép sang dòng bản B09 lúc lập."""
        self.ensure_one()
        if self.content_kind == 'text':
            return {
                'text': self.text_value or '',
                'table_json': False,
                'o': 0.0, 'c': 0.0, 'na_o': True, 'na_c': True,
            }
        if self.content_kind == 'amount':
            return {
                'text': False,
                'table_json': False,
                'o': self.amount_opening if self.has_opening else 0.0,
                'c': self.amount_closing if self.has_closing else 0.0,
                'na_o': not self.has_opening,
                'na_c': not self.has_closing,
            }
        import json
        rows = [{
            'sequence': r.sequence,
            'name': r.name or '',
            'amount_opening': r.amount_opening,
            'amount_closing': r.amount_closing,
        } for r in self.row_ids.sorted(lambda x: (x.sequence, x.id))]
        return {
            'text': False,
            'table_json': json.dumps(rows, ensure_ascii=False),
            'o': 0.0, 'c': 0.0, 'na_o': True, 'na_c': True,
        }

    def snapshot_value_source(self):
        self.ensure_one()
        if self.origin == 'suggestion' and not self.is_confirmed:
            return 'suggestion'
        if self.origin == 'copied_prior' and not self.is_confirmed:
            return 'copied_prior'
        if self.is_filled():
            return 'user'
        return 'empty'

    @api.model
    def _domain_period(self, company, period_from, period_to):
        return [
            ('company_id', '=', company.id),
            ('period_from_id', '=', period_from.id),
            ('period_to_id', '=', period_to.id),
        ]

    @api.model
    def map_for_period(self, company, period_from, period_to):
        return {
            e.code: e
            for e in self.search(self._domain_period(company, period_from, period_to))
        }

    @api.model
    def get_or_create(self, company, period_from, period_to, code, **extra):
        kind = B09_CONTENT_KIND.get(code)
        if not kind:
            raise UserError(_('Mã B09 %(c)s không thuộc phạm vi người điền.', c=code))
        existing = self.search(
            self._domain_period(company, period_from, period_to) + [('code', '=', code)],
            limit=1,
        )
        if existing:
            # Người điền / gọi API kèm giá trị → cập nhật kho (không giữ gợi ý cũ).
            if extra:
                existing.write(extra)
            return existing
        vals = {
            'company_id': company.id,
            'period_from_id': period_from.id,
            'period_to_id': period_to.id,
            'code': code,
            'content_kind': kind,
            'origin': extra.pop('origin', 'user'),
            'is_confirmed': extra.pop('is_confirmed', True),
            'is_from_prior_year': extra.pop('is_from_prior_year', False),
            'prior_label': extra.pop('prior_label', False),
        }
        vals.update(extra)
        return self.create(vals)

    @api.model
    def find_prior_periods(self, company, period_from, period_to):
        """Kỳ cùng tháng năm trước (cùng công ty)."""
        fy = period_to.fiscalyear_id
        if not fy or not fy.date_from:
            return self.env['vas.period'], self.env['vas.period']
        prior_year = fy.date_from.year - 1
        prior_fy = self.env['vas.fiscalyear'].search([
            ('company_id', '=', company.id),
            ('date_from', '>=', '%s-01-01' % prior_year),
            ('date_from', '<=', '%s-12-31' % prior_year),
        ], limit=1)
        if not prior_fy:
            return self.env['vas.period'], self.env['vas.period']
        def _shift_year(d):
            try:
                return d.replace(year=prior_year)
            except ValueError:
                return d.replace(year=prior_year, day=28)

        p_from = self.env['vas.period'].search([
            ('fiscalyear_id', '=', prior_fy.id),
            ('date_start', '=', _shift_year(period_from.date_start)),
        ], limit=1)
        p_to = self.env['vas.period'].search([
            ('fiscalyear_id', '=', prior_fy.id),
            ('date_start', '=', _shift_year(period_to.date_start)),
        ], limit=1)
        if not p_from:
            p_from = self.env['vas.period'].search([
                ('fiscalyear_id', '=', prior_fy.id),
            ], order='date_start asc', limit=1)
        if not p_to:
            p_to = self.env['vas.period'].search([
                ('fiscalyear_id', '=', prior_fy.id),
            ], order='date_start desc', limit=1)
        return p_from, p_to

    @api.model
    def copy_from_prior_year(self, company, period_from, period_to, only_if_empty=True):
        """Chép nội dung kỳ trước làm nền; đánh dấu năm trước, chưa xác nhận."""
        if only_if_empty:
            if self.search_count(self._domain_period(company, period_from, period_to)):
                return self.browse()
        prior_from, prior_to = self.find_prior_periods(company, period_from, period_to)
        if not prior_from or not prior_to:
            return self.browse()
        prior_entries = self.search(self._domain_period(company, prior_from, prior_to))
        if not prior_entries:
            return self.browse()
        label = prior_to.fiscalyear_id.name or str(prior_to.date_start.year)
        created = self.browse()
        for src in prior_entries:
            if self.search_count(
                self._domain_period(company, period_from, period_to)
                + [('code', '=', src.code)],
            ):
                continue
            text = src.text_value or ''
            if src.content_kind == 'text' and text.strip():
                if not text.startswith(PRIOR_PREFIX):
                    text = PRIOR_PREFIX + text
            vals = {
                'company_id': company.id,
                'period_from_id': period_from.id,
                'period_to_id': period_to.id,
                'code': src.code,
                'content_kind': src.content_kind,
                'text_value': text or False,
                'amount_opening': src.amount_opening,
                'amount_closing': src.amount_closing,
                'has_opening': src.has_opening,
                'has_closing': src.has_closing,
                'origin': 'copied_prior',
                'is_confirmed': False,
                'is_from_prior_year': True,
                'prior_label': label,
                'row_ids': [
                    (0, 0, {
                        'sequence': r.sequence,
                        'name': r.name,
                        'amount_opening': r.amount_opening,
                        'amount_closing': r.amount_closing,
                    }) for r in src.row_ids
                ],
            }
            created |= self.create(vals)
        return created

    @api.model
    def ensure_suggestions(self, company, period_from, period_to):
        """Tạo gợi ý máy cho mục trống — không đè nội dung người đã xác nhận.

        Gợi ý chưa xác nhận được làm mới khi cấu hình đổi (vd bóc tách KH HTK).
        """
        existing = self.map_for_period(company, period_from, period_to)
        suggestions = self._build_suggestion_texts(company)
        created = self.browse()
        for code, text in suggestions.items():
            body = text if text.startswith(SUGGESTION_PREFIX) else (
                SUGGESTION_PREFIX + text
            )
            if code in existing:
                ent = existing[code]
                if ent.origin == 'suggestion' and not ent.is_confirmed:
                    ent.write({
                        'text_value': body,
                        'origin': 'suggestion',
                        'is_confirmed': False,
                    })
                    continue
                if ent.is_filled():
                    continue
                # Bản ghi trống (không phải gợi ý đang chờ) — ghi gợi ý mới
                ent.write({
                    'text_value': body,
                    'origin': 'suggestion',
                    'is_confirmed': False,
                })
                continue
            created |= self.create({
                'company_id': company.id,
                'period_from_id': period_from.id,
                'period_to_id': period_to.id,
                'code': code,
                'content_kind': 'text',
                'text_value': body,
                'origin': 'suggestion',
                'is_confirmed': False,
            })
        return created

    @api.model
    def _build_suggestion_texts(self, company):
        """Map code → text gợi ý (không prefix). Chỉ mục máy biết chắc."""
        out = {}
        partner = company.partner_id
        # I.1 — hình thức sở hữu: Odoo không chuẩn hóa; gợi ý nhẹ nếu có loại DN
        if partner and partner.is_company:
            out['I.1'] = _(
                'Doanh nghiệp (theo hồ sơ công ty Odoo: «%(name)s»). '
                'Kế toán xác nhận đúng hình thức sở hữu vốn trên đăng ký kinh doanh.',
                name=company.name or partner.name or '',
            )
        # I.2 — lĩnh vực
        industry = False
        if partner and 'industry_id' in partner._fields and partner.industry_id:
            industry = partner.industry_id.name
        if industry:
            out['I.2'] = industry
        elif partner and partner.category_id:
            out['I.2'] = ', '.join(partner.category_id.mapped('name'))

        out['III.1'] = TT133_COMPLIANCE_TEMPLATE

        # IV.6 tồn kho — cost method trên nhóm SP
        if 'product.category' in self.env:
            cats = self.env['product.category'].search([
                ('property_cost_method', '!=', False),
            ], limit=30)
            methods = sorted({
                c.property_cost_method for c in cats if c.property_cost_method
            })
            labels = {
                'fifo': _('Nhập trước xuất trước (FIFO)'),
                'average': _('Bình quân gia quyền'),
                'standard': _('Giá chuẩn'),
            }
            if methods:
                out['IV.6'] = _(
                    'Phương pháp tính giá hàng tồn kho đang cấu hình trên nhóm '
                    'sản phẩm Odoo: %(m)s.',
                    m='; '.join(labels.get(m, m) for m in methods),
                )

        # IV.7 — chính sách KH trong HTK (TT133 hai trường hợp) + phương pháp KH TSCĐ
        iv7_parts = []
        if company.vas_boc_tach_khau_hao_htk:
            iv7_parts.append(_(
                'Chính sách khấu hao trong hàng tồn kho (TT133): doanh nghiệp '
                'đang áp dụng trường hợp BÓC TÁCH được số khấu hao nằm trong '
                'hàng tồn kho. Số KH trong HTK cuối kỳ khai trên cấu hình công ty: '
                '%(amt)s.',
                amt='{:,.0f}'.format(company.vas_khau_hao_trong_htk or 0.0),
            ))
        else:
            iv7_parts.append(_(
                'Chính sách khấu hao trong hàng tồn kho (TT133): doanh nghiệp '
                'đang áp dụng trường hợp KHÔNG bóc tách số khấu hao nằm trong '
                'hàng tồn kho — khấu hao kỳ ghi đầy đủ ở chỉ tiêu B03 mã 03; '
                'biến động hàng tồn kho (mã 11) gồm phần KH trong tồn cuối kỳ.'
            ))
        assets = self.env['vas.asset'].search([
            ('company_id', '=', company.id),
            ('asset_type', '=', 'tscd'),
            ('state', 'in', ('running', 'closed')),
        ], limit=40)
        if assets:
            methods = sorted(set(assets.mapped('method')))
            labels = {
                'straight_line': _('Đường thẳng'),
                'declining': _('Số dư giảm dần có điều chỉnh'),
                'units': _('Theo sản lượng'),
            }
            iv7_parts.append(_(
                'Phương pháp khấu hao TSCĐ đang dùng trên thẻ tài sản VAS: %(m)s.',
                m='; '.join(labels.get(m, m) for m in methods),
            ))
        out['IV.7'] = '\n\n'.join(iv7_parts)

        # IV.9 chi phí đi vay từ vas.loan
        loans = self.env['vas.loan'].search([
            ('company_id', '=', company.id),
            ('state', '!=', 'draft'),
        ], limit=20)
        if loans:
            bases = sorted(set(loans.mapped('day_count_basis')))
            modes = sorted(set(loans.mapped('interest_balance_mode')))
            out['IV.9'] = _(
                'Chi phí lãi vay được ghi nhận theo cấu hình khoản vay VAS: '
                'cơ sở ngày %(b)s; cách tính dư nợ %(m)s. '
                'Vốn hóa chi phí đi vay (nếu có) do kế toán xác nhận thêm.',
                b=', '.join(bases) or '—',
                m=', '.join(modes) or '—',
            )
        return out

    @api.model
    def count_pending(self, company, period_from, period_to):
        """(số mục còn trống, số gợi ý/chép chưa xác nhận)."""
        by = self.map_for_period(company, period_from, period_to)
        empty = 0
        unconfirmed = 0
        for code in B09_ENTRY_CODES:
            ent = by.get(code)
            if not ent or not ent.is_filled():
                empty += 1
                continue
            if not ent.is_confirmed and ent.origin in ('suggestion', 'copied_prior'):
                unconfirmed += 1
        return empty, unconfirmed


class VasB09EntryRow(models.Model):
    _name = 'vas.b09.entry.row'
    _description = 'Dòng bảng người điền B09'
    _order = 'sequence, id'

    entry_id = fields.Many2one(
        'vas.b09.entry', required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Diễn giải', required=True)
    amount_opening = fields.Float(string='Số đầu năm')
    amount_closing = fields.Float(string='Số cuối kỳ')
