# -*- coding: utf-8 -*-
"""Chặng 6 — khai bổ sung 01/KHBS · giải trình · canh hạn trả chậm · rà soát mục đích · quyết toán năm."""
from calendar import monthrange

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero, float_round


# --- Khuyến nghị kỳ điều chỉnh (TT 89 PL II điểm 3 + NĐ 252 Điều 12 k.6) ---
ADJUST_DECREASE_CARRY = 'discovery_37'       # giảm [43] → [37] kỳ phát hiện
ADJUST_INCREASE_CARRY = 'discovery_38'       # tăng [43] → [38] kỳ phát hiện
ADJUST_INCREASE_PAYABLE = 'amend_origin'     # tăng [40] → KHBS kỳ gốc + chậm nộp
ADJUST_REFUND = 'amend_origin_refund'        # liên quan hoàn
ADJUST_INPUT_ONLY = 'discovery_only'         # sai sót ĐV chỉ ảnh hưởng chuyển kỳ — [37]/[38] kỳ PH, không KHBS


class VasGtgtDeclarationExplanation(models.Model):
    """01-1/KHBS — chỉ tiêu có chênh lệch giữa bản đã nộp và bản bổ sung."""
    _name = 'vas.gtgt.declaration.explanation'
    _description = 'Bản giải trình khai bổ sung GTGT'
    _order = 'sequence, code, id'

    declaration_id = fields.Many2one(
        'vas.gtgt.declaration', required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=10)
    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    amount_old = fields.Monetary(currency_field='currency_id')
    amount_new = fields.Monetary(currency_field='currency_id')
    difference = fields.Monetary(currency_field='currency_id')
    currency_id = fields.Many2one(related='declaration_id.currency_id')


class VasGtgtDeferredAdjustment(models.Model):
    """Điều chỉnh khấu trừ do trả chậm / khôi phục sau thanh toán không dùng tiền mặt."""
    _name = 'vas.gtgt.deferred.adjustment'
    _description = 'Điều chỉnh khấu trừ trả chậm GTGT'
    _order = 'date_event desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(related='company_id.currency_id')
    kind = fields.Selection(
        [
            ('reduce', 'Giảm khấu trừ (đến hạn chưa thanh toán đúng)'),
            ('restore', 'Khôi phục khấu trừ (đã có chứng từ không dùng tiền mặt)'),
        ],
        required=True, index=True,
    )
    invoice_ref = fields.Char(string='Hóa đơn gốc', required=True)
    source_move_line_id = fields.Many2one('vas.move.line', ondelete='set null')
    source_res_model = fields.Char()
    source_res_id = fields.Integer()
    amount_tax = fields.Monetary(
        string='Số thuế điều chỉnh', required=True, currency_field='currency_id',
    )
    reason = fields.Text(required=True)
    date_event = fields.Date(required=True, index=True)
    period_date_start = fields.Date(string='Kỳ điều chỉnh từ', required=True)
    period_date_end = fields.Date(string='Kỳ điều chỉnh đến', required=True)
    state = fields.Selection(
        [('draft', 'Nháp'), ('confirmed', 'Đã xác nhận'), ('cancelled', 'Hủy')],
        default='draft', required=True, index=True,
    )
    confirmed_by = fields.Many2one('res.users', string='Người xác nhận', readonly=True)
    confirmed_date = fields.Datetime(readonly=True)

    @api.depends('kind', 'invoice_ref', 'date_event')
    def _compute_name(self):
        for rec in self:
            kind = dict(rec._fields['kind'].selection).get(rec.kind, '')
            rec.name = '%s · %s · %s' % (kind, rec.invoice_ref or '', rec.date_event or '')

    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Chỉ xác nhận bản nháp.'))
            # Không sửa sổ kỳ đã khóa — chỉ ghi bản ghi điều chỉnh
            period = self.env['vas.period'].search([
                ('fiscalyear_id.company_id', '=', rec.company_id.id),
                ('date_start', '<=', rec.date_event),
                ('date_end', '>=', rec.date_event),
            ], limit=1)
            if period and period.state == 'closed':
                # Cho phép xác nhận bản ghi hướng vào kỳ đích; cấm sửa move
                pass
            rec.write({
                'state': 'confirmed',
                'confirmed_by': self.env.user.id,
                'confirmed_date': fields.Datetime.now(),
            })
        return True

    @api.model
    def cron_scan_deferred(self, as_of_date=None):
        """Máy định kỳ: HĐ trả chậm quá hạn chưa thanh toán đúng → bản ghi giảm."""
        companies = self.env['res.company'].search([
            ('vas_regime_id', '!=', False),
        ])
        today = as_of_date or fields.Date.context_today(self)
        if isinstance(today, str):
            today = fields.Date.to_date(today)
        created = 0
        for company in companies:
            lines = self.env['vas.move.line'].search([
                ('move_id.company_id', '=', company.id),
                ('move_id.state', '=', 'posted'),
                ('debit', '>', 0),
                ('account_id.code', '=like', '1331%'),
                ('deduction_check', '=', 'fail'),
                ('deduction_rule_id.code', '=', 'DEFERRED_PAYMENT'),
            ])
            for line in lines:
                if float_is_zero(line.debit, 2):
                    continue
                exists = self.search_count([
                    ('source_move_line_id', '=', line.id),
                    ('kind', '=', 'reduce'),
                    ('state', '!=', 'cancelled'),
                ])
                if exists:
                    continue
                due = line.date
                move = line.move_id
                if move.source_model == 'account.move' and move.source_res_id:
                    inv = self.env['account.move'].browse(move.source_res_id).exists()
                    if inv and inv.invoice_date_due:
                        due = inv.invoice_date_due
                if due and due > today:
                    continue
                # Kỳ điều chỉnh = kỳ phát sinh nghĩa vụ thanh toán (ngày đến hạn)
                adj_date = due or line.date
                start = adj_date.replace(day=1)
                end = adj_date.replace(
                    day=monthrange(adj_date.year, adj_date.month)[1],
                )
                inv_ref = line.move_id.source_ref or line.move_id.ref or line.move_id.name
                self.create({
                    'company_id': company.id,
                    'kind': 'reduce',
                    'invoice_ref': inv_ref,
                    'source_move_line_id': line.id,
                    'source_res_model': line.move_id.source_model,
                    'source_res_id': line.move_id.source_res_id,
                    'amount_tax': line.debit,
                    'reason': _(
                        'Đến hạn %s chưa có chứng từ thanh toán không dùng tiền mặt '
                        '(TT 89 ghi chú [37]).',
                        due,
                    ),
                    'date_event': adj_date,
                    'period_date_start': start,
                    'period_date_end': end,
                    'state': 'draft',
                })
                created += 1
        return created


class VasGtgtPurposeReview(models.Model):
    """Việc cần rà soát khi mục đích sử dụng thuế đầu vào đổi sau ngày mua."""
    _name = 'vas.gtgt.purpose.review'
    _description = 'Rà soát đổi mục đích sử dụng GTGT'
    _order = 'id desc'

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    move_line_id = fields.Many2one('vas.move.line', required=True, ondelete='cascade')
    invoice_ref = fields.Char()
    purpose_old = fields.Char()
    purpose_new = fields.Char()
    choice = fields.Selection(
        [
            ('no_adjust', 'Không điều chỉnh — mục đích đổi sau ngày mua'),
            ('discovery', 'Điều chỉnh vào kỳ phát hiện ([37]/[38])'),
            ('amend_origin', 'Khai bổ sung kỳ gốc'),
        ],
        string='Lựa chọn',
    )
    choice_reason = fields.Text(string='Lý do')
    state = fields.Selection(
        [('open', 'Cần rà soát'), ('done', 'Đã chọn'), ('cancelled', 'Hủy')],
        default='open', required=True,
    )

    @api.depends('invoice_ref', 'purpose_old', 'purpose_new')
    def _compute_name(self):
        for rec in self:
            rec.name = _('Rà soát mục đích %s: %s → %s') % (
                rec.invoice_ref or '', rec.purpose_old or '', rec.purpose_new or '',
            )

    def action_set_choice(self):
        for rec in self:
            if not rec.choice:
                raise UserError(_('Chọn một trong ba phương án.'))
            if not rec.choice_reason:
                raise UserError(_('Ghi lý do lựa chọn.'))
            rec.state = 'done'
        return True


class VasGtgtAnnualSummary(models.Model):
    """Bảng tổng hợp quyết toán năm — lưới tự kiểm chuyển kỳ."""
    _name = 'vas.gtgt.annual.summary'
    _description = 'Bảng tổng hợp GTGT năm'
    _order = 'year desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(related='company_id.currency_id')
    year = fields.Integer(required=True)
    period_kind = fields.Selection(
        [('month', 'Tháng'), ('quarter', 'Quý')],
        required=True, default='month',
    )
    line_ids = fields.One2many('vas.gtgt.annual.summary.line', 'summary_id')

    @api.depends('year', 'period_kind', 'company_id')
    def _compute_name(self):
        for rec in self:
            kind = dict(rec._fields['period_kind'].selection).get(rec.period_kind, '')
            rec.name = _('Tổng hợp GTGT %s · %s · %s') % (
                rec.year or '', kind, rec.company_id.display_name or '',
            )

    def action_rebuild(self):
        for rec in self:
            rec.line_ids.unlink()
            Decl = self.env['vas.gtgt.declaration']
            domain = [
                ('company_id', '=', rec.company_id.id),
                ('year', '=', rec.year),
                ('period_kind', '=', rec.period_kind),
                ('declaration_round', '=', 0),
                ('state', 'in', ('prepared', 'filed', 'accepted')),
            ]
            decls = Decl.search(domain, order='date_start')
            prev_43 = 0.0
            rows = []
            for i, d in enumerate(decls):
                amt = {l.code: l.amount for l in d.line_ids}
                carry_in = amt.get('22', 0.0)
                mismatch = False
                if i > 0:
                    mismatch = float_compare(abs(carry_in - prev_43), 0.5, 0) > 0
                rows.append({
                    'summary_id': rec.id,
                    'sequence': (i + 1) * 10,
                    'period_label': d.name,
                    'declaration_id': d.id,
                    'date_start': d.date_start,
                    'amount_22': carry_in,
                    'amount_35': amt.get('35', 0.0),
                    'amount_24': amt.get('24', 0.0),
                    'amount_25': amt.get('25', 0.0),
                    'amount_40': amt.get('40', 0.0),
                    'amount_42': amt.get('42', 0.0),
                    'amount_43': amt.get('43', 0.0),
                    'is_carry_mismatch': mismatch,
                    'prev_43': prev_43 if i > 0 else 0.0,
                })
                prev_43 = amt.get('43', 0.0)
            self.env['vas.gtgt.annual.summary.line'].create(rows)
        return True


class VasGtgtAnnualSummaryLine(models.Model):
    _name = 'vas.gtgt.annual.summary.line'
    _description = 'Dòng bảng tổng hợp GTGT năm'
    _order = 'sequence, id'

    summary_id = fields.Many2one(
        'vas.gtgt.annual.summary', required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=10)
    period_label = fields.Char()
    declaration_id = fields.Many2one('vas.gtgt.declaration', ondelete='set null')
    date_start = fields.Date()
    amount_22 = fields.Monetary(string='Còn KT kỳ trước chuyển sang [22]', currency_field='currency_id')
    amount_35 = fields.Monetary(string='Thuế đầu ra [35]', currency_field='currency_id')
    amount_24 = fields.Monetary(string='Thuế đầu vào [24]', currency_field='currency_id')
    amount_25 = fields.Monetary(string='Được khấu trừ [25]', currency_field='currency_id')
    amount_40 = fields.Monetary(string='Phải nộp [40]', currency_field='currency_id')
    amount_42 = fields.Monetary(string='Đề nghị hoàn [42]', currency_field='currency_id')
    amount_43 = fields.Monetary(string='Còn KT chuyển kỳ sau [43]', currency_field='currency_id')
    prev_43 = fields.Monetary(string='[43] kỳ trước', currency_field='currency_id')
    is_carry_mismatch = fields.Boolean(string='Lệch chuyển kỳ')
    currency_id = fields.Many2one(related='summary_id.currency_id')


class VasGtgtDeclarationSupplement(models.Model):
    """Mở rộng tờ khai: KHBS · giải trình · khóa · [37]/[38] từ bổ sung / trả chậm."""
    _inherit = 'vas.gtgt.declaration'

    base_declaration_id = fields.Many2one(
        'vas.gtgt.declaration',
        string='Tờ khai gốc (đã nộp)',
        ondelete='restrict', index=True,
        help='Bản lần đầu / lần trước — không sửa đè.',
    )
    date_prepared = fields.Date(
        string='Ngày lập',
        default=fields.Date.context_today,
    )
    explanation_ids = fields.One2many(
        'vas.gtgt.declaration.explanation', 'declaration_id',
        string='Bản giải trình 01-1/KHBS',
    )
    adjust_choice = fields.Selection(
        [
            (ADJUST_DECREASE_CARRY, 'Đưa chênh lệch giảm [43] vào [37] kỳ phát hiện'),
            (ADJUST_INCREASE_CARRY, 'Đưa chênh lệch tăng [43] vào [38] kỳ phát hiện'),
            (ADJUST_INCREASE_PAYABLE, 'Khai bổ sung kỳ gốc (phát sinh thuế phải nộp)'),
            (ADJUST_REFUND, 'Khai bổ sung kỳ gốc (liên quan hoàn thuế)'),
            (ADJUST_INPUT_ONLY, 'Chỉ [37]/[38] kỳ phát hiện (không KHBS)'),
        ],
        string='Kỳ điều chỉnh (máy / kế toán)',
    )
    adjust_reason_auto = fields.Text(
        string='Lý do máy chọn kỳ',
        readonly=True,
    )
    adjust_reason_user = fields.Text(
        string='Lý do kế toán đổi kỳ',
    )
    adjust_choice_overridden = fields.Boolean(
        string='Kế toán đã đổi kỳ',
        default=False,
    )
    discovery_declaration_id = fields.Many2one(
        'vas.gtgt.declaration',
        string='Tờ khai kỳ phát hiện',
        ondelete='set null', index=True,
        help='Kỳ nhận [37]/[38] từ chênh lệch KHBS này.',
    )
    delta_43 = fields.Monetary(
        string='Chênh [43] (mới − cũ)',
        currency_field='currency_id', readonly=True,
    )
    delta_40 = fields.Monetary(
        string='Chênh [40] (mới − cũ)',
        currency_field='currency_id', readonly=True,
    )
    late_interest_note = fields.Text(
        string='Ghi chú tiền chậm nộp',
        readonly=True,
    )
    is_amount_locked = fields.Boolean(
        compute='_compute_is_amount_locked',
        string='Khóa số (đã nộp)',
    )
    supplementary_ids = fields.One2many(
        'vas.gtgt.declaration', 'base_declaration_id',
        string='Các lần bổ sung',
    )

    @api.depends('state')
    def _compute_is_amount_locked(self):
        for rec in self:
            rec.is_amount_locked = rec.state in ('filed', 'accepted')

    def write(self, vals):
        # Khóa số tờ đã nộp — chỉ cho đổi state / reject_reason / liên kết KHBS
        locked_keys = {
            'amount_22', 'amount_22_manual', 'line_ids',
            'taxpayer_name', 'taxpayer_vat', 'period_kind', 'year', 'month',
            'quarter', 'date_start', 'date_end', 'activity_id', 'form_version_id',
            'declaration_round',
        }
        if self.env.context.get('vas_allow_filed_write'):
            return super().write(vals)
        for rec in self:
            if rec.state in ('filed', 'accepted') and locked_keys.intersection(vals):
                raise UserError(_(
                    'Tờ khai «%s» đã nộp — không sửa số. Chỉ được khai bổ sung.',
                    rec.display_name,
                ))
        # Ghi nhận kế toán đổi kỳ điều chỉnh
        if 'adjust_choice' in vals and not self.env.context.get('vas_auto_adjust'):
            for rec in self:
                if rec.adjust_choice and vals['adjust_choice'] != rec.adjust_choice:
                    vals = dict(vals, adjust_choice_overridden=True)
                    break
        return super().write(vals)

    def action_create_supplementary(self):
        """Lập tờ khai bổ sung từ bản đã nộp — giữ nguyên bản gốc."""
        self.ensure_one()
        if self.state not in ('filed', 'accepted'):
            raise UserError(_('Chỉ khai bổ sung từ tờ khai đã nộp / đã chấp nhận.'))
        if self.declaration_round and self.base_declaration_id:
            # Bổ sung từ lần bổ sung gần nhất cũng được — base vẫn là lần đầu
            root = self.base_declaration_id
            while root.base_declaration_id:
                root = root.base_declaration_id
        else:
            root = self
        next_round = max(root.supplementary_ids.mapped('declaration_round') or [0]) + 1
        if self.declaration_round:
            next_round = max(next_round, self.declaration_round + 1)
        copy_vals = {
            'declaration_round': next_round,
            'base_declaration_id': root.id,
            'state': 'draft',
            'date_prepared': fields.Date.context_today(self),
            'amount_22': self.amount_22,
            'amount_22_manual': self.amount_22_manual,
            'reject_reason': False,
            'tax_balance_warning': False,
            'reduction_warning_text': False,
        }
        # Copy header fields
        for f in (
            'company_id', 'form_type_id', 'form_version_id', 'activity_id',
            'period_kind', 'year', 'month', 'quarter', 'date_start', 'date_end',
            'taxpayer_name', 'taxpayer_vat', 'agent_name', 'agent_vat',
            'agent_contract', 'branch_name', 'branch_vat', 'branch_address',
            'branch_ward', 'branch_province',
        ):
            val = self[f]
            copy_vals[f] = val.id if isinstance(val, models.BaseModel) else val
        new = self.create(copy_vals)
        # Sao chép số chỉ tiêu từ bản nguồn (không đụng bản gốc)
        src_amt = {l.code: l.amount for l in self.line_ids}
        for line in new.line_ids:
            if line.code in src_amt:
                line.amount = src_amt[line.code]
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'vas.gtgt.declaration',
            'res_id': new.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_rebuild_explanation(self):
        """So chỉ tiêu bản gốc ↔ bổ sung — chỉ dòng có chênh lệch."""
        Expl = self.env['vas.gtgt.declaration.explanation']
        for rec in self:
            if not rec.base_declaration_id:
                raise UserError(_('Không có tờ khai gốc để so sánh.'))
            # So với lần nộp gần nhất trước lần này (cùng kỳ, round thấp hơn)
            prior = rec.search([
                ('company_id', '=', rec.company_id.id),
                ('form_type_id', '=', rec.form_type_id.id),
                ('activity_id', '=', rec.activity_id.id),
                ('date_start', '=', rec.date_start),
                ('date_end', '=', rec.date_end),
                ('declaration_round', '<', rec.declaration_round),
                ('state', 'in', ('filed', 'accepted', 'prepared')),
            ], order='declaration_round desc', limit=1) or rec.base_declaration_id
            old_map = {l.code: (l.name, l.amount) for l in prior.line_ids}
            new_map = {l.code: (l.name, l.amount) for l in rec.line_ids}
            Expl.search([('declaration_id', '=', rec.id)]).unlink()
            rows = []
            seq = 10
            for code in sorted(set(old_map) | set(new_map), key=lambda c: (len(c), c)):
                o_name, o_amt = old_map.get(code, ('', 0.0))
                n_name, n_amt = new_map.get(code, (o_name, 0.0))
                diff = float_round(n_amt - o_amt, 0)
                if float_is_zero(diff, 2):
                    continue
                rows.append({
                    'declaration_id': rec.id,
                    'sequence': seq,
                    'code': code,
                    'name': n_name or o_name or code,
                    'amount_old': o_amt,
                    'amount_new': n_amt,
                    'difference': diff,
                })
                seq += 10
            Expl.create(rows)
            rec.delta_43 = float_round(
                new_map.get('43', (None, 0.0))[1] - old_map.get('43', (None, 0.0))[1], 0,
            )
            rec.delta_40 = float_round(
                new_map.get('40', (None, 0.0))[1] - old_map.get('40', (None, 0.0))[1], 0,
            )
            rec._recommend_adjust_choice()
        return True

    def _recommend_adjust_choice(self):
        """Máy chọn kỳ theo PL II TT 89 điểm 3 — HIỆN RÕ lý do."""
        self.ensure_one()
        d43 = self.delta_43
        d40 = self.delta_40
        old40 = 0.0
        if self.base_declaration_id:
            ol = self.base_declaration_id.line_ids.filtered(lambda l: l.code == '40')[:1]
            old40 = ol.amount if ol else 0.0
        new40 = old40 + d40
        refund_touched = False
        expl42 = self.explanation_ids.filtered(lambda e: e.code == '42')
        if expl42:
            refund_touched = True

        if refund_touched:
            choice = ADJUST_REFUND
            reason = _(
                'PL II TT 89 điểm 3.b.2 / NĐ 252 Điều 12 k.6: liên quan số thuế đã '
                '(đề nghị) hoàn — khai bổ sung kỳ gốc; thu hồi hoàn + tiền chậm nộp '
                'nếu đã được hoàn. Phần còn đủ ĐKKT → [38] kỳ phát hiện.'
            )
            late = _('Phải nộp số thu hồi hoàn + tiền chậm nộp theo quy định.')
        elif float_compare(d40, 0.0, 0) > 0 or (
            float_compare(new40, 0.0, 0) > 0 and float_compare(d40, 0.0, 0) > 0
        ):
            choice = ADJUST_INCREASE_PAYABLE
            reason = _(
                'PL II TT 89 điểm 3.c / NĐ 252 Điều 12 k.6: khai bổ sung làm '
                'PHÁT SINH / TĂNG thuế phải nộp kỳ gốc → khai bổ sung kỳ gốc, '
                'nộp thuế tăng thêm và tiền chậm nộp. Nếu [43] giảm thì đồng thời '
                'đưa chênh lệch vào [37] kỳ phát hiện.'
            )
            late = _(
                'Tiền chậm nộp tính trên số thuế phải nộp tăng thêm từ ngày hết hạn '
                'nộp thuế của kỳ gốc đến ngày nộp (NĐ 252 Điều 12).'
            )
        elif float_compare(d43, 0.0, 0) < 0:
            choice = ADJUST_DECREASE_CARRY
            reason = _(
                'PL II TT 89 điểm 3.b.1: KHBS chỉ làm GIẢM số thuế chưa khấu trừ hết '
                'chuyển kỳ sau ([43]) và chưa đề nghị hoàn → lập KHBS kỳ gốc; '
                'số điều chỉnh giảm khai vào [37] của kỳ tính thuế PHÁT HIỆN sai sót.'
            )
            late = False
        elif float_compare(d43, 0.0, 0) > 0:
            choice = ADJUST_INCREASE_CARRY
            reason = _(
                'PL II TT 89 điểm 3.a: KHBS chỉ làm TĂNG số chưa khấu trừ chuyển kỳ sau '
                '→ lập KHBS kỳ gốc; số điều chỉnh tăng khai vào [38] kỳ phát hiện.'
            )
            late = False
        else:
            choice = ADJUST_DECREASE_CARRY
            reason = _('Không có chênh [40]/[43] — giữ mặc định đưa vào kỳ phát hiện nếu có.')
            late = False

        vals = {
            'adjust_reason_auto': reason,
            'late_interest_note': late or False,
        }
        if not self.adjust_choice_overridden:
            vals['adjust_choice'] = choice
        self.with_context(vas_auto_adjust=True).write(vals)

    def action_apply_discovery_adjustments(self):
        """Đẩy chênh lệch [43] vào [37]/[38] của tờ khai kỳ phát hiện."""
        for rec in self:
            if not rec.discovery_declaration_id:
                raise UserError(_('Chọn tờ khai kỳ phát hiện.'))
            if rec.state not in ('prepared', 'filed', 'accepted'):
                raise UserError(_('Lập / nộp tờ bổ sung trước khi đẩy [37]/[38].'))
            disc = rec.discovery_declaration_id
            if disc.is_amount_locked:
                raise UserError(_(
                    'Kỳ phát hiện «%s» đã khóa — không ghi đè số. '
                    'Chỉ được khai bổ sung kỳ đó.',
                    disc.display_name,
                ))
            # Cộng dồn các KHBS đã nộp hướng vào kỳ này
            disc._apply_khbs_and_deferred_to_37_38()
            disc.action_recompute_amounts()
        return True

    def _sum_khbs_deltas_for_discovery(self):
        """Tổng chênh [43] từ KHBS đã nộp gắn discovery = self."""
        self.ensure_one()
        khbs = self.search([
            ('discovery_declaration_id', '=', self.id),
            ('declaration_round', '>', 0),
            ('state', 'in', ('prepared', 'filed', 'accepted')),
        ])
        down = up = 0.0
        for k in khbs:
            if float_compare(k.delta_43, 0.0, 0) < 0:
                down += abs(k.delta_43)
            elif float_compare(k.delta_43, 0.0, 0) > 0:
                up += k.delta_43
        return down, up

    def _sum_deferred_for_period(self):
        self.ensure_one()
        Adj = self.env['vas.gtgt.deferred.adjustment']
        domain = [
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'confirmed'),
            ('period_date_start', '<=', self.date_end),
            ('period_date_end', '>=', self.date_start),
        ]
        reduce = sum(Adj.search(domain + [('kind', '=', 'reduce')]).mapped('amount_tax'))
        restore = sum(Adj.search(domain + [('kind', '=', 'restore')]).mapped('amount_tax'))
        return reduce, restore

    def _apply_khbs_and_deferred_to_37_38(self):
        """Ghi [37]/[38] từ KHBS + điều chỉnh trả chậm — không đụng [22]."""
        self.ensure_one()
        if self.state in ('filed', 'accepted'):
            return
        khbs_down, khbs_up = self._sum_khbs_deltas_for_discovery()
        def_down, def_up = self._sum_deferred_for_period()
        amount_37 = float_round(khbs_down + def_down, 0)
        amount_38 = float_round(khbs_up + def_up, 0)
        for code, val in (('37', amount_37), ('38', amount_38)):
            line = self.line_ids.filtered(lambda l, c=code: l.code == c)[:1]
            if line:
                line.amount = val

    def action_prepare(self):
        for rec in self:
            if rec.state in ('filed', 'accepted'):
                raise UserError(_(
                    'Tờ khai «%s» đã nộp — không lập lại. Chỉ khai bổ sung.',
                    rec.display_name,
                ))
            if rec.declaration_round and rec.base_declaration_id:
                # KHBS: giữ số đã chỉnh, chỉ tính lại công thức + giải trình
                rec._recompute_supplementary_formulas()
                rec.action_rebuild_explanation()
                rec.write({'state': 'prepared'})
            else:
                rec._apply_khbs_and_deferred_to_37_38()
                super(VasGtgtDeclarationSupplement, rec).action_prepare()
        return True

    def _recompute_supplementary_formulas(self):
        """Tờ bổ sung: không lấy lại sổ — chỉ tính chuỗi công thức từ số đã chỉnh."""
        self.ensure_one()
        amounts = {l.code: l.amount for l in self.line_ids}
        for _pass in range(3):
            for line in self.line_ids.sorted('sequence'):
                ind = line.indicator_id
                if ind and ind.source_kind == 'formula':
                    amounts[line.code] = self._eval_formula(ind.formula, amounts)
                    line.amount = amounts[line.code]
        amt_map = {l.code: l.amount for l in self.line_ids}
        for code, formula in (('40', '[40a]-[40b]'), ('43', '[41]-[42]')):
            line = self.line_ids.filtered(lambda l, c=code: l.code == c)[:1]
            if line:
                line.amount = self._eval_formula(formula, amt_map)
                amt_map[code] = line.amount

    def action_recompute_amounts(self):
        for rec in self:
            if rec.state in ('filed', 'accepted'):
                raise UserError(_(
                    'Tờ khai «%s» đã nộp — không lập lại số. Chỉ khai bổ sung.',
                    rec.display_name,
                ))
            if rec.declaration_round:
                rec._recompute_supplementary_formulas()
                continue
            # [22] từ tờ LẦN ĐẦU kỳ trước (declaration_round=0) — _previous_declaration
            super(VasGtgtDeclarationSupplement, rec).action_recompute_amounts()
            rec._apply_khbs_and_deferred_to_37_38()
            # Tính lại công thức sau khi ghi [37]/[38]
            amounts = {l.code: l.amount for l in rec.line_ids}
            for _pass in range(3):
                for line in rec.line_ids.sorted('sequence'):
                    ind = line.indicator_id
                    if ind and ind.source_kind == 'formula':
                        amounts[line.code] = rec._eval_formula(ind.formula, amounts)
                        line.amount = amounts[line.code]
            amt_map = {l.code: l.amount for l in rec.line_ids}
            for code, formula in (('40', '[40a]-[40b]'), ('43', '[41]-[42]')):
                line = rec.line_ids.filtered(lambda l, c=code: l.code == c)[:1]
                if line:
                    line.amount = rec._eval_formula(formula, amt_map)
                    amt_map[code] = line.amount
        return True

    def action_open_purpose_review(self, move_line, purpose_old, purpose_new):
        """Sinh việc cần rà soát — KHÔNG tự sửa tờ khai cũ."""
        Review = self.env['vas.gtgt.purpose.review']
        return Review.create({
            'company_id': move_line.move_id.company_id.id,
            'move_line_id': move_line.id,
            'invoice_ref': (
                move_line.move_id.source_ref
                or move_line.move_id.ref
                or move_line.move_id.name
            ),
            'purpose_old': purpose_old,
            'purpose_new': purpose_new,
            'state': 'open',
        })


class VasGtgtDeclarationLineLock(models.Model):
    _inherit = 'vas.gtgt.declaration.line'

    def write(self, vals):
        if 'amount' in vals and not self.env.context.get('vas_allow_filed_write'):
            for line in self:
                if line.declaration_id.state in ('filed', 'accepted'):
                    raise UserError(_(
                        'Tờ khai «%s» đã nộp — không sửa chỉ tiêu [%s].',
                        line.declaration_id.display_name, line.code,
                    ))
        return super().write(vals)


class VasGtgtDeferredAdjustmentRestore(models.Model):
    _inherit = 'vas.gtgt.deferred.adjustment'

    @api.model
    def action_restore_after_non_cash(self, move_line, payment_date, company=None):
        """Sau khi đã giảm: có chứng từ không dùng tiền mặt → khấu trừ lại kỳ có chứng từ."""
        company = company or move_line.move_id.company_id
        prior = self.search([
            ('source_move_line_id', '=', move_line.id),
            ('kind', '=', 'reduce'),
            ('state', '=', 'confirmed'),
        ], limit=1)
        if not prior:
            return self.browse()
        exists = self.search_count([
            ('source_move_line_id', '=', move_line.id),
            ('kind', '=', 'restore'),
            ('state', '!=', 'cancelled'),
        ])
        if exists:
            return self.browse()
        start = payment_date.replace(day=1)
        end = payment_date.replace(day=monthrange(payment_date.year, payment_date.month)[1])
        rec = self.create({
            'company_id': company.id,
            'kind': 'restore',
            'invoice_ref': prior.invoice_ref,
            'source_move_line_id': move_line.id,
            'source_res_model': prior.source_res_model,
            'source_res_id': prior.source_res_id,
            'amount_tax': prior.amount_tax,
            'reason': _(
                'Đã có chứng từ thanh toán không dùng tiền mặt ngày %s — '
                'khấu trừ lại vào [38] kỳ có chứng từ (TT 89 ghi chú [38]).',
                payment_date,
            ),
            'date_event': payment_date,
            'period_date_start': start,
            'period_date_end': end,
            'state': 'draft',
        })
        return rec
